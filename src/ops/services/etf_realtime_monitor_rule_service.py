from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.dao.etf_basic_dao import EtfBasicDAO
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.models.ops.etf_realtime_monitor_rule import EtfRealtimeMonitorRule
from src.ops.schemas.etf_realtime_monitor import (
    EtfRealtimeMonitorDefaultRulesResponse,
    EtfRealtimeMonitorMutationResponse,
    EtfRealtimeMonitorRuleItem,
    EtfRealtimeMonitorRuleListResponse,
)


GLOBAL_SCOPE_KEY = "__GLOBAL__"
CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
SUPPORTED_WINDOWS = (1, 5, 15)
DEFAULT_OBSERVE_RATIO = Decimal("2.0")
DEFAULT_ALERT_RATIO = Decimal("3.0")
DEFAULT_STRONG_RATIO = Decimal("5.0")
DEFAULT_COOLDOWN_MINUTES = 15


class EtfRealtimeMonitorRuleService:
    def list_rules(
        self,
        session: Session,
        *,
        scope_type: str | None,
        window_minutes: int | None,
    ) -> EtfRealtimeMonitorRuleListResponse:
        stmt = select(EtfRealtimeMonitorRule).order_by(
            EtfRealtimeMonitorRule.scope_type,
            EtfRealtimeMonitorRule.scope_key,
            EtfRealtimeMonitorRule.window_minutes,
        )
        if scope_type:
            normalized_scope = _normalize_scope_type(scope_type)
            stmt = stmt.where(EtfRealtimeMonitorRule.scope_type == normalized_scope)
        if window_minutes is not None:
            _assert_window(window_minutes)
            stmt = stmt.where(EtfRealtimeMonitorRule.window_minutes == window_minutes)
        rows = list(session.scalars(stmt).all())
        return EtfRealtimeMonitorRuleListResponse(
            items=[_rule_item(session, row) for row in rows],
            total=len(rows),
        )

    def create_rule(
        self,
        session: Session,
        *,
        scope_type: str,
        scope_key: str,
        window_minutes: int,
        observe_ratio: Decimal,
        alert_ratio: Decimal,
        strong_ratio: Decimal,
        cooldown_minutes: int,
        feishu_enabled: bool,
        enabled: bool,
        user_id: int | None,
    ) -> EtfRealtimeMonitorMutationResponse:
        normalized_scope_type, normalized_scope_key = self._validate_rule_scope(session, scope_type, scope_key)
        _assert_window(window_minutes)
        _assert_ratios(observe_ratio, alert_ratio, strong_ratio)
        existing = session.scalar(
            select(EtfRealtimeMonitorRule)
            .where(EtfRealtimeMonitorRule.scope_type == normalized_scope_type)
            .where(EtfRealtimeMonitorRule.scope_key == normalized_scope_key)
            .where(EtfRealtimeMonitorRule.window_minutes == window_minutes)
        )
        if existing is not None:
            raise WebAppError(status_code=409, code="conflict", message="该规则已存在")
        rule = EtfRealtimeMonitorRule(
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            window_minutes=window_minutes,
            observe_ratio=observe_ratio,
            alert_ratio=alert_ratio,
            strong_ratio=strong_ratio,
            cooldown_minutes=cooldown_minutes,
            feishu_enabled=feishu_enabled,
            enabled=enabled,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
        return EtfRealtimeMonitorMutationResponse(id=rule.id, ts_code=rule.scope_key)

    def update_rule(
        self,
        session: Session,
        *,
        rule_id: int,
        scope_type: str,
        scope_key: str,
        window_minutes: int,
        observe_ratio: Decimal,
        alert_ratio: Decimal,
        strong_ratio: Decimal,
        cooldown_minutes: int,
        feishu_enabled: bool,
        enabled: bool,
        user_id: int | None,
    ) -> EtfRealtimeMonitorMutationResponse:
        rule = session.get(EtfRealtimeMonitorRule, rule_id)
        if rule is None:
            raise WebAppError(status_code=404, code="not_found", message="阈值规则不存在")
        normalized_scope_type, normalized_scope_key = self._validate_rule_scope(session, scope_type, scope_key)
        _assert_window(window_minutes)
        _assert_ratios(observe_ratio, alert_ratio, strong_ratio)
        duplicate = session.scalar(
            select(EtfRealtimeMonitorRule.id)
            .where(EtfRealtimeMonitorRule.scope_type == normalized_scope_type)
            .where(EtfRealtimeMonitorRule.scope_key == normalized_scope_key)
            .where(EtfRealtimeMonitorRule.window_minutes == window_minutes)
            .where(EtfRealtimeMonitorRule.id != rule_id)
            .limit(1)
        )
        if duplicate is not None:
            raise WebAppError(status_code=409, code="conflict", message="该规则已存在")
        rule.scope_type = normalized_scope_type
        rule.scope_key = normalized_scope_key
        rule.window_minutes = window_minutes
        rule.observe_ratio = observe_ratio
        rule.alert_ratio = alert_ratio
        rule.strong_ratio = strong_ratio
        rule.cooldown_minutes = cooldown_minutes
        rule.feishu_enabled = feishu_enabled
        rule.enabled = enabled
        rule.updated_by_user_id = user_id
        session.commit()
        session.refresh(rule)
        return EtfRealtimeMonitorMutationResponse(id=rule.id, ts_code=rule.scope_key)

    def delete_rule(self, session: Session, *, rule_id: int) -> EtfRealtimeMonitorMutationResponse:
        rule = session.get(EtfRealtimeMonitorRule, rule_id)
        if rule is None:
            raise WebAppError(status_code=404, code="not_found", message="阈值规则不存在")
        response = EtfRealtimeMonitorMutationResponse(id=rule.id, ts_code=rule.scope_key)
        session.delete(rule)
        session.commit()
        return response

    def create_default_global_rules(self, session: Session, *, user_id: int | None) -> EtfRealtimeMonitorDefaultRulesResponse:
        created = 0
        skipped = 0
        for window in SUPPORTED_WINDOWS:
            existing = session.scalar(
                select(EtfRealtimeMonitorRule.id)
                .where(EtfRealtimeMonitorRule.scope_type == "global")
                .where(EtfRealtimeMonitorRule.scope_key == GLOBAL_SCOPE_KEY)
                .where(EtfRealtimeMonitorRule.window_minutes == window)
            )
            if existing is not None:
                skipped += 1
                continue
            session.add(
                EtfRealtimeMonitorRule(
                    scope_type="global",
                    scope_key=GLOBAL_SCOPE_KEY,
                    window_minutes=window,
                    observe_ratio=DEFAULT_OBSERVE_RATIO,
                    alert_ratio=DEFAULT_ALERT_RATIO,
                    strong_ratio=DEFAULT_STRONG_RATIO,
                    cooldown_minutes=DEFAULT_COOLDOWN_MINUTES,
                    feishu_enabled=True,
                    enabled=True,
                    created_by_user_id=user_id,
                    updated_by_user_id=user_id,
                )
            )
            created += 1
        session.commit()
        return EtfRealtimeMonitorDefaultRulesResponse(created=created, skipped=skipped)

    def _validate_rule_scope(self, session: Session, scope_type: str, scope_key: str) -> tuple[str, str]:
        normalized_scope_type = _normalize_scope_type(scope_type)
        normalized_scope_key = str(scope_key or "").strip()
        if normalized_scope_type == "global":
            if normalized_scope_key != GLOBAL_SCOPE_KEY:
                raise WebAppError(status_code=422, code="invalid_scope", message="全局规则 scope_key 必须是 __GLOBAL__")
            return normalized_scope_type, normalized_scope_key
        if normalized_scope_type == "group":
            exists = session.scalar(
                select(EtfRealtimeMonitorPool.group_key)
                .where(EtfRealtimeMonitorPool.group_key == normalized_scope_key)
                .limit(1)
            )
            if exists is None:
                raise WebAppError(status_code=422, code="invalid_scope", message="分组规则必须指向已存在的监控分组")
            return normalized_scope_type, normalized_scope_key
        normalized_scope_key = normalized_scope_key.upper()
        exists = session.scalar(
            select(EtfRealtimeMonitorPool.ts_code)
            .where(EtfRealtimeMonitorPool.ts_code == normalized_scope_key)
            .limit(1)
        )
        if exists is None:
            raise WebAppError(status_code=422, code="invalid_scope", message="ETF 规则必须指向监控池中的 ETF")
        target = EtfBasicDAO(session).get_requestable_target(
            ts_code=normalized_scope_key,
            as_of_date=datetime.now(CN_TIMEZONE).date(),
        )
        if target is None:
            raise WebAppError(
                status_code=422,
                code="invalid_scope",
                message="ETF 规则必须指向当前可请求的监控池 ETF",
            )
        return normalized_scope_type, normalized_scope_key


def _rule_item(session: Session, rule: EtfRealtimeMonitorRule) -> EtfRealtimeMonitorRuleItem:
    return EtfRealtimeMonitorRuleItem(
        id=rule.id,
        scope_type=rule.scope_type,
        scope_key=rule.scope_key,
        scope_display_name=_scope_display_name(session, rule),
        window_minutes=rule.window_minutes,
        observe_ratio=rule.observe_ratio,
        alert_ratio=rule.alert_ratio,
        strong_ratio=rule.strong_ratio,
        cooldown_minutes=rule.cooldown_minutes,
        feishu_enabled=rule.feishu_enabled,
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _scope_display_name(session: Session, rule: EtfRealtimeMonitorRule) -> str | None:
    if rule.scope_type == "global":
        return "全局默认"
    if rule.scope_type == "group":
        return session.scalar(
            select(EtfRealtimeMonitorPool.group_name)
            .where(EtfRealtimeMonitorPool.group_key == rule.scope_key)
            .limit(1)
        )
    item = session.scalar(
        select(EtfRealtimeMonitorPool)
        .where(EtfRealtimeMonitorPool.ts_code == rule.scope_key)
        .limit(1)
    )
    return item.ts_code if item is not None else rule.scope_key


def _normalize_scope_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"global", "group", "etf"}:
        raise WebAppError(status_code=422, code="invalid_scope", message="规则层级只能是 global、group 或 etf")
    return normalized


def _assert_window(value: int) -> None:
    if value not in SUPPORTED_WINDOWS:
        raise WebAppError(status_code=422, code="invalid_window", message="窗口只能是 1、5、15 分钟")


def _assert_ratios(observe: Decimal, alert: Decimal, strong: Decimal) -> None:
    if not (Decimal("0") < observe <= alert <= strong):
        raise WebAppError(status_code=422, code="invalid_ratio", message="阈值必须满足 0 < observe <= alert <= strong")
