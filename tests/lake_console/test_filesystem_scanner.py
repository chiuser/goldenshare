from __future__ import annotations

from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner


def test_scanner_lists_stk_mins_by_date_partition(tmp_path):
    partition = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24"
    partition.mkdir(parents=True)
    (partition / "part-000.parquet").write_bytes(b"fake")

    scanner = FilesystemScanner(tmp_path)
    partitions = scanner.list_partitions(dataset_key="stk_mins", node_key="raw_tushare_by_date")
    datasets = scanner.list_datasets(dataset_key="stk_mins", node_key="raw_tushare_by_date")

    assert len(partitions) == 1
    assert partitions[0].node_key == "raw_tushare_by_date"
    assert partitions[0].partition_values == {"freq": 30, "trade_date": "2026-04-24"}
    assert partitions[0].partition_locator == "freq=30/trade_date=2026-04-24"
    assert len(datasets) == 1
    raw_node = _node_by_key(datasets[0].node_summaries, "raw_tushare_by_date")
    assert raw_node.registered_state == "registered"
    assert raw_node.file_count == 1
    assert raw_node.partition_count == 1
    assert raw_node.freqs == [30]
    assert raw_node.latest_trade_date == "2026-04-24"
    assert datasets[0].latest_trade_date == "2026-04-24"


def test_scanner_lists_stock_basic_raw_dataset(tmp_path):
    stock_basic = tmp_path / "raw_tushare" / "stock_basic" / "current" / "part-000.parquet"
    stock_basic.parent.mkdir(parents=True)
    stock_basic.write_bytes(b"fake")

    scanner = FilesystemScanner(tmp_path)
    datasets = scanner.list_datasets(dataset_key="stock_basic")
    raw_partitions = scanner.list_partitions(dataset_key="stock_basic", node_key="raw_current")

    assert len(datasets) == 1
    assert datasets[0].dataset_key == "stock_basic"
    assert datasets[0].file_count == 1
    raw_node = _node_by_key(datasets[0].node_summaries, "raw_current")
    manifest_node = _node_by_key(datasets[0].node_summaries, "manifest_file")
    assert raw_node.registered_state == "registered"
    assert raw_node.path == "raw_tushare/stock_basic/current/part-000.parquet"
    assert raw_node.file_count == 1
    assert manifest_node.registered_state == "missing_on_disk"
    assert len(raw_partitions) == 1
    assert raw_partitions[0].node_key == "raw_current"
    assert raw_partitions[0].partition_locator == "current"
    assert raw_partitions[0].partition_label == "当前版本"


def _node_by_key(node_summaries, node_key):
    for node_summary in node_summaries:
        if node_summary.node_key == node_key:
            return node_summary
    raise AssertionError(f"missing node_key={node_key}")
