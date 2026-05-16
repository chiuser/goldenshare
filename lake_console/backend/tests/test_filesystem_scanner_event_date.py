from __future__ import annotations

import pytest

from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet


def test_filesystem_scanner_reads_event_date_dataset(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    write_rows_to_parquet(
        [{"ann_date": "2026-05-13", "ts_code": "000001.SZ", "name": "样本", "title": "公告", "url": "u", "rec_time": "t"}],
        tmp_path / "raw_tushare" / "anns_d" / "event_date=2026-05-13" / "part-000.parquet",
    )
    write_rows_to_parquet(
        [{"ann_date": "2026-05-15", "ts_code": "000002.SZ", "name": "样本2", "title": "公告2", "url": "u2", "rec_time": "t2"}],
        tmp_path / "raw_tushare" / "anns_d" / "event_date=2026-05-15" / "part-000.parquet",
    )

    scanner = FilesystemScanner(tmp_path)
    dataset = next(item for item in scanner.list_datasets() if item.dataset_key == "anns_d")

    assert dataset.source == "prod-raw-db"
    assert dataset.partition_count == 2
    assert dataset.coverage_label == "2026-05-13 至 2026-05-15"
    assert dataset.earliest_event_date == "2026-05-13"
    assert dataset.latest_event_date == "2026-05-15"
    assert dataset.earliest_trade_date is None
    node = dataset.node_summaries[0]
    assert node.node_key == "raw_by_event_date"
    assert node.scan_profile == "event_date"
    assert node.partition_dimensions == ["event_date"]
    assert node.earliest_event_date == "2026-05-13"
    assert node.latest_event_date == "2026-05-15"

    partitions = scanner.list_partitions(
        dataset_key="anns_d",
        node_key="raw_by_event_date",
        event_date_from="2026-05-14",
        event_date_to="2026-05-15",
    )
    assert len(partitions) == 1
    assert partitions[0].partition_values == {"event_date": "2026-05-15"}
    assert partitions[0].partition_locator == "event_date=2026-05-15"
    assert partitions[0].partition_label == "2026-05-15"
