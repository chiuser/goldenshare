from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap import (
    index_daily_000680_history_supplement_apply as apply,
)
from orchestrator.defs.bootstrap import (
    index_daily_000680_history_supplement_plan as plan,
)
from orchestrator.defs.duckdb_sql import INDEX_DAILY_RAW_COLUMNS
from tests._index_daily_000680_history_supplement_helpers import frozen_plan_payload


def _expected_dates() -> tuple[str, ...]:
    start = date.fromisoformat(plan.HISTORY_START_DATE)
    values = tuple(
        (start + timedelta(days=offset)).isoformat()
        for offset in range(plan.EXPECTED_HISTORY_DATE_COUNT - 1)
    )
    return (*values, plan.HISTORY_END_DATE)


def _row(trade_date: str, *, ts_code: str = plan.TARGET_CODE) -> tuple[object, ...]:
    values = {
        "ts_code": ts_code,
        "trade_date": trade_date.replace("-", ""),
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "pre_close": 10.0,
        "change": 0.5,
        "pct_chg": 5.0,
        "vol": 100.0,
        "amount": 1_000.0,
    }
    return tuple(values[column] for column in INDEX_DAILY_RAW_COLUMNS)


def test_source_audit_accepts_only_the_frozen_1223_date_contract() -> None:
    expected_dates = _expected_dates()
    audit = plan.build_source_audit(
        rows=tuple(_row(value) for value in expected_dates),
        expected_dates=expected_dates,
        boundary_close=10.5,
        following_pre_close=10.5,
    )

    assert audit.passed is True
    assert audit.row_count == plan.EXPECTED_HISTORY_DATE_COUNT
    assert audit.min_trade_date == plan.HISTORY_START_DATE
    assert audit.max_trade_date == plan.HISTORY_END_DATE
    assert audit.duplicate_key_count == 0
    assert audit.missing_date_samples == ()


def test_source_audit_fails_closed_for_duplicate_and_wrong_code() -> None:
    expected_dates = _expected_dates()
    rows = [_row(value) for value in expected_dates]
    rows[0] = _row(expected_dates[0], ts_code="000001.SH")
    rows.append(rows[1])

    audit = plan.build_source_audit(
        rows=rows,
        expected_dates=expected_dates,
        boundary_close=10.5,
        following_pre_close=10.5,
    )

    assert audit.passed is False
    assert audit.unexpected_code_count == 1
    assert audit.duplicate_key_count == 1


def test_frozen_plan_hash_covers_run_and_target_paths() -> None:
    payload = frozen_plan_payload()
    observed_hash = str(payload["plan_hash"])

    payload["run_id"] = "changed-run"
    assert plan.compute_frozen_plan_hash(payload) != observed_hash

    payload = frozen_plan_payload()
    targets = payload["targets"]
    assert isinstance(targets, dict)
    targets["raw_files"] = [
        "/Volumes/datasource/data_lake/raw/index_daily/trade_date=2020-01-03/part-000.parquet"
    ]
    targets["silver_files"] = [
        "/Volumes/datasource/data_lake/silver/index_daily/trade_date=2020-01-03/part-000.parquet"
    ]
    assert plan.compute_frozen_plan_hash(payload) != payload["plan_hash"]


def test_raw_layer_audit_uses_physical_trade_date_column(tmp_path: Path) -> None:
    raw_path = (
        tmp_path
        / "raw"
        / "index_daily"
        / "trade_date=2020-01-02"
        / "part-000.parquet"
    )
    with duckdb.connect(":memory:") as connection:
        apply._write_source_staging(
            connection=connection,
            rows=(_row("2020-01-02"),),
            target_path=raw_path,
        )
        audit = plan._audit_layer(connection, layer="raw", paths=(raw_path,))

    assert audit.target_row_count == 1
    assert audit.target_distinct_date_count == 1
    assert audit.target_duplicate_date_count == 0


def test_supplement_code_has_no_forbidden_source_or_lake_paths() -> None:
    bootstrap_dir = Path(plan.__file__).parent
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in bootstrap_dir.glob("index_daily_000680_history_supplement*.py")
    ).lower()

    assert "kopia" not in sources
    assert "tushare.pro_api" not in sources
    assert "/data/goldenshare" not in sources
    assert "major_index_mins" not in sources
    assert "update core_serving" not in sources
    assert "delete from core_serving" not in sources
