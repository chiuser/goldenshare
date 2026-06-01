from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session

from src.foundation.realtime import RealtimeCollectorService, build_realtime_state_store, get_realtime_runtime_config


def run_realtime_collector_serve(
    *,
    session_local: Callable[[], Session],
    max_cycles: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    config = get_realtime_runtime_config()
    store = build_realtime_state_store(config.redis_url)
    collector = RealtimeCollectorService(store=store, config=config)
    cycle = 0
    while True:
        cycle += 1
        with session_local() as session:
            cycle_result = collector.run_due_cycle(session)
        if not cycle_result.feed_runs:
            echo_fn(f"realtime-collector-serve: cycle={cycle} no_due_feeds=true")
        for result in cycle_result.feed_runs:
            freq = f" freq={result.freq}" if result.freq else ""
            echo_fn(
                "realtime-collector-serve: "
                f"cycle={cycle} feed_key={result.feed_key}{freq} status={result.status} "
                f"collection_status={result.collection_status} batch_id={result.batch_id or '-'} "
                f"fetched={result.fetched_rows} snapshots={result.snapshot_count} "
                f"deltas={result.delta_count} invalid={result.invalid_count}"
            )
            if result.message:
                echo_fn(f"realtime-collector-serve: feed_key={result.feed_key}{freq} message={result.message}")
        if max_cycles is not None and cycle >= max_cycles:
            return
        time.sleep(cycle_result.next_sleep_seconds)
