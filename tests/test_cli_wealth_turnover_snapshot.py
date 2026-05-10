from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app


def _combined_output(result) -> str:
    return (result.stdout or "") + (getattr(result, "stderr", "") or "")


def _build_item(*, trade_date: date, freq: int = 30, build_status: str = "READY") -> SimpleNamespace:
    return SimpleNamespace(
        trade_date=trade_date,
        freq=freq,
        build_status=build_status,
        latest_trade_time=datetime.combine(trade_date, datetime.min.time()).replace(hour=15),
        security_count=5187,
        source_row_count=51720,
        points_count=9,
        total_amount=Decimal("3075700000.00"),
        total_vol=91234567,
        build_note=None,
    )


def test_wealth_build_turnover_snapshot_invokes_materializer_and_prints_summary(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.materialize_trade_date.return_value = [_build_item(trade_date=date(2026, 5, 8))]
    service_cls = mocker.patch("src.cli.TurnoverSnapshotMaterializeService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "wealth-build-turnover-snapshot",
            "--trade-date",
            "2026-05-08",
            "--freq",
            "30",
        ],
    )

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.materialize_trade_date.assert_called_once_with(
        session,
        trade_date=date(2026, 5, 8),
        freqs=[30],
    )
    session.commit.assert_called_once()
    assert "turnover-snapshot trade_date=2026-05-08 freq=30 status=READY" in result.stdout
    assert "wealth-build-turnover-snapshot done trade_date=2026-05-08 freq_count=1 ready=1 failed=0" in result.stdout


def test_wealth_build_turnover_snapshot_range_expands_open_dates_and_commits_each_day(mocker) -> None:
    calendar_context = mocker.MagicMock()
    calendar_session = mocker.Mock()
    calendar_context.__enter__.return_value = calendar_session
    calendar_context.__exit__.return_value = False
    calendar_session.scalars.return_value = [date(2026, 5, 4), date(2026, 5, 5)]

    first_context = mocker.MagicMock()
    first_session = mocker.Mock()
    first_context.__enter__.return_value = first_session
    first_context.__exit__.return_value = False

    second_context = mocker.MagicMock()
    second_session = mocker.Mock()
    second_context.__enter__.return_value = second_session
    second_context.__exit__.return_value = False

    mocker.patch("src.cli.SessionLocal", side_effect=[calendar_context, first_context, second_context])

    service = mocker.Mock()
    service.materialize_trade_date.side_effect = [
        [_build_item(trade_date=date(2026, 5, 4), freq=30)],
        [_build_item(trade_date=date(2026, 5, 5), freq=30)],
    ]
    service_cls = mocker.patch("src.cli.TurnoverSnapshotMaterializeService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "wealth-build-turnover-snapshot",
            "--start-date",
            "2026-05-01",
            "--end-date",
            "2026-05-08",
            "--freq",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert service_cls.call_count == 2
    assert service.materialize_trade_date.call_args_list == [
        mocker.call(first_session, trade_date=date(2026, 5, 4), freqs=[30]),
        mocker.call(second_session, trade_date=date(2026, 5, 5), freqs=[30]),
    ]
    first_session.commit.assert_called_once()
    second_session.commit.assert_called_once()
    calendar_session.commit.assert_not_called()
    assert (
        "wealth-build-turnover-snapshot plan range=2026-05-01~2026-05-08 trade_days=2 freqs=30"
        in result.stdout
    )
    assert "[1/2] trade_date=2026-05-04 ready=1 failed=0" in result.stdout
    assert "[2/2] trade_date=2026-05-05 ready=1 failed=0" in result.stdout
    assert "wealth-build-turnover-snapshot done dates=2 freq_jobs=2 ready=2 failed=0" in result.stdout


def test_wealth_build_turnover_snapshot_rejects_mixed_single_and_range_modes() -> None:
    result = CliRunner().invoke(
        app,
        [
            "wealth-build-turnover-snapshot",
            "--trade-date",
            "2026-05-08",
            "--start-date",
            "2026-05-01",
            "--end-date",
            "2026-05-08",
        ],
    )

    assert result.exit_code != 0
    assert "--trade-date 不能与 --start-date/--end-date 同时使用" in _combined_output(result)


def test_wealth_build_turnover_snapshot_rejects_partial_range() -> None:
    result = CliRunner().invoke(
        app,
        [
            "wealth-build-turnover-snapshot",
            "--start-date",
            "2026-05-01",
        ],
    )

    assert result.exit_code != 0
    assert "--start-date 与 --end-date 必须同时提供" in _combined_output(result)


def test_wealth_build_turnover_snapshot_rejects_range_without_open_trade_days(mocker) -> None:
    calendar_context = mocker.MagicMock()
    calendar_session = mocker.Mock()
    calendar_context.__enter__.return_value = calendar_session
    calendar_context.__exit__.return_value = False
    calendar_session.scalars.return_value = []
    mocker.patch("src.cli.SessionLocal", return_value=calendar_context)

    result = CliRunner().invoke(
        app,
        [
            "wealth-build-turnover-snapshot",
            "--start-date",
            "2026-05-02",
            "--end-date",
            "2026-05-03",
        ],
    )

    assert result.exit_code != 0
    assert "区间 2026-05-02~2026-05-03 内没有开市交易日" in _combined_output(result)
