from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.realtime import StockRtDailyCollector, build_realtime_state_store


def run_realtime_stock_rt_daily_serve(
    *,
    session_local: Callable[[], Session],
    max_cycles: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    settings = get_settings()
    store = build_realtime_state_store(settings.redis_url)
    collector = StockRtDailyCollector(store=store)
    cycle = 0
    while True:
        cycle += 1
        started = time.monotonic()
        with session_local() as session:
            result = collector.run_cycle(session)
        echo_fn(
            "realtime-stock-rt-daily-serve: "
            f"cycle={cycle} status={result.status} collection_status={result.collection_status} "
            f"batch_id={result.batch_id or '-'} fetched={result.fetched_rows} "
            f"snapshots={result.snapshot_count} deltas={result.delta_count}"
        )
        if result.message:
            echo_fn(f"realtime-stock-rt-daily-serve: message={result.message}")
        if max_cycles is not None and cycle >= max_cycles:
            return
        elapsed = time.monotonic() - started
        time.sleep(max(settings.realtime_stock_rt_daily_poll_interval_seconds - elapsed, 0.1))
