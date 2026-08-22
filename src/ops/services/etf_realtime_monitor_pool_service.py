from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.models.ops.etf_realtime_monitor_rule import EtfRealtimeMonitorRule
from src.ops.models.ops.etf_series_active import EtfSeriesActive
from src.ops.schemas.etf_realtime_monitor import (
    EtfRealtimeMonitorActiveEtfItem,
    EtfRealtimeMonitorActiveEtfListResponse,
    EtfRealtimeMonitorMutationResponse,
    EtfRealtimeMonitorPoolItem,
    EtfRealtimeMonitorPoolListResponse,
)


ETF_RT_DAILY_RESOURCE = "etf_rt_daily"
ETF_MONITOR_GROUPS = {
    "broad_base": "宽基ETF",
    "theme": "主题ETF",
}


class EtfRealtimeMonitorPoolService:
    def list_active_etfs(
        self,
        session: Session,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> EtfRealtimeMonitorActiveEtfListResponse:
        latest_daily = _latest_fund_daily_subquery()
        stmt = (
            select(
                EtfSeriesActive.ts_code,
                EtfBasic.csname,
                EtfBasic.extname,
                EtfBasic.cname,
                EtfBasic.exchange,
                EtfBasic.etf_type,
                EtfBasic.list_date,
                EtfBasic.list_status,
                latest_daily.c.latest_fund_daily_date,
                EtfRealtimeMonitorPool.id.label("pool_id"),
            )
            .outerjoin(EtfBasic, EtfBasic.ts_code == EtfSeriesActive.ts_code)
            .outerjoin(latest_daily, latest_daily.c.ts_code == EtfSeriesActive.ts_code)
            .outerjoin(EtfRealtimeMonitorPool, EtfRealtimeMonitorPool.ts_code == EtfSeriesActive.ts_code)
            .where(EtfSeriesActive.resource == ETF_RT_DAILY_RESOURCE)
        )
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    EtfSeriesActive.ts_code.ilike(pattern),
                    EtfBasic.csname.ilike(pattern),
                    EtfBasic.extname.ilike(pattern),
                    EtfBasic.cname.ilike(pattern),
                )
            )
        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = session.execute(
            stmt.order_by(EtfSeriesActive.ts_code).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return EtfRealtimeMonitorActiveEtfListResponse(
            items=[
                EtfRealtimeMonitorActiveEtfItem(
                    ts_code=row.ts_code,
                    csname=row.csname,
                    extname=row.extname,
                    cname=row.cname,
                    exchange=row.exchange,
                    etf_type=row.etf_type,
                    list_date=row.list_date,
                    list_status=row.list_status,
                    latest_fund_daily_date=row.latest_fund_daily_date,
                    in_monitor_pool=row.pool_id is not None,
                )
                for row in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    def list_pool(
        self,
        session: Session,
        *,
        keyword: str | None,
        enabled: bool | None,
        page: int,
        page_size: int,
    ) -> EtfRealtimeMonitorPoolListResponse:
        latest_alert = (
            select(
                EtfRealtimeAlert.ts_code.label("ts_code"),
                func.max(EtfRealtimeAlert.triggered_at).label("latest_alert_at"),
            )
            .where(EtfRealtimeAlert.severity.in_(("alert", "strong")))
            .group_by(EtfRealtimeAlert.ts_code)
            .subquery()
        )
        stmt = (
            select(
                EtfRealtimeMonitorPool,
                EtfBasic.csname,
                EtfBasic.extname,
                EtfBasic.cname,
                latest_alert.c.latest_alert_at,
                EtfRealtimeAlert.severity.label("latest_alert_severity"),
                func.count(EtfRealtimeMonitorRule.id).label("rule_override_count"),
            )
            .outerjoin(EtfBasic, EtfBasic.ts_code == EtfRealtimeMonitorPool.ts_code)
            .outerjoin(latest_alert, latest_alert.c.ts_code == EtfRealtimeMonitorPool.ts_code)
            .outerjoin(
                EtfRealtimeAlert,
                and_(
                    EtfRealtimeAlert.ts_code == latest_alert.c.ts_code,
                    EtfRealtimeAlert.triggered_at == latest_alert.c.latest_alert_at,
                ),
            )
            .outerjoin(
                EtfRealtimeMonitorRule,
                and_(
                    EtfRealtimeMonitorRule.scope_type == "etf",
                    EtfRealtimeMonitorRule.scope_key == EtfRealtimeMonitorPool.ts_code,
                ),
            )
            .group_by(EtfRealtimeMonitorPool.id, EtfBasic.ts_code, latest_alert.c.latest_alert_at, EtfRealtimeAlert.severity)
        )
        if enabled is not None:
            stmt = stmt.where(EtfRealtimeMonitorPool.enabled.is_(enabled))
        if keyword:
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    EtfRealtimeMonitorPool.ts_code.ilike(pattern),
                    EtfBasic.csname.ilike(pattern),
                    EtfBasic.extname.ilike(pattern),
                    EtfBasic.cname.ilike(pattern),
                )
            )
        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = session.execute(
            stmt.order_by(EtfRealtimeMonitorPool.display_order, EtfRealtimeMonitorPool.ts_code)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return EtfRealtimeMonitorPoolListResponse(
            items=[
                EtfRealtimeMonitorPoolItem(
                    id=row.EtfRealtimeMonitorPool.id,
                    ts_code=row.EtfRealtimeMonitorPool.ts_code,
                    etf_name=_display_name(row),
                    group_key=row.EtfRealtimeMonitorPool.group_key,
                    group_name=row.EtfRealtimeMonitorPool.group_name,
                    enabled=row.EtfRealtimeMonitorPool.enabled,
                    display_order=row.EtfRealtimeMonitorPool.display_order,
                    note=row.EtfRealtimeMonitorPool.note,
                    has_etf_rule_override=int(row.rule_override_count or 0) > 0,
                    latest_alert_at=row.latest_alert_at,
                    latest_alert_severity=row.latest_alert_severity,
                    created_at=row.EtfRealtimeMonitorPool.created_at,
                    updated_at=row.EtfRealtimeMonitorPool.updated_at,
                )
                for row in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    def add_to_pool(
        self,
        session: Session,
        *,
        ts_code: str,
        group_key: str,
        group_name: str,
        enabled: bool,
        display_order: int,
        note: str | None,
        user_id: int | None,
    ) -> EtfRealtimeMonitorMutationResponse:
        normalized_ts_code = _normalize_ts_code(ts_code)
        _assert_group(group_key, group_name)
        _assert_active_etf(session, normalized_ts_code)
        existing = session.scalar(select(EtfRealtimeMonitorPool).where(EtfRealtimeMonitorPool.ts_code == normalized_ts_code))
        if existing is not None:
            raise WebAppError(status_code=409, code="conflict", message="该 ETF 已在监控池中")
        item = EtfRealtimeMonitorPool(
            ts_code=normalized_ts_code,
            group_key=group_key,
            group_name=group_name,
            enabled=enabled,
            display_order=display_order,
            note=note,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return EtfRealtimeMonitorMutationResponse(id=item.id, ts_code=item.ts_code)

    def update_pool_item(
        self,
        session: Session,
        *,
        item_id: int,
        group_key: str,
        group_name: str,
        enabled: bool,
        display_order: int,
        note: str | None,
        user_id: int | None,
    ) -> EtfRealtimeMonitorMutationResponse:
        _assert_group(group_key, group_name)
        item = session.get(EtfRealtimeMonitorPool, item_id)
        if item is None:
            raise WebAppError(status_code=404, code="not_found", message="监控池记录不存在")
        item.group_key = group_key
        item.group_name = group_name
        item.enabled = enabled
        item.display_order = display_order
        item.note = note
        item.updated_by_user_id = user_id
        session.commit()
        session.refresh(item)
        return EtfRealtimeMonitorMutationResponse(id=item.id, ts_code=item.ts_code)

    def delete_pool_item(self, session: Session, *, item_id: int) -> EtfRealtimeMonitorMutationResponse:
        item = session.get(EtfRealtimeMonitorPool, item_id)
        if item is None:
            raise WebAppError(status_code=404, code="not_found", message="监控池记录不存在")
        response = EtfRealtimeMonitorMutationResponse(id=item.id, ts_code=item.ts_code)
        session.delete(item)
        session.commit()
        return response


def _latest_fund_daily_subquery():
    return (
        select(
            FundDailyBar.ts_code.label("ts_code"),
            func.max(FundDailyBar.trade_date).label("latest_fund_daily_date"),
        )
        .group_by(FundDailyBar.ts_code)
        .subquery()
    )


def _assert_active_etf(session: Session, ts_code: str) -> None:
    exists = session.scalar(
        select(EtfSeriesActive.ts_code)
        .where(EtfSeriesActive.resource == ETF_RT_DAILY_RESOURCE)
        .where(EtfSeriesActive.ts_code == ts_code)
        .limit(1)
    )
    if exists is None:
        raise WebAppError(status_code=422, code="invalid_etf", message="ETF 不在实时 ETF 活跃池中")


def _assert_group(group_key: str, group_name: str) -> None:
    if ETF_MONITOR_GROUPS.get(group_key) != group_name:
        raise WebAppError(status_code=422, code="invalid_group", message="监控分组只能选择宽基ETF或主题ETF")


def _normalize_ts_code(value: str) -> str:
    return str(value or "").strip().upper()


def _display_name(row: Any) -> str | None:
    return row.csname or row.extname or row.cname
