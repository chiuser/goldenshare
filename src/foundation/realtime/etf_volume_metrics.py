from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from src.foundation.realtime.state_store import RealtimeStateStore


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
ETF_VOLUME_WINDOWS = (1, 5, 15)
DATA_QUALITY_OK = "ok"
DATA_QUALITY_MISSING = "missing"
DATA_QUALITY_INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class EtfMinuteMetric:
    trade_date: date
    minute_bucket: time
    ts_code: str
    source_trade_time: datetime | None
    source_batch_id: str | None
    previous_batch_id: str | None
    cumulative_amount_yuan: Decimal | None
    amount_delta_yuan: Decimal | None
    cumulative_vol: Decimal | None
    vol_delta: Decimal | None
    data_quality: str
    missing_reason: str | None


@dataclass(frozen=True, slots=True)
class EtfWindowMetric:
    trade_date: date
    bucket_end_time: time
    window_minutes: int
    ts_code: str
    amount_yuan: Decimal | None
    data_quality: str
    missing_reason: str | None


def build_latest_etf_minute_metrics(
    store: RealtimeStateStore,
    *,
    feed_key: str,
    ts_codes: Sequence[str],
    batch_limit: int = 260,
) -> list[EtfMinuteMetric]:
    batch_ids = list(reversed(store.list_batch_ids(feed_key, limit=batch_limit)))
    return _build_pairwise_metrics(store, feed_key=feed_key, batch_ids=batch_ids, ts_codes=ts_codes)[-len(ts_codes) :]


def build_etf_minute_metrics_for_trade_date(
    store: RealtimeStateStore,
    *,
    feed_key: str,
    ts_codes: Sequence[str],
    trade_date: date,
    batch_limit: int | None = None,
) -> list[EtfMinuteMetric]:
    batch_ids = list(reversed(store.list_batch_ids(feed_key, limit=batch_limit)))
    filtered_batch_ids: list[str] = []
    for batch_id in batch_ids:
        meta = store.get_batch_meta(feed_key, batch_id) or {}
        meta_date = _parse_iso_datetime(meta.get("published_at") or meta.get("received_at"))
        if meta_date is not None and meta_date.astimezone(CN_TIMEZONE).date() == trade_date:
            filtered_batch_ids.append(batch_id)
    return _build_pairwise_metrics(store, feed_key=feed_key, batch_ids=filtered_batch_ids, ts_codes=ts_codes)


def aggregate_etf_window_metrics(
    minute_metrics: Sequence[EtfMinuteMetric],
    *,
    window_minutes: int,
) -> list[EtfWindowMetric]:
    if window_minutes not in ETF_VOLUME_WINDOWS:
        raise ValueError(f"unsupported ETF volume window: {window_minutes}")
    if window_minutes == 1:
        return [
            EtfWindowMetric(
                trade_date=item.trade_date,
                bucket_end_time=item.minute_bucket,
                window_minutes=1,
                ts_code=item.ts_code,
                amount_yuan=item.amount_delta_yuan,
                data_quality=item.data_quality,
                missing_reason=item.missing_reason,
            )
            for item in minute_metrics
        ]

    grouped: dict[tuple[date, str], list[EtfMinuteMetric]] = {}
    for item in minute_metrics:
        grouped.setdefault((item.trade_date, item.ts_code), []).append(item)

    results: list[EtfWindowMetric] = []
    for (trade_date, ts_code), items in sorted(grouped.items(), key=lambda value: (value[0][0], value[0][1])):
        sorted_items = sorted(items, key=lambda item: item.minute_bucket)
        by_bucket = {item.minute_bucket: item for item in sorted_items}
        for item in sorted_items:
            bucket = _window_bucket_end(item.minute_bucket, window_minutes)
            if bucket is None:
                continue
            expected_buckets = _window_buckets(bucket, window_minutes)
            window_items = [by_bucket.get(expected_bucket) for expected_bucket in expected_buckets]
            if any(window_item is None for window_item in window_items):
                results.append(
                    EtfWindowMetric(
                        trade_date=trade_date,
                        bucket_end_time=bucket,
                        window_minutes=window_minutes,
                        ts_code=ts_code,
                        amount_yuan=None,
                        data_quality=DATA_QUALITY_MISSING,
                        missing_reason="window_not_complete",
                    )
                )
                continue
            materialized_items = [window_item for window_item in window_items if window_item is not None]
            bad_item = next((window_item for window_item in materialized_items if window_item.data_quality != DATA_QUALITY_OK), None)
            if bad_item is not None:
                results.append(
                    EtfWindowMetric(
                        trade_date=trade_date,
                        bucket_end_time=bucket,
                        window_minutes=window_minutes,
                        ts_code=ts_code,
                        amount_yuan=None,
                        data_quality=bad_item.data_quality,
                        missing_reason=bad_item.missing_reason,
                    )
                )
                continue
            results.append(
                EtfWindowMetric(
                    trade_date=trade_date,
                    bucket_end_time=bucket,
                    window_minutes=window_minutes,
                    ts_code=ts_code,
                    amount_yuan=sum((window_item.amount_delta_yuan or Decimal("0")) for window_item in materialized_items),
                    data_quality=DATA_QUALITY_OK,
                    missing_reason=None,
                )
            )
    return results


def _build_pairwise_metrics(
    store: RealtimeStateStore,
    *,
    feed_key: str,
    batch_ids: Sequence[str],
    ts_codes: Sequence[str],
) -> list[EtfMinuteMetric]:
    normalized_codes = [_normalize_ts_code(item) for item in ts_codes if _normalize_ts_code(item)]
    if len(batch_ids) < 2:
        return [_missing_metric(ts_code=code, reason="insufficient_batches") for code in normalized_codes]

    results: list[EtfMinuteMetric] = []
    previous_snapshots: dict[str, dict[str, Any]] | None = None
    previous_batch_id: str | None = None
    for batch_id in batch_ids:
        current_snapshots = store.get_batch_snapshots(feed_key, batch_id, ts_codes=normalized_codes)
        if previous_snapshots is not None and previous_batch_id is not None:
            for code in normalized_codes:
                results.append(
                    _metric_from_pair(
                        ts_code=code,
                        batch_id=batch_id,
                        snapshot=current_snapshots.get(code),
                        previous_batch_id=previous_batch_id,
                        previous_snapshot=previous_snapshots.get(code),
                    )
                )
        previous_snapshots = current_snapshots
        previous_batch_id = batch_id
    return results


def _metric_from_pair(
    *,
    ts_code: str,
    batch_id: str,
    snapshot: Mapping[str, Any] | None,
    previous_batch_id: str,
    previous_snapshot: Mapping[str, Any] | None,
) -> EtfMinuteMetric:
    if snapshot is None:
        return _missing_metric(ts_code=ts_code, reason="current_snapshot_missing", batch_id=batch_id, previous_batch_id=previous_batch_id)
    if previous_snapshot is None:
        return _missing_metric(ts_code=ts_code, reason="previous_snapshot_missing", batch_id=batch_id, previous_batch_id=previous_batch_id)

    source_trade_time = _parse_iso_datetime(snapshot.get("trade_time"))
    if source_trade_time is None:
        return _invalid_metric(ts_code=ts_code, reason="invalid_trade_time", batch_id=batch_id, previous_batch_id=previous_batch_id)
    source_trade_time = source_trade_time.astimezone(CN_TIMEZONE)
    bucket = _minute_bucket_end(source_trade_time)
    if bucket is None:
        return _missing_metric(
            ts_code=ts_code,
            reason="trade_time_outside_session",
            batch_id=batch_id,
            previous_batch_id=previous_batch_id,
            source_trade_time=source_trade_time,
        )

    current_amount = _parse_decimal(snapshot.get("amount"))
    previous_amount = _parse_decimal(previous_snapshot.get("amount"))
    current_vol = _parse_decimal(snapshot.get("vol"))
    previous_vol = _parse_decimal(previous_snapshot.get("vol"))
    if current_amount is None or previous_amount is None:
        return _invalid_metric(ts_code=ts_code, reason="invalid_amount", batch_id=batch_id, previous_batch_id=previous_batch_id, source_trade_time=source_trade_time)
    if current_vol is None or previous_vol is None:
        return _invalid_metric(ts_code=ts_code, reason="invalid_vol", batch_id=batch_id, previous_batch_id=previous_batch_id, source_trade_time=source_trade_time)
    amount_delta = current_amount - previous_amount
    vol_delta = current_vol - previous_vol
    if amount_delta < 0:
        return _invalid_metric(ts_code=ts_code, reason="amount_decreased", batch_id=batch_id, previous_batch_id=previous_batch_id, source_trade_time=source_trade_time)
    if vol_delta < 0:
        return _invalid_metric(ts_code=ts_code, reason="vol_decreased", batch_id=batch_id, previous_batch_id=previous_batch_id, source_trade_time=source_trade_time)
    return EtfMinuteMetric(
        trade_date=source_trade_time.date(),
        minute_bucket=bucket,
        ts_code=ts_code,
        source_trade_time=source_trade_time,
        source_batch_id=batch_id,
        previous_batch_id=previous_batch_id,
        cumulative_amount_yuan=current_amount,
        amount_delta_yuan=amount_delta,
        cumulative_vol=current_vol,
        vol_delta=vol_delta,
        data_quality=DATA_QUALITY_OK,
        missing_reason=None,
    )


def _missing_metric(
    *,
    ts_code: str,
    reason: str,
    batch_id: str | None = None,
    previous_batch_id: str | None = None,
    source_trade_time: datetime | None = None,
) -> EtfMinuteMetric:
    trade_date = source_trade_time.date() if source_trade_time is not None else date.min
    minute_bucket = _minute_bucket_end(source_trade_time) if source_trade_time is not None else time.min
    return EtfMinuteMetric(
        trade_date=trade_date,
        minute_bucket=minute_bucket or time.min,
        ts_code=ts_code,
        source_trade_time=source_trade_time,
        source_batch_id=batch_id,
        previous_batch_id=previous_batch_id,
        cumulative_amount_yuan=None,
        amount_delta_yuan=None,
        cumulative_vol=None,
        vol_delta=None,
        data_quality=DATA_QUALITY_MISSING,
        missing_reason=reason,
    )


def _invalid_metric(
    *,
    ts_code: str,
    reason: str,
    batch_id: str | None = None,
    previous_batch_id: str | None = None,
    source_trade_time: datetime | None = None,
) -> EtfMinuteMetric:
    trade_date = source_trade_time.date() if source_trade_time is not None else date.min
    minute_bucket = _minute_bucket_end(source_trade_time) if source_trade_time is not None else time.min
    return EtfMinuteMetric(
        trade_date=trade_date,
        minute_bucket=minute_bucket or time.min,
        ts_code=ts_code,
        source_trade_time=source_trade_time,
        source_batch_id=batch_id,
        previous_batch_id=previous_batch_id,
        cumulative_amount_yuan=None,
        amount_delta_yuan=None,
        cumulative_vol=None,
        vol_delta=None,
        data_quality=DATA_QUALITY_INVALID,
        missing_reason=reason,
    )


def _minute_bucket_end(value: datetime) -> time | None:
    value = value.astimezone(CN_TIMEZONE)
    start_end_pairs = (
        (time(9, 30), time(11, 30)),
        (time(13, 0), time(15, 0)),
    )
    current = value.time().replace(second=0, microsecond=0)
    for start, end in start_end_pairs:
        if start <= current < end:
            bucket_dt = value.replace(second=0, microsecond=0) + timedelta(minutes=1)
            return bucket_dt.time().replace(second=0, microsecond=0)
    if current in {time(11, 30), time(15, 0)}:
        return current
    return None


def _window_bucket_end(bucket: time, window_minutes: int) -> time | None:
    sessions = ((time(9, 31), time(11, 30)), (time(13, 1), time(15, 0)))
    for start, end in sessions:
        if not (start <= bucket <= end):
            continue
        start_minutes = start.hour * 60 + start.minute
        current_minutes = bucket.hour * 60 + bucket.minute
        offset = current_minutes - start_minutes + 1
        if offset % window_minutes != 0:
            return None
        return bucket
    return None


def _window_buckets(bucket_end_time: time, window_minutes: int) -> list[time]:
    end_dt = datetime.combine(date(2000, 1, 1), bucket_end_time)
    return [(end_dt - timedelta(minutes=offset)).time() for offset in reversed(range(window_minutes))]


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CN_TIMEZONE)
    return parsed


def _normalize_ts_code(value: Any) -> str:
    return str(value or "").strip().upper()
