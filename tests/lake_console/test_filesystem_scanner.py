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


def test_physical_assets_classify_registered_containers_and_system_files(tmp_path):
    stock_basic = tmp_path / "raw_tushare" / "stock_basic" / "current" / "part-000.parquet"
    stock_basic.parent.mkdir(parents=True)
    stock_basic.write_bytes(b"fake")
    (tmp_path / "raw_tushare" / ".DS_Store").write_bytes(b"macos")
    unknown_dir = tmp_path / "raw_tushare" / "manual_dump"
    unknown_dir.mkdir()
    (unknown_dir / "part-000.parquet").write_bytes(b"manual")

    scanner = FilesystemScanner(tmp_path)
    assets = scanner.list_physical_assets(limit=1000)
    assets_by_path = {asset.path: asset for asset in assets}

    assert "raw_tushare/.DS_Store" not in assets_by_path
    stock_basic_container = assets_by_path["raw_tushare/stock_basic"]
    assert stock_basic_container.registered_state == "registered_container"
    assert stock_basic_container.dataset_key == "stock_basic"
    assert stock_basic_container.node_key is None
    assert stock_basic_container.risk_level == "none"
    assert stock_basic_container.risk_label == "已登记节点容器"

    unknown_asset = assets_by_path["raw_tushare/manual_dump"]
    assert unknown_asset.registered_state == "unregistered"
    assert unknown_asset.risk_level == "warning"
    assert unknown_asset.risk_label == "未登记资产"

    ignored_assets = scanner.list_physical_assets(registered_state="ignored", limit=1000)
    assert [asset.path for asset in ignored_assets] == ["raw_tushare/.DS_Store"]
    assert ignored_assets[0].risk_label == "系统文件"

    unregistered_metric = next(metric for metric in scanner.overview().summary_metrics if metric.key == "unregistered_assets")
    assert unregistered_metric.value == "1"


def _node_by_key(node_summaries, node_key):
    for node_summary in node_summaries:
        if node_summary.node_key == node_key:
            return node_summary
    raise AssertionError(f"missing node_key={node_key}")
