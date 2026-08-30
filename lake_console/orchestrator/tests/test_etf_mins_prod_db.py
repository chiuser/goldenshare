from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Self

import pytest

from orchestrator.defs.prod_db.etf_mins import (
    PROD_ETF_MINS_COVERAGE_SQL,
    PROD_ETF_MINS_DUCKDB_ATTACHED_DATABASE,
    PROD_ETF_MINS_SOURCE_TABLE,
    build_prod_etf_mins_duckdb_attach_sql,
    build_prod_etf_mins_duckdb_source_sql,
    build_prod_etf_mins_remote_query,
    load_prod_etf_mins_code_coverage,
    probe_prod_etf_mins_code_coverage,
    validate_prod_etf_mins_duckdb_contract,
    validate_prod_etf_mins_select_contract,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_SOURCE_COLUMNS,
    EtfMinsRequestableTarget,
)


class _CoverageCursor:
    def __init__(
        self,
        *,
        missing: set[tuple[str, str, str]] | None = None,
    ) -> None:
        self.missing = missing or set()
        self.execute_count = 0
        self.sql = ""
        self.params: tuple[object, ...] = ()
        self.rows: list[tuple[object, ...]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.execute_count += 1
        self.sql = sql
        self.params = params
        trade_dates, codes, list_dates, source_freqs, sample_limit = params
        self.rows = []
        for trade_date in trade_dates:
            normalized_date = date.fromisoformat(str(trade_date))
            expected_codes = sorted(
                str(code)
                for code, list_date in zip(codes, list_dates, strict=True)
                if list_date <= normalized_date
            )
            for source_freq in source_freqs:
                missing_codes = [
                    code
                    for code in expected_codes
                    if (normalized_date.isoformat(), str(source_freq), code)
                    in self.missing
                ]
                self.rows.append(
                    (
                        normalized_date,
                        source_freq,
                        len(expected_codes),
                        len(expected_codes) - len(missing_codes),
                        len(missing_codes),
                        missing_codes[: int(sample_limit)],
                    )
                )

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class _CoverageConnection:
    def __init__(self, cursor: _CoverageCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _CoverageCursor:
        return self._cursor


class _FakeProdPostgres:
    def __init__(self, cursor: _CoverageCursor) -> None:
        self._connection = _CoverageConnection(cursor)
        self.transaction_count = 0

    @contextmanager
    def connect_readonly_transaction(self):  # type: ignore[no-untyped-def]
        self.transaction_count += 1
        yield self._connection


def _targets(count: int = 2) -> tuple[EtfMinsRequestableTarget, ...]:
    targets = []
    for index in range(count):
        suffix = "SH" if index % 2 == 0 else "SZ"
        targets.append(
            EtfMinsRequestableTarget(
                ts_code=f"{510000 + index:06d}.{suffix}",
                list_date=date(2026, 8, 17) + timedelta(days=index),
                exchange=suffix,
            )
        )
    return tuple(targets)


def test_detail_sql_uses_only_the_approved_table_and_explicit_columns() -> None:
    remote_sql = build_prod_etf_mins_remote_query(
        source_freq="1min",
        start_datetime="2026-08-28 00:00:00",
        end_datetime="2026-08-29 00:00:00",
    )
    normalized = " ".join(remote_sql.lower().split())

    assert f"from {PROD_ETF_MINS_SOURCE_TABLE}" in normalized
    assert "select *" not in normalized
    assert " join " not in normalized
    assert "ts_code in" not in normalized
    assert "ts_code = any" not in normalized
    assert "ops." not in normalized
    assert "core_serving." not in normalized
    assert "%s" not in remote_sql
    assert "trade_time >= timestamp '2026-08-28 00:00:00'" in normalized
    assert "trade_time < timestamp '2026-08-29 00:00:00'" in normalized
    for column in ETF_MINS_SOURCE_COLUMNS:
        assert column in normalized
    validate_prod_etf_mins_select_contract()


def test_prod_module_has_no_task_run_serving_or_private_connection_path() -> None:
    module_path = Path(
        "src/orchestrator/defs/prod_db/etf_mins.py"
    )
    source = module_path.read_text(encoding="utf-8").lower()

    assert "task_run" not in source
    assert "core_serving" not in source
    assert "ops." not in source
    assert "connect_timeout" not in source
    assert "duckdb.connect" not in source


@pytest.mark.parametrize(
    ("source_freq", "start_datetime", "end_datetime"),
    (
        ("1min'; DROP TABLE raw_tushare.etf_minute_bar; --", "2026-08-28 00:00:00", "2026-08-29 00:00:00"),
        ("1min", "2026-08-28T00:00:00", "2026-08-29 00:00:00"),
        ("1min", "2026-08-28 00:00:00' OR true --", "2026-08-29 00:00:00"),
        ("1min", "2026-08-29 00:00:00", "2026-08-28 00:00:00"),
    ),
)
def test_detail_sql_rejects_noncanonical_or_injected_scope(
    source_freq: str,
    start_datetime: str,
    end_datetime: str,
) -> None:
    with pytest.raises(ValueError):
        build_prod_etf_mins_remote_query(
            source_freq=source_freq,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
        )


def test_duckdb_attach_is_read_only_and_conninfo_stays_out_of_source_sql() -> None:
    fake_conninfo = "host=fake.invalid user=fake password=not-a-secret"
    attach_sql = build_prod_etf_mins_duckdb_attach_sql(conninfo=fake_conninfo)
    source_sql = build_prod_etf_mins_duckdb_source_sql(
        source_freq="5min",
        start_datetime="2026-08-28 00:00:00",
        end_datetime="2026-08-29 00:00:00",
    )

    normalized_attach = " ".join(attach_sql.lower().replace(",", " ").split())
    assert "type postgres" in normalized_attach
    assert "read_only" in normalized_attach
    assert fake_conninfo in attach_sql
    assert fake_conninfo not in source_sql
    assert "postgres_query(" in source_sql
    assert PROD_ETF_MINS_DUCKDB_ATTACHED_DATABASE in source_sql
    validate_prod_etf_mins_duckdb_contract()


def test_one_evaluator_handles_one_day_and_ten_days_with_one_sql_each() -> None:
    targets = _targets()
    one_day_cursor = _CoverageCursor()
    one_day_prod = _FakeProdPostgres(one_day_cursor)

    one_day = load_prod_etf_mins_code_coverage(
        prod_postgres=one_day_prod,
        trade_dates=("2026-08-17",),
        requestable_targets=targets,
    )

    assert one_day_cursor.execute_count == 1
    assert one_day_prod.transaction_count == 1
    assert len(one_day) == 5
    assert {coverage.expected_code_count for coverage in one_day} == {1}
    assert all(coverage.ready for coverage in one_day)

    ten_dates = tuple(
        (date(2026, 8, 17) + timedelta(days=offset)).isoformat()
        for offset in range(10)
    )
    missing_key = (ten_dates[-1], "5min", targets[1].ts_code)
    ten_day_cursor = _CoverageCursor(missing={missing_key})
    ten_day_prod = _FakeProdPostgres(ten_day_cursor)
    ten_day = probe_prod_etf_mins_code_coverage(
        prod_postgres=ten_day_prod,
        trade_dates=ten_dates,
        requestable_targets=targets,
    )

    assert ten_day_cursor.execute_count == 1
    assert ten_day_prod.transaction_count == 1
    assert len(ten_day.frequency_coverages) == 50
    assert ten_day.ready is False
    assert ten_day.first_incomplete_trade_date == ten_dates[-1]
    assert ten_day.first_incomplete_source_freq == "5min"
    first_day_counts = {
        coverage.expected_code_count
        for coverage in ten_day.frequency_coverages
        if coverage.trade_date == ten_dates[0]
    }
    last_day_counts = {
        coverage.expected_code_count
        for coverage in ten_day.frequency_coverages
        if coverage.trade_date == ten_dates[-1]
    }
    assert first_day_counts == {1}
    assert last_day_counts == {2}


def test_coverage_samples_are_bounded_and_sql_is_one_index_presence_query() -> None:
    targets = _targets(25)
    trade_date = "2026-09-30"
    missing = {
        (trade_date, "60min", target.ts_code)
        for target in targets
    }
    cursor = _CoverageCursor(missing=missing)
    coverages = load_prod_etf_mins_code_coverage(
        prod_postgres=_FakeProdPostgres(cursor),
        trade_dates=(trade_date,),
        requestable_targets=targets,
    )

    sixty = next(item for item in coverages if item.source_freq == "60min")
    assert sixty.missing_code_count == 25
    assert len(sixty.missing_code_samples) == ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT
    assert cursor.execute_count == 1
    assert cursor.params[-1] == ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT
    normalized_sql = " ".join(cursor.sql.lower().split())
    assert "from raw_tushare.etf_minute_bar" in normalized_sql
    assert "exists ( select 1" in normalized_sql
    assert "limit 1" in normalized_sql
    assert "targets.list_date <= date_freqs.trade_date" in normalized_sql
    assert "ops." not in normalized_sql
    assert normalized_sql == " ".join(PROD_ETF_MINS_COVERAGE_SQL.lower().split())


def test_coverage_rejects_more_than_ten_dates_before_opening_prod() -> None:
    cursor = _CoverageCursor()
    prod = _FakeProdPostgres(cursor)
    eleven_dates = tuple(
        (date(2026, 8, 1) + timedelta(days=offset)).isoformat()
        for offset in range(11)
    )

    with pytest.raises(ValueError, match="at most ten"):
        load_prod_etf_mins_code_coverage(
            prod_postgres=prod,
            trade_dates=eleven_dates,
            requestable_targets=_targets(),
        )

    assert prod.transaction_count == 0
    assert cursor.execute_count == 0


def test_coverage_query_error_fails_closed_without_error_text_leakage() -> None:
    class _FailingProd:
        @contextmanager
        def connect_readonly_transaction(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("password=must-not-appear")
            yield

    result = probe_prod_etf_mins_code_coverage(
        prod_postgres=_FailingProd(),
        trade_dates=("2026-08-28",),
        requestable_targets=_targets(),
    )

    assert result.ready is False
    assert result.reason_code == "prod_etf_mins_source_query_error"
    assert result.error_type == "RuntimeError"
    assert "password" not in repr(result)
