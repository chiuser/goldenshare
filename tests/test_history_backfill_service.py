from __future__ import annotations

from datetime import date

from src.services.history_backfill_service import HistoryBackfillService


def test_backfill_equity_series_emits_progress(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.security.get_active_equities.return_value = [
        mocker.Mock(ts_code="000001.SZ"),
        mocker.Mock(ts_code="000002.SZ"),
    ]
    progress = mocker.Mock()

    sync_service_1 = mocker.Mock()
    sync_service_1.run_full.return_value = mocker.Mock(rows_fetched=10, rows_written=10)
    sync_service_2 = mocker.Mock()
    sync_service_2.run_full.return_value = mocker.Mock(rows_fetched=20, rows_written=20)
    build_sync_service = mocker.patch("src.services.history_backfill_service.build_sync_service", side_effect=[sync_service_1, sync_service_2])

    summary = service.backfill_equity_series(
        resource="daily",
        start_date=date(2010, 1, 1),
        end_date=date(2026, 3, 24),
        progress=progress,
    )

    assert summary.units_processed == 2
    assert summary.rows_fetched == 30
    assert summary.rows_written == 30
    assert build_sync_service.call_count == 2
    assert progress.call_args_list[0].args[0] == "daily: 1/2 ts_code=000001.SZ fetched=10 written=10"
    assert progress.call_args_list[1].args[0] == "daily: 2/2 ts_code=000002.SZ fetched=20 written=20"


def test_backfill_equity_series_supports_period_resources(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.security.get_active_equities.return_value = [mocker.Mock(ts_code="000001.SZ")]

    sync_service = mocker.Mock()
    sync_service.run_full.return_value = mocker.Mock(rows_fetched=12, rows_written=12)
    build_sync_service = mocker.patch("src.services.history_backfill_service.build_sync_service", return_value=sync_service)

    summary = service.backfill_equity_series(
        resource="stk_period_bar_month",
        start_date=date(2010, 1, 1),
        end_date=date(2026, 3, 24),
    )

    assert summary.units_processed == 1
    assert summary.rows_fetched == 12
    assert summary.rows_written == 12
    build_sync_service.assert_called_once_with("stk_period_bar_month", session)
    sync_service.run_full.assert_called_once_with(
        ts_code="000001.SZ",
        start_date="2010-01-01",
        end_date="2026-03-24",
    )


def test_backfill_by_trade_dates_emits_progress(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.trade_calendar.get_open_dates.return_value = [date(2026, 3, 20), date(2026, 3, 21)]
    progress = mocker.Mock()

    sync_service_1 = mocker.Mock()
    sync_service_1.run_incremental.return_value = mocker.Mock(rows_fetched=5, rows_written=5)
    sync_service_2 = mocker.Mock()
    sync_service_2.run_incremental.return_value = mocker.Mock(rows_fetched=6, rows_written=6)
    mocker.patch("src.services.history_backfill_service.build_sync_service", side_effect=[sync_service_1, sync_service_2])

    summary = service.backfill_by_trade_dates(
        resource="daily_basic",
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 21),
        progress=progress,
    )

    assert summary.units_processed == 2
    assert summary.rows_fetched == 11
    assert summary.rows_written == 11
    assert progress.call_args_list[0].args[0] == "daily_basic: 1/2 trade_date=2026-03-20 fetched=5 written=5"
    assert progress.call_args_list[1].args[0] == "daily_basic: 2/2 trade_date=2026-03-21 fetched=6 written=6"


def test_backfill_by_trade_dates_supports_limit_list_d(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.trade_calendar.get_open_dates.return_value = [date(2026, 3, 24)]
    progress = mocker.Mock()

    sync_service = mocker.Mock()
    sync_service.run_incremental.return_value = mocker.Mock(rows_fetched=113, rows_written=113)
    build_sync_service = mocker.patch("src.services.history_backfill_service.build_sync_service", return_value=sync_service)

    summary = service.backfill_by_trade_dates(
        resource="limit_list_d",
        start_date=date(2026, 3, 24),
        end_date=date(2026, 3, 24),
        progress=progress,
    )

    assert summary.units_processed == 1
    assert summary.rows_fetched == 113
    assert summary.rows_written == 113
    build_sync_service.assert_called_once_with("limit_list_d", session)
    sync_service.run_incremental.assert_called_once_with(trade_date=date(2026, 3, 24))
    assert progress.call_args_list[0].args[0] == "limit_list_d: 1/1 trade_date=2026-03-24 fetched=113 written=113"


def test_backfill_by_trade_dates_emits_progress_for_incremental_resources(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.trade_calendar.get_open_dates.return_value = [
        date(2026, 3, 20),
        date(2026, 3, 21),
    ]
    progress = mocker.Mock()

    sync_service_1 = mocker.Mock()
    sync_service_1.run_incremental.return_value = mocker.Mock(rows_fetched=10, rows_written=10)
    sync_service_2 = mocker.Mock()
    sync_service_2.run_incremental.return_value = mocker.Mock(rows_fetched=12, rows_written=12)
    mocker.patch("src.services.history_backfill_service.build_sync_service", side_effect=[sync_service_1, sync_service_2])

    summary = service.backfill_by_trade_dates(
        resource="limit_list_d",
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 21),
        progress=progress,
    )

    assert summary.units_processed == 2
    sync_service_1.run_incremental.assert_called_once_with(trade_date=date(2026, 3, 20))
    sync_service_2.run_incremental.assert_called_once_with(trade_date=date(2026, 3, 21))
    assert progress.call_args_list[0].args[0] == "limit_list_d: 1/2 trade_date=2026-03-20 fetched=10 written=10"


def test_backfill_by_trade_dates_rejects_period_resources(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)

    try:
        service.backfill_by_trade_dates(
            resource="stk_period_bar_week",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 28),
        )
    except ValueError as exc:
        assert "limit_list_d" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_backfill_fund_series_emits_progress(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.etf_basic.get_fund_daily_candidates.return_value = [
        mocker.Mock(ts_code="159915.SZ"),
        mocker.Mock(ts_code="510300.SH"),
    ]
    progress = mocker.Mock()

    sync_service_1 = mocker.Mock()
    sync_service_1.run_full.return_value = mocker.Mock(rows_fetched=10, rows_written=10)
    sync_service_2 = mocker.Mock()
    sync_service_2.run_full.return_value = mocker.Mock(rows_fetched=20, rows_written=20)
    build_sync_service = mocker.patch("src.services.history_backfill_service.build_sync_service", side_effect=[sync_service_1, sync_service_2])

    summary = service.backfill_fund_series(
        resource="fund_daily",
        start_date=date(2010, 1, 1),
        end_date=date(2026, 3, 29),
        progress=progress,
    )

    assert summary.units_processed == 2
    assert summary.rows_fetched == 30
    assert summary.rows_written == 30
    assert build_sync_service.call_count == 2
    assert progress.call_args_list[0].args[0] == "fund_daily: 1/2 ts_code=159915.SZ fetched=10 written=10"
    assert progress.call_args_list[1].args[0] == "fund_daily: 2/2 ts_code=510300.SH fetched=20 written=20"


def test_backfill_fund_series_rejects_unsupported_resources(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)

    try:
        service.backfill_fund_series(
            resource="daily",
            start_date=date(2010, 1, 1),
            end_date=date(2026, 3, 29),
        )
    except ValueError as exc:
        assert "fund_daily" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_backfill_index_series_emits_progress_for_ts_code_resources(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.index_basic.get_active_indexes.return_value = [
        mocker.Mock(ts_code="000001.SH"),
        mocker.Mock(ts_code="000300.SH"),
    ]
    progress = mocker.Mock()

    sync_service_1 = mocker.Mock()
    sync_service_1.run_full.return_value = mocker.Mock(rows_fetched=10, rows_written=10)
    sync_service_2 = mocker.Mock()
    sync_service_2.run_full.return_value = mocker.Mock(rows_fetched=20, rows_written=20)
    build_sync_service = mocker.patch("src.services.history_backfill_service.build_sync_service", side_effect=[sync_service_1, sync_service_2])

    summary = service.backfill_index_series(
        resource="index_weekly",
        start_date=date(2020, 1, 1),
        end_date=date(2026, 3, 29),
        progress=progress,
    )

    assert summary.units_processed == 2
    assert summary.rows_fetched == 30
    assert summary.rows_written == 30
    assert build_sync_service.call_count == 2
    sync_service_1.run_full.assert_called_once_with(
        ts_code="000001.SH",
        start_date="2020-01-01",
        end_date="2026-03-29",
    )
    assert progress.call_args_list[0].args[0] == "index_weekly: 1/2 ts_code=000001.SH fetched=10 written=10"


def test_backfill_index_series_uses_index_code_for_index_weight(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)
    service.dao = mocker.Mock()
    service.dao.index_basic.get_active_indexes.return_value = [mocker.Mock(ts_code="000300.SH")]
    progress = mocker.Mock()

    sync_service = mocker.Mock()
    sync_service.run_full.return_value = mocker.Mock(rows_fetched=300, rows_written=300)
    build_sync_service = mocker.patch("src.services.history_backfill_service.build_sync_service", return_value=sync_service)

    summary = service.backfill_index_series(
        resource="index_weight",
        start_date=date(2020, 1, 1),
        end_date=date(2026, 3, 29),
        progress=progress,
    )

    assert summary.units_processed == 1
    assert summary.rows_fetched == 300
    assert summary.rows_written == 300
    build_sync_service.assert_called_once_with("index_weight", session)
    sync_service.run_full.assert_called_once_with(
        index_code="000300.SH",
        start_date="2020-01-01",
        end_date="2026-03-29",
    )
    assert progress.call_args_list[0].args[0] == "index_weight: 1/1 index_code=000300.SH fetched=300 written=300"


def test_backfill_index_series_rejects_unsupported_resources(mocker) -> None:
    session = mocker.Mock()
    service = HistoryBackfillService(session)

    try:
        service.backfill_index_series(
            resource="fund_daily",
            start_date=date(2020, 1, 1),
            end_date=date(2026, 3, 29),
        )
    except ValueError as exc:
        assert "index_weight" in str(exc)
    else:
        raise AssertionError("expected ValueError")
