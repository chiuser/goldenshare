from __future__ import annotations

from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner


def test_scanner_lists_stk_mins_by_date_partition(tmp_path):
    partition = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24"
    partition.mkdir(parents=True)
    (partition / "part-000.parquet").write_bytes(b"fake")

    partitions = FilesystemScanner(tmp_path).list_partitions(dataset_key="stk_mins")
    datasets = FilesystemScanner(tmp_path).list_datasets(dataset_key="stk_mins")

    assert len(partitions) == 1
    assert partitions[0].freq == 30
    assert partitions[0].trade_date == "2026-04-24"
    assert len(datasets) == 1
    assert datasets[0].latest_trade_date == "2026-04-24"


def test_scanner_lists_stock_basic_raw_dataset(tmp_path):
    stock_basic = tmp_path / "raw_tushare" / "stock_basic" / "current" / "part-000.parquet"
    stock_basic.parent.mkdir(parents=True)
    stock_basic.write_bytes(b"fake")

    datasets = FilesystemScanner(tmp_path).list_datasets()

    assert len(datasets) == 1
    assert datasets[0].dataset_key == "stock_basic"
    assert datasets[0].layers == ["raw_tushare"]
    assert datasets[0].file_count == 1
