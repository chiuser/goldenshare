from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap import etf_mins_raw_decision as decision_module
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    EtfMinsBootstrapError,
    apply_etf_mins_bootstrap_silver,
)
from orchestrator.defs.bootstrap.etf_mins_raw_decision import decide_etf_mins_raw
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import raw_etf_mins_path, silver_etf_mins_path
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    get_etf_mins_raw_decision_policy,
)
from tests.etf_mins_bootstrap_support import TestDuckDBResource
from tests.test_etf_mins_raw_decision import (
    _canonical_rows,
    _observe_tiny_operation,
)


def _decision_operation(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation_id: str,
    trade_dates: tuple[str, ...],
    rows: list[tuple[object, ...]],
):  # type: ignore[no-untyped-def]
    operation_root, observation_summary_path = _observe_tiny_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id=operation_id,
        trade_dates=trade_dates,
        rows=rows,
    )
    monkeypatch.setattr(
        decision_module,
        "connect_configured_duckdb",
        TestDuckDBResource().connect,
    )
    decision = decide_etf_mins_raw(
        observation_summary_path=observation_summary_path,
        approved_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
        output_dir=operation_root,
    )
    return operation_root, decision


def _apply(
    *,
    tmp_path: Path,
    operation_root: Path,
    decision,  # type: ignore[no-untyped-def]
    confirm: bool = True,
):  # type: ignore[no-untyped-def]
    return apply_etf_mins_bootstrap_silver(
        lake_root=tmp_path / "data_lake",
        staging_root=tmp_path / "data_lake_staging",
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        raw_decision_summary_path=decision.raw_decision_summary_path,
        decision_manifest_path=decision.raw_partition_decision_manifest_path,
        checkpoint_path=operation_root / "silver_checkpoint.json",
        final_report_path=operation_root / "physical_final_report.json",
        confirm_silver_lake_write=confirm,
    )


def test_silver_bootstrap_writes_only_eligible_exact_copies_and_is_resumable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    trade_dates = ("2026-01-02", "2026-01-05")
    rows = _canonical_rows(policy=policy, trade_date=trade_dates[0])
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
    operation_root, decision = _decision_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="silver-apply-green-warn",
        trade_dates=trade_dates,
        rows=rows,
    )
    lake_root = tmp_path / "data_lake"
    preexisting_raw = raw_etf_mins_path(lake_root, "1min", trade_dates[0])
    preexisting_silver = silver_etf_mins_path(lake_root, "1min", trade_dates[0])
    preexisting_silver.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM "
                f"{read_parquet(preexisting_raw, hive_partitioning=False)}",
                preexisting_silver,
            )
        )

    report = _apply(
        tmp_path=tmp_path,
        operation_root=operation_root,
        decision=decision,
    )
    assert report.raw_file_count == 10
    assert report.silver_file_count == 10
    assert report.added_file_count == 9
    assert report.reused_file_count == 1
    assert report.blocked_partition_count == 0
    assert report.warn_partition_count == 5
    assert report.raw_row_count == report.silver_row_count
    assert report.final_report_path.is_file()
    assert report.silver_work_manifest_path.is_file()
    assert report.finalized_silver_manifest_path.is_file()
    assert not list((operation_root / "silver").rglob("*.parquet"))

    with duckdb.connect(":memory:") as connection:
        difference = connection.execute(
            "SELECT count(*) FROM ((SELECT * FROM "
            f"{read_parquet(preexisting_raw, hive_partitioning=False)} "
            "EXCEPT ALL SELECT * FROM "
            f"{read_parquet(preexisting_silver, hive_partitioning=False)}) "
            "UNION ALL (SELECT * FROM "
            f"{read_parquet(preexisting_silver, hive_partitioning=False)} "
            "EXCEPT ALL SELECT * FROM "
            f"{read_parquet(preexisting_raw, hive_partitioning=False)}))"
        ).fetchone()[0]
    assert difference == 0

    resumed = _apply(
        tmp_path=tmp_path,
        operation_root=operation_root,
        decision=decision,
    )
    assert resumed.report_hash == report.report_hash
    assert resumed.checkpoint_hash == report.checkpoint_hash


def test_silver_bootstrap_keeps_blocked_raw_but_writes_no_blocked_silver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    trade_date = "2026-01-02"
    operation_root, decision = _decision_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="silver-apply-blocked",
        trade_dates=(trade_date,),
        rows=_canonical_rows(
            policy=policy,
            trade_date=trade_date,
            missing_clock=("5min", "10:00:00"),
            invalid_price=("1min", "09:30:00"),
        ),
    )
    report = _apply(
        tmp_path=tmp_path,
        operation_root=operation_root,
        decision=decision,
    )
    lake_root = tmp_path / "data_lake"
    assert report.raw_file_count == 5
    assert report.silver_file_count == 3
    assert report.blocked_partition_count == 2
    assert raw_etf_mins_path(lake_root, "1min", trade_date).is_file()
    assert raw_etf_mins_path(lake_root, "5min", trade_date).is_file()
    assert not silver_etf_mins_path(lake_root, "1min", trade_date).exists()
    assert not silver_etf_mins_path(lake_root, "5min", trade_date).exists()


def test_silver_bootstrap_requires_confirmation_and_never_overwrites_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    trade_date = "2026-01-02"
    operation_root, decision = _decision_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="silver-apply-conflict",
        trade_dates=(trade_date,),
        rows=_canonical_rows(policy=policy, trade_date=trade_date),
    )
    with pytest.raises(EtfMinsBootstrapError, match="confirmation_required"):
        _apply(
            tmp_path=tmp_path,
            operation_root=operation_root,
            decision=decision,
            confirm=False,
        )
    lake_root = tmp_path / "data_lake"
    raw_path = raw_etf_mins_path(lake_root, "1min", trade_date)
    target_path = silver_etf_mins_path(lake_root, "1min", trade_date)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            copy_query_to_parquet(
                "SELECT * REPLACE (close + 1 AS close) FROM "
                f"{read_parquet(raw_path, hive_partitioning=False)}",
                target_path,
            )
        )
    conflicting_hash = target_path.read_bytes()
    with pytest.raises(EtfMinsBootstrapError, match="silver_target_conflict"):
        _apply(
            tmp_path=tmp_path,
            operation_root=operation_root,
            decision=decision,
        )
    assert target_path.read_bytes() == conflicting_hash
    assert not (operation_root / "physical_final_report.json").exists()
