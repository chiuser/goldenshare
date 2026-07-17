from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardSourceProbeResult,
    probe_dc_daily,
    probe_dc_index,
    probe_dc_member,
)
from orchestrator.defs.paths import raw_dc_index_path
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    DC_INDEX_TYPES,
    DC_MEMBER_FIELDS,
)


class _FakeTushare:
    def __init__(self, *, empty_index=False, drift=False):
        self.calls = []
        self.empty_index = empty_index
        self.drift = drift

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        if self.drift:
            return TushareResult(rows=[], columns=("wrong",), metadata={})
        if api_name == "dc_index":
            if self.empty_index:
                return TushareResult(rows=[], columns=tuple(fields), metadata={})
            idx_type = params["idx_type"]
            return TushareResult(
                rows=[
                    {
                        "ts_code": "BK0001.DC",
                        "trade_date": params["trade_date"],
                        "idx_type": idx_type,
                    }
                ],
                columns=tuple(fields),
                metadata={},
            )
        if api_name == "dc_daily":
            return TushareResult(
                rows=[{"trade_date": params["trade_date"]}],
                columns=tuple(fields),
                metadata={},
            )
        if api_name == "dc_member":
            return TushareResult(
                rows=[
                    {
                        "trade_date": params["trade_date"],
                        "ts_code": params["ts_code"],
                    }
                ],
                columns=tuple(fields),
                metadata={},
            )
        raise AssertionError(api_name)


class _MemoryDuckDB:
    def connect(self):
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


def _write_member_probe_index(root: Path) -> None:
    path = raw_dc_index_path(root, "2026-07-14")
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES ('BK0001.DC'), ('BK0002.DC')) AS t(ts_code)) TO '{path}' (FORMAT PARQUET)"
        )


def test_index_probe_requires_all_types_terminal_and_nonempty(tmp_path):
    tushare = _FakeTushare()
    result = probe_dc_index(
        connection=object(),
        lake_root=Path(tmp_path),
        tushare=tushare,
        trade_date="2026-07-14",
    )
    assert result.ready is True
    assert result.request_count == 3
    assert all(call[2] == DC_INDEX_FIELDS for call in tushare.calls)

    empty = _FakeTushare(empty_index=True)
    result = probe_dc_index(tushare=empty, trade_date="2026-07-14")
    assert result.ready is False
    assert result.reason_code == "source_probe_not_ready"
    assert result.empty_count == len(DC_INDEX_TYPES)


def test_daily_probe_is_one_bounded_request_with_explicit_fields():
    tushare = _FakeTushare()
    result = probe_dc_daily(
        connection=object(),
        lake_root=Path("/private/tmp/unused-dc-board-probe"),
        tushare=tushare,
        trade_date="2026-07-14",
    )
    assert result.ready is True
    assert len(tushare.calls) == 1
    assert tushare.calls[0][2] == DC_DAILY_FIELDS


def test_member_probe_is_limited_to_sampled_board_codes(tmp_path):
    root = Path(tmp_path)
    _write_member_probe_index(root)
    tushare = _FakeTushare()
    with _MemoryDuckDB().connect() as connection:
        result = probe_dc_member(
            connection=connection,
            lake_root=root,
            tushare=tushare,
            trade_date="2026-07-14",
        )
    assert result.ready is True
    assert len(tushare.calls) == 2
    assert all(call[2] == DC_MEMBER_FIELDS for call in tushare.calls)


def test_source_probe_fails_closed_on_column_drift():
    result = probe_dc_daily(
        tushare=_FakeTushare(drift=True),
        trade_date="2026-07-14",
    )
    assert result.ready is False
    assert result.reason_code == "source_probe_error"


def test_source_probe_summary_is_ascii_and_does_not_embed_failure_samples():
    result = DcBoardSourceProbeResult(
        dataset="dc_index",
        trade_date="2026-07-14",
        ready=False,
        reason_code="source_probe_error",
        request_count=1,
        retry_count=0,
        elapsed_ms=1.0,
        successful_count=0,
        empty_count=0,
        failed_count=1,
        unattempted_count=0,
        sample=({"error": "频率超限"},),
    )
    summary = result.to_summary()
    assert str(summary).isascii()
    assert summary["sample_count"] == 1
    assert "sample" not in summary
