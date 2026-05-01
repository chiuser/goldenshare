from __future__ import annotations

from datetime import date

from lake_console.backend.app.cli import StkMinsTerminalProgress
from lake_console.backend.app.services.tushare_stk_mins_sync_service import StkMinsProgressEvent


class FakeStream:
    def __init__(self) -> None:
        self.payload = ""

    def write(self, value: str) -> None:
        self.payload += value

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def test_stk_mins_terminal_progress_keeps_event_updates_on_one_line_for_non_tty_stream():
    stream = FakeStream()
    progress = StkMinsTerminalProgress(stream=stream, min_interval_seconds=0)

    progress(
        StkMinsProgressEvent(
            units_done=1,
            units_total=2,
            ts_code="600000.SH",
            trade_date=None,
            freq=30,
            fetched_rows=100,
            written_rows=0,
            window_start=date(2026, 4, 1),
            window_end=date(2026, 4, 30),
        )
    )
    progress(
        StkMinsProgressEvent(
            units_done=2,
            units_total=2,
            ts_code="000001.SZ",
            trade_date=None,
            freq=30,
            fetched_rows=120,
            written_rows=100,
            window_start=date(2026, 4, 1),
            window_end=date(2026, 4, 30),
        )
    )

    assert "\r" in stream.payload
    assert "\n" not in stream.payload

    progress.finish()

    assert stream.payload.endswith("\n")
