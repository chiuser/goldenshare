from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.assets.index_global_raw import _extract_index_global_rows
from orchestrator.defs.bootstrap.index_global_bootstrap_apply import (
    IndexGlobalBootstrapApplyError,
    run_bootstrap_apply,
)
from orchestrator.defs.bootstrap.index_global_bootstrap_plan import build_date_plan
from orchestrator.defs.bootstrap.index_global_bootstrap_source_probe import (
    probe_index_global_source,
)
from orchestrator.defs.resources import TushareResult


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


class _FakeTushare:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, api_name, params, fields):
        self.calls.append(dict(params))
        row = {
            "ts_code": "XIN9",
            "trade_date": params["trade_date"],
            "open": 1.0,
            "close": 1.0,
            "high": 1.0,
            "low": 1.0,
            "pre_close": 1.0,
            "change": 0.0,
            "pct_chg": 0.0,
            "swing": 0.0,
            "vol": None,
            "amount": None,
        }
        return TushareResult(rows=[row], columns=tuple(fields), metadata={})


def _source_report(tmp_path: Path) -> Path:
    fake = _FakeTushare()
    plan = build_date_plan(start_date="2022-01-01", end_date="2022-01-02")
    report = probe_index_global_source(
        tushare=fake,
        date_plan=plan,
        sleep_fn=lambda _seconds: None,
    )
    path = tmp_path / "source.json"
    path.write_text(json.dumps(report.to_dict()), encoding="utf-8")
    return path


def test_apply_requires_source_report_and_preserves_bounded_phase_order(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    report = run_bootstrap_apply(
        lake_root=lake,
        duckdb_resource=_MemoryDuckDB(),
        tushare=_FakeTushare(),
        source_report_path=_source_report(tmp_path),
        output_dir=tmp_path / "reports",
        start_date="2022-01-01",
        end_date="2022-01-02",
        sleep_fn=lambda _seconds: None,
    )
    assert report["should_stop"] is False
    assert len(report["raw_records"]) == 2
    assert len(report["silver_records"]) == 2
    assert report["raw_audit"]["missing_count"] == 0
    assert report["silver_audit"]["missing_count"] == 0
    assert len(list((lake / "raw/index_global").glob("trade_date=*/part-000.parquet"))) == 2
    assert len(list((lake / "silver/index_global").glob("trade_date=*/part-000.parquet"))) == 2


def test_apply_rejects_mismatched_source_fingerprint(tmp_path: Path) -> None:
    path = _source_report(tmp_path)
    payload = json.loads(path.read_text())
    payload["date_plan"]["fingerprint"] = "wrong"
    path.write_text(json.dumps(payload), encoding="utf-8")
    lake = tmp_path / "lake"
    lake.mkdir()
    with pytest.raises(IndexGlobalBootstrapApplyError, match="fingerprint"):
        run_bootstrap_apply(
            lake_root=lake,
            duckdb_resource=_MemoryDuckDB(),
            tushare=_FakeTushare(),
            source_report_path=path,
            output_dir=tmp_path / "reports",
            start_date="2022-01-01",
            end_date="2022-01-02",
            sleep_fn=lambda _seconds: None,
        )
    assert not (lake / "raw").exists()


def test_empty_response_with_empty_columns_is_valid_source_observation() -> None:
    assert _extract_index_global_rows(TushareResult(rows=[], columns=(), metadata={})) == ()
