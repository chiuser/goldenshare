from __future__ import annotations

from datetime import date

from src.services.sync.sync_dc_hot_service import SyncDcHotService, build_dc_hot_params
from src.services.sync.sync_kpl_concept_cons_service import build_kpl_concept_cons_params
from src.services.sync.sync_kpl_list_service import build_kpl_list_params
from src.services.sync.sync_ths_hot_service import SyncThsHotService, build_ths_hot_params


def test_ths_hot_supports_incremental_and_range_params() -> None:
    incremental = build_ths_hot_params("INCREMENTAL", trade_date=date(2026, 4, 2), market="热股", is_new="Y")
    assert incremental == {"trade_date": "20260402", "market": "热股", "is_new": "Y"}

    full = build_ths_hot_params("FULL", start_date="2026-03-01", end_date="2026-03-31", market="热股", is_new="N")
    assert full == {"start_date": "20260301", "end_date": "20260331", "market": "热股", "is_new": "N"}


def test_dc_hot_supports_incremental_and_range_params() -> None:
    incremental = build_dc_hot_params("INCREMENTAL", trade_date=date(2026, 4, 2), market="A股市场", hot_type="人气榜", is_new="Y")
    assert incremental == {"trade_date": "20260402", "market": "A股市场", "hot_type": "人气榜", "is_new": "Y"}

    full = build_dc_hot_params("FULL", start_date="2026-03-01", end_date="2026-03-31", hot_type="飙升榜")
    assert full == {"start_date": "20260301", "end_date": "20260331", "hot_type": "飙升榜"}


def test_kpl_list_supports_incremental_and_range_params() -> None:
    incremental = build_kpl_list_params("INCREMENTAL", trade_date=date(2026, 4, 2), tag="龙虎榜")
    assert incremental == {"trade_date": "20260402", "tag": "龙虎榜"}

    full = build_kpl_list_params("FULL", start_date="2026-03-01", end_date="2026-03-31", tag="涨停池")
    assert full == {"tag": "涨停池", "start_date": "20260301", "end_date": "20260331"}


def test_kpl_concept_cons_supports_incremental_params() -> None:
    incremental = build_kpl_concept_cons_params("INCREMENTAL", trade_date=date(2026, 4, 2), con_code="GN001")
    assert incremental == {"trade_date": "20260402", "con_code": "GN001"}


def test_ths_hot_persists_query_context_keys(mocker) -> None:
    session = mocker.Mock()
    service = SyncThsHotService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "trade_date": "20260402",
            "data_type": "热度",
            "ts_code": "000001.SZ",
            "rank_time": "10:00:00",
            "ts_name": "平安银行",
            "rank": 1,
        }
    ]
    service.dao.raw_ths_hot = mocker.Mock()
    service.dao.ths_hot = mocker.Mock()
    service.dao.ths_hot.bulk_upsert.return_value = 1

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 2),
        market="热股",
        is_new="Y",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 2)
    assert message is None
    persisted_row = service.dao.ths_hot.bulk_upsert.call_args.args[0][0]
    assert persisted_row["query_market"] == "热股"
    assert persisted_row["query_is_new"] == "Y"


def test_ths_hot_expands_multi_value_filters(mocker) -> None:
    session = mocker.Mock()
    service = SyncThsHotService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [
            {
                "trade_date": "20260402",
                "data_type": "热度",
                "ts_code": "000001.SZ",
                "rank_time": "10:00:00",
                "ts_name": "平安银行",
                "rank": 1,
            }
        ],
        [],
    ]
    service.dao.raw_ths_hot = mocker.Mock()
    service.dao.ths_hot = mocker.Mock()
    service.dao.ths_hot.bulk_upsert.side_effect = [1, 0]

    fetched, written, _, _ = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 2),
        market=["热股", "港股"],
        is_new="N",
    )

    assert fetched == 1
    assert written == 1
    assert service.client.call.call_count == 2


def test_ths_hot_accepts_long_concept_and_rank_reason_text(mocker) -> None:
    session = mocker.Mock()
    service = SyncThsHotService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "trade_date": "20260402",
            "data_type": "热度",
            "ts_code": "000001.SZ",
            "rank_time": "10:00:00",
            "ts_name": "平安银行",
            "rank": 1,
            "concept": "概念" * 400,
            "rank_reason": "原因" * 400,
        }
    ]
    service.dao.raw_ths_hot = mocker.Mock()
    service.dao.ths_hot = mocker.Mock()
    service.dao.raw_ths_hot.bulk_upsert.return_value = 1
    service.dao.ths_hot.bulk_upsert.return_value = 1

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 2),
        market="热股",
        is_new="N",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 2)
    assert message is None
    raw_row = service.dao.raw_ths_hot.bulk_upsert.call_args.args[0][0]
    assert raw_row["concept"] == "概念" * 400
    assert raw_row["rank_reason"] == "原因" * 400


def test_dc_hot_persists_query_context_keys(mocker) -> None:
    session = mocker.Mock()
    service = SyncDcHotService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "trade_date": "20260402",
            "data_type": "热度",
            "ts_code": "000001.SZ",
            "rank_time": "10:00:00",
            "ts_name": "平安银行",
            "rank": 1,
        }
    ]
    service.dao.raw_dc_hot = mocker.Mock()
    service.dao.dc_hot = mocker.Mock()
    service.dao.dc_hot.bulk_upsert.return_value = 1

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 2),
        market="A股市场",
        hot_type="人气榜",
        is_new="Y",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 4, 2)
    assert message is None
    persisted_row = service.dao.dc_hot.bulk_upsert.call_args.args[0][0]
    assert persisted_row["query_market"] == "A股市场"
    assert persisted_row["query_hot_type"] == "人气榜"
    assert persisted_row["query_is_new"] == "Y"


def test_dc_hot_expands_multi_value_filters(mocker) -> None:
    session = mocker.Mock()
    service = SyncDcHotService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [
            {
                "trade_date": "20260402",
                "data_type": "热度",
                "ts_code": "000001.SZ",
                "rank_time": "10:00:00",
                "ts_name": "平安银行",
                "rank": 1,
            }
        ],
        [],
        [],
        [],
    ]
    service.dao.raw_dc_hot = mocker.Mock()
    service.dao.dc_hot = mocker.Mock()
    service.dao.dc_hot.bulk_upsert.side_effect = [1, 0, 0, 0]

    fetched, written, _, _ = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 4, 2),
        market=["A股市场", "ETF基金"],
        hot_type=["人气榜", "飙升榜"],
        is_new="N",
    )

    assert fetched == 1
    assert written == 1
    assert service.client.call.call_count == 4
    first_call = service.client.call.call_args_list[0]
    assert first_call.kwargs["params"] == {
        "trade_date": "20260402",
        "market": "A股市场",
        "hot_type": "人气榜",
        "is_new": "N",
    }


def test_dc_hot_enriches_missing_us_ts_code_from_us_security(mocker) -> None:
    session = mocker.Mock()
    service = SyncDcHotService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "trade_date": "20260105",
            "data_type": "美股市场",
            "ts_code": None,
            "ts_name": "苹果",
            "rank": 1,
            "pct_change": "-0.31",
            "current_price": "271.01",
            "rank_time": "2026-01-05 08:00:26",
        }
    ]
    mocker.patch.object(service.session, "scalars", return_value=iter(["AAPL"]))
    service.dao.raw_dc_hot = mocker.Mock()
    service.dao.dc_hot = mocker.Mock()
    service.dao.raw_dc_hot.bulk_upsert.return_value = 1
    service.dao.dc_hot.bulk_upsert.return_value = 1

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 1, 5),
        market="美股市场",
        hot_type="人气榜",
        is_new="N",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 1, 5)
    assert message is None
    persisted_row = service.dao.raw_dc_hot.bulk_upsert.call_args.args[0][0]
    assert persisted_row["ts_code"] == "AAPL"


def test_dc_hot_reports_unresolved_us_rows_when_lookup_fails(mocker) -> None:
    session = mocker.Mock()
    service = SyncDcHotService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "trade_date": "20260105",
            "data_type": "美股市场",
            "ts_code": None,
            "ts_name": "苹果",
            "rank": 1,
            "rank_time": "2026-01-05 08:00:26",
        }
    ]
    mocker.patch.object(service.session, "scalars", return_value=iter([]))
    service.dao.raw_dc_hot = mocker.Mock()
    service.dao.dc_hot = mocker.Mock()
    service.dao.raw_dc_hot.bulk_upsert.return_value = 1
    service.dao.dc_hot.bulk_upsert.return_value = 1

    fetched, written, result_date, message = service.execute(
        "INCREMENTAL",
        trade_date=date(2026, 1, 5),
        market="美股市场",
        hot_type="人气榜",
        is_new="N",
    )

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 1, 5)
    assert message == "unresolved 1 dc_hot rows missing ts_code after us_security lookup"
    persisted_row = service.dao.raw_dc_hot.bulk_upsert.call_args.args[0][0]
    assert persisted_row["ts_code"] is None
