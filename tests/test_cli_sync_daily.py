from __future__ import annotations

from datetime import date

import pytest

from src.cli import _resolve_default_sync_date


def test_resolve_default_sync_date_uses_pretrade_date_when_today_is_open(mocker) -> None:
    session = mocker.Mock()
    trade_calendar_dao = mocker.Mock()
    trade_calendar_dao.get_latest_open_date.return_value = date(2026, 3, 24)
    trade_calendar_dao.fetch_by_pk.return_value = mocker.Mock(is_open=True, pretrade_date=date(2026, 3, 23))
    trade_cal_service = mocker.Mock()
    trade_cal_service.dao.trade_calendar = trade_calendar_dao
    mocker.patch("src.cli.build_dataset_maintain_service", return_value=trade_cal_service)

    result = _resolve_default_sync_date(session)

    assert result == date(2026, 3, 23)
    trade_cal_service.run_incremental.assert_called_once_with()


def test_resolve_default_sync_date_uses_latest_open_date_when_today_is_closed(mocker) -> None:
    session = mocker.Mock()
    trade_calendar_dao = mocker.Mock()
    trade_calendar_dao.get_latest_open_date.return_value = date(2026, 3, 27)
    trade_calendar_dao.fetch_by_pk.return_value = mocker.Mock(is_open=False, pretrade_date=date(2026, 3, 27))
    trade_cal_service = mocker.Mock()
    trade_cal_service.dao.trade_calendar = trade_calendar_dao
    mocker.patch("src.cli.build_dataset_maintain_service", return_value=trade_cal_service)

    result = _resolve_default_sync_date(session)

    assert result == date(2026, 3, 27)


def test_resolve_default_sync_date_raises_clear_error_when_today_row_missing(mocker) -> None:
    session = mocker.Mock()
    trade_calendar_dao = mocker.Mock()
    trade_calendar_dao.get_latest_open_date.return_value = date(2026, 3, 27)
    trade_calendar_dao.fetch_by_pk.return_value = None
    trade_cal_service = mocker.Mock()
    trade_cal_service.dao.trade_calendar = trade_calendar_dao
    mocker.patch("src.cli.build_dataset_maintain_service", return_value=trade_cal_service)

    with pytest.raises(Exception, match="Today's trade calendar row is missing."):
        _resolve_default_sync_date(session)
