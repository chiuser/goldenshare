from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap import etf_mins_raw_decision as decision_module
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    EtfMinsBootstrapError,
    compute_etf_mins_bootstrap_payload_hash,
)
from orchestrator.defs.bootstrap.etf_mins_raw_decision import decide_etf_mins_raw
from orchestrator.defs.bootstrap.etf_mins_raw_observation import (
    observe_etf_mins_raw,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    EtfMinsRawDecisionPolicy,
    get_etf_mins_raw_decision_policy,
)
from tests.etf_mins_bootstrap_support import TestDuckDBResource
from tests.test_etf_mins_raw_observation import _complete_tiny_raw_operation


def _canonical_rows(
    *,
    policy: EtfMinsRawDecisionPolicy,
    trade_date: str,
    zero_volume_source_freqs: frozenset[str] = frozenset(),
    missing_clock: tuple[str, str] | None = None,
    invalid_price: tuple[str, str] | None = None,
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for source_freq, clock_times in policy.expected_clock_times_by_source_freq:
        for clock_time in clock_times:
            if missing_clock == (source_freq, clock_time):
                continue
            price_is_invalid = invalid_price == (source_freq, clock_time)
            zero_volume = source_freq in zero_volume_source_freqs
            rows.append(
                (
                    "510300.SH",
                    source_freq,
                    datetime.fromisoformat(f"{trade_date}T{clock_time}"),
                    -1.0 if price_is_invalid else 10.0,
                    10.1,
                    10.2,
                    -2.0 if price_is_invalid else 9.9,
                    0 if zero_volume else 100,
                    0.0 if zero_volume else 1000.0,
                    10.05,
                    "XSHG",
                )
            )
    return rows


def _observe_tiny_operation(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation_id: str,
    trade_dates: tuple[str, ...],
    rows: list[tuple[object, ...]],
) -> tuple[Path, Path]:
    lake_root, operation_root, report_path = _complete_tiny_raw_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rows=rows,
        operation_id=operation_id,
        trade_dates=trade_dates,
    )
    observation = observe_etf_mins_raw(
        lake_root=lake_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        raw_bootstrap_report_path=report_path,
        output_dir=operation_root / "raw-observe",
    )
    monkeypatch.setattr(
        decision_module,
        "connect_configured_duckdb",
        TestDuckDBResource().connect,
    )
    return operation_root, observation.raw_observation_summary_path


def test_raw_decision_accepts_exact_lunch_grid_and_warns_only_full_zero_days(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    trade_dates = ("2026-01-02", "2026-01-05")
    rows = _canonical_rows(
        policy=policy,
        trade_date=trade_dates[0],
        zero_volume_source_freqs=frozenset({"1min"}),
    )
    rows.extend(
        _canonical_rows(
            policy=policy,
            trade_date=trade_dates[1],
            zero_volume_source_freqs=frozenset(
                source_freq
                for source_freq, _ in policy.expected_clock_times_by_source_freq
            ),
        )
    )
    operation_root, observation_summary_path = _observe_tiny_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="raw-decide-green-warn",
        trade_dates=trade_dates,
        rows=rows,
    )

    result = decide_etf_mins_raw(
        observation_summary_path=observation_summary_path,
        approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
        output_dir=operation_root,
    )

    assert result.partition_count == 10
    assert result.green_partition_count == 5
    assert result.warn_partition_count == 5
    assert result.blocked_partition_count == 0
    assert result.silver_eligible_partition_count == 10
    summary = json.loads(result.raw_decision_summary_path.read_text())
    assert summary["raw_scan_query_count"] == 0
    assert summary["prod_query_count"] == 0
    assert summary["approved_policy_hash"] == policy.policy_hash
    with duckdb.connect(":memory:") as connection:
        manifest_rows = connection.execute(
            "SELECT trade_date, source_freq, decision, silver_eligible, "
            "internal_grid_gap_candidate_count, "
            "minute_grid_contract_anomaly_count, "
            "full_zero_volume_etf_day_observed_count, "
            "decision_reason_codes_json FROM "
            f"{read_parquet(result.raw_partition_decision_manifest_path)} "
            "ORDER BY trade_date, source_freq"
        ).fetchall()
    first_date_rows = [row for row in manifest_rows if str(row[0]) == trade_dates[0]]
    second_date_rows = [row for row in manifest_rows if str(row[0]) == trade_dates[1]]
    assert all(row[2] == "green" and row[3] is True for row in first_date_rows)
    assert all(row[4] > 0 and row[5] == 0 for row in first_date_rows)
    assert all(row[6] == 0 for row in first_date_rows)
    assert all(row[2] == "warn" and row[3] is True for row in second_date_rows)
    assert all(row[6] == 1 for row in second_date_rows)
    assert all(
        json.loads(row[7]) == ["full_zero_volume_etf_day_observed"]
        for row in second_date_rows
    )

    reused = decide_etf_mins_raw(
        observation_summary_path=observation_summary_path,
        approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
        output_dir=operation_root,
    )
    assert reused.raw_decision_summary_hash == result.raw_decision_summary_hash

    with monkeypatch.context() as policy_patch:
        policy_patch.setattr(
            decision_module,
            "get_etf_mins_raw_decision_policy",
            lambda _: replace(policy, warning_reason_codes=()),
        )
        with pytest.raises(EtfMinsBootstrapError, match="output_conflict"):
            decide_etf_mins_raw(
                observation_summary_path=observation_summary_path,
                approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
                output_dir=operation_root,
            )

    result.raw_partition_decision_manifest_path.write_bytes(b"changed")
    with pytest.raises(EtfMinsBootstrapError, match="output_conflict"):
        decide_etf_mins_raw(
            observation_summary_path=observation_summary_path,
            approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
            output_dir=operation_root,
        )


def test_raw_decision_blocks_noncanonical_grid_and_price_domain_anomaly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    trade_dates = ("2026-01-02", "2026-01-05")
    rows = _canonical_rows(
        policy=policy,
        trade_date=trade_dates[0],
        missing_clock=("5min", "10:00:00"),
        invalid_price=("1min", "09:30:00"),
    )
    rows.extend(_canonical_rows(policy=policy, trade_date=trade_dates[1]))
    operation_root, observation_summary_path = _observe_tiny_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="raw-decide-blocked",
        trade_dates=trade_dates,
        rows=rows,
    )

    result = decide_etf_mins_raw(
        observation_summary_path=observation_summary_path,
        approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
        output_dir=operation_root,
    )

    assert result.partition_count == 10
    assert result.green_partition_count == 8
    assert result.warn_partition_count == 0
    assert result.blocked_partition_count == 2
    assert result.silver_eligible_partition_count == 8
    with duckdb.connect(":memory:") as connection:
        decisions = {
            (str(row[0]), str(row[1])): (str(row[2]), json.loads(str(row[3])))
            for row in connection.execute(
                "SELECT trade_date, source_freq, decision, "
                "decision_reason_codes_json FROM "
                f"{read_parquet(result.raw_partition_decision_manifest_path)}"
            ).fetchall()
        }
    assert decisions[(trade_dates[0], "1min")] == (
        "blocked",
        ["price_domain_anomaly"],
    )
    assert decisions[(trade_dates[0], "5min")] == (
        "blocked",
        ["minute_grid_contract_anomaly"],
    )
    assert decisions[(trade_dates[1], "5min")] == ("green", [])


def test_raw_decision_rejects_unregistered_policy_and_wrong_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    trade_date = "2026-01-02"
    operation_root, observation_summary_path = _observe_tiny_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="raw-decide-controls",
        trade_dates=(trade_date,),
        rows=_canonical_rows(policy=policy, trade_date=trade_date),
    )

    with pytest.raises(EtfMinsBootstrapError, match="policy_not_registered"):
        decide_etf_mins_raw(
            observation_summary_path=observation_summary_path,
            approved_policy_version="operator-threshold-v99",
            output_dir=operation_root,
        )
    with pytest.raises(EtfMinsBootstrapError, match="output_path_invalid"):
        decide_etf_mins_raw(
            observation_summary_path=observation_summary_path,
            approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
            output_dir=operation_root / "raw-decide",
        )

    original_summary = observation_summary_path.read_bytes()
    changed_summary = json.loads(original_summary)
    changed_summary["operation_id"] = "different-operation"
    changed_summary["observation_summary_hash"] = (
        compute_etf_mins_bootstrap_payload_hash(
            changed_summary,
            self_hash_field="observation_summary_hash",
        )
    )
    observation_summary_path.write_text(
        json.dumps(changed_summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(EtfMinsBootstrapError, match="operation_id_mismatch"):
        decide_etf_mins_raw(
            observation_summary_path=observation_summary_path,
            approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
            output_dir=operation_root,
        )
    observation_summary_path.write_bytes(original_summary)

    issue_path = operation_root / "raw-observe" / "raw_issue_details.parquet"
    issue_path.write_bytes(b"changed")
    with pytest.raises(EtfMinsBootstrapError, match="artifact_changed"):
        decide_etf_mins_raw(
            observation_summary_path=observation_summary_path,
            approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
            output_dir=operation_root,
        )
