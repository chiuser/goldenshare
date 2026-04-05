from __future__ import annotations

from datetime import date

from src.foundation.services.sync.sync_limit_cpt_list_service import SyncLimitCptListService, build_limit_cpt_list_params
from src.foundation.services.sync.sync_limit_list_ths_service import SyncLimitListThsService, build_limit_list_ths_params
from src.foundation.services.sync.sync_limit_step_service import SyncLimitStepService, build_limit_step_params


def test_limit_list_ths_supports_incremental_and_range_params() -> None:
    incremental = build_limit_list_ths_params(
        "INCREMENTAL",
        trade_date=date(2026, 4, 3),
        limit_type="涨停池",
        market="HS",
    )
    assert incremental == {"trade_date": "20260403", "limit_type": "涨停池", "market": "HS"}

    full = build_limit_list_ths_params(
        "FULL",
        start_date="2026-03-01",
        end_date="2026-03-31",
        limit_type="炸板池",
        market="GEM",
    )
    assert full == {"start_date": "20260301", "end_date": "20260331", "limit_type": "炸板池", "market": "GEM"}


def test_limit_step_supports_incremental_and_range_params() -> None:
    assert build_limit_step_params("INCREMENTAL", trade_date=date(2026, 4, 3)) == {"trade_date": "20260403"}
    assert build_limit_step_params("FULL", start_date="2026-03-01", end_date="2026-03-31") == {
        "start_date": "20260301",
        "end_date": "20260331",
    }


def test_limit_cpt_list_supports_incremental_and_range_params() -> None:
    assert build_limit_cpt_list_params("INCREMENTAL", trade_date=date(2026, 4, 3)) == {"trade_date": "20260403"}
    assert build_limit_cpt_list_params("FULL", start_date="2026-03-01", end_date="2026-03-31") == {
        "start_date": "20260301",
        "end_date": "20260331",
    }


def test_limit_list_ths_persists_query_context_keys(mocker) -> None:
    session = mocker.Mock()
    service = SyncLimitListThsService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "trade_date": "20260403",
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "price": "11.20",
            "pct_chg": "10.01",
            "limit_type": "涨停池",
            "market_type": "HS",
        }
    ]
    service.dao.raw_limit_list_ths = mocker.Mock()
    service.dao.limit_list_ths = mocker.Mock()
    service.dao.limit_list_ths.bulk_upsert.return_value = 1

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 3),
        limit_type="涨停池",
        market="HS",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 3)
    assert message is None
    persisted_row = service.dao.limit_list_ths.bulk_upsert.call_args.args[0][0]
    assert persisted_row["query_limit_type"] == "涨停池"
    assert persisted_row["query_market"] == "HS"


def test_limit_step_service_normalizes_and_upserts_rows(mocker) -> None:
    session = mocker.Mock()
    service = SyncLimitStepService(session)
    mocker.patch.object(
        service.client,
        "call",
        return_value=[
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "trade_date": "20260403",
                "nums": "2",
            }
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_limit_step, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.limit_step, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 3))

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 3)
    assert message is None
    raw_rows = raw_upsert.call_args.args[0]
    assert raw_rows[0]["trade_date"].isoformat() == "2026-04-03"
    core_upsert.assert_called_once_with(raw_rows)


def test_limit_cpt_list_service_normalizes_and_upserts_rows(mocker) -> None:
    session = mocker.Mock()
    service = SyncLimitCptListService(session)
    mocker.patch.object(
        service.client,
        "call",
        return_value=[
            {
                "ts_code": "CPT001",
                "name": "AI算力",
                "trade_date": "20260403",
                "days": 3,
                "up_stat": "3天2板",
                "cons_nums": 5,
                "up_nums": 12,
                "pct_chg": "8.32",
                "rank": "1",
            }
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_limit_cpt_list, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.limit_cpt_list, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 4, 3))

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 3)
    assert message is None
    raw_rows = raw_upsert.call_args.args[0]
    assert raw_rows[0]["trade_date"].isoformat() == "2026-04-03"
    core_upsert.assert_called_once_with(raw_rows)
