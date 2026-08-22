from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app


def test_cli_ops_archive_etf_realtime_minute_stats_help_registers() -> None:
    result = CliRunner().invoke(app, ["ops-archive-etf-realtime-minute-stats", "--help"])

    assert result.exit_code == 0
    assert "--trade-date" in result.stdout


def test_cli_ops_archive_etf_realtime_minute_stats_rejects_invalid_trade_date() -> None:
    result = CliRunner().invoke(
        app,
        ["ops-archive-etf-realtime-minute-stats", "--trade-date", "20260822"],
    )

    assert result.exit_code != 0
    assert "trade_date 必须为 YYYY-MM-DD 格式" in result.stderr
