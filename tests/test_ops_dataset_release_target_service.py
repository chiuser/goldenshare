from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.foundation.datasets.registry import get_dataset_definition
from src.ops.services.dataset_release_target_service import DatasetReleaseTargetService


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_kpl_list_release_target_uses_next_calendar_day_release_time() -> None:
    service = DatasetReleaseTargetService()
    definition = get_dataset_definition("kpl_list")
    open_trade_dates = [date(2026, 7, 24), date(2026, 7, 27)]

    before_monday_release = service.resolve(
        definition=definition,
        now=datetime(2026, 7, 28, 7, 0, tzinfo=SHANGHAI),
        open_trade_dates=open_trade_dates,
    )
    after_monday_release = service.resolve(
        definition=definition,
        now=datetime(2026, 7, 28, 8, 35, tzinfo=SHANGHAI),
        open_trade_dates=open_trade_dates,
    )

    assert before_monday_release.target_trade_date == date(2026, 7, 24)
    assert before_monday_release.is_resolved is True
    assert after_monday_release.target_trade_date == date(2026, 7, 27)
    assert after_monday_release.is_resolved is True


def test_kpl_list_release_target_supports_weekend_release_for_friday_data() -> None:
    service = DatasetReleaseTargetService()
    definition = get_dataset_definition("kpl_list")
    open_trade_dates = [date(2026, 7, 24)]

    saturday = service.resolve(
        definition=definition,
        now=datetime(2026, 7, 25, 8, 35, tzinfo=SHANGHAI),
        open_trade_dates=open_trade_dates,
    )
    sunday = service.resolve(
        definition=definition,
        now=datetime(2026, 7, 26, 12, 0, tzinfo=SHANGHAI),
        open_trade_dates=open_trade_dates,
    )

    assert saturday.target_trade_date == date(2026, 7, 24)
    assert sunday.target_trade_date == date(2026, 7, 24)


def test_same_day_release_target_uses_latest_open_day() -> None:
    result = DatasetReleaseTargetService().resolve(
        definition=get_dataset_definition("daily"),
        now=datetime(2026, 7, 28, 8, 0, tzinfo=SHANGHAI),
        open_trade_dates=[date(2026, 7, 27), date(2026, 7, 28)],
    )

    assert result.target_trade_date == date(2026, 7, 28)
    assert result.is_resolved is True


def test_release_target_does_not_guess_when_calendar_has_no_open_day() -> None:
    result = DatasetReleaseTargetService().resolve(
        definition=get_dataset_definition("kpl_list"),
        now=datetime(2026, 7, 28, 9, 0, tzinfo=SHANGHAI),
        open_trade_dates=[],
    )

    assert result.target_trade_date is None
    assert result.is_resolved is False
    assert result.reason == "交易日历缺少可用开市日"
