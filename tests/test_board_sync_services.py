from __future__ import annotations

from datetime import date

from src.foundation.services.sync.sync_dc_member_service import SyncDcMemberService, build_dc_member_params
from src.foundation.services.sync.sync_ths_member_service import SyncThsMemberService, build_ths_member_params
from src.foundation.services.sync.sync_dc_daily_service import SyncDcDailyService, build_dc_daily_params
from src.foundation.services.sync.sync_dc_index_service import build_dc_index_params
from src.foundation.services.sync.sync_ths_daily_service import SyncThsDailyService, build_ths_daily_params
from src.foundation.services.sync.sync_ths_index_service import build_ths_index_params


def test_ths_index_builds_filter_params() -> None:
    params = build_ths_index_params("FULL", ts_code="885001.TI", exchange="A", type="N")
    assert params == {"ts_code": "885001.TI", "exchange": "A", "type": "N"}


def test_ths_member_builds_filter_params() -> None:
    params = build_ths_member_params("FULL", ts_code="000001.SZ", con_code="885001.TI")
    assert params == {"ts_code": "000001.SZ", "con_code": "885001.TI"}


def test_ths_daily_supports_incremental_and_range_params() -> None:
    incremental = build_ths_daily_params("INCREMENTAL", trade_date=date(2026, 4, 1), ts_code="885001.TI")
    assert incremental == {"trade_date": "20260401", "ts_code": "885001.TI"}

    full = build_ths_daily_params("FULL", ts_code="885001.TI", start_date="2020-01-01", end_date="2026-03-31")
    assert full == {"ts_code": "885001.TI", "start_date": "20200101", "end_date": "20260331"}


def test_dc_index_supports_incremental_and_range_params() -> None:
    incremental = build_dc_index_params("INCREMENTAL", trade_date=date(2026, 4, 1), idx_type="concept")
    assert incremental == {"trade_date": "20260401", "idx_type": "concept"}

    full = build_dc_index_params("FULL", start_date="2020-01-01", end_date="2026-03-31", idx_type="concept")
    assert full == {"start_date": "20200101", "end_date": "20260331", "idx_type": "concept"}


def test_dc_member_builds_incremental_params() -> None:
    params = build_dc_member_params("INCREMENTAL", trade_date=date(2026, 4, 1), con_code="BK1234")
    assert params == {"trade_date": "20260401", "con_code": "BK1234"}


def test_dc_daily_supports_incremental_and_range_params() -> None:
    incremental = build_dc_daily_params("INCREMENTAL", trade_date=date(2026, 4, 1), idx_type="concept")
    assert incremental == {"trade_date": "20260401", "idx_type": "concept"}

    full = build_dc_daily_params("FULL", ts_code="BK1234", start_date="2020-01-01", end_date="2026-03-31")
    assert full == {"ts_code": "BK1234", "start_date": "20200101", "end_date": "20260331"}


def test_ths_member_full_sync_refreshes_indices_then_fetches_members_by_board(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["885001.TI", "885002.TI"]
    mocker.patch("src.foundation.services.sync.sync_ths_member_service.SyncThsIndexService.run_full")
    service = SyncThsMemberService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [{"ts_code": "885001.TI", "con_code": "000001.SZ"}],
        [{"ts_code": "885002.TI", "con_code": "000002.SZ"}],
    ]
    service.dao.raw_ths_member = mocker.Mock()
    service.dao.ths_member = mocker.Mock()
    service.dao.ths_member.bulk_upsert.side_effect = [1, 1]

    fetched, written, result_date, message = service.execute("FULL")

    assert fetched == 2
    assert written == 2
    assert result_date is None
    assert message == "boards=2"
    assert service.client.call.call_args_list[0].kwargs["params"] == {"ts_code": "885001.TI"}
    assert service.client.call.call_args_list[1].kwargs["params"] == {"ts_code": "885002.TI"}


def test_dc_member_incremental_refreshes_board_index_then_fetches_members_by_board(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["BK001", "BK002"]
    mocker.patch("src.foundation.services.sync.sync_dc_member_service.SyncDcIndexService.run_incremental")
    service = SyncDcMemberService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [{"trade_date": "20260401", "ts_code": "BK001", "con_code": "000001.SZ", "name": "A"}],
        [{"trade_date": "20260401", "ts_code": "BK002", "con_code": "000002.SZ", "name": "B"}],
    ]
    service.dao.raw_dc_member = mocker.Mock()
    service.dao.dc_member = mocker.Mock()
    service.dao.dc_member.bulk_upsert.side_effect = [1, 1]
    trade_date = date(2026, 4, 1)

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=trade_date)

    assert fetched == 2
    assert written == 2
    assert result_date == trade_date
    assert message == "boards=2"
    assert service.client.call.call_args_list[0].kwargs["params"] == {"trade_date": "20260401", "ts_code": "BK001"}
    assert service.client.call.call_args_list[1].kwargs["params"] == {"trade_date": "20260401", "ts_code": "BK002"}


def test_dc_daily_incremental_refreshes_board_index_then_fetches_daily_by_board(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["BK001", "BK002"]
    mocker.patch("src.foundation.services.sync.sync_dc_daily_service.SyncDcIndexService.run_incremental")
    service = SyncDcDailyService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [{"trade_date": "20260401", "ts_code": "BK001", "close": "1"}],
        [{"trade_date": "20260401", "ts_code": "BK002", "close": "2"}],
    ]
    service.dao.raw_dc_daily = mocker.Mock()
    service.dao.dc_daily = mocker.Mock()
    service.dao.dc_daily.bulk_upsert.side_effect = [1, 1]
    trade_date = date(2026, 4, 1)

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=trade_date)

    assert fetched == 2
    assert written == 2
    assert result_date == trade_date
    assert message == "boards=2"
    assert service.client.call.call_args_list[0].kwargs["params"] == {"trade_date": "20260401", "ts_code": "BK001"}
    assert service.client.call.call_args_list[1].kwargs["params"] == {"trade_date": "20260401", "ts_code": "BK002"}


def test_dc_daily_full_refreshes_board_index_then_fetches_daily_by_board(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["BK001", "BK002"]
    mocker.patch("src.foundation.services.sync.sync_dc_daily_service.SyncDcIndexService.run_full")
    service = SyncDcDailyService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [{"trade_date": "20260331", "ts_code": "BK001", "close": "1"}],
        [{"trade_date": "20260331", "ts_code": "BK002", "close": "2"}],
    ]
    service.dao.raw_dc_daily = mocker.Mock()
    service.dao.dc_daily = mocker.Mock()
    service.dao.dc_daily.bulk_upsert.side_effect = [1, 1]

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2026-03-01",
        end_date="2026-03-31",
    )

    assert fetched == 2
    assert written == 2
    assert result_date is None
    assert message == "boards=2"
    assert service.client.call.call_args_list[0].kwargs["params"] == {
        "ts_code": "BK001",
        "start_date": "20260301",
        "end_date": "20260331",
    }
    assert service.client.call.call_args_list[1].kwargs["params"] == {
        "ts_code": "BK002",
        "start_date": "20260301",
        "end_date": "20260331",
    }


def test_ths_daily_incremental_refreshes_board_index_then_fetches_daily_by_board(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["885001.TI", "885002.TI"]
    mocker.patch("src.foundation.services.sync.sync_ths_daily_service.SyncThsIndexService.run_full")
    service = SyncThsDailyService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [{"trade_date": "20260401", "ts_code": "885001.TI", "close": "1"}],
        [{"trade_date": "20260401", "ts_code": "885002.TI", "close": "2"}],
    ]
    service.dao.raw_ths_daily = mocker.Mock()
    service.dao.ths_daily = mocker.Mock()
    service.dao.ths_daily.bulk_upsert.side_effect = [1, 1]
    trade_date = date(2026, 4, 1)

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=trade_date)

    assert fetched == 2
    assert written == 2
    assert result_date == trade_date
    assert message == "boards=2"
    assert service.client.call.call_args_list[0].kwargs["params"] == {
        "ts_code": "885001.TI",
        "start_date": "20260401",
        "end_date": "20260401",
    }
    assert service.client.call.call_args_list[1].kwargs["params"] == {
        "ts_code": "885002.TI",
        "start_date": "20260401",
        "end_date": "20260401",
    }


def test_ths_daily_full_refreshes_board_index_then_fetches_daily_by_board(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["885001.TI", "885002.TI"]
    mocker.patch("src.foundation.services.sync.sync_ths_daily_service.SyncThsIndexService.run_full")
    service = SyncThsDailyService(session)
    service.client = mocker.Mock()
    service.client.call.side_effect = [
        [{"trade_date": "20260331", "ts_code": "885001.TI", "close": "1"}],
        [{"trade_date": "20260331", "ts_code": "885002.TI", "close": "2"}],
    ]
    service.dao.raw_ths_daily = mocker.Mock()
    service.dao.ths_daily = mocker.Mock()
    service.dao.ths_daily.bulk_upsert.side_effect = [1, 1]

    fetched, written, result_date, message = service.execute(
        "FULL",
        start_date="2026-03-01",
        end_date="2026-03-31",
    )

    assert fetched == 2
    assert written == 2
    assert result_date == date(2026, 3, 31)
    assert message == "boards=2"
    assert service.client.call.call_args_list[0].kwargs["params"] == {
        "ts_code": "885001.TI",
        "start_date": "20260301",
        "end_date": "20260331",
    }
    assert service.client.call.call_args_list[1].kwargs["params"] == {
        "ts_code": "885002.TI",
        "start_date": "20260301",
        "end_date": "20260331",
    }
