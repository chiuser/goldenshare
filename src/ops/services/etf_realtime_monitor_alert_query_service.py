from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.models.ops.etf_realtime_minute_stat import EtfRealtimeMinuteStat
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.schemas.etf_realtime_monitor import (
    EtfRealtimeMonitorAlertDetailResponse,
    EtfRealtimeMonitorAlertItem,
    EtfRealtimeMonitorAlertListResponse,
    EtfRealtimeMonitorSummaryResponse,
)


class EtfRealtimeMonitorAlertQueryService:
    def list_alerts(
        self,
        session: Session,
        *,
        trade_date: date | None,
        severity: str | None,
        feishu_status: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> EtfRealtimeMonitorAlertListResponse:
        stmt = select(EtfRealtimeAlert)
        if trade_date is not None:
            stmt = stmt.where(EtfRealtimeAlert.trade_date == trade_date)
        if severity:
            stmt = stmt.where(EtfRealtimeAlert.severity == severity)
        if feishu_status:
            stmt = stmt.where(EtfRealtimeAlert.feishu_status == feishu_status)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where((EtfRealtimeAlert.ts_code.ilike(pattern)) | (EtfRealtimeAlert.etf_name.ilike(pattern)))
        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = list(
            session.scalars(
                stmt.order_by(EtfRealtimeAlert.triggered_at.desc(), EtfRealtimeAlert.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return EtfRealtimeMonitorAlertListResponse(
            items=[_alert_item(row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_alert(self, session: Session, alert_id: int) -> EtfRealtimeMonitorAlertDetailResponse:
        alert = session.get(EtfRealtimeAlert, alert_id)
        if alert is None:
            raise WebAppError(status_code=404, code="not_found", message="告警记录不存在")
        return EtfRealtimeMonitorAlertDetailResponse(
            **_alert_item(alert).model_dump(),
            rule_id=alert.rule_id,
            baseline_trade_dates_json=alert.baseline_trade_dates_json,
            cooldown_key=alert.cooldown_key,
            feishu_message_id=alert.feishu_message_id,
            feishu_error=alert.feishu_error,
            notified_at=alert.notified_at,
            created_at=alert.created_at,
        )

    def get_summary(self, session: Session, *, trade_date: date) -> EtfRealtimeMonitorSummaryResponse:
        severity_rows = session.execute(
            select(EtfRealtimeAlert.severity, func.count())
            .where(EtfRealtimeAlert.trade_date == trade_date)
            .group_by(EtfRealtimeAlert.severity)
        ).all()
        severity_counts = {row[0]: int(row[1]) for row in severity_rows}
        feishu_rows = session.execute(
            select(EtfRealtimeAlert.feishu_status, func.count())
            .where(EtfRealtimeAlert.trade_date == trade_date)
            .group_by(EtfRealtimeAlert.feishu_status)
        ).all()
        feishu_counts = {row[0]: int(row[1]) for row in feishu_rows}
        return EtfRealtimeMonitorSummaryResponse(
            monitor_total=session.scalar(select(func.count()).select_from(EtfRealtimeMonitorPool)) or 0,
            monitor_enabled=session.scalar(select(func.count()).select_from(EtfRealtimeMonitorPool).where(EtfRealtimeMonitorPool.enabled.is_(True))) or 0,
            observe_count=severity_counts.get("observe", 0),
            alert_count=severity_counts.get("alert", 0),
            strong_count=severity_counts.get("strong", 0),
            feishu_success_count=feishu_counts.get("success", 0),
            feishu_failed_count=feishu_counts.get("failed", 0),
            latest_archive_date=session.scalar(select(func.max(EtfRealtimeMinuteStat.trade_date))),
        )


def _alert_item(alert: EtfRealtimeAlert) -> EtfRealtimeMonitorAlertItem:
    return EtfRealtimeMonitorAlertItem(
        id=alert.id,
        trade_date=alert.trade_date,
        triggered_at=alert.triggered_at,
        bucket_end_time=alert.bucket_end_time,
        window_minutes=alert.window_minutes,
        ts_code=alert.ts_code,
        etf_name=alert.etf_name,
        group_key=alert.group_key,
        group_name=alert.group_name,
        severity=alert.severity,
        current_amount_yuan=alert.current_amount_yuan,
        baseline_amount_yuan=alert.baseline_amount_yuan,
        ratio=alert.ratio,
        feishu_status=alert.feishu_status,
    )
