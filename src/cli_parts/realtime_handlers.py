from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session

from src.foundation.realtime import StockRtDailyCollector, build_realtime_state_store, get_realtime_runtime_config


def run_realtime_collector_serve(
    *,
    session_local: Callable[[], Session],
    max_cycles: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    config = get_realtime_runtime_config()
    store = build_realtime_state_store(config.redis_url)
    collector = StockRtDailyCollector(store=store, config=config.stock_rt_daily)
    cycle = 0
    while True:
        cycle += 1
        started = time.monotonic()
        with session_local() as session:
            result = collector.run_cycle(session)
        echo_fn(
            "realtime-collector-serve: "
            f"cycle={cycle} status={result.status} collection_status={result.collection_status} "
            f"batch_id={result.batch_id or '-'} fetched={result.fetched_rows} "
            f"snapshots={result.snapshot_count} deltas={result.delta_count}"
        )
        if result.message:
            echo_fn(f"realtime-collector-serve: message={result.message}")
        if max_cycles is not None and cycle >= max_cycles:
            return
        elapsed = time.monotonic() - started
        time.sleep(max(config.stock_rt_daily.poll_interval_seconds - elapsed, 0.1))
