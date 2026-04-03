from __future__ import annotations

from src.services.sync.sync_hk_basic_service import SyncHkBasicService, build_hk_basic_params
from src.services.sync.sync_us_basic_service import SyncUsBasicService, build_us_basic_params


def test_build_hk_basic_params_supports_ts_code_and_list_status() -> None:
    assert build_hk_basic_params("FULL") == {}
    assert build_hk_basic_params("FULL", ts_code="00005.HK", list_status="L") == {
        "ts_code": "00005.HK",
        "list_status": "L",
    }


def test_build_us_basic_params_supports_filters_and_paging() -> None:
    assert build_us_basic_params("FULL") == {}
    assert build_us_basic_params("FULL", ts_code="AAPL", classify="EQ", offset=100, limit=200) == {
        "ts_code": "AAPL",
        "classify": "EQ",
        "offset": 100,
        "limit": 200,
    }


def test_sync_hk_basic_service_normalizes_and_upserts_rows(mocker) -> None:
    session = mocker.Mock()
    service = SyncHkBasicService(session)
    mocker.patch.object(
        service.client,
        "call",
        return_value=[
            {
                "ts_code": "00005.HK",
                "name": "汇丰控股",
                "fullname": "汇丰控股有限公司",
                "enname": "HSBC Holdings plc",
                "cn_spell": "huifengkonggu",
                "market": "主板",
                "list_status": "L",
                "list_date": "2000-01-03",
                "delist_date": None,
                "trade_unit": 400,
                "isin": "GB0005405286",
                "curr_type": "HKD",
            }
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_hk_basic, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.hk_security, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute("FULL")

    assert fetched == 1
    assert written == 1
    assert result_date is None
    assert message is None
    raw_rows = raw_upsert.call_args.args[0]
    assert raw_rows[0]["list_date"].isoformat() == "2000-01-03"
    assert raw_rows[0]["trade_unit"] == 400
    core_upsert.assert_called_once_with(
        [
            {
                **raw_rows[0],
                "source": "tushare",
            }
        ]
    )


def test_sync_us_basic_service_normalizes_and_upserts_rows(mocker) -> None:
    session = mocker.Mock()
    service = SyncUsBasicService(session)
    mocker.patch.object(
        service.client,
        "call",
        return_value=[
            {
                "ts_code": "AAPL",
                "name": "苹果",
                "enname": "Apple Inc.",
                "classify": "EQ",
                "list_date": "1980-12-12",
                "delist_date": None,
            }
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_us_basic, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.us_security, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute("FULL")

    assert fetched == 1
    assert written == 1
    assert result_date is None
    assert message is None
    raw_rows = raw_upsert.call_args.args[0]
    assert raw_rows[0]["list_date"].isoformat() == "1980-12-12"
    core_upsert.assert_called_once_with(
        [
            {
                **raw_rows[0],
                "source": "tushare",
            }
        ]
    )
