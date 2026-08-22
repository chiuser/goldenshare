from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.realtime.etf_volume_metrics import (
    DATA_QUALITY_OK,
    EtfWindowMetric,
    aggregate_etf_window_metrics,
    build_etf_minute_metrics_for_trade_date,
)
from src.foundation.realtime.state_store import RealtimeStateStore
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.models.ops.etf_realtime_minute_stat import EtfRealtimeMinuteStat
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.models.ops.etf_realtime_monitor_rule import EtfRealtimeMonitorRule
from src.ops.services.etf_realtime_feishu_alert_service import EtfRealtimeFeishuAlertService


LOGGER = logging.getLogger(__name__)
CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
SEVERITY_RANK = {"observe": 1, "alert": 2, "strong": 3}


@dataclass(frozen=True, slots=True)
class EtfRealtimeMonitorRunResult:
    status: str
    evaluated_count: int
    alert_count: int
    failed_count: int = 0
    message: str | None = None


class EtfRealtimeMonitorService:
    def __init__(
        self,
        *,
        feishu_service: EtfRealtimeFeishuAlertService | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._feishu_service = feishu_service or EtfRealtimeFeishuAlertService()
        self._logger = logger or LOGGER

    def run_after_etf_batch(
        self,
        session: Session,
        *,
        store: RealtimeStateStore,
        feed_key: str,
        trade_date: datetime | None = None,
    ) -> EtfRealtimeMonitorRunResult:
        pool_items = list(
            session.scalars(
                select(EtfRealtimeMonitorPool)
                .where(EtfRealtimeMonitorPool.enabled.is_(True))
                .order_by(EtfRealtimeMonitorPool.ts_code)
            ).all()
        )
        if not pool_items:
            return EtfRealtimeMonitorRunResult(status="skipped", evaluated_count=0, alert_count=0, message="monitor pool empty")
        rule_items = list(session.scalars(select(EtfRealtimeMonitorRule).where(EtfRealtimeMonitorRule.enabled.is_(True))).all())
        if not rule_items:
            return EtfRealtimeMonitorRunResult(status="skipped", evaluated_count=0, alert_count=0, message="monitor rules empty")

        now = datetime.now(CN_TIMEZONE)
        target_trade_date = (trade_date or now).astimezone(CN_TIMEZONE).date()
        ts_codes = [item.ts_code for item in pool_items]
        etf_names = _load_etf_names(session, ts_codes, logger=self._logger)
        minute_metrics = build_etf_minute_metrics_for_trade_date(
            store,
            feed_key=feed_key,
            ts_codes=ts_codes,
            trade_date=target_trade_date,
            batch_limit=260,
        )
        alerts_created = 0
        evaluated = 0
        failed = 0
        pool_by_code = {item.ts_code: item for item in pool_items}
        for window in (1, 5, 15):
            for metric in _latest_window_metrics(aggregate_etf_window_metrics(minute_metrics, window_minutes=window)):
                try:
                    if metric.data_quality != DATA_QUALITY_OK or metric.amount_yuan is None:
                        continue
                    pool_item = pool_by_code.get(metric.ts_code)
                    if pool_item is None:
                        continue
                    rule = _resolve_rule(rule_items, ts_code=metric.ts_code, group_key=pool_item.group_key, window_minutes=window)
                    if rule is None:
                        continue
                    baseline_amount, baseline_trade_dates = _baseline_amount(
                        session,
                        ts_code=metric.ts_code,
                        bucket_end_time=metric.bucket_end_time,
                        window_minutes=window,
                        before_trade_date=target_trade_date,
                    )
                    if baseline_amount is None or not baseline_trade_dates:
                        continue
                    evaluated += 1
                    severity = _severity(metric.amount_yuan, baseline_amount, rule)
                    if severity is None:
                        continue
                    if not _cooldown_allows(session, rule=rule, severity=severity, metric=metric, now=now):
                        continue
                    alert = EtfRealtimeAlert(
                        trade_date=target_trade_date,
                        triggered_at=now,
                        bucket_end_time=metric.bucket_end_time,
                        window_minutes=window,
                        ts_code=metric.ts_code,
                        etf_name=etf_names.get(metric.ts_code),
                        group_key=pool_item.group_key,
                        group_name=pool_item.group_name,
                        rule_id=rule.id,
                        severity=severity,
                        current_amount_yuan=metric.amount_yuan,
                        baseline_amount_yuan=baseline_amount,
                        ratio=_ratio(metric.amount_yuan, baseline_amount),
                        baseline_trade_dates_json=[item.isoformat() for item in baseline_trade_dates],
                        cooldown_key=_cooldown_key(metric.ts_code, window, rule.id),
                        feishu_status="skipped" if severity == "observe" or not rule.feishu_enabled else "pending",
                    )
                    self._persist_alert_and_notify(session, alert)
                    alerts_created += 1
                except Exception as exc:
                    session.rollback()
                    failed += 1
                    self._logger.exception(
                        "ETF monitor item failed: ts_code=%s window_minutes=%s reason=%s",
                        metric.ts_code,
                        window,
                        exc,
                    )
        return EtfRealtimeMonitorRunResult(
            status="ok",
            evaluated_count=evaluated,
            alert_count=alerts_created,
            failed_count=failed,
        )

    def _persist_alert_and_notify(self, session: Session, alert: EtfRealtimeAlert) -> None:
        session.add(alert)
        session.commit()
        if alert.feishu_status != "pending":
            return

        try:
            message_id, error_message = self._feishu_service.send_alert(alert)
        except Exception as exc:  # notification failure must not abort monitor evaluation
            message_id, error_message = None, str(exc)
        persisted = session.get(EtfRealtimeAlert, alert.id)
        if persisted is None:
            return
        if error_message:
            persisted.feishu_status = "failed"
            persisted.feishu_error = error_message
        else:
            persisted.feishu_status = "success"
            persisted.feishu_message_id = message_id
            persisted.notified_at = datetime.now(CN_TIMEZONE)
        session.commit()


def _latest_window_metrics(metrics: Sequence[EtfWindowMetric]) -> list[EtfWindowMetric]:
    latest_by_code: dict[str, EtfWindowMetric] = {}
    for metric in metrics:
        current = latest_by_code.get(metric.ts_code)
        if current is None or metric.bucket_end_time > current.bucket_end_time:
            latest_by_code[metric.ts_code] = metric
    return list(latest_by_code.values())


def _resolve_rule(
    rules: Sequence[EtfRealtimeMonitorRule],
    *,
    ts_code: str,
    group_key: str,
    window_minutes: int,
) -> EtfRealtimeMonitorRule | None:
    for scope_type, scope_key in (("etf", ts_code), ("group", group_key), ("global", "__GLOBAL__")):
        for rule in rules:
            if rule.scope_type == scope_type and rule.scope_key == scope_key and rule.window_minutes == window_minutes:
                return rule
    return None


def _baseline_amount(
    session: Session,
    *,
    ts_code: str,
    bucket_end_time,
    window_minutes: int,
    before_trade_date,
) -> tuple[Decimal | None, list]:
    window_buckets = _window_buckets(bucket_end_time, window_minutes)
    rows = session.execute(
        select(EtfRealtimeMinuteStat.trade_date, EtfRealtimeMinuteStat.amount_delta_yuan)
        .where(EtfRealtimeMinuteStat.ts_code == ts_code)
        .where(EtfRealtimeMinuteStat.trade_date < before_trade_date)
        .where(EtfRealtimeMinuteStat.minute_bucket.in_(window_buckets))
        .where(EtfRealtimeMinuteStat.data_quality == DATA_QUALITY_OK)
        .order_by(EtfRealtimeMinuteStat.trade_date.desc())
    ).all()
    grouped: dict = {}
    for trade_date, amount in rows:
        grouped.setdefault(trade_date, Decimal("0"))
        grouped[trade_date] += Decimal(amount or 0)
    usable = list(grouped.items())[:5]
    if len(usable) < 3:
        return None, []
    total = sum((amount for _, amount in usable), Decimal("0"))
    return (total / Decimal(len(usable))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), [trade_date for trade_date, _ in usable]


def _window_buckets(bucket_end_time, window_minutes: int) -> list:
    from datetime import datetime as dt, date as dt_date, timedelta as dt_timedelta

    end_dt = dt.combine(dt_date(2000, 1, 1), bucket_end_time)
    return [(end_dt - dt_timedelta(minutes=offset)).time() for offset in reversed(range(window_minutes))]


def _severity(current: Decimal, baseline: Decimal, rule: EtfRealtimeMonitorRule) -> str | None:
    if baseline <= 0:
        return None
    ratio = _ratio(current, baseline)
    if ratio >= rule.strong_ratio:
        return "strong"
    if ratio >= rule.alert_ratio:
        return "alert"
    if ratio >= rule.observe_ratio:
        return "observe"
    return None


def _ratio(current: Decimal, baseline: Decimal) -> Decimal:
    return (current / baseline).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _cooldown_allows(
    session: Session,
    *,
    rule: EtfRealtimeMonitorRule,
    severity: str,
    metric: EtfWindowMetric,
    now: datetime,
) -> bool:
    cooldown_key = _cooldown_key(metric.ts_code, metric.window_minutes, rule.id)
    since = now - timedelta(minutes=rule.cooldown_minutes)
    rows = list(
        session.scalars(
            select(EtfRealtimeAlert)
            .where(EtfRealtimeAlert.cooldown_key == cooldown_key)
            .where(EtfRealtimeAlert.triggered_at >= since)
            .order_by(EtfRealtimeAlert.triggered_at.desc())
        ).all()
    )
    if not rows:
        return True
    highest_rank = max(SEVERITY_RANK.get(row.severity, 0) for row in rows)
    return SEVERITY_RANK.get(severity, 0) > highest_rank


def _cooldown_key(ts_code: str, window_minutes: int, rule_id: int | None) -> str:
    return f"etf_realtime:{ts_code}:{window_minutes}:{rule_id or 'none'}"


def _load_etf_names(session: Session, ts_codes: Sequence[str], *, logger: logging.Logger) -> dict[str, str | None]:
    try:
        rows = session.execute(
            select(EtfBasic.ts_code, EtfBasic.csname, EtfBasic.extname, EtfBasic.cname)
            .where(EtfBasic.ts_code.in_(list(ts_codes)))
        ).all()
    except Exception as exc:
        session.rollback()
        logger.warning("ETF monitor name snapshot unavailable: %s", exc)
        return {}
    return {
        row.ts_code: row.csname or row.extname or row.cname or None
        for row in rows
    }
