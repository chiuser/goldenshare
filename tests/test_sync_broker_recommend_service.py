from __future__ import annotations

from datetime import date

from src.foundation.services.sync.sync_broker_recommend_service import (
    SyncBrokerRecommendService,
    build_broker_recommend_params,
)


def test_build_broker_recommend_params_supports_month_formats() -> None:
    assert build_broker_recommend_params("FULL", month="2026-03") == {"month": "202603"}
    assert build_broker_recommend_params("FULL", month="202603") == {"month": "202603"}
    assert build_broker_recommend_params("INCREMENTAL", trade_date=date(2026, 3, 31)) == {"month": "202603"}


def test_sync_broker_recommend_incremental_paginates_and_upserts(mocker) -> None:
    session = mocker.Mock()
    service = SyncBrokerRecommendService(session)

    rows_page_1 = [
        {
            "month": "202603",
            "currency": "CNY",
            "name": "平安银行",
            "ts_code": "000001.SZ",
            "trade_date": "20260301",
            "close": "12.30",
            "pct_change": "1.20",
            "target_price": "13.00",
            "industry": "银行",
            "broker": "某券商",
            "broker_mkt": "境内",
            "author": "分析师A",
            "recom_type": "买入",
            "reason": "基本面改善",
        },
        {
            "month": "202603",
            "currency": "CNY",
            "name": "万科A",
            "ts_code": "000002.SZ",
            "trade_date": "20260302",
            "close": "8.80",
            "pct_change": "-0.50",
            "target_price": "9.50",
            "industry": "地产",
            "broker": "某券商",
            "broker_mkt": "境内",
            "author": "分析师B",
            "recom_type": "增持",
            "reason": "估值修复",
        },
    ]
    rows_page_2 = [
        {
            "month": "202603",
            "currency": "CNY",
            "name": "招商银行",
            "ts_code": "600036.SH",
            "trade_date": "20260303",
            "close": "34.50",
            "pct_change": "0.80",
            "target_price": "36.00",
            "industry": "银行",
            "broker": "另一券商",
            "broker_mkt": "境内",
            "author": "分析师C",
            "recom_type": "买入",
            "reason": "盈利稳定",
        }
    ]
    mock_call = mocker.patch.object(service.client, "call", side_effect=[rows_page_1, rows_page_2])
    raw_upsert = mocker.patch.object(service.dao.raw_broker_recommend, "bulk_upsert", side_effect=[2, 1])
    core_upsert = mocker.patch.object(service.dao.broker_recommend, "bulk_upsert", side_effect=[2, 1])

    fetched, written, result_date, message = service.execute("INCREMENTAL", month="2026-03", limit=2)

    assert fetched == 3
    assert written == 3
    assert result_date == date(2026, 3, 1)
    assert message is None
    assert mock_call.call_args_list[0].kwargs["params"] == {"month": "202603", "limit": 2, "offset": 0}
    assert mock_call.call_args_list[1].kwargs["params"] == {"month": "202603", "limit": 2, "offset": 2}
    assert raw_upsert.call_count == 2
    assert core_upsert.call_count == 2
