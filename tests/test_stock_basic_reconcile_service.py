from __future__ import annotations

from types import SimpleNamespace

from src.operations.services.stock_basic_reconcile_service import StockBasicReconcileService


def test_stock_basic_reconcile_service_counts_and_normalization(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = [
        SimpleNamespace(source_key="tushare", ts_code="000001.SZ", name="万 科Ａ", exchange="SZSE"),
        SimpleNamespace(source_key="biying", ts_code="000001.SZ", name="万科Ａ", exchange="SZ"),
        SimpleNamespace(source_key="tushare", ts_code="000002.SZ", name="平安银行", exchange="SZSE"),
        SimpleNamespace(source_key="biying", ts_code="000002.SZ", name="平安银 行", exchange="SH"),
        SimpleNamespace(source_key="tushare", ts_code="000003.SZ", name="只在左侧", exchange="SZSE"),
        SimpleNamespace(source_key="biying", ts_code="000004.SZ", name="只在右侧", exchange="SZ"),
    ]

    report = StockBasicReconcileService().run(session, sample_limit=10)

    assert report.total_union == 4
    assert report.comparable == 2
    assert report.only_tushare == 1
    assert report.only_biying == 1
    assert report.comparable_diff == 1
    assert report.samples["only_tushare"][0].ts_code == "000003.SZ"
    assert report.samples["only_biying"][0].ts_code == "000004.SZ"
    assert report.samples["comparable_diff"][0].ts_code == "000002.SZ"
