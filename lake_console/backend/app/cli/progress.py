from __future__ import annotations

import sys
import time

from lake_console.backend.app.services.tushare_stk_mins_sync_service import StkMinsProgressEvent


class StkMinsTerminalProgress:
    def __init__(self, *, stream=None, width: int = 24, min_interval_seconds: float = 0.2) -> None:
        self.stream = stream or sys.stderr
        self.width = width
        self.min_interval_seconds = min_interval_seconds
        self._last_render_at = 0.0
        self._last_line_length = 0
        self._line_active = False

    def __call__(self, payload: str | StkMinsProgressEvent) -> None:
        if isinstance(payload, StkMinsProgressEvent):
            self._render_event(payload)
            return
        self._print_message(payload)

    def finish(self) -> None:
        if self._line_active:
            self.stream.write("\n")
            self.stream.flush()
            self._line_active = False
            self._last_line_length = 0

    def _render_event(self, event: StkMinsProgressEvent) -> None:
        now = time.monotonic()
        if event.units_done < event.units_total and now - self._last_render_at < self.min_interval_seconds:
            return
        self._last_render_at = now
        percent = 0.0 if event.units_total <= 0 else min(1.0, event.units_done / event.units_total)
        filled = int(round(self.width * percent))
        bar = "█" * filled + "░" * (self.width - filled)
        line = (
            f"[{bar}] {percent * 100:6.2f}% "
            f"unit={event.units_done}/{event.units_total} "
            f"ts_code={event.ts_code} {_format_event_window(event)} freq={event.freq} "
            f"fetched={event.fetched_rows} written={event.written_rows}"
        )
        if event.page is not None and event.offset is not None:
            line += f" page={event.page} offset={event.offset}"
        padding = " " * max(0, self._last_line_length - len(line))
        self.stream.write(f"\r{line}{padding}")
        self.stream.flush()
        self._last_line_length = len(line)
        self._line_active = True

    def _print_message(self, message: str) -> None:
        if self._line_active:
            self.stream.write("\n")
            self._line_active = False
            self._last_line_length = 0
        self.stream.write(message + "\n")
        self.stream.flush()


def _format_event_window(event: StkMinsProgressEvent) -> str:
    if event.window_start and event.window_end:
        return f"window={event.window_start.isoformat()}~{event.window_end.isoformat()}"
    if event.trade_date:
        return f"trade_date={event.trade_date.isoformat()}"
    return "window=-"
