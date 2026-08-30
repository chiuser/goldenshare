from __future__ import annotations

import inspect
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import pytest

from orchestrator.defs import tushare_api_io
from orchestrator.defs.assets import etf_basic as etf_basic_assets
from orchestrator.defs.assets.etf_basic import (
    EtfBasicSnapshotValidationError,
    audit_etf_basic_raw_snapshot,
    build_etf_basic_raw_materialization_metadata,
    write_etf_basic_raw_snapshot,
)
from orchestrator.defs.paths import raw_etf_basic_snapshot_path
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_PAGE_LIMIT,
    ETF_BASIC_SOURCE_API,
    ETF_BASIC_SOURCE_COLUMNS,
)


class TestDuckDBResource:
    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with duckdb.connect(":memory:") as connection:
            yield connection


class FakeTushare:
    def __init__(
        self,
        pages: Mapping[int, Sequence[dict[str, object]]],
        *,
        columns_by_offset: Mapping[int, tuple[str, ...]] | None = None,
        error_offsets: Sequence[int] = (),
    ) -> None:
        self.pages = {offset: list(rows) for offset, rows in pages.items()}
        self.columns_by_offset = dict(columns_by_offset or {})
        self.error_offsets = set(error_offsets)
        self.calls: list[tuple[str, dict[str, Any], tuple[str, ...]]] = []

    def call(
        self,
        api_name: str,
        params: Mapping[str, Any] | None,
        fields: Sequence[str],
    ) -> TushareResult:
        request_params = dict(params or {})
        field_names = tuple(fields)
        self.calls.append((api_name, request_params, field_names))
        offset = int(request_params["offset"])
        if offset in self.error_offsets:
            raise RuntimeError(f"fake source failure at offset={offset}")
        return TushareResult(
            rows=self.pages.get(offset, []),
            columns=self.columns_by_offset.get(offset, field_names),
            metadata={},
        )


def _row(
    code: str = "510300.SH",
    *,
    list_status: str = "L",
    exchange: str | None = "SH",
    mgt_fee: float | None = 0.5,
) -> dict[str, object]:
    return {
        "ts_code": code,
        "csname": f"ETF-{code}",
        "extname": None,
        "cname": None,
        "index_code": None,
        "index_name": None,
        "setup_date": "20120504",
        "list_date": "20120528",
        "list_status": list_status,
        "exchange": exchange,
        "mgr_name": None,
        "custod_name": None,
        "mgt_fee": mgt_fee,
        "etf_type": "境内",
    }


@pytest.fixture(autouse=True)
def _use_test_duckdb(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def connect() -> Iterator[duckdb.DuckDBPyConnection]:
        with duckdb.connect(":memory:") as connection:
            yield connection

    monkeypatch.setattr(tushare_api_io, "connect_configured_duckdb", connect)


def _write(
    tmp_path: Path,
    tushare: FakeTushare,
    *,
    run_id: str = "run-1",
):
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir(exist_ok=True)
    staging_root.mkdir(exist_ok=True)
    return write_etf_basic_raw_snapshot(
        tushare=tushare,  # type: ignore[arg-type]
        duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        run_id=run_id,
        observed_at="2026-08-30T09:00:00+08:00",
    )


def test_raw_writer_uses_unfiltered_exact_contract_and_stops_on_short_page(
    tmp_path: Path,
) -> None:
    tushare = FakeTushare(
        {
            0: [
                _row(),
                _row("159001.OF", list_status="D", exchange=None),
            ]
        }
    )

    result = _write(tmp_path, tushare)

    assert tushare.calls == [
        (
            ETF_BASIC_SOURCE_API,
            {"limit": ETF_BASIC_PAGE_LIMIT, "offset": 0},
            ETF_BASIC_SOURCE_COLUMNS,
        )
    ]
    assert result.source_row_count == result.row_count == 2
    assert result.page_count == 1
    assert result.suffix_counts == {"OF": 1, "SH": 1}
    assert result.write_mode == "write_new"
    assert result.target_path == raw_etf_basic_snapshot_path(
        tmp_path / "data_lake", result.raw_snapshot_hash
    )
    assert result.target_path.is_file()


def test_exactly_full_first_page_requests_the_next_offset(tmp_path: Path) -> None:
    first_page = [_row(f"{index:06d}.SH") for index in range(ETF_BASIC_PAGE_LIMIT)]
    tushare = FakeTushare({0: first_page, ETF_BASIC_PAGE_LIMIT: []})

    result = _write(tmp_path, tushare)

    assert [call[1]["offset"] for call in tushare.calls] == [0, 5_000]
    assert result.source_row_count == 5_000
    assert result.page_count == 2


def test_second_page_failure_never_creates_a_formal_snapshot(tmp_path: Path) -> None:
    first_page = [_row(f"{index:06d}.SH") for index in range(ETF_BASIC_PAGE_LIMIT)]
    tushare = FakeTushare(
        {0: first_page},
        error_offsets=(ETF_BASIC_PAGE_LIMIT,),
    )

    with pytest.raises(RuntimeError, match="fake source failure"):
        _write(tmp_path, tushare)

    assert not list((tmp_path / "data_lake" / "raw").rglob("*.parquet"))


@pytest.mark.parametrize(
    ("pages", "columns", "expected_error"),
    [
        ({0: []}, None, "returned 0 rows"),
        (
            {0: [_row()]},
            {
                0: tuple(
                    column
                    for column in ETF_BASIC_SOURCE_COLUMNS
                    if column != "etf_type"
                )
            },
            "returned columns",
        ),
    ],
)
def test_empty_or_column_drift_never_publishes(
    tmp_path: Path,
    pages: Mapping[int, Sequence[dict[str, object]]],
    columns: Mapping[int, tuple[str, ...]] | None,
    expected_error: str,
) -> None:
    tushare = FakeTushare(pages, columns_by_offset=columns)

    with pytest.raises(RuntimeError, match=expected_error):
        _write(tmp_path, tushare)

    assert not list((tmp_path / "data_lake" / "raw").rglob("*.parquet"))


def test_duplicate_across_pages_is_rejected_before_publish(tmp_path: Path) -> None:
    first_page = [_row(f"{index:06d}.SH") for index in range(ETF_BASIC_PAGE_LIMIT)]
    tushare = FakeTushare(
        {
            0: first_page,
            ETF_BASIC_PAGE_LIMIT: [_row("000000.SH")],
        }
    )

    with pytest.raises(
        EtfBasicSnapshotValidationError,
        match="ts_code_duplicate",
    ):
        _write(tmp_path, tushare)

    assert not list((tmp_path / "data_lake" / "raw").rglob("*.parquet"))


@pytest.mark.parametrize(
    "invalid_row",
    [
        _row("510300.SH", list_status="X"),
        _row("510300.XX"),
        _row("510300.SH", exchange="SZ"),
    ],
)
def test_unknown_status_suffix_or_exchange_mismatch_is_rejected(
    tmp_path: Path,
    invalid_row: dict[str, object],
) -> None:
    with pytest.raises(EtfBasicSnapshotValidationError):
        _write(tmp_path, FakeTushare({0: [invalid_row]}))

    assert not list((tmp_path / "data_lake" / "raw").rglob("*.parquet"))


def test_same_hash_reuses_and_different_content_creates_a_new_version(
    tmp_path: Path,
) -> None:
    first = _write(tmp_path, FakeTushare({0: [_row()]}), run_id="run-1")
    reused = _write(tmp_path, FakeTushare({0: [_row()]}), run_id="run-2")
    changed = _write(
        tmp_path,
        FakeTushare({0: [_row(mgt_fee=0.6)]}),
        run_id="run-3",
    )

    assert reused.target_path == first.target_path
    assert reused.write_mode == "reuse_existing"
    assert changed.target_path != first.target_path
    assert changed.write_mode == "write_new"
    assert len(list((tmp_path / "data_lake" / "raw").rglob("*.parquet"))) == 2


def test_existing_hash_path_conflict_stops_without_overwrite(tmp_path: Path) -> None:
    first = _write(tmp_path, FakeTushare({0: [_row()]}), run_id="run-1")
    first.target_path.write_text("not parquet", encoding="utf-8")

    with pytest.raises(
        EtfBasicSnapshotValidationError,
        match="etf_basic_snapshot_conflict",
    ):
        _write(tmp_path, FakeTushare({0: [_row()]}), run_id="run-2")

    assert first.target_path.read_text(encoding="utf-8") == "not parquet"


def test_formal_parquet_hash_recomputes_from_readback(tmp_path: Path) -> None:
    result = _write(tmp_path, FakeTushare({0: [_row()]}))

    audit = audit_etf_basic_raw_snapshot(
        path=result.target_path,
        duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
        expected_source_row_count=result.source_row_count,
        expected_snapshot_hash=result.raw_snapshot_hash,
    )

    assert audit.passed
    assert audit.raw_snapshot_hash == result.raw_snapshot_hash


def test_materialization_metadata_contains_exact_p2_evidence_without_storage_id(
    tmp_path: Path,
) -> None:
    result = _write(tmp_path, FakeTushare({0: [_row()]}))

    metadata = build_etf_basic_raw_materialization_metadata(result)

    assert set(metadata) == {
        "dagster/uri",
        "dagster/row_count",
        "goldenshare/observed_columns",
        "goldenshare/source_row_count",
        "goldenshare/raw_snapshot_hash",
        "goldenshare/observed_at",
        "goldenshare/api_name",
        "goldenshare/business_params",
        "goldenshare/fields",
        "goldenshare/page_limit",
        "goldenshare/page_count",
        "goldenshare/status_counts",
        "goldenshare/suffix_counts",
        "goldenshare/list_date_null_counts",
        "goldenshare/write_mode",
    }
    assert metadata["goldenshare/business_params"] == {}
    assert "storage_id" not in " ".join(metadata)


def test_asset_reuses_generic_full_file_helper_without_private_pagination_loop() -> (
    None
):
    source = inspect.getsource(etf_basic_assets)

    assert "fetch_tushare_full_file_to_raw(" in source
    assert "_fetch_all_pages" not in source
    assert "while True" not in source
    assert "storage_id" not in source
    assert "eligibility_as_of" not in source
    assert "list_status=" not in source
