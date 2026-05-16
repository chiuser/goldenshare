from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lake_console.backend.app.services.db_event_date_export_service import DbEventDateExportService
from lake_console.backend.app.services.parquet_writer import read_parquet_row_count


def test_event_date_export_writes_only_non_empty_partitions(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    captured: list[tuple[str, date]] = []

    def fake_iter_rows(
        *,
        database_url: str | None,
        dataset_key: str,
        event_date: date,
        batch_size: int,
        cursor_name: str,
    ):
        assert database_url == "postgresql://readonly@example/raw"
        assert dataset_key == "irm_qa_sh"
        captured.append((cursor_name, event_date))
        if event_date == date(2026, 5, 13):
            yield [
                {
                    "ts_code": "600000.SH",
                    "name": "浦发银行",
                    "trade_date": date(2026, 5, 13),
                    "q": "问题",
                    "a": "回答",
                    "pub_time": "2026-05-13 10:00:00",
                },
                {
                    "ts_code": "600001.SH",
                    "name": "样本公司",
                    "trade_date": date(2026, 5, 13),
                    "q": "问题2",
                    "a": "回答2",
                    "pub_time": "2026-05-13 11:00:00",
                },
            ]

    service = DbEventDateExportService(
        lake_root=tmp_path,
        dataset_key="irm_qa_sh",
        database_url="postgresql://readonly@example/raw",
        iter_rows=fake_iter_rows,
        progress=lambda _: None,
    )

    summary = service.export(event_dates=[date(2026, 5, 15), date(2026, 5, 13)])

    assert [item[1] for item in captured] == [date(2026, 5, 13), date(2026, 5, 15)]
    assert summary["dataset_key"] == "irm_qa_sh"
    assert summary["date_axis"] == "event_date"
    assert summary["event_dates"] == ["2026-05-13", "2026-05-15"]
    assert summary["fetched_rows"] == 2
    assert summary["written_rows"] == 2
    assert summary["skipped_partitions"] == 1
    assert summary["source_changed_to_zero_partitions"] == 1
    output = tmp_path / "raw_tushare" / "irm_qa_sh" / "event_date=2026-05-13" / "part-000.parquet"
    assert read_parquet_row_count(output) == 2
    assert not (tmp_path / "raw_tushare" / "irm_qa_sh" / "event_date=2026-05-15").exists()


def test_event_date_export_rejects_mismatched_source_date(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")

    def fake_iter_rows(**_: Any):
        yield [
            {
                "ann_date": date(2026, 5, 14),
                "ts_code": "000001.SZ",
                "name": "样本",
                "title": "公告",
                "url": "https://example.com",
                "rec_time": "2026-05-14 10:00:00",
            }
        ]

    service = DbEventDateExportService(
        lake_root=tmp_path,
        dataset_key="anns_d",
        database_url="postgresql://readonly@example/raw",
        iter_rows=fake_iter_rows,
        progress=lambda _: None,
    )

    with pytest.raises(ValueError, match="与计划 event_date=2026-05-15 不一致"):
        service.export(event_dates=[date(2026, 5, 15)])
