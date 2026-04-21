from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.foundation.services.sync.sync_moneyflow_service import SyncMoneyflowService


def test_sync_moneyflow_service_writes_std_and_publishes_serving(mocker) -> None:
    session = mocker.Mock()
    client = mocker.Mock()
    client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "trade_date": "2026-04-16",
            "buy_sm_vol": "1",
            "buy_sm_amount": "2",
            "sell_sm_vol": "3",
            "sell_sm_amount": "4",
            "buy_md_vol": "5",
            "buy_md_amount": "6",
            "sell_md_vol": "7",
            "sell_md_amount": "8",
            "buy_lg_vol": "9",
            "buy_lg_amount": "10",
            "sell_lg_vol": "11",
            "sell_lg_amount": "12",
            "buy_elg_vol": "13",
            "buy_elg_amount": "14",
            "sell_elg_vol": "15",
            "sell_elg_amount": "16",
            "net_mf_vol": "17",
            "net_mf_amount": "18",
        }
    ]
    mocker.patch("src.foundation.services.sync.sync_moneyflow_service.TushareHttpClient", return_value=client)

    service = SyncMoneyflowService(session)
    raw_upsert = mocker.patch.object(service.dao.raw_moneyflow, "bulk_upsert", return_value=1)
    std_upsert = mocker.patch.object(service.dao.moneyflow_std, "bulk_upsert", return_value=1)
    publish = mocker.patch(
        "src.foundation.services.sync.sync_moneyflow_service.publish_moneyflow_serving_for_keys",
        return_value=1,
    )

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 16))

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 16)
    assert message == "source=tushare std=1 serving=1"
    raw_upsert.assert_called_once()
    std_upsert.assert_called_once()
    publish.assert_called_once()
    raw_row = raw_upsert.call_args.args[0][0]
    assert raw_row["buy_sm_vol"] == 1
    assert raw_row["sell_sm_vol"] == 3
    assert raw_row["net_mf_vol"] == 17
    std_row = std_upsert.call_args.args[0][0]
    assert std_row["source_key"] == "tushare"
    assert std_row["ts_code"] == "000001.SZ"
    assert std_row["trade_date"] == date(2026, 4, 16)
    assert std_row["net_mf_amount"] == Decimal("18")


def test_sync_moneyflow_service_raises_on_fractional_volume(mocker) -> None:
    session = mocker.Mock()
    client = mocker.Mock()
    client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "trade_date": "2026-04-16",
            "buy_sm_vol": "1.5",
            "buy_sm_amount": "2",
            "sell_sm_vol": "3",
            "sell_sm_amount": "4",
            "buy_md_vol": "5",
            "buy_md_amount": "6",
            "sell_md_vol": "7",
            "sell_md_amount": "8",
            "buy_lg_vol": "9",
            "buy_lg_amount": "10",
            "sell_lg_vol": "11",
            "sell_lg_amount": "12",
            "buy_elg_vol": "13",
            "buy_elg_amount": "14",
            "sell_elg_vol": "15",
            "sell_elg_amount": "16",
            "net_mf_vol": "17",
            "net_mf_amount": "18",
        }
    ]
    mocker.patch("src.foundation.services.sync.sync_moneyflow_service.TushareHttpClient", return_value=client)

    service = SyncMoneyflowService(session)
    with pytest.raises(ValueError, match="must be integer-like"):
        service.execute("INCREMENTAL", trade_date=date(2026, 4, 16))
