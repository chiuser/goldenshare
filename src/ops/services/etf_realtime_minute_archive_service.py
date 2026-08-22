from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.foundation.realtime.etf_volume_metrics import build_etf_minute_metrics_for_trade_date
from src.foundation.realtime.etf_volume_metrics import DATA_QUALITY_OK, EtfMinuteMetric
from src.foundation.realtime.state_store import RealtimeStateStore
from src.ops.models.ops.etf_realtime_minute_stat import EtfRealtimeMinuteStat
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool


@dataclass(frozen=True, slots=True)
class EtfRealtimeMinuteArchiveReport:
    trade_date: date
    monitor_count: int
    metric_count: int
    upserted_count: int


class EtfRealtimeMinuteArchiveService:
    def run(
        self,
        session: Session,
        *,
        store: RealtimeStateStore,
        feed_key: str,
        trade_date: date,
    ) -> EtfRealtimeMinuteArchiveReport:
        ts_codes = [
            item.ts_code
            for item in session.query(EtfRealtimeMonitorPool)
            .filter(EtfRealtimeMonitorPool.enabled.is_(True))
            .order_by(EtfRealtimeMonitorPool.ts_code)
            .all()
        ]
        if not ts_codes:
            return EtfRealtimeMinuteArchiveReport(trade_date=trade_date, monitor_count=0, metric_count=0, upserted_count=0)
        metrics = build_etf_minute_metrics_for_trade_date(
            store,
            feed_key=feed_key,
            ts_codes=ts_codes,
            trade_date=trade_date,
            batch_limit=None,
            complete_missing=True,
        )
        selected_metrics = _select_final_metrics(metrics, trade_date=trade_date)
        rows = [_metric_to_row(metric) for metric in selected_metrics]
        if not rows:
            return EtfRealtimeMinuteArchiveReport(trade_date=trade_date, monitor_count=len(ts_codes), metric_count=0, upserted_count=0)
        if session.bind and session.bind.dialect.name == "postgresql":
            stmt = pg_insert(EtfRealtimeMinuteStat).values(rows)
            update_columns = {
                key: getattr(stmt.excluded, key)
                for key in rows[0]
                if key not in {"trade_date", "minute_bucket", "ts_code"}
            }
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["trade_date", "minute_bucket", "ts_code"],
                    set_=update_columns,
                )
            )
        else:
            for row in rows:
                existing = session.get(EtfRealtimeMinuteStat, (row["trade_date"], row["minute_bucket"], row["ts_code"]))
                if existing is None:
                    session.add(EtfRealtimeMinuteStat(**row))
                else:
                    for key, value in row.items():
                        if key not in {"trade_date", "minute_bucket", "ts_code"}:
                            setattr(existing, key, value)
        session.commit()
        return EtfRealtimeMinuteArchiveReport(
            trade_date=trade_date,
            monitor_count=len(ts_codes),
            metric_count=len(rows),
            upserted_count=len(rows),
        )


def _select_final_metrics(metrics: list[EtfMinuteMetric], *, trade_date: date) -> list[EtfMinuteMetric]:
    selected: dict[tuple[date, time, str], EtfMinuteMetric] = {}
    for metric in metrics:
        if metric.trade_date != trade_date:
            continue
        key = (metric.trade_date, metric.minute_bucket, metric.ts_code)
        current = selected.get(key)
        if current is None or metric.data_quality == DATA_QUALITY_OK or current.data_quality != DATA_QUALITY_OK:
            selected[key] = metric
    return sorted(selected.values(), key=lambda item: (item.ts_code, item.minute_bucket))


def _metric_to_row(metric: EtfMinuteMetric) -> dict[str, object]:
    return {
        "trade_date": metric.trade_date,
        "minute_bucket": metric.minute_bucket,
        "ts_code": metric.ts_code,
        "source_trade_time": metric.source_trade_time,
        "source_batch_id": metric.source_batch_id,
        "previous_batch_id": metric.previous_batch_id,
        "cumulative_amount_yuan": metric.cumulative_amount_yuan,
        "amount_delta_yuan": metric.amount_delta_yuan,
        "cumulative_vol": metric.cumulative_vol,
        "vol_delta": metric.vol_delta,
        "data_quality": metric.data_quality,
        "missing_reason": metric.missing_reason,
    }
