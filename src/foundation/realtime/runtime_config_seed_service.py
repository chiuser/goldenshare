from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime.config_catalog import STOCK_RT_DAILY_OBJECT_KEY, STOCK_RT_MIN_OBJECT_KEY
from src.foundation.realtime.runtime_config import RealtimeRuntimeConfig, build_realtime_runtime_config_from_json

DEFAULT_STOCK_RT_DAILY_RUNTIME_CONFIG: dict = {
    "enabled": False,
    "poll_interval_seconds": 6,
    "max_calls_per_minute": 10,
    "lease_ttl_seconds": 30,
    "stale_after_seconds": 20,
    "snapshot_ttl_seconds": 259200,
    "keep_recent_batches": 3,
    "batch_stream_maxlen": 5000,
    "delta_stream_maxlen": 200000,
}

DEFAULT_STOCK_RT_MIN_RUNTIME_CONFIG: dict = {
    "enabled": False,
    "enabled_freqs": ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"],
    "poll_interval_seconds": 60,
    "max_calls_per_minute": 20,
    "lease_ttl_seconds": 90,
    "stale_after_seconds": 90,
    "snapshot_ttl_seconds": 259200,
    "keep_recent_batches": 3,
    "batch_stream_maxlen": 5000,
    "delta_stream_maxlen": 200000,
    "source_timeout_seconds": 20,
}


@dataclass(frozen=True, slots=True)
class RealtimeRuntimeConfigSeedItem:
    object_key: str
    object_kind: str
    status: str
    runtime_config_json: dict


@dataclass(frozen=True, slots=True)
class RealtimeRuntimeConfigSeedReport:
    dry_run: bool
    created_count: int
    skipped_count: int
    items: tuple[RealtimeRuntimeConfigSeedItem, ...]


class RealtimeRuntimeConfigSeedService:
    def run(
        self,
        session: Session,
        *,
        dry_run: bool = True,
        runtime_config: RealtimeRuntimeConfig | None = None,
    ) -> RealtimeRuntimeConfigSeedReport:
        config = runtime_config or build_default_realtime_runtime_config()
        seed_items = _build_seed_items(config)
        results: list[RealtimeRuntimeConfigSeedItem] = []
        created_count = 0
        skipped_count = 0

        for item in seed_items:
            existing = session.get(RealtimeRuntimeConfigRecord, item.object_key)
            if existing is not None:
                skipped_count += 1
                results.append(
                    RealtimeRuntimeConfigSeedItem(
                        object_key=item.object_key,
                        object_kind=existing.object_kind,
                        status="existing",
                        runtime_config_json=dict(existing.runtime_config_json or {}),
                    )
                )
                continue

            created_count += 1
            results.append(item)
            if dry_run:
                continue

            session.add(
                RealtimeRuntimeConfigRecord(
                    object_key=item.object_key,
                    object_kind=item.object_kind,
                    runtime_config_json=dict(item.runtime_config_json),
                    version=1,
                    requires_collector_restart=True,
                    updated_by_user_id=None,
                )
            )

        if not dry_run:
            session.commit()

        return RealtimeRuntimeConfigSeedReport(
            dry_run=dry_run,
            created_count=created_count,
            skipped_count=skipped_count,
            items=tuple(results),
        )


def build_default_realtime_runtime_config() -> RealtimeRuntimeConfig:
    return build_realtime_runtime_config_from_json(
        daily_config=deepcopy(DEFAULT_STOCK_RT_DAILY_RUNTIME_CONFIG),
        minute_config=deepcopy(DEFAULT_STOCK_RT_MIN_RUNTIME_CONFIG),
    )


def _build_seed_items(config: RealtimeRuntimeConfig) -> tuple[RealtimeRuntimeConfigSeedItem, ...]:
    daily = config.stock_rt_daily
    minute = config.stock_rt_min
    _validate_seed_runtime_config(config)
    return (
        RealtimeRuntimeConfigSeedItem(
            object_key=STOCK_RT_DAILY_OBJECT_KEY,
            object_kind="collector_feed",
            status="create",
            runtime_config_json={
                "enabled": daily.enabled,
                "poll_interval_seconds": daily.poll_interval_seconds,
                "max_calls_per_minute": daily.max_calls_per_minute,
                "lease_ttl_seconds": daily.lease_ttl_seconds,
                "stale_after_seconds": daily.stale_after_seconds,
                "snapshot_ttl_seconds": daily.storage.snapshot_ttl_seconds,
                "keep_recent_batches": daily.storage.keep_recent_batches,
                "batch_stream_maxlen": daily.storage.batch_stream_maxlen,
                "delta_stream_maxlen": daily.storage.delta_stream_maxlen,
            },
        ),
        RealtimeRuntimeConfigSeedItem(
            object_key=STOCK_RT_MIN_OBJECT_KEY,
            object_kind="feed_group",
            status="create",
            runtime_config_json={
                "enabled": minute.enabled,
                "enabled_freqs": list(minute.enabled_freqs),
                "poll_interval_seconds": minute.poll_interval_seconds,
                "max_calls_per_minute": minute.max_calls_per_minute,
                "lease_ttl_seconds": minute.lease_ttl_seconds,
                "stale_after_seconds": minute.stale_after_seconds,
                "snapshot_ttl_seconds": minute.storage.snapshot_ttl_seconds,
                "keep_recent_batches": minute.storage.keep_recent_batches,
                "batch_stream_maxlen": minute.storage.batch_stream_maxlen,
                "delta_stream_maxlen": minute.storage.delta_stream_maxlen,
                "source_timeout_seconds": minute.source_timeout_seconds,
            },
        ),
    )


def _validate_seed_runtime_config(config: RealtimeRuntimeConfig) -> None:
    build_realtime_runtime_config_from_json(
        daily_config={
            "enabled": config.stock_rt_daily.enabled,
            "poll_interval_seconds": config.stock_rt_daily.poll_interval_seconds,
            "max_calls_per_minute": config.stock_rt_daily.max_calls_per_minute,
            "lease_ttl_seconds": config.stock_rt_daily.lease_ttl_seconds,
            "stale_after_seconds": config.stock_rt_daily.stale_after_seconds,
            "snapshot_ttl_seconds": config.stock_rt_daily.storage.snapshot_ttl_seconds,
            "keep_recent_batches": config.stock_rt_daily.storage.keep_recent_batches,
            "batch_stream_maxlen": config.stock_rt_daily.storage.batch_stream_maxlen,
            "delta_stream_maxlen": config.stock_rt_daily.storage.delta_stream_maxlen,
        },
        minute_config={
            "enabled": config.stock_rt_min.enabled,
            "enabled_freqs": list(config.stock_rt_min.enabled_freqs),
            "poll_interval_seconds": config.stock_rt_min.poll_interval_seconds,
            "max_calls_per_minute": config.stock_rt_min.max_calls_per_minute,
            "lease_ttl_seconds": config.stock_rt_min.lease_ttl_seconds,
            "stale_after_seconds": config.stock_rt_min.stale_after_seconds,
            "snapshot_ttl_seconds": config.stock_rt_min.storage.snapshot_ttl_seconds,
            "keep_recent_batches": config.stock_rt_min.storage.keep_recent_batches,
            "batch_stream_maxlen": config.stock_rt_min.storage.batch_stream_maxlen,
            "delta_stream_maxlen": config.stock_rt_min.storage.delta_stream_maxlen,
            "source_timeout_seconds": config.stock_rt_min.source_timeout_seconds,
        },
    )
