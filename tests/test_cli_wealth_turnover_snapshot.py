from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app


def test_wealth_build_turnover_snapshot_invokes_materializer_and_prints_summary(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.materialize_trade_date.return_value = [
        SimpleNamespace(
            trade_date=date(2026, 5, 8),
            freq=30,
            build_status="READY",
            latest_trade_time=datetime(2026, 5, 8, 15, 0, 0),
            security_count=5187,
            source_row_count=51720,
            points_count=9,
            total_amount=Decimal("3075700000.00"),
            total_vol=91234567,
            build_note=None,
        )
    ]
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
