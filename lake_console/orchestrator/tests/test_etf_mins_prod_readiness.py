from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED,
    evaluate_etf_mins_raw_candidate,
)
from orchestrator.defs.asset_guards.etf_mins_prod_readiness import (
    etf_mins_prod_source_ready_for_trade_date,
    validate_etf_mins_prod_coverage_reference,
)
from orchestrator.defs.prod_db.etf_mins import (
    ProdEtfMinsCodeCoverageProbe,
    ProdEtfMinsFrequencyCoverage,
)
from orchestrator.defs.run_contracts.etf_basic import (
    build_etf_basic_silver_snapshot_reference,
    compute_etf_requestable_target_hash,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_SOURCE_FREQS,
    EtfMinsProdCoverageReference,
    EtfMinsRequestableTarget,
)

TRADE_DATE = "2026-08-28"


def _requestable_targets() -> tuple[EtfMinsRequestableTarget, ...]:
    return (
        EtfMinsRequestableTarget(
            ts_code="510300.SH",
            list_date=date(2012, 5, 28),
            exchange="SH",
        ),
        EtfMinsRequestableTarget(
            ts_code="159915.SZ",
            list_date=date(2026, 9, 1),
            exchange="SZ",
        ),
    )


def _basic_reference(targets: tuple[EtfMinsRequestableTarget, ...]):
    target_rows = tuple(
        {
            "ts_code": target.ts_code,
            "list_date": target.list_date,
            "exchange": target.exchange,
        }
        for target in targets
    )
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash="a" * 64,
        silver_content_hash="b" * 64,
        raw_uri="/lake/raw/etf_basic.parquet",
        silver_uri="/lake/silver/etf_basic.parquet",
        raw_observed_at="2026-09-30T08:00:00+08:00",
        silver_observed_at="2026-09-30T08:05:00+08:00",
        eligibility_as_of="2026-09-30",
        requestable_code_count=len(targets),
        requestable_code_hash=compute_etf_requestable_target_hash(target_rows),
    )


def _coverage_probe(*, ready: bool = True) -> ProdEtfMinsCodeCoverageProbe:
    coverages = tuple(
        ProdEtfMinsFrequencyCoverage(
            trade_date=TRADE_DATE,
            source_freq=source_freq,
            expected_code_count=1,
            present_code_count=1 if ready else 0,
            missing_code_count=0 if ready else 1,
            missing_code_samples=() if ready else ("510300.SH",),
        )
        for source_freq in ETF_MINS_SOURCE_FREQS
    )
    return ProdEtfMinsCodeCoverageProbe(
        ready=ready,
        reason_code=(
            "prod_etf_mins_code_coverage_ready"
            if ready
            else "prod_etf_mins_code_coverage_incomplete"
        ),
        frequency_coverages=coverages,
        first_incomplete_trade_date=None if ready else TRADE_DATE,
        first_incomplete_source_freq=None if ready else "1min",
        elapsed_ms=1,
    )


def test_daily_readiness_builds_a_small_fingerprinted_five_frequency_reference() -> None:
    targets = _requestable_targets()
    basic_reference = _basic_reference(targets)
    with patch(
        "orchestrator.defs.asset_guards.etf_mins_prod_readiness."
        "probe_prod_etf_mins_code_coverage",
        return_value=_coverage_probe(),
    ) as coverage_probe:
        result = etf_mins_prod_source_ready_for_trade_date(
            prod_postgres=object(),
            trade_date=TRADE_DATE,
            basic_reference=basic_reference,
            requestable_targets=targets,
            observed_at=datetime.fromisoformat("2026-09-30T20:00:00+08:00"),
        )

    assert coverage_probe.call_count == 1
    assert result.ready is True
    assert result.coverage_reference is not None
    reference = result.coverage_reference
    assert reference.trade_date == TRADE_DATE
    assert reference.basic_reference_fingerprint == (
        basic_reference.reference_fingerprint
    )
    assert reference.expected_code_count == 1
    assert tuple(item[0] for item in reference.frequency_coverages) == (
        ETF_MINS_SOURCE_FREQS
    )
    payload = reference.to_config_dict()
    assert "ts_codes" not in payload
    assert "storage_id" not in repr(payload)
    assert EtfMinsProdCoverageReference.from_config_mapping(payload) == reference

    assert (
        validate_etf_mins_prod_coverage_reference(
            partition_key=TRADE_DATE,
            basic_reference=basic_reference,
            requestable_targets=targets,
            coverage_reference=reference,
        )
        == reference
    )


def test_daily_readiness_fails_closed_for_basic_drift_or_incomplete_coverage() -> None:
    targets = _requestable_targets()
    basic_reference = _basic_reference(targets)
    changed_targets = targets + (
        EtfMinsRequestableTarget(
            ts_code="512000.SH",
            list_date=date(2013, 1, 1),
            exchange="SH",
        ),
    )
    with patch(
        "orchestrator.defs.asset_guards.etf_mins_prod_readiness."
        "probe_prod_etf_mins_code_coverage"
    ) as coverage_probe:
        drifted = etf_mins_prod_source_ready_for_trade_date(
            prod_postgres=object(),
            trade_date=TRADE_DATE,
            basic_reference=basic_reference,
            requestable_targets=changed_targets,
            observed_at=datetime.fromisoformat("2026-09-30T20:00:00+08:00"),
        )
    assert drifted.ready is False
    assert drifted.reason_code == "etf_basic_reference_changed"
    coverage_probe.assert_not_called()

    with patch(
        "orchestrator.defs.asset_guards.etf_mins_prod_readiness."
        "probe_prod_etf_mins_code_coverage",
        return_value=_coverage_probe(ready=False),
    ):
        incomplete = etf_mins_prod_source_ready_for_trade_date(
            prod_postgres=object(),
            trade_date=TRADE_DATE,
            basic_reference=basic_reference,
            requestable_targets=targets,
            observed_at=datetime.fromisoformat("2026-09-30T20:00:00+08:00"),
        )
    assert incomplete.ready is False
    assert incomplete.coverage_reference is None
    assert incomplete.reason_code == "prod_etf_mins_code_coverage_incomplete"


def _minute_row(
    *,
    ts_code: str,
    trade_time: str,
    freq: str = "1min",
    exchange: str | None = None,
) -> list[object]:
    source_exchange = exchange or ("XSHG" if ts_code.endswith(".SH") else "XSHE")
    return [
        ts_code,
        freq,
        datetime.fromisoformat(trade_time),
        10.0,
        10.1,
        10.2,
        9.9,
        100,
        1000.0,
        10.05,
        source_exchange,
    ]


def _create_validation_relations(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_rows: list[list[object]],
    candidate_rows: list[list[object]],
    requestable_rows: tuple[tuple[object, ...], ...] | None = None,
    basic_codes: tuple[str, ...] = ("510300.SH", "159915.SZ"),
    existing_codes: tuple[str, ...] = (),
) -> None:
    raw_schema = """
      ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
      open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
      vol BIGINT, amount DOUBLE, vwap DOUBLE, exchange VARCHAR
    """
    connection.execute(f"CREATE TABLE source_rows ({raw_schema})")
    connection.execute(f"CREATE TABLE candidate_rows ({raw_schema})")
    placeholders = ", ".join("?" for _ in range(11))
    if source_rows:
        connection.executemany(
            f"INSERT INTO source_rows VALUES ({placeholders})",
            source_rows,
        )
    if candidate_rows:
        connection.executemany(
            f"INSERT INTO candidate_rows VALUES ({placeholders})",
            candidate_rows,
        )
    connection.execute("CREATE TABLE basic_all (ts_code VARCHAR)")
    connection.executemany(
        "INSERT INTO basic_all VALUES (?)",
        [(code,) for code in basic_codes],
    )
    connection.execute(
        "CREATE TABLE requestable_targets (ts_code VARCHAR, list_date DATE)"
    )
    rows = requestable_rows or (
        ("510300.SH", date(2012, 5, 28)),
        ("159915.SZ", date(2026, 9, 1)),
    )
    connection.executemany(
        "INSERT INTO requestable_targets VALUES (?, ?)",
        rows,
    )
    connection.execute("CREATE TABLE existing_target (ts_code VARCHAR)")
    if existing_codes:
        connection.executemany(
            "INSERT INTO existing_target VALUES (?)",
            [(code,) for code in existing_codes],
        )


def _evaluate_candidate(
    *,
    source_rows: list[list[object]],
    candidate_rows: list[list[object]],
    requestable_rows: tuple[tuple[object, ...], ...] | None = None,
    basic_codes: tuple[str, ...] = ("510300.SH", "159915.SZ"),
    existing_codes: tuple[str, ...] = (),
):
    with duckdb.connect(":memory:") as connection:
        _create_validation_relations(
            connection,
            source_rows=source_rows,
            candidate_rows=candidate_rows,
            requestable_rows=requestable_rows,
            basic_codes=basic_codes,
            existing_codes=existing_codes,
        )
        return evaluate_etf_mins_raw_candidate(
            connection=connection,
            source_relation="source_rows",
            candidate_relation="candidate_rows",
            basic_all_relation="basic_all",
            requestable_targets_relation="requestable_targets",
            existing_target_relation="existing_target",
            trade_date=TRADE_DATE,
            source_freq="1min",
        )


def test_raw_validator_reports_six_sets_and_keeps_grid_unclassified() -> None:
    rows = [
        _minute_row(ts_code="510300.SH", trade_time="2026-08-28T09:30:00"),
        _minute_row(ts_code="510300.SH", trade_time="2026-08-28T09:32:00"),
        _minute_row(ts_code="159915.SZ", trade_time="2026-08-28T09:30:00"),
    ]
    result = _evaluate_candidate(source_rows=rows, candidate_rows=rows)

    assert result.promotion_allowed is True
    assert result.silver_eligible is False
    assert result.policy_state == ETF_MINS_RAW_POLICY_STATE_UNCLASSIFIED
    assert result.stable_blocking_reason_codes == ()
    assert result.expected_count == 1
    assert result.present_count == 2
    assert result.missing_count == 0
    assert result.known_non_required_present_count == 1
    assert result.known_non_required_samples == ("159915.SZ",)
    assert result.retained_legacy_count == 0
    assert result.unexplained_new_count == 0
    assert result.grid_gap_candidate_count == 1


def test_missing_and_domain_anomalies_are_diagnostics_not_raw_blockers() -> None:
    invalid = _minute_row(
        ts_code="510300.SH",
        trade_time="2026-08-28T18:00:00",
    )
    invalid[3] = None
    invalid[7] = -1
    invalid[9] = None
    requestable_rows = (
        ("510300.SH", date(2012, 5, 28)),
        ("512000.SH", date(2013, 1, 1)),
    )
    result = _evaluate_candidate(
        source_rows=[invalid],
        candidate_rows=[invalid],
        requestable_rows=requestable_rows,
        basic_codes=("510300.SH", "512000.SH"),
    )

    assert result.promotion_allowed is True
    assert result.silver_eligible is False
    assert result.missing_count == 1
    assert result.missing_samples == ("512000.SH",)
    assert result.invalid_ohlc_count == 1
    assert result.invalid_volume_amount_count == 1
    assert result.invalid_vwap_count == 1
    assert result.off_session_time_count == 1


def test_unexplained_new_and_transport_mismatch_block_raw_promotion() -> None:
    known = _minute_row(ts_code="510300.SH", trade_time="2026-08-28T09:30:00")
    unknown = _minute_row(ts_code="512999.SH", trade_time="2026-08-28T09:30:00")
    unexplained = _evaluate_candidate(
        source_rows=[known, unknown],
        candidate_rows=[known, unknown],
    )
    assert unexplained.promotion_allowed is False
    assert unexplained.unexplained_new_count == 1
    assert unexplained.unexplained_new_samples == ("512999.SH",)
    assert "etf_mins_unexplained_new_code" in (
        unexplained.stable_blocking_reason_codes
    )

    transport = _evaluate_candidate(
        source_rows=[known, unknown],
        candidate_rows=[known],
    )
    assert transport.promotion_allowed is False
    assert "etf_mins_raw_transport_mismatch" in (
        transport.stable_blocking_reason_codes
    )


def test_retained_legacy_is_classified_without_becoming_unexplained_new() -> None:
    legacy = _minute_row(ts_code="512999.SH", trade_time="2026-08-28T09:30:00")
    result = _evaluate_candidate(
        source_rows=[legacy],
        candidate_rows=[legacy],
        existing_codes=("512999.SH",),
    )

    assert result.promotion_allowed is True
    assert result.retained_legacy_count == 1
    assert result.retained_legacy_samples == ("512999.SH",)
    assert result.unexplained_new_count == 0


@pytest.mark.parametrize(
    "mutation",
    ("duplicate", "null_key", "wrong_date", "wrong_freq", "wrong_exchange"),
)
def test_stable_key_partition_and_identity_failures_block(mutation: str) -> None:
    row = _minute_row(ts_code="510300.SH", trade_time="2026-08-28T09:30:00")
    rows = [row]
    if mutation == "duplicate":
        rows.append(deepcopy(row))
    elif mutation == "null_key":
        row[0] = None
    elif mutation == "wrong_date":
        row[2] = datetime.fromisoformat("2026-08-27T09:30:00")
    elif mutation == "wrong_freq":
        row[1] = "5min"
    else:
        row[10] = "XSHE"

    result = _evaluate_candidate(source_rows=rows, candidate_rows=rows)
    assert result.promotion_allowed is False
    assert result.stable_blocking_reason_codes


def test_raw_validator_rejects_schema_drift_before_summary_query() -> None:
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE source_rows (ts_code VARCHAR)")
        connection.execute("CREATE TABLE candidate_rows (ts_code VARCHAR)")
        connection.execute("CREATE TABLE basic_all (ts_code VARCHAR)")
        connection.execute(
            "CREATE TABLE requestable_targets (ts_code VARCHAR, list_date DATE)"
        )

        with pytest.raises(ValueError, match="11-column"):
            evaluate_etf_mins_raw_candidate(
                connection=connection,
                source_relation="source_rows",
                candidate_relation="candidate_rows",
                basic_all_relation="basic_all",
                requestable_targets_relation="requestable_targets",
                trade_date=TRADE_DATE,
                source_freq="1min",
            )
