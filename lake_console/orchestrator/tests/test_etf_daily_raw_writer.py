from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import orchestrator.defs.io.etf_daily_raw_writer as raw_writer
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawValidationError,
    audit_etf_daily_raw_relation,
    write_fund_adj_raw_partition,
    write_fund_daily_raw_partition,
)
from orchestrator.defs.paths import raw_fund_adj_path, raw_fund_daily_path
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.run_contracts.etf_daily import (
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_SOURCE_COLUMNS,
)
from orchestrator.defs.tushare_request_policy import BoundedPageRequestResult

PARTITION = "2026-09-01"
SOURCE_DATE = "20260901"


def _fund_daily_row(
    ts_code: str = "510330.SH",
    *,
    close: float = 4.01,
    trade_date: str = SOURCE_DATE,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
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


def _fund_adj_row(
    index: int,
    *,
    discount_rate: float | None = 0.0,
    trade_date: str = SOURCE_DATE,
) -> dict[str, object]:
    return {
        "ts_code": f"{index:06d}.SH",
        "trade_date": trade_date,
        "adj_factor": 1.0,
        "discount_rate": discount_rate,
    }


class FakeTushare:
    def __init__(
        self,
        pages: Mapping[int, Sequence[Mapping[str, object]]],
        *,
        columns: tuple[str, ...],
    ) -> None:
        self.pages = {offset: [dict(row) for row in rows] for offset, rows in pages.items()}
        self.columns = columns
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(
        self,
        api_name: str,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> TushareResult:
        copied_params = dict(params)
        self.calls.append((api_name, copied_params, tuple(fields)))
        offset = int(copied_params["offset"])
        return TushareResult(
            rows=list(self.pages.get(offset, ())),
            columns=self.columns,
            metadata={},
        )


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    return lake_root, staging_root


def _write_daily(
    *,
    lake_root: Path,
    staging_root: Path,
    tushare: FakeTushare,
    operation_id: str = "run-1",
):
    return write_fund_daily_raw_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        tushare=tushare,  # type: ignore[arg-type]
        partition_key=PARTITION,
        operation_id=operation_id,
    )


def test_fund_daily_short_page_writes_every_source_row_including_of(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    rows = [_fund_daily_row(), _fund_daily_row("158008.OF")]
    tushare = FakeTushare({0: rows}, columns=FUND_DAILY_SOURCE_COLUMNS)

    result = _write_daily(
        lake_root=lake_root,
        staging_root=staging_root,
        tushare=tushare,
    )

    assert result.write_mode == "write_new"
    assert result.source_row_count == result.normalized_row_count == 2
    assert result.candidate_row_count == result.written_row_count == 2
    assert result.page_count == result.request_count == 1
    assert result.page_offsets == (0,)
    assert len(result.content_hash) == 64
    assert result.target_path == raw_fund_daily_path(lake_root, PARTITION)
    assert result.target_path.is_file()
    assert not result.staging_path.exists()
    assert tushare.calls == [
        (
            "fund_daily",
            {"trade_date": SOURCE_DATE, "limit": 5_000, "offset": 0},
            FUND_DAILY_SOURCE_COLUMNS,
        )
    ]
    with DuckDBResource().connect() as connection:
        codes = connection.execute(
            f"SELECT ts_code FROM {read_parquet(result.target_path, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall()
    assert codes == [("158008.OF",), ("510330.SH",)]


def test_fund_adj_two_pages_preserve_nullable_and_extreme_discount_rate(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    first_page = [_fund_adj_row(index) for index in range(2_000)]
    second_page = [_fund_adj_row(2_000, discount_rate=9_940.7)]
    first_page[0]["discount_rate"] = None
    tushare = FakeTushare(
        {0: first_page, 2_000: second_page},
        columns=FUND_ADJ_SOURCE_COLUMNS,
    )

    result = write_fund_adj_raw_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        tushare=tushare,  # type: ignore[arg-type]
        partition_key=PARTITION,
        operation_id="run-1",
    )

    assert result.write_mode == "write_new"
    assert result.source_row_count == result.written_row_count == 2_001
    assert result.page_count == result.request_count == 2
    assert result.page_offsets == (0, 2_000)
    assert [call[1]["offset"] for call in tushare.calls] == [0, 2_000]
    with DuckDBResource().connect() as connection:
        values = connection.execute(
            f"""
            SELECT
              count(*) FILTER (WHERE discount_rate IS NULL),
              max(discount_rate)
            FROM {read_parquet(result.target_path, hive_partitioning=False)}
            """
        ).fetchone()
    assert values == (1, 9_940.7)


@pytest.mark.parametrize(
    ("pages", "columns", "message"),
    [
        ({0: [_fund_daily_row(trade_date="20260829")]}, FUND_DAILY_SOURCE_COLUMNS, "partition date"),
        ({0: [_fund_daily_row(ts_code="")]}, FUND_DAILY_SOURCE_COLUMNS, "invalid key"),
        ({0: []}, FUND_DAILY_SOURCE_COLUMNS, "returned no rows"),
        ({0: [_fund_daily_row()]}, FUND_DAILY_SOURCE_COLUMNS[:-1], "schema_drift"),
    ],
)
def test_writer_fails_closed_before_promotion(
    tmp_path: Path,
    pages: Mapping[int, Sequence[Mapping[str, object]]],
    columns: tuple[str, ...],
    message: str,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    tushare = FakeTushare(pages, columns=columns)

    with pytest.raises(EtfDailyRawValidationError, match=message):
        _write_daily(
            lake_root=lake_root,
            staging_root=staging_root,
            tushare=tushare,
        )

    assert not raw_fund_daily_path(lake_root, PARTITION).exists()
    assert not tuple(staging_root.rglob("*.parquet"))


def test_cross_page_duplicate_key_fails_without_promotion(tmp_path: Path) -> None:
    lake_root, staging_root = _roots(tmp_path)
    first_page = [_fund_adj_row(index) for index in range(2_000)]
    tushare = FakeTushare(
        {0: first_page, 2_000: [dict(first_page[0])]},
        columns=FUND_ADJ_SOURCE_COLUMNS,
    )

    with pytest.raises(EtfDailyRawValidationError, match="duplicate row"):
        write_fund_adj_raw_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            tushare=tushare,  # type: ignore[arg-type]
            partition_key=PARTITION,
            operation_id="run-1",
        )

    assert not raw_fund_adj_path(lake_root, PARTITION).exists()


def test_budget_failure_result_never_promotes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    tushare = FakeTushare({0: [_fund_daily_row()]}, columns=FUND_DAILY_SOURCE_COLUMNS)
    monkeypatch.setattr(
        raw_writer,
        "execute_bounded_pages",
        lambda **_kwargs: BoundedPageRequestResult(
            rows=(),
            page_count=1,
            page_offsets=(0,),
            failed_pages=(),
            request_count=2,
            retry_count=1,
            elapsed_ms=30_000.0,
            budget_exceeded=True,
            budget_reason="request_budget_exceeded",
        ),
    )

    with pytest.raises(EtfDailyRawValidationError, match="request_budget_exceeded"):
        _write_daily(
            lake_root=lake_root,
            staging_root=staging_root,
            tushare=tushare,
        )

    assert not raw_fund_daily_path(lake_root, PARTITION).exists()


def test_equivalent_existing_target_is_reused_without_rewrite(tmp_path: Path) -> None:
    lake_root, staging_root = _roots(tmp_path)
    rows = [_fund_daily_row(), _fund_daily_row("158008.OF")]
    first = _write_daily(
        lake_root=lake_root,
        staging_root=staging_root,
        tushare=FakeTushare({0: rows}, columns=FUND_DAILY_SOURCE_COLUMNS),
    )
    original_mtime = first.target_path.stat().st_mtime_ns

    second_source = FakeTushare(
        {0: list(reversed(rows))},
        columns=FUND_DAILY_SOURCE_COLUMNS,
    )
    second = _write_daily(
        lake_root=lake_root,
        staging_root=staging_root,
        tushare=second_source,
        operation_id="run-2",
    )

    assert second.write_mode == "reuse_existing"
    assert second.content_hash == first.content_hash
    assert second.target_path.stat().st_mtime_ns == original_mtime
    assert len(second_source.calls) == 1


def test_conflicting_existing_target_is_never_overwritten(tmp_path: Path) -> None:
    lake_root, staging_root = _roots(tmp_path)
    first = _write_daily(
        lake_root=lake_root,
        staging_root=staging_root,
        tushare=FakeTushare(
            {0: [_fund_daily_row(close=4.01)]},
            columns=FUND_DAILY_SOURCE_COLUMNS,
        ),
    )
    original_bytes = first.target_path.read_bytes()

    with pytest.raises(EtfDailyRawValidationError, match="conflicts"):
        _write_daily(
            lake_root=lake_root,
            staging_root=staging_root,
            tushare=FakeTushare(
                {0: [_fund_daily_row(close=4.02)]},
                columns=FUND_DAILY_SOURCE_COLUMNS,
            ),
            operation_id="run-2",
        )

    assert first.target_path.read_bytes() == original_bytes
    assert not tuple(staging_root.rglob("*.parquet"))


def test_content_hash_is_order_independent_and_value_sensitive() -> None:
    rows = [_fund_daily_row(), _fund_daily_row("158008.OF")]
    with DuckDBResource().connect() as connection:
        import pandas as pd

        connection.register(
            "rows_forward",
            pd.DataFrame.from_records(rows, columns=FUND_DAILY_SOURCE_COLUMNS),
        )
        connection.register(
            "rows_reverse",
            pd.DataFrame.from_records(
                list(reversed(rows)), columns=FUND_DAILY_SOURCE_COLUMNS
            ),
        )
        changed = [dict(row) for row in rows]
        changed[0]["amount"] = 401.0
        connection.register(
            "rows_changed",
            pd.DataFrame.from_records(changed, columns=FUND_DAILY_SOURCE_COLUMNS),
        )
        audits = [
            audit_etf_daily_raw_relation(
                connection,
                relation_sql=(
                    "SELECT "
                    + ", ".join(
                        f'CAST("{column}" AS {FUND_DAILY_RAW_SPEC.raw_column_types[column]}) AS "{column}"'
                        for column in FUND_DAILY_SOURCE_COLUMNS
                    )
                    + f" FROM {relation_name}"
                ),
                spec=FUND_DAILY_RAW_SPEC,
                partition_key=PARTITION,
            )
            for relation_name in ("rows_forward", "rows_reverse", "rows_changed")
        ]

    assert audits[0].error_codes == audits[1].error_codes == audits[2].error_codes == ()
    assert audits[0].content_hash == audits[1].content_hash
    assert audits[0].content_hash != audits[2].content_hash


def test_writer_rejects_missing_roots_staging_residue_and_cross_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    tushare = FakeTushare({0: [_fund_daily_row()]}, columns=FUND_DAILY_SOURCE_COLUMNS)
    with pytest.raises(EtfDailyRawValidationError, match="must already exist"):
        _write_daily(
            lake_root=lake_root,
            staging_root=staging_root,
            tushare=tushare,
        )

    lake_root.mkdir()
    staging_root.mkdir()
    original_stat = Path.stat

    class _StatProxy:
        def __init__(self, delegate, st_dev: int) -> None:  # type: ignore[no-untyped-def]
            self._delegate = delegate
            self.st_dev = st_dev

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(self._delegate, name)

    def fake_stat(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = original_stat(path, *args, **kwargs)
        if path == staging_root:
            return _StatProxy(result, result.st_dev + 1)
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(EtfDailyRawValidationError, match="share one filesystem"):
        _write_daily(
            lake_root=lake_root,
            staging_root=staging_root,
            tushare=tushare,
        )

    monkeypatch.setattr(Path, "stat", original_stat)
    staging_path = FUND_DAILY_RAW_SPEC.staging_path_builder(
        staging_root, "run-1", PARTITION
    )
    staging_path.parent.mkdir(parents=True)
    staging_path.write_bytes(b"residue")
    with pytest.raises(EtfDailyRawValidationError, match="already exists"):
        _write_daily(
            lake_root=lake_root,
            staging_root=staging_root,
            tushare=tushare,
        )
