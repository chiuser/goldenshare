from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.foundation.services.sync.sync_biying_moneyflow_service import SyncBiyingMoneyflowService


def test_sync_biying_moneyflow_full_writes_raw_rows(mocker) -> None:
    session = mocker.Mock()
    connector = mocker.Mock()
    connector.call.return_value = [
        {
            "t": "2026-04-10 00:00:00",
            "zmbzds": 2567,
            "zmszds": 2113,
            "dddx": -5.3,
            "zmbtdcje": 643556632.0,
            "zmbtdcjl": 534893,
            "zmbtdcjzlv": 534893,
        }
    ]
    mocker.patch("src.foundation.services.sync.sync_biying_moneyflow_service.create_source_connector", return_value=connector)

    service = SyncBiyingMoneyflowService(session)
    mocker.patch.object(service, "_load_stocks", return_value=[("000001.SZ", "平安银行")])
    mocker.patch.object(service, "_build_windows", return_value=[(date(2026, 4, 1), date(2026, 4, 10))])
    raw_upsert = mocker.patch.object(service.dao.raw_biying_moneyflow, "bulk_upsert", return_value=1)
    std_upsert = mocker.patch.object(service.dao.moneyflow_std, "bulk_upsert", return_value=1)
    publish = mocker.patch(
        "src.foundation.services.sync.sync_biying_moneyflow_service.publish_moneyflow_serving_for_keys",
        return_value=1,
    )

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2026-04-01",
        end_date="2026-04-10",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 10)
    assert message == "stocks=1 windows=1 std=1 serving=1"
    connector.call.assert_called_once_with(
        "moneyflow",
        params={"dm": "000001.SZ", "st": "20260401", "et": "20260410"},
    )
    std_upsert.assert_called_once()
    publish.assert_called_once()

    first_row = raw_upsert.call_args.args[0][0]
    assert first_row["dm"] == "000001.SZ"
    assert first_row["trade_date"] == date(2026, 4, 10)
    assert first_row["mc"] == "平安银行"
    assert first_row["zmbzds"] == 2567
    assert first_row["dddx"] == Decimal("-5.3")
    assert first_row["zmbtdcje"] == Decimal("643556632.0")
    assert first_row["zmbtdcjl"] == 534893
    assert first_row["zmbtdcjzlv"] == 534893

    std_row = std_upsert.call_args.args[0][0]
    assert std_row["source_key"] == "biying"
    assert std_row["ts_code"] == "000001.SZ"
    assert std_row["trade_date"] == date(2026, 4, 10)


def test_sync_biying_moneyflow_incremental_requires_trade_date(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.sync_biying_moneyflow_service.create_source_connector", return_value=mocker.Mock())
    service = SyncBiyingMoneyflowService(session)
    with pytest.raises(ValueError, match="trade_date is required"):
        service.execute("INCREMENTAL")
