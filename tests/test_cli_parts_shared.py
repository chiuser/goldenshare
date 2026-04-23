from __future__ import annotations

from types import SimpleNamespace

from src.cli_parts.shared import attach_cli_progress_reporter


class _FakeService:
    def __init__(self) -> None:
        self.contract = object()
        self.reporter = None

    def set_cli_progress_reporter(self, reporter) -> None:  # type: ignore[no-untyped-def]
        self.reporter = reporter


def test_attach_cli_progress_reporter_emits_throttled_progress(mocker) -> None:
    service = _FakeService()
    messages: list[str] = []

    monotonic = mocker.patch("src.cli_parts.shared.time.monotonic")
    monotonic.side_effect = [100.0, 101.0, 102.0]
    mocker.patch("src.cli_parts.shared.typer.echo", side_effect=messages.append)

    attach_cli_progress_reporter(service, resource="index_daily")
    assert callable(service.reporter)

    service.reporter(
        SimpleNamespace(
            unit_done=1,
            unit_failed=0,
            unit_total=100,
            rows_fetched=10,
            rows_written=10,
        ),
        "ignored",
    )
    service.reporter(
        SimpleNamespace(
            unit_done=2,
            unit_failed=0,
            unit_total=100,
            rows_fetched=20,
            rows_written=20,
        ),
        "ignored",
    )
    service.reporter(
        SimpleNamespace(
            unit_done=51,
            unit_failed=0,
            unit_total=100,
            rows_fetched=510,
            rows_written=510,
        ),
        "ignored",
    )

    assert len(messages) == 2
    assert "progress 1/100 (1.0%) fetched=10 written=10" in messages[0]
    assert "progress 51/100 (51.0%) fetched=510 written=510" in messages[1]
