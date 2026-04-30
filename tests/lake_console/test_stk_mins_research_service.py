from __future__ import annotations

from pathlib import Path
from typing import Any

import lake_console.backend.app.services.stk_mins_research_service as research_module
from lake_console.backend.app.services.stk_mins_research_service import StkMinsResearchService, bucket_rows, stable_bucket


def test_stable_bucket_is_deterministic():
    first = stable_bucket(ts_code="000001.SZ", bucket_count=32)
    second = stable_bucket(ts_code="000001.SZ", bucket_count=32)

    assert first == second
    assert 0 <= first < 32


def test_bucket_rows_groups_by_stable_bucket():
    rows = [{"ts_code": "000001.SZ"}, {"ts_code": "000001.SZ"}, {"ts_code": "600000.SH"}]

    buckets = bucket_rows(rows=rows, bucket_count=32)

    assert sum(len(items) for items in buckets.values()) == 3


def test_rebuild_month_writes_research_month(tmp_path, monkeypatch):
    source = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24"
    source.mkdir(parents=True)
    (source / "part-000.parquet").write_text("fake", encoding="utf-8")

    monkeypatch.setattr(
        research_module,
        "read_parquet_files",
        lambda paths: [
            {"ts_code": "000001.SZ", "trade_time": "2026-04-24 09:30:00"},
            {"ts_code": "600000.SH", "trade_time": "2026-04-24 09:30:00"},
        ],
    )
    monkeypatch.setattr(research_module, "read_parquet_row_count", lambda path: 1)

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(research_module, "write_rows_to_parquet", fake_write)

    summary = StkMinsResearchService(lake_root=tmp_path, bucket_count=32, progress=lambda message: None).rebuild_month(
        freq=30,
        trade_month="2026-04",
    )

    assert summary["written_rows"] == 2
    assert (tmp_path / "research" / "stk_mins_by_symbol_month" / "freq=30" / "trade_month=2026-04").exists()
