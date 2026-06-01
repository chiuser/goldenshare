from __future__ import annotations

from pathlib import Path


def test_realtime_collector_cli_uses_generic_command_only() -> None:
    cli_text = Path("src/cli.py").read_text(encoding="utf-8")
    handler_text = Path("src/cli_parts/realtime_handlers.py").read_text(encoding="utf-8")

    assert '@app.command("realtime-collector-serve")' in cli_text
    assert "run_realtime_collector_serve" in handler_text
    assert "realtime-stock-rt-daily-serve" not in cli_text
    assert "realtime-stock-rt-daily-serve" not in handler_text


def test_realtime_collector_systemd_unit_uses_generic_command() -> None:
    unit_text = Path("scripts/goldenshare-realtime-collector.service").read_text(encoding="utf-8")

    assert "goldenshare realtime-collector-serve" in unit_text
    assert "realtime-stock-rt-daily-serve" not in unit_text
