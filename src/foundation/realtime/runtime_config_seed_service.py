from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime.feed_config import RealtimeRuntimeConfig, get_realtime_runtime_config


STOCK_RT_DAILY_OBJECT_KEY = "stock_rt_daily"
STOCK_RT_MIN_OBJECT_KEY = "stock_rt_min"


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
        config = runtime_config or get_realtime_runtime_config()
        seed_items = self._build_seed_items(config)
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

    @staticmethod
    def _build_seed_items(config: RealtimeRuntimeConfig) -> tuple[RealtimeRuntimeConfigSeedItem, ...]:
        daily = config.stock_rt_daily
        minute = config.stock_rt_min
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
