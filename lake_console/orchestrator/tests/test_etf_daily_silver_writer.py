from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    EtfDailySilverValidationError,
    write_etf_adj_factor_silver_partition,
    write_etf_daily_silver_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF,
    classify_etf_basic_requestability,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_REJECTION_REASON_CODES,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_SOURCE_COLUMNS,
    classify_etf_daily_source_row,
)
from tests.etf_daily_test_support import (
    basic_row,
    make_roots,
    write_basic_reference,
    write_raw_fixture,
)

PARTITION = "2026-09-01"
SOURCE_DATE = "20260901"


def _daily_row(ts_code: str, *, close: float = 4.01) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": SOURCE_DATE,
        "pre_close": 4.0,
        "open": 4.0,
        "high": 4.02,
        "low": 3.99,
        "close": close,
        "change": close - 4.0,
        "pct_chg": (close - 4.0) / 4.0 * 100,
        "vol": 100.0,
        "amount": 400.0,
    }


def _adj_row(
    ts_code: str,
    *,
    adj_factor: float = 1.0,
    discount_rate: float | None = 0.0,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": SOURCE_DATE,
        "adj_factor": adj_factor,
        "discount_rate": discount_rate,
    }


@pytest.mark.parametrize(
    ("ts_code", "basic", "expected"),
    [
        ("158008.OF", None, "NON_EXCHANGE_SUFFIX"),
        ("510330.SH", None, "BASIC_CODE_ABSENT"),
        (
            "510330.SH",
            basic_row("510330.SH", exchange="SZ"),
            "EXCHANGE_MISMATCH",
        ),
        (
            "510330.SH",
            basic_row("510330.SH", list_status="D"),
            "STATUS_NOT_LISTED",
        ),
        (
            "510330.SH",
            basic_row("510330.SH", list_date=None),
            "LIST_DATE_NULL",
        ),
        (
            "510330.SH",
            basic_row("510330.SH", list_date="20260902"),
            "LIST_DATE_AFTER_TRADE_DATE",
        ),
        ("510330.SH", basic_row("510330.SH"), None),
    ],
)
def test_classification_has_fixed_priority_and_matches_basic_semantics(
    ts_code: str,
    basic: dict[str, object] | None,
    expected: str | None,
) -> None:
    normalized_basic = dict(basic) if basic is not None else None
    if normalized_basic is not None and isinstance(
        normalized_basic.get("list_date"), str
    ):
        normalized_basic["list_date"] = date.fromisoformat(
            f"{normalized_basic['list_date'][:4]}-"
            f"{normalized_basic['list_date'][4:6]}-"
            f"{normalized_basic['list_date'][6:]}"
        )
    observed = classify_etf_daily_source_row(
        ts_code=ts_code,
        trade_date=date(2026, 9, 1),
        basic_row=normalized_basic,
    )
    assert observed == expected
    if normalized_basic is not None and expected not in {
        "BASIC_CODE_ABSENT",
        "NON_EXCHANGE_SUFFIX",
    }:
        basic_reason = classify_etf_basic_requestability(
            normalized_basic,
            eligibility_as_of=date(2026, 9, 1),
        )
        assert observed == {
            None: None,
            "EXCHANGE_MISMATCH": "EXCHANGE_MISMATCH",
            "STATUS_NOT_LISTED": "STATUS_NOT_LISTED",
            "LIST_DATE_NULL": "LIST_DATE_NULL",
            ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF: (
                "LIST_DATE_AFTER_TRADE_DATE"
            ),
        }[basic_reason]


def test_daily_writer_filters_with_frozen_basic_and_only_casts_date(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(
            basic_row("510330.SH"),
            basic_row("159919.SZ"),
            basic_row("512000.SH", list_status="D"),
            basic_row("513000.SH", list_status="P"),
            basic_row("515000.SH", list_date=None),
            basic_row("516000.SH", list_date="20260902"),
            basic_row("158008.OF"),
        ),
    )
    rows = (
        _daily_row("510330.SH"),
        _daily_row("159919.SZ", close=3.99),
        _daily_row("512000.SH"),
        _daily_row("513000.SH"),
        _daily_row("515000.SH"),
        _daily_row("516000.SH"),
        _daily_row("588000.SH"),
        _daily_row("158008.OF"),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=PARTITION,
        rows=rows,
    )

    result = write_etf_daily_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="daily-silver",
        basic_reference=reference,
    )

    assert result.write_mode == "write_new"
    assert result.raw_row_count == 8
    assert result.selected_row_count == result.written_row_count == 2
    assert result.rejected_row_count == 6
    assert set(result.reason_counts) == set(ETF_DAILY_REJECTION_REASON_CODES)
    assert result.reason_counts == {
        "NON_EXCHANGE_SUFFIX": 1,
        "BASIC_CODE_ABSENT": 1,
        "EXCHANGE_MISMATCH": 0,
        "STATUS_NOT_LISTED": 2,
        "LIST_DATE_NULL": 1,
        "LIST_DATE_AFTER_TRADE_DATE": 1,
    }
    assert not result.staging_path.exists()
    details = result.to_details()
    assert details["basic_reference_fingerprint"] == reference.reference_fingerprint
    assert details["basic_reference"] == reference.model_dump(mode="json")
    with DuckDBResource().connect() as connection:
        description = connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(result.target_path, hive_partitioning=False)}"
        ).fetchall()
        output = connection.execute(
            f"SELECT * FROM {read_parquet(result.target_path, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall()
    assert tuple(row[0] for row in description) == FUND_DAILY_SOURCE_COLUMNS
    assert tuple(str(row[1]).upper() for row in description) == (
        "VARCHAR",
        "DATE",
        *("DOUBLE" for _ in FUND_DAILY_SOURCE_COLUMNS[2:]),
    )
    assert [row[0] for row in output] == ["159919.SZ", "510330.SH"]
    source_by_code = {str(row["ts_code"]): row for row in rows}
    for output_row in output:
        source = source_by_code[str(output_row[0])]
        assert str(output_row[1]) == PARTITION
        assert output_row[2:] == tuple(source[column] for column in FUND_DAILY_SOURCE_COLUMNS[2:])
    assert "change" in FUND_DAILY_SOURCE_COLUMNS
    assert "change_amount" not in FUND_DAILY_SOURCE_COLUMNS


def test_adj_writer_preserves_nullable_negative_and_extreme_discount_rate(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    codes = ("510330.SH", "159919.SZ", "512000.SH")
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=tuple(basic_row(code) for code in codes),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=PARTITION,
        rows=(
            _adj_row(codes[0], discount_rate=None),
            _adj_row(codes[1], discount_rate=-3.5),
            _adj_row(codes[2], discount_rate=9_940.7),
        ),
    )

    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="adj-silver",
        basic_reference=reference,
    )

    with DuckDBResource().connect() as connection:
        output = connection.execute(
            f"SELECT ts_code, discount_rate FROM {read_parquet(result.target_path, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall()
        columns = tuple(
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {read_parquet(result.target_path, hive_partitioning=False)}"
            ).fetchall()
        )
    assert result.raw_row_count == result.selected_row_count == result.written_row_count == 3
    assert columns == FUND_ADJ_SOURCE_COLUMNS
    assert output == [
        ("159919.SZ", -3.5),
        ("510330.SH", None),
        ("512000.SH", 9_940.7),
    ]


def test_equivalent_reuse_and_changed_basic_conflict_never_overwrite(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(basic_row("510330.SH"),),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=PARTITION,
        rows=(_daily_row("510330.SH"),),
    )
    first = write_etf_daily_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="first",
        basic_reference=reference,
    )
    original_bytes = first.target_path.read_bytes()
    original_mtime = first.target_path.stat().st_mtime_ns

    reused = write_etf_daily_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="reuse",
        basic_reference=reference,
    )
    assert reused.write_mode == "reuse_existing"
    assert first.target_path.stat().st_mtime_ns == original_mtime

    changed_reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(basic_row("510330.SH", list_status="D"),),
    )
    with pytest.raises(EtfDailySilverValidationError, match="conflicts"):
        write_etf_daily_silver_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            partition_key=PARTITION,
            operation_id="changed-basic",
            basic_reference=changed_reference,
        )
    assert first.target_path.read_bytes() == original_bytes


def test_basic_reference_path_or_content_drift_fails_before_promotion(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(basic_row("510330.SH"),),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=PARTITION,
        rows=(_daily_row("510330.SH"),),
    )
    wrong_path_reference = reference.model_copy(
        update={"silver_uri": str(lake_root / "silver" / "wrong.parquet")}
    )
    with pytest.raises(EtfDailySilverValidationError, match="could not be validated"):
        write_etf_daily_silver_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            partition_key=PARTITION,
            operation_id="wrong-path",
            basic_reference=wrong_path_reference,
        )

    basic_path = Path(reference.silver_uri)
    replacement = basic_path.with_name("replacement.parquet")
    with DuckDBResource().connect() as connection:
        connection.execute(
            f"COPY (SELECT * REPLACE ('D' AS list_status) FROM {read_parquet(basic_path, hive_partitioning=False)}) "
            f"TO '{replacement.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    replacement.replace(basic_path)
    with pytest.raises(EtfDailySilverValidationError, match="content failed"):
        write_etf_daily_silver_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            partition_key=PARTITION,
            operation_id="changed-content",
            basic_reference=reference,
        )
