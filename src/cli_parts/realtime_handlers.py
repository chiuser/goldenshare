from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session

from src.foundation.realtime import RealtimeCollectorService, build_realtime_state_store, get_realtime_runtime_config
from src.foundation.realtime.config_catalog import ETF_RT_DAILY_FEED_KEY
from src.ops.services.etf_realtime_monitor_service import EtfRealtimeMonitorService


def run_realtime_collector_serve(
    *,
    session_local: Callable[[], Session],
    max_cycles: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        config = get_realtime_runtime_config(session)
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
            if result.feed_key == ETF_RT_DAILY_FEED_KEY and result.status == "ok" and result.batch_id:
                try:
                    with session_local() as monitor_session:
                        monitor_result = EtfRealtimeMonitorService().run_after_etf_batch(
                            monitor_session,
                            store=store,
                            feed_key=result.feed_key,
                        )
                    echo_fn(
                        "realtime-collector-serve: "
                        f"feed_key={result.feed_key} monitor_status={monitor_result.status} "
                        f"evaluated={monitor_result.evaluated_count} alerts={monitor_result.alert_count} "
                        f"failed={monitor_result.failed_count}"
                    )
                    if monitor_result.message:
                        echo_fn(f"realtime-collector-serve: feed_key={result.feed_key} monitor_message={monitor_result.message}")
                except Exception as exc:
                    echo_fn(f"realtime-collector-serve: feed_key={result.feed_key} monitor_status=failed message={exc}")
        if max_cycles is not None and cycle >= max_cycles:
            return
        time.sleep(cycle_result.next_sleep_seconds)
