from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_qfq_nineturn_daily import EquityQfqNineTurnDaily
from src.foundation.models.core_serving.index_nineturn_daily import IndexNineTurnDaily
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import WealthSectorAnalysisPublishBatch
from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy
from src.ops.action_catalog import get_maintenance_action
from src.ops.catalog.biz_dataset_definitions import (
    BIZ_TABLE_SOURCE_DISPLAY_NAME,
    BIZ_TABLE_SOURCE_KEY,
    BizDatasetDefinition,
    lint_biz_dataset_definitions,
    list_biz_dataset_definitions,
)
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.schemas.dataset_card import DatasetCardGroup, DatasetCardItem, DatasetCardListResponse


logger = logging.getLogger(__name__)
_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_ACTIVE_TASK_STATUSES = ("queued", "running", "canceling")
_TASK_TRACE_STATUSES = ("success", "failed", "partial_success")
_DIRECT_TABLES = {
    "core_serving.wealth_sector_heat_daily": WealthSectorHeatDaily.__table__,
    "core_serving.equity_qfq_nineturn_daily": EquityQfqNineTurnDaily.__table__,
    "core_serving.index_nineturn_daily": IndexNineTurnDaily.__table__,
}


@dataclass(frozen=True, slots=True)
class BizDatasetObservation:
    earliest_business_date: date | None = None
    latest_business_date: date | None = None
    latest_success_at: datetime | None = None
    latest_observed_at: datetime | None = None
    query_error: bool = False


@dataclass(frozen=True, slots=True)
class BizActionRuntimeSnapshot:
    active_status: str | None = None
    active_started_at: datetime | None = None
    latest_success_at: datetime | None = None
    latest_failure_at: datetime | None = None
    schedule_total: int = 0
    schedule_active: int = 0
    schedule_next_run_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BizDatasetFreshness:
    status: str
    freshness_status: str
    expected_business_date: date | None
    lag_days: int | None
    note: str


class BizTableCardQueryService:
    """Project internal Biz dataset definitions into Ops dataset cards."""

    def list_cards(self, session: Session, *, limit: int = 2000) -> DatasetCardListResponse:
        limit = max(1, min(limit, 2000))
        definitions = tuple(
            sorted(
                list_biz_dataset_definitions(),
                key=lambda item: (item.group_order, item.item_order, item.dataset_key),
            )
        )
        lint_issues = lint_biz_dataset_definitions(definitions)
        if lint_issues:
            detail = "; ".join(f"{item.dataset_key}:{item.code}" for item in lint_issues)
            raise RuntimeError(f"invalid Biz dataset definitions: {detail}")

        maintenance_keys = {
            item.producer_key for item in definitions if item.producer_type == "maintenance_action"
        }
        runtime_by_action = self._load_action_runtime(session, maintenance_keys)
        observation_cache: dict[str, BizDatasetObservation] = {}
        cards: list[DatasetCardItem] = []
        for definition in definitions:
            runtime = runtime_by_action.get(definition.producer_key, BizActionRuntimeSnapshot())
            observation = self._observation_for(
                session,
                definition,
                runtime=runtime,
                cache=observation_cache,
            )
            cards.append(self._build_card(session, definition, observation=observation, runtime=runtime))

        sliced = cards[:limit]
        return DatasetCardListResponse(total=len(cards), groups=self._group_cards(sliced))

    def _build_card(
        self,
        session: Session,
        definition: BizDatasetDefinition,
        *,
        observation: BizDatasetObservation,
        runtime: BizActionRuntimeSnapshot,
    ) -> DatasetCardItem:
        freshness = self._build_freshness(session, definition, observation=observation, runtime=runtime)
        primary_action_type, primary_action_key = self._primary_action(definition)
        auto_schedule_status = (
            "active" if runtime.schedule_active > 0 else "paused" if runtime.schedule_total > 0 else "none"
        )

        return DatasetCardItem(
            card_key=definition.dataset_key,
            dataset_key=definition.dataset_key,
            detail_dataset_key=definition.dataset_key,
            resource_key=definition.dataset_key,
            display_name=definition.display_name,
            group_key=definition.group_key,
            group_label=definition.group_label,
            group_order=definition.group_order,
            item_order=definition.item_order,
            domain_key=BIZ_TABLE_SOURCE_KEY,
            domain_display_name=BIZ_TABLE_SOURCE_DISPLAY_NAME,
            status=(
                "running"
                if runtime.active_status and not observation.query_error
                else freshness.status
            ),
            freshness_status=freshness.freshness_status,
            delivery_mode="biz_table_snapshot",
            delivery_mode_label="业务派生表",
            delivery_mode_tone="info",
            layer_plan=BIZ_TABLE_SOURCE_KEY,
            freshness_policy=definition.freshness_policy_key,
            raw_table=None,
            raw_table_label=None,
            target_table=definition.table_name,
            latest_business_date=observation.latest_business_date,
            earliest_business_date=observation.earliest_business_date,
            latest_observed_at=observation.latest_observed_at,
            earliest_observed_at=None,
            last_sync_date=None,
            latest_success_at=observation.latest_success_at,
            expected_business_date=freshness.expected_business_date,
            latest_observed_date=(
                observation.latest_business_date.isoformat() if observation.latest_business_date else None
            ),
            latest_observed_date_label="最新业务日期" if observation.latest_business_date else None,
            expected_observed_date=(
                freshness.expected_business_date.isoformat() if freshness.expected_business_date else None
            ),
            expected_observed_date_label="应完成业务日期" if freshness.expected_business_date else None,
            last_success_label="最近构建成功时间" if observation.latest_success_at else None,
            lag_days=freshness.lag_days,
            freshness_note=freshness.note,
            primary_action_type=primary_action_type,
            primary_action_key=primary_action_key,
            active_task_run_status=runtime.active_status,
            active_task_run_started_at=runtime.active_started_at,
            auto_schedule_status=auto_schedule_status,
            auto_schedule_total=runtime.schedule_total,
            auto_schedule_active=runtime.schedule_active,
            auto_schedule_next_run_at=runtime.schedule_next_run_at,
            probe_total=0,
            probe_active=0,
            std_mapping_configured=False,
            std_cleansing_configured=False,
            resolution_policy_configured=False,
        )

    def _observation_for(
        self,
        session: Session,
        definition: BizDatasetDefinition,
        *,
        runtime: BizActionRuntimeSnapshot,
        cache: dict[str, BizDatasetObservation],
    ) -> BizDatasetObservation:
        if definition.observation_query_key == "maintenance_task_trace":
            return BizDatasetObservation(latest_success_at=runtime.latest_success_at)

        cache_key = (
            "sector_analysis_published_batch"
            if definition.observation_query_key == "sector_analysis_published_batch"
            else definition.dataset_key
        )
        if cache_key in cache:
            return cache[cache_key]

        try:
            with session.begin_nested():
                observation = self._load_business_observation(session, definition)
        except Exception:
            logger.exception("Biz dataset observation query failed: %s", cache_key)
            observation = BizDatasetObservation(query_error=True)
        cache[cache_key] = observation
        return observation

    def _load_business_observation(
        self,
        session: Session,
        definition: BizDatasetDefinition,
    ) -> BizDatasetObservation:
        query_key = definition.observation_query_key
        if query_key == "wealth_turnover_ready_snapshot":
            return self._load_turnover_observation(session)
        if query_key == "direct_trade_date":
            return self._load_direct_trade_date_observation(session, definition)
        if query_key == "static_snapshot":
            return self._load_static_snapshot_observation(session)
        if query_key == "sector_analysis_published_batch":
            return self._load_sector_analysis_observation(session)
        raise ValueError(f"unsupported Biz observation query: {query_key}")

    @staticmethod
    def _load_turnover_observation(session: Session) -> BizDatasetObservation:
        conditions = (
            WealthMarketTurnoverSnapshot.type == "stock",
            WealthMarketTurnoverSnapshot.market == "CN_A",
            WealthMarketTurnoverSnapshot.build_status == "READY",
        )
        earliest = session.scalar(
            select(WealthMarketTurnoverSnapshot.trade_date)
            .where(*conditions)
            .order_by(WealthMarketTurnoverSnapshot.trade_date.asc())
            .limit(1)
        )
        latest = session.execute(
            select(
                WealthMarketTurnoverSnapshot.trade_date,
                WealthMarketTurnoverSnapshot.built_at,
                WealthMarketTurnoverSnapshot.latest_trade_time,
            )
            .where(*conditions)
            .order_by(
                WealthMarketTurnoverSnapshot.trade_date.desc(),
                WealthMarketTurnoverSnapshot.built_at.desc(),
            )
            .limit(1)
        ).one_or_none()
        if latest is None:
            return BizDatasetObservation()
        return BizDatasetObservation(
            earliest_business_date=earliest,
            latest_business_date=latest.trade_date,
            latest_success_at=latest.built_at,
            latest_observed_at=latest.latest_trade_time,
        )

    @staticmethod
    def _load_direct_trade_date_observation(
        session: Session,
        definition: BizDatasetDefinition,
    ) -> BizDatasetObservation:
        table = _DIRECT_TABLES[definition.table_name]
        date_column = table.c[definition.business_date_column]
        observed_column = table.c[definition.observed_at_column]
        earliest = session.scalar(select(date_column).order_by(date_column.asc()).limit(1))
        latest = session.execute(
            select(date_column, observed_column)
            .order_by(date_column.desc(), observed_column.desc())
            .limit(1)
        ).one_or_none()
        if latest is None:
            return BizDatasetObservation()
        return BizDatasetObservation(
            earliest_business_date=earliest,
            latest_business_date=latest[0],
            latest_success_at=latest[1],
            latest_observed_at=latest[1],
        )

    @staticmethod
    def _load_static_snapshot_observation(session: Session) -> BizDatasetObservation:
        latest = session.execute(
            select(
                WealthSectorHierarchy.code_reference_trade_date,
                WealthSectorHierarchy.published_at,
            )
            .order_by(WealthSectorHierarchy.published_at.desc())
            .limit(1)
        ).one_or_none()
        if latest is None:
            return BizDatasetObservation()
        return BizDatasetObservation(
            earliest_business_date=latest.code_reference_trade_date,
            latest_business_date=latest.code_reference_trade_date,
            latest_success_at=latest.published_at,
            latest_observed_at=latest.published_at,
        )

    @staticmethod
    def _load_sector_analysis_observation(session: Session) -> BizDatasetObservation:
        published = WealthSectorAnalysisPublishBatch.status == "PUBLISHED"
        earliest = session.scalar(
            select(WealthSectorAnalysisPublishBatch.trade_date)
            .where(published)
            .order_by(WealthSectorAnalysisPublishBatch.trade_date.asc())
            .limit(1)
        )
        latest = session.execute(
            select(
                WealthSectorAnalysisPublishBatch.trade_date,
                WealthSectorAnalysisPublishBatch.published_at,
            )
            .where(published)
            .order_by(
                WealthSectorAnalysisPublishBatch.trade_date.desc(),
                WealthSectorAnalysisPublishBatch.published_at.desc(),
            )
            .limit(1)
        ).one_or_none()
        if latest is None:
            return BizDatasetObservation()
        return BizDatasetObservation(
            earliest_business_date=earliest,
            latest_business_date=latest.trade_date,
            latest_success_at=latest.published_at,
            latest_observed_at=latest.published_at,
        )

    def _build_freshness(
        self,
        session: Session,
        definition: BizDatasetDefinition,
        *,
        observation: BizDatasetObservation,
        runtime: BizActionRuntimeSnapshot,
    ) -> BizDatasetFreshness:
        if observation.query_error:
            return BizDatasetFreshness("unknown", "unknown", None, None, "状态读取失败")
        if definition.freshness_policy_key == "maintenance_task_trace":
            return self._task_trace_freshness(runtime)
        if definition.freshness_policy_key == "static_snapshot_ready":
            if observation.latest_business_date is None or observation.latest_success_at is None:
                return BizDatasetFreshness("unknown", "unknown", None, None, "暂无已发布快照。")
            return BizDatasetFreshness("healthy", "fresh", None, 0, "当前快照已发布。")
        return self._date_freshness(
            session,
            observation,
            ready_after_local_time=definition.ready_after_local_time,
        )

    @staticmethod
    def _task_trace_freshness(runtime: BizActionRuntimeSnapshot) -> BizDatasetFreshness:
        if runtime.latest_failure_at is not None and (
            runtime.latest_success_at is None or runtime.latest_failure_at > runtime.latest_success_at
        ):
            return BizDatasetFreshness("failed", "failed", None, None, "最近一次构建失败。")
        if runtime.latest_success_at is not None:
            return BizDatasetFreshness("healthy", "fresh", None, 0, "最近一次构建已完成。")
        return BizDatasetFreshness("unknown", "unknown", None, None, "暂无构建记录。")

    def _date_freshness(
        self,
        session: Session,
        observation: BizDatasetObservation,
        *,
        ready_after_local_time: str | None,
    ) -> BizDatasetFreshness:
        expected_date = self._expected_business_date(session, ready_after_local_time)
        if observation.latest_business_date is None:
            return BizDatasetFreshness("unknown", "unknown", expected_date, None, "暂无业务数据。")
        if expected_date is None:
            return BizDatasetFreshness("unknown", "unknown", None, None, "缺少交易日历，无法判断。")
        if observation.latest_business_date >= expected_date:
            return BizDatasetFreshness("healthy", "fresh", expected_date, 0, "已完成期望业务日。")

        lag_days = self._trading_day_lag(
            session,
            latest_date=observation.latest_business_date,
            expected_date=expected_date,
        )
        if lag_days <= 1:
            return BizDatasetFreshness("warning", "lagging", expected_date, lag_days, "滞后 1 个交易日。")
        return BizDatasetFreshness(
            "stale",
            "stale",
            expected_date,
            lag_days,
            f"滞后 {lag_days} 个交易日。",
        )

    def _expected_business_date(
        self,
        session: Session,
        ready_after_local_time: str | None,
    ) -> date | None:
        if ready_after_local_time is None:
            return None
        hour, minute = (int(value) for value in ready_after_local_time.split(":"))
        ready_time = time(hour=hour, minute=minute)
        exchange = get_settings().default_exchange
        local_now = self._local_now()
        today = local_now.date()
        today_row = session.scalar(
            select(TradeCalendar).where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.trade_date == today,
            )
        )
        if today_row is not None and today_row.is_open:
            if local_now.timetz().replace(tzinfo=None) >= ready_time:
                return today
            if today_row.pretrade_date is not None:
                return today_row.pretrade_date
            return self._latest_open_date(session, exchange=exchange, before_or_on=today, strict_before=True)
        return self._latest_open_date(session, exchange=exchange, before_or_on=today, strict_before=False)

    @staticmethod
    def _local_now() -> datetime:
        return datetime.now(_CN_TIMEZONE)

    @staticmethod
    def _latest_open_date(
        session: Session,
        *,
        exchange: str,
        before_or_on: date,
        strict_before: bool,
    ) -> date | None:
        stmt = select(func.max(TradeCalendar.trade_date)).where(
            TradeCalendar.exchange == exchange,
            TradeCalendar.is_open.is_(True),
        )
        stmt = stmt.where(
            TradeCalendar.trade_date < before_or_on
            if strict_before
            else TradeCalendar.trade_date <= before_or_on
        )
        return session.scalar(stmt)

    @staticmethod
    def _trading_day_lag(session: Session, *, latest_date: date, expected_date: date) -> int:
        count = session.scalar(
            select(func.count()).where(
                TradeCalendar.exchange == get_settings().default_exchange,
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date > latest_date,
                TradeCalendar.trade_date <= expected_date,
            )
        )
        return int(count) if count else max((expected_date - latest_date).days, 0)

    @staticmethod
    def _primary_action(definition: BizDatasetDefinition) -> tuple[str | None, str | None]:
        if definition.producer_type != "maintenance_action":
            return None, None
        action = get_maintenance_action(definition.producer_key)
        if action is None or not action.manual_enabled:
            return None, None
        return "maintenance_action", action.key

    def _load_action_runtime(
        self,
        session: Session,
        action_keys: set[str],
    ) -> dict[str, BizActionRuntimeSnapshot]:
        if not action_keys:
            return {}
        mutable: dict[str, dict[str, object]] = {
            key: {
                "active_status": None,
                "active_started_at": None,
                "latest_success_at": None,
                "latest_failure_at": None,
                "schedule_total": 0,
                "schedule_active": 0,
                "schedule_next_run_at": None,
            }
            for key in action_keys
        }

        active_runs = session.scalars(
            select(TaskRun)
            .where(
                TaskRun.task_type == "maintenance_action",
                TaskRun.status.in_(_ACTIVE_TASK_STATUSES),
            )
            .order_by(TaskRun.requested_at.desc(), TaskRun.id.desc())
        ).all()
        seen_active: set[str] = set()
        for task_run in active_runs:
            target_key = str((task_run.request_payload_json or {}).get("target_key") or "")
            if target_key not in mutable or target_key in seen_active:
                continue
            mutable[target_key]["active_status"] = task_run.status
            mutable[target_key]["active_started_at"] = task_run.started_at or task_run.requested_at
            seen_active.add(target_key)

        target_key_expr = TaskRun.request_payload_json["target_key"].as_string()
        finished_at_expr = func.coalesce(TaskRun.ended_at, TaskRun.started_at, TaskRun.requested_at)
        trace_rows = session.execute(
            select(
                target_key_expr.label("target_key"),
                TaskRun.status,
                func.max(finished_at_expr).label("finished_at"),
            )
            .where(
                TaskRun.task_type == "maintenance_action",
                target_key_expr.in_(action_keys),
                TaskRun.status.in_(_TASK_TRACE_STATUSES),
            )
            .group_by(target_key_expr, TaskRun.status)
        ).all()
        for target_key, status, finished_at in trace_rows:
            if target_key not in mutable or finished_at is None:
                continue
            field = "latest_success_at" if status == "success" else "latest_failure_at"
            current = mutable[target_key][field]
            if current is None or finished_at > current:
                mutable[target_key][field] = finished_at

        schedules = session.scalars(
            select(OpsSchedule).where(
                OpsSchedule.target_type == "maintenance_action",
                OpsSchedule.target_key.in_(action_keys),
            )
        ).all()
        for schedule in schedules:
            item = mutable[schedule.target_key]
            item["schedule_total"] = int(item["schedule_total"]) + 1
            if schedule.status != "active":
                continue
            item["schedule_active"] = int(item["schedule_active"]) + 1
            current_next_run = item["schedule_next_run_at"]
            if schedule.next_run_at is not None and (
                current_next_run is None or schedule.next_run_at < current_next_run
            ):
                item["schedule_next_run_at"] = schedule.next_run_at

        return {
            key: BizActionRuntimeSnapshot(
                active_status=value["active_status"],
                active_started_at=value["active_started_at"],
                latest_success_at=value["latest_success_at"],
                latest_failure_at=value["latest_failure_at"],
                schedule_total=int(value["schedule_total"]),
                schedule_active=int(value["schedule_active"]),
                schedule_next_run_at=value["schedule_next_run_at"],
            )
            for key, value in mutable.items()
        }

    @staticmethod
    def _group_cards(cards: list[DatasetCardItem]) -> list[DatasetCardGroup]:
        grouped: dict[tuple[int, str, str], list[DatasetCardItem]] = {}
        for item in cards:
            grouped.setdefault((item.group_order, item.group_key, item.group_label), []).append(item)
        return [
            DatasetCardGroup(
                group_key=group_key,
                group_label=group_label,
                group_order=group_order,
                items=items,
            )
            for (group_order, group_key, group_label), items in sorted(
                grouped.items(), key=lambda entry: (entry[0][0], entry[0][2])
            )
        ]
