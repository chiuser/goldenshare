from __future__ import annotations

from decimal import Decimal

from src.services.sync.sync_etf_basic_service import SyncEtfBasicService


def test_sync_etf_basic_service_normalizes_and_upserts_rows(mocker) -> None:
    session = mocker.Mock()
    service = SyncEtfBasicService(session)
    mocker.patch.object(
        service.client,
        "call",
        return_value=[
            {
                "ts_code": "510300.SH",
                "csname": "沪深300ETF",
                "extname": "沪深300交易型开放式指数证券投资基金",
                "cname": "300ETF",
                "index_code": "000300.SH",
                "index_name": "沪深300",
                "setup_date": "2012-05-04",
                "list_date": "2012-05-28",
                "list_status": "L",
                "exchange": "SSE",
                "mgr_name": "华泰柏瑞基金",
                "custod_name": "中国工商银行",
                "mgt_fee": "0.500000",
                "etf_type": "股票型",
            }
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_etf_basic, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.etf_basic, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute("FULL")

    assert fetched == 1
    assert written == 1
    assert result_date is None
    assert message is None
    raw_rows = raw_upsert.call_args.args[0]
    assert raw_rows[0]["setup_date"].isoformat() == "2012-05-04"
    assert raw_rows[0]["list_date"].isoformat() == "2012-05-28"
    assert raw_rows[0]["mgt_fee"] == Decimal("0.500000")
    core_upsert.assert_called_once_with(raw_rows)
