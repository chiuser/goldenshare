from __future__ import annotations

from src.foundation.services.sync import sync_stock_basic_service
from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.services.sync.sync_stock_basic_service import SyncStockBasicService


def test_sync_stock_basic_tushare_writes_std_and_serving(mocker) -> None:
    service = SyncStockBasicService(mocker.Mock())
    mocker.patch.object(
        service,
        "_get_rows_from_source",
        return_value=[
            {
                "ts_code": "000001.SZ",
                "symbol": "000001",
                "name": "平安银行",
                "exchange": "SZSE",
                "list_status": "L",
            }
        ],
    )
    mocker.patch.object(service.dao.raw_tushare_stock_basic, "bulk_upsert", return_value=1)
    std_upsert = mocker.patch.object(service.dao.security_std, "bulk_upsert", return_value=1)
    serving_upsert = mocker.patch.object(service.dao.security, "upsert_many", return_value=1)

    fetched, written, result_date, message = service.execute("FULL", source_key="tushare")

    assert fetched == 1
    assert written == 1
    assert result_date is None
    assert message == "source=tushare"
    std_upsert.assert_called_once()
    serving_upsert.assert_called_once()


def test_sync_stock_basic_biying_only_inserts_missing_codes(mocker) -> None:
    service = SyncStockBasicService(mocker.Mock())
    mocker.patch.object(
        service,
        "_get_rows_from_source",
        return_value=[
            {"dm": "000001.SZ", "mc": "平安银行", "jys": "SZ"},
            {"dm": "000002.SZ", "mc": "万科A", "jys": "SZ"},
        ],
    )
    mocker.patch.object(service.dao.raw_biying_stock_basic, "bulk_upsert", return_value=2)
    mocker.patch.object(service.dao.security_std, "bulk_upsert", return_value=2)
    mocker.patch.object(service.dao.security, "get_existing_ts_codes", return_value={"000001.SZ"})
    serving_upsert = mocker.patch.object(service.dao.security, "upsert_many", return_value=1)

    fetched, written, result_date, message = service.execute("FULL", source_key="biying")

    assert fetched == 2
    assert written == 1
    assert result_date is None
    assert message == "source=biying"
    serving_rows = serving_upsert.call_args.args[0]
    assert len(serving_rows) == 1
    assert serving_rows[0]["ts_code"] == "000002.SZ"


def test_sync_stock_basic_all_runs_both_sources_and_accumulates_counts(mocker) -> None:
    service = SyncStockBasicService(mocker.Mock())
    get_rows = mocker.patch.object(
        service,
        "_get_rows_from_source",
        side_effect=[
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "exchange": "SZSE",
                    "list_status": "L",
                }
            ],
            [{"dm": "000002.SZ", "mc": "万科A", "jys": "SZ"}],
        ],
    )
    raw_tushare_upsert = mocker.patch.object(service.dao.raw_tushare_stock_basic, "bulk_upsert", return_value=1)
    raw_biying_upsert = mocker.patch.object(service.dao.raw_biying_stock_basic, "bulk_upsert", return_value=1)
    security_std_upsert = mocker.patch.object(service.dao.security_std, "bulk_upsert", return_value=1)
    mocker.patch.object(service._policy_store, "get_enabled_policy", return_value=None)
    mocker.patch.object(service._policy_store, "get_active_sources", return_value={"tushare", "biying"})
    serving_upsert = mocker.patch.object(service.dao.security, "upsert_many", return_value=2)

    fetched, written, result_date, message = service.execute("FULL", source_key="all")

    assert fetched == 2
    assert written == 2
    assert result_date is None
    assert message == "source=all policy=primary@v1"
    assert get_rows.call_args_list[0].args == ("tushare",)
    assert get_rows.call_args_list[1].args == ("biying",)
    raw_tushare_upsert.assert_called_once()
    raw_biying_upsert.assert_called_once()
    assert security_std_upsert.call_count == 2
    serving_upsert.assert_called_once()
    serving_rows = serving_upsert.call_args.args[0]
    assert len(serving_rows) == 2


def test_sync_stock_basic_tushare_requests_include_g_status(mocker) -> None:
    service = SyncStockBasicService(mocker.Mock())
    connector = mocker.Mock()
    connector.call.return_value = []
    mocker.patch.object(sync_stock_basic_service, "create_source_connector", return_value=connector)

    service._get_rows_from_source("tushare")

    connector.call.assert_called_once_with(
        "stock_basic",
        params={"list_status": "L,D,P,G"},
        fields=service.fields,
    )


def test_sync_stock_basic_all_respects_resolution_policy(mocker) -> None:
    service = SyncStockBasicService(mocker.Mock())
    mocker.patch.object(
        service,
        "_get_rows_from_source",
        side_effect=[
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "exchange": "SZSE",
                    "list_status": "L",
                }
            ],
            [{"dm": "000001.SZ", "mc": "平 安 银 行", "jys": "SZ"}],
        ],
    )
    mocker.patch.object(service.dao.raw_tushare_stock_basic, "bulk_upsert", return_value=1)
    mocker.patch.object(service.dao.raw_biying_stock_basic, "bulk_upsert", return_value=1)
    mocker.patch.object(service.dao.security_std, "bulk_upsert", return_value=1)
    mocker.patch.object(
        service._policy_store,
        "get_enabled_policy",
        return_value=ResolutionPolicy(
            dataset_key="stock_basic",
            mode="primary",
            primary_source_key="biying",
            fallback_source_keys=("tushare",),
            version=9,
            enabled=True,
        ),
    )
    mocker.patch.object(service._policy_store, "get_active_sources", return_value={"tushare", "biying"})
    serving_upsert = mocker.patch.object(service.dao.security, "upsert_many", return_value=1)

    fetched, written, result_date, message = service.execute("FULL", source_key="all")

    assert fetched == 2
    assert written == 1
    assert result_date is None
    assert message == "source=all policy=primary@v9"
    serving_rows = serving_upsert.call_args.args[0]
    assert len(serving_rows) == 1
    assert serving_rows[0]["name"] == "平 安 银 行"
    assert serving_rows[0]["source"] == "biying"
