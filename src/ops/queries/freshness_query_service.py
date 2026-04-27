from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.foundation.models.core.equity_cyq_perf import EquityCyqPerf
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core.equity_dividend import EquityDividend
from src.foundation.models.core.equity_holder_number import EquityHolderNumber
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_margin import EquityMargin
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core.equity_nineturn import EquityNineTurn
from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.equity_stk_limit import EquityStkLimit
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.etf_index import EtfIndex
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.core.fund_adj_factor import FundAdjFactor
from src.foundation.models.core.hk_security import HkSecurity
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_hot import DcHot
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_bar import IndexDailyBar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_monthly_bar import IndexMonthlyBar
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core.kpl_concept_cons import KplConceptCons
from src.foundation.models.core.kpl_list import KplList
from src.foundation.models.core.index_weekly_bar import IndexWeeklyBar
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.limit_step import LimitStep
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.stk_period_bar import StkPeriodBar
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.datasets.models import DatasetDateModel
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.core.us_security import UsSecurity
from src.foundation.models.core.ths_daily import ThsDaily
from src.foundation.models.core.ths_hot import ThsHot
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.raw_multi.raw_biying_equity_daily_bar import RawBiyingEquityDailyBar
from src.foundation.models.raw_multi.raw_biying_moneyflow import RawBiyingMoneyflow
from src.ops.dataset_definition_projection import (
    DatasetFreshnessProjection,
    get_dataset_freshness_projection,
    list_dataset_freshness_projections,
)
from src.ops.dataset_observation_registry import (
    OBSERVED_DATE_FILTERS,
    OBSERVED_DATE_MODEL_REGISTRY,
)
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.action_catalog import get_workflow_definition
from src.ops.dataset_status_projection import snapshot_row_to_freshness_item
from src.ops.schemas.freshness import DatasetFreshnessItem, FreshnessGroup, OpsFreshnessResponse, OpsFreshnessSummary


STATUS_PRIORITY = {"stale": 0, "lagging": 1, "unknown": 2, "disabled": 3, "fresh": 4}
DISABLED_DATASET_KEYS: set[str] = set()
ACTIVE_EXECUTION_STATUSES = ("queued", "running", "canceling")

UNDEFINED_COLUMN_RE = re.compile(r'column "([^"]+)" of relation "([^"]+)" does not exist', re.IGNORECASE)
NOT_NULL_RE = re.compile(
    r'null value in column "([^"]+)" of relation "([^"]+)" violates not-null constraint',
    re.IGNORECASE,
)
ON_CONFLICT_RE = re.compile(
    r"there is no unique or exclusion constraint matching the ON CONFLICT specification",
    re.IGNORECASE,
)

# Shared-table datasets that must be refreshed live on each page load to avoid
# stale snapshot perception when period data just finished syncing.
FORCE_LIVE_RESOURCE_KEYS = {
    "stk_period_bar_week",
    "stk_period_bar_month",
    "stk_period_bar_adj_week",
    "stk_period_bar_adj_month",
}

class FailureSnapshot:
    def __init__(self, *, message: str | None, occurred_at: datetime | None) -> None:
        self.message = message
        self.occurred_at = occurred_at


class AutoScheduleSnapshot:
    def __init__(self) -> None:
        self.total = 0
        self.active = 0
        self.paused = 0
        self.next_run_at: datetime | None = None


class OpsFreshnessQueryService:
    def build_freshness(self, session: Session, *, today: date | None = None) -> OpsFreshnessResponse:
        snapshot_response = self._build_from_snapshot(session)
        if snapshot_response is not None:
            all_projections = list_dataset_freshness_projections()
            snapshot_items_by_key = {
                item.dataset_key: item
                for group in snapshot_response.groups
                for item in group.items
            }
            snapshot_keys = set(snapshot_items_by_key)
            missing_resource_keys = [
                projection.resource_key
                for projection in all_projections
                if projection.dataset_key not in snapshot_keys
            ]
            live_override_resource_keys = [
                projection.resource_key
                for projection in all_projections
                if projection.resource_key in FORCE_LIVE_RESOURCE_KEYS
            ]
            cadence_mismatch_resource_keys = [
                projection.resource_key
                for projection in all_projections
                if (
                    projection.dataset_key in snapshot_items_by_key
                    and snapshot_items_by_key[projection.dataset_key].cadence != projection.cadence
                )
            ]
            missing_business_date_resource_keys = [
                projection.resource_key
                for projection in all_projections
                if (
                    projection.observed_date_column is not None
                    and projection.dataset_key in snapshot_items_by_key
                    and snapshot_items_by_key[projection.dataset_key].last_sync_date is not None
                    and snapshot_items_by_key[projection.dataset_key].latest_business_date is None
                )
            ]
            missing_business_range_resource_keys = [
                projection.resource_key
                for projection in all_projections
                if (
                    projection.observed_date_column is not None
                    and projection.dataset_key in snapshot_items_by_key
                    and snapshot_items_by_key[projection.dataset_key].last_sync_date is not None
                    and snapshot_items_by_key[projection.dataset_key].latest_business_date is not None
                    and snapshot_items_by_key[projection.dataset_key].earliest_business_date is None
                )
            ]
            live_refresh_resource_keys = sorted(
                set(
                    [
                        *missing_resource_keys,
                        *live_override_resource_keys,
                        *cadence_mismatch_resource_keys,
                        *missing_business_date_resource_keys,
                        *missing_business_range_resource_keys,
                    ]
                )
            )
            if not live_refresh_resource_keys:
                return self._attach_runtime_metadata(session, snapshot_response)

            live_refreshed_items = self.build_live_items(session, today=today, resource_keys=live_refresh_resource_keys)
            merged_by_key = {
                item.dataset_key: item
                for group in snapshot_response.groups
                for item in group.items
            }
            for live_item in live_refreshed_items:
                merged_by_key[live_item.dataset_key] = live_item
            merged_items = list(merged_by_key.values())
            groups = self._group_items(merged_items)
            summary = self._build_summary(merged_items)
            return self._attach_runtime_metadata(
                session,
                OpsFreshnessResponse(summary=summary, groups=groups),
            )
        items = self.build_live_items(session, today=today)
        groups = self._group_items(items)
        summary = self._build_summary(items)
        return self._attach_runtime_metadata(
            session,
            OpsFreshnessResponse(summary=summary, groups=groups),
        )

    def build_live_items(
        self,
        session: Session,
        *,
        today: date | None = None,
        resource_keys: list[str] | None = None,
    ) -> list[DatasetFreshnessItem]:
        reference_date = today or datetime.now(timezone.utc).date()
        latest_open_date = self._get_latest_open_date(session, before_or_on=reference_date)
        latest_success_by_resource = self._latest_success_by_resource(session)
        failures_by_resource = self._latest_failures_by_resource(session)
        quality_notes_by_resource = self._latest_quality_notes_by_resource(session)
        projections = list_dataset_freshness_projections()
        if resource_keys is not None:
            target_keys = set(resource_keys)
            projections = tuple(
                projection
                for projection in projections
                if projection.resource_key in target_keys
            )
        open_trade_dates = self._open_trade_dates(session)
        observed_business_ranges, observed_sync_dates, observed_at_ranges = self._observed_dataset_snapshots(
            session,
            list(projections),
            open_trade_dates=open_trade_dates,
        )

        items = [
            self._build_item(
                projection=projection,
                latest_success_at=latest_success_by_resource.get(projection.resource_key),
                latest_open_date=latest_open_date,
                reference_date=reference_date,
                expected_business_date=self._expected_business_date_for_projection(
                    projection,
                    reference_date=reference_date,
                    latest_open_date=latest_open_date,
                    open_trade_dates=open_trade_dates,
                ),
                recent_failure=failures_by_resource.get(projection.resource_key),
                quality_note=quality_notes_by_resource.get(projection.resource_key),
                observed_business_range=observed_business_ranges.get(projection.dataset_key),
                observed_sync_date=observed_sync_dates.get(projection.dataset_key),
                observed_at_range=observed_at_ranges.get(projection.dataset_key),
            )
            for projection in projections
        ]
        return items

    @staticmethod
    def summarize(response: OpsFreshnessResponse) -> tuple[OpsFreshnessSummary, list[DatasetFreshnessItem]]:
        lagging_items = [
            item
            for group in response.groups
            for item in group.items
            if item.freshness_status in {"lagging", "stale"}
        ]
        lagging_items.sort(key=lambda item: (STATUS_PRIORITY[item.freshness_status], -(item.lag_days or 0), item.display_name))
        return response.summary, lagging_items[:5]

    def _build_item(
        self,
        *,
        projection: DatasetFreshnessProjection,
        latest_success_at: datetime | None,
        latest_open_date: date,
        reference_date: date,
        expected_business_date: date | None,
        recent_failure: FailureSnapshot | None,
        quality_note: str | None,
        observed_business_range: tuple[date | None, date | None] | None,
        observed_sync_date: date | None,
        observed_at_range: tuple[datetime | None, datetime | None] | None,
    ) -> DatasetFreshnessItem:
        date_model = self._date_model_for_projection(projection)
        normalized_success_at = self._normalize_datetime(latest_success_at)
        success_sync_date = normalized_success_at.date() if normalized_success_at is not None else None
        if success_sync_date and observed_sync_date:
            last_sync_date = max(success_sync_date, observed_sync_date)
        else:
            last_sync_date = observed_sync_date or success_sync_date
        earliest_business_date = observed_business_range[0] if observed_business_range else None
        observed_business_date = observed_business_range[1] if observed_business_range else None
        earliest_observed_at = observed_at_range[0] if observed_at_range else None
        latest_observed_at = observed_at_range[1] if observed_at_range else None
        latest_business_date = observed_business_date
        effective_date = latest_business_date
        lag_days = max((expected_business_date - effective_date).days, 0) if expected_business_date and effective_date else None
        freshness_status = self._freshness_status_for_date_model(
            date_model,
            cadence=projection.cadence,
            lag_days=lag_days,
            latest_success_at=normalized_success_at,
        )
        if projection.dataset_key in DISABLED_DATASET_KEYS:
            freshness_status = "disabled"
            lag_days = None
        visible_failure = self._visible_failure_snapshot(recent_failure, normalized_success_at)

        base_note = self._freshness_note(
            observed_business_date=observed_business_date,
            latest_observed_at=latest_observed_at,
            last_sync_date=last_sync_date,
            date_model=date_model,
        )
        freshness_note = self._compose_freshness_note(base_note=base_note, quality_note=quality_note)
        if freshness_status == "disabled":
            freshness_note = self._compose_freshness_note(
                base_note="该数据集已停用，不纳入健康度统计。",
                quality_note=quality_note,
            )

        return DatasetFreshnessItem(
            dataset_key=projection.dataset_key,
            resource_key=projection.resource_key,
            display_name=projection.display_name,
            domain_key=projection.domain_key,
            domain_display_name=projection.domain_display_name,
            target_table=projection.target_table,
            raw_table=projection.raw_table,
            cadence=projection.cadence,
            earliest_business_date=earliest_business_date,
            observed_business_date=observed_business_date,
            latest_business_date=latest_business_date,
            earliest_observed_at=earliest_observed_at,
            latest_observed_at=latest_observed_at,
            freshness_note=freshness_note,
            latest_success_at=normalized_success_at,
            last_sync_date=last_sync_date,
            expected_business_date=expected_business_date,
            lag_days=lag_days,
            freshness_status=freshness_status,
            recent_failure_message=visible_failure.message if visible_failure else None,
            recent_failure_summary=self._summarize_failure_message(visible_failure.message) if visible_failure else None,
            recent_failure_at=visible_failure.occurred_at if visible_failure else None,
            primary_action_key=projection.primary_action_key,
        )

    @staticmethod
    def _freshness_note(
        *,
        observed_business_date: date | None,
        latest_observed_at: datetime | None,
        last_sync_date: date | None,
        date_model: DatasetDateModel | None,
    ) -> str | None:
        if latest_observed_at is not None:
            return "最新时间当前来自真实目标表观测值。"
        if observed_business_date is not None:
            return "最新业务日当前来自真实目标表观测值。"
        if date_model is not None and date_model.bucket_rule == "not_applicable" and last_sync_date is not None:
            return "该数据集当前不按业务日期判断新鲜度，仅展示最近一次任务运行迹象。"
        return None

    @staticmethod
    def _freshness_status(cadence: str, lag_days: int | None, latest_success_at: datetime | None) -> str:
        if latest_success_at is None and lag_days is None:
            return "unknown"
        if lag_days is None:
            return "unknown"

        fresh_limit, lagging_limit = {
            "reference": (1, 7),
            "daily": (0, 2),
            "weekly": (7, 14),
            "monthly": (31, 62),
            "event": (30, 90),
        }.get(cadence, (1, 7))

        if lag_days <= fresh_limit:
            return "fresh"
        if lag_days <= lagging_limit:
            return "lagging"
        return "stale"

    @staticmethod
    def _freshness_status_for_date_model(
        date_model: DatasetDateModel | None,
        *,
        cadence: str,
        lag_days: int | None,
        latest_success_at: datetime | None,
    ) -> str:
        if date_model is None:
            return OpsFreshnessQueryService._freshness_status(cadence, lag_days, latest_success_at)
        if date_model.bucket_rule == "not_applicable":
            return "unknown"
        if latest_success_at is None and lag_days is None:
            return "unknown"
        if lag_days is None:
            return "unknown"
        if lag_days <= 0:
            return "fresh"

        lagging_limit = {
            "every_open_day": 2,
            "week_last_open_day": 14,
            "month_last_open_day": 31,
            "every_natural_month": 31,
            "month_window_has_data": 31,
            "every_natural_day": 2,
        }.get(date_model.bucket_rule, 7)

        if lag_days <= lagging_limit:
            return "lagging"
        return "stale"

    @staticmethod
    def _expected_business_date(cadence: str, reference_date: date, latest_open_date: date) -> date:
        if cadence in {"daily", "weekly", "monthly"}:
            return latest_open_date
        return reference_date

    def _expected_business_date_for_projection(
        self,
        projection: DatasetFreshnessProjection,
        *,
        reference_date: date,
        latest_open_date: date,
        open_trade_dates: list[date],
    ) -> date | None:
        date_model = self._date_model_for_projection(projection)
        if date_model is None:
            return self._expected_business_date(projection.cadence, reference_date, latest_open_date)
        if date_model.bucket_rule == "not_applicable":
            return None
        if date_model.date_axis == "trade_open_day":
            if date_model.bucket_rule == "every_open_day":
                return latest_open_date
            if date_model.bucket_rule == "week_last_open_day":
                return self._latest_due_week_bucket(reference_date=reference_date, open_trade_dates=open_trade_dates)
            if date_model.bucket_rule == "month_last_open_day":
                return self._latest_due_month_bucket(reference_date=reference_date, open_trade_dates=open_trade_dates)
            return latest_open_date
        if date_model.date_axis == "natural_day":
            return reference_date
        if date_model.date_axis in {"month_key", "month_window"}:
            return date(reference_date.year, reference_date.month, 1)
        return self._expected_business_date(projection.cadence, reference_date, latest_open_date)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _group_items(items: list[DatasetFreshnessItem]) -> list[FreshnessGroup]:
        grouped: dict[tuple[str, str], list[DatasetFreshnessItem]] = {}
        for item in items:
            grouped.setdefault((item.domain_key, item.domain_display_name), []).append(item)

        groups: list[FreshnessGroup] = []
        for (domain_key, domain_display_name), domain_items in sorted(grouped.items(), key=lambda pair: pair[0][0]):
            ordered_items = sorted(
                domain_items,
                key=lambda item: (STATUS_PRIORITY[item.freshness_status], -(item.lag_days or 0), item.display_name),
            )
            groups.append(
                FreshnessGroup(
                    domain_key=domain_key,
                    domain_display_name=domain_display_name,
                    items=ordered_items,
                )
            )
        return groups

    @staticmethod
    def _build_summary(items: list[DatasetFreshnessItem]) -> OpsFreshnessSummary:
        counts = {"fresh": 0, "lagging": 0, "stale": 0, "unknown": 0, "disabled": 0}
        for item in items:
            counts[item.freshness_status] = counts.get(item.freshness_status, 0) + 1
        return OpsFreshnessSummary(
            total_datasets=len(items),
            fresh_datasets=counts["fresh"],
            lagging_datasets=counts["lagging"],
            stale_datasets=counts["stale"],
            unknown_datasets=counts["unknown"],
            disabled_datasets=counts["disabled"],
        )

    def _attach_runtime_metadata(self, session: Session, response: OpsFreshnessResponse) -> OpsFreshnessResponse:
        response = self._attach_auto_schedule_metadata(session, response)
        response = self._attach_active_task_run_metadata(session, response)
        return response

    def _attach_auto_schedule_metadata(self, session: Session, response: OpsFreshnessResponse) -> OpsFreshnessResponse:
        action_keys = {
            item.primary_action_key
            for group in response.groups
            for item in group.items
            if item.primary_action_key
        }
        if not action_keys:
            return response
        by_action_key = self._auto_schedule_by_action_key(session, action_keys=action_keys)
        for group in response.groups:
            for item in group.items:
                if not item.primary_action_key:
                    continue
                schedule_snapshot = by_action_key.get(item.primary_action_key)
                if schedule_snapshot is None:
                    continue
                item.auto_schedule_total = schedule_snapshot.total
                item.auto_schedule_active = schedule_snapshot.active
                item.auto_schedule_next_run_at = schedule_snapshot.next_run_at
                if schedule_snapshot.active > 0:
                    item.auto_schedule_status = "active"
                elif schedule_snapshot.total > 0:
                    item.auto_schedule_status = "paused"
                else:
                    item.auto_schedule_status = "none"
        return response

    @staticmethod
    def _attach_active_task_run_metadata(session: Session, response: OpsFreshnessResponse) -> OpsFreshnessResponse:
        action_keys = {
            item.primary_action_key
            for group in response.groups
            for item in group.items
            if item.primary_action_key
        }
        dataset_keys = {
            item.dataset_key
            for group in response.groups
            for item in group.items
            if item.dataset_key
        }
        if not action_keys and not dataset_keys:
            return response

        rows = session.execute(
            select(
                TaskRun.task_type,
                TaskRun.resource_key,
                TaskRun.status,
                TaskRun.started_at,
                TaskRun.requested_at,
            )
            .where(TaskRun.status.in_(ACTIVE_EXECUTION_STATUSES))
            .order_by(desc(TaskRun.requested_at), desc(TaskRun.id))
        ).all()

        by_action_key: dict[str, tuple[str, datetime | None]] = {}
        by_dataset_key: dict[str, tuple[str, datetime | None]] = {}
        for row in rows:
            effective_started_at = row.started_at or row.requested_at
            action_key = None
            if row.task_type == "dataset_action" and row.resource_key:
                try:
                    action_key = get_dataset_definition(row.resource_key).action_key("maintain")
                except KeyError:
                    action_key = None
            if action_key and action_key in action_keys and action_key not in by_action_key:
                by_action_key[action_key] = (row.status, effective_started_at)
            if row.resource_key and row.resource_key in dataset_keys and row.resource_key not in by_dataset_key:
                by_dataset_key[row.resource_key] = (row.status, effective_started_at)

        for group in response.groups:
            for item in group.items:
                active = None
                if item.primary_action_key:
                    active = by_action_key.get(item.primary_action_key)
                if active is None and item.dataset_key:
                    active = by_dataset_key.get(item.dataset_key)
                if active is None:
                    continue
                item.active_task_run_status = active[0]
                item.active_task_run_started_at = active[1]
        return response

    @staticmethod
    def _auto_schedule_by_action_key(
        session: Session,
        *,
        action_keys: set[str],
    ) -> dict[str, AutoScheduleSnapshot]:
        if not action_keys:
            return {}
        rows = session.execute(
            select(OpsSchedule.target_type, OpsSchedule.target_key, OpsSchedule.status, OpsSchedule.next_run_at)
            .where(OpsSchedule.target_type.in_(("dataset_action", "maintenance_action", "workflow")))
        ).all()
        result: dict[str, AutoScheduleSnapshot] = {}

        def merge_schedule_snapshot(target_action_key: str, status: str | None, next_run_at: datetime | None) -> None:
            if target_action_key not in action_keys:
                return
            snap = result.setdefault(target_action_key, AutoScheduleSnapshot())
            snap.total += 1
            status_value = (status or "").lower()
            if status_value == "active":
                snap.active += 1
                if isinstance(next_run_at, datetime):
                    if snap.next_run_at is None or next_run_at < snap.next_run_at:
                        snap.next_run_at = next_run_at
            elif status_value == "paused":
                snap.paused += 1

        workflow_action_keys_cache: dict[str, tuple[str, ...]] = {}
        for target_type, target_key, status, next_run_at in rows:
            if target_type in {"dataset_action", "maintenance_action"}:
                merge_schedule_snapshot(target_key, status, next_run_at)
                continue
            if target_type != "workflow":
                continue
            if target_key not in workflow_action_keys_cache:
                workflow = get_workflow_definition(target_key)
                workflow_action_keys_cache[target_key] = tuple(step.action_key for step in workflow.steps) if workflow else ()
            for action_key in workflow_action_keys_cache[target_key]:
                merge_schedule_snapshot(action_key, status, next_run_at)
        return result

    @staticmethod
    def _latest_success_by_resource(session: Session) -> dict[str, datetime]:
        successes: dict[str, datetime] = {}
        node_rows = session.execute(
            select(TaskRunNode.resource_key, TaskRunNode.ended_at, TaskRun.ended_at, TaskRun.started_at, TaskRun.requested_at)
            .join(TaskRun, TaskRun.id == TaskRunNode.task_run_id)
            .where(TaskRunNode.status == "success")
            .where(TaskRunNode.resource_key.is_not(None))
            .order_by(TaskRunNode.resource_key.asc(), desc(TaskRunNode.ended_at), desc(TaskRunNode.id))
        ).all()
        for resource_key, node_ended_at, run_ended_at, run_started_at, requested_at in node_rows:
            if resource_key in successes:
                continue
            effective_at = OpsFreshnessQueryService._normalize_datetime(node_ended_at or run_ended_at or run_started_at or requested_at)
            if effective_at is not None:
                successes[resource_key] = effective_at

        task_rows = session.execute(
            select(TaskRun.resource_key, TaskRun.ended_at, TaskRun.started_at, TaskRun.requested_at)
            .where(TaskRun.status == "success")
            .where(TaskRun.resource_key.is_not(None))
            .order_by(TaskRun.resource_key.asc(), desc(TaskRun.ended_at), desc(TaskRun.id))
        ).all()
        for resource_key, ended_at, started_at, requested_at in task_rows:
            if resource_key in successes:
                continue
            effective_at = OpsFreshnessQueryService._normalize_datetime(ended_at or started_at or requested_at)
            if effective_at is not None:
                successes[resource_key] = effective_at
        return successes

    @staticmethod
    def _latest_failures_by_resource(session: Session) -> dict[str, FailureSnapshot]:
        rows = session.execute(
            select(TaskRunIssue, TaskRun, TaskRunNode)
            .join(TaskRun, TaskRun.id == TaskRunIssue.task_run_id)
            .outerjoin(TaskRunNode, TaskRunNode.id == TaskRunIssue.node_id)
            .where(TaskRun.status.in_(("failed", "partial_success")))
            .order_by(desc(TaskRunIssue.occurred_at), desc(TaskRunIssue.id))
        ).all()
        failures: dict[str, FailureSnapshot] = {}
        for issue, run, node in rows:
            resource_key = node.resource_key if node is not None and node.resource_key else run.resource_key
            if not resource_key or resource_key in failures:
                continue
            failures[resource_key] = FailureSnapshot(
                message=issue.operator_message,
                occurred_at=OpsFreshnessQueryService._normalize_datetime(issue.occurred_at),
            )
        return failures

    @staticmethod
    def _latest_quality_notes_by_resource(session: Session) -> dict[str, str]:
        _ = session
        return {}

    @staticmethod
    def _extract_quality_warning_marker(message: str) -> str | None:
        marker_prefix = "data_quality_warning:"
        for part in message.split(";"):
            normalized = part.strip()
            if normalized.startswith(marker_prefix):
                return normalized[len(marker_prefix) :].strip()
        return None

    @staticmethod
    def _compose_freshness_note(*, base_note: str | None, quality_note: str | None) -> str | None:
        if quality_note:
            quality_text = f"质量提醒：{quality_note}"
            if base_note:
                return f"{base_note} {quality_text}"
            return quality_text
        return base_note

    def _observed_dataset_snapshots(
        self,
        session: Session,
        projections: list[DatasetFreshnessProjection],
        open_trade_dates: list[date] | None = None,
    ) -> tuple[
        dict[str, tuple[date | None, date | None]],
        dict[str, date | None],
        dict[str, tuple[datetime | None, datetime | None]],
    ]:
        observed_ranges: dict[str, tuple[date | None, date | None]] = {}
        observed_sync_dates: dict[str, date | None] = {}
        observed_at_ranges: dict[str, tuple[datetime | None, datetime | None]] = {}
        open_trade_dates = open_trade_dates if open_trade_dates is not None else self._open_trade_dates(session)
        for projection in projections:
            model = OBSERVED_DATE_MODEL_REGISTRY.get(projection.target_table)
            if model is None:
                continue
            date_model = self._date_model_for_projection(projection)
            if projection.observed_date_column:
                if not hasattr(model, projection.observed_date_column):
                    observed_ranges[projection.dataset_key] = (None, None)
                    observed_sync_dates[projection.dataset_key] = None
                    observed_at_ranges[projection.dataset_key] = (None, None)
                    continue
                try:
                    column = getattr(model, projection.observed_date_column)
                    base_filters = []
                    filter_spec = OBSERVED_DATE_FILTERS.get(projection.dataset_key)
                    if filter_spec is not None:
                        filter_field, filter_value = filter_spec
                        if hasattr(model, filter_field):
                            base_filters.append(getattr(model, filter_field) == filter_value)
                    earliest_query = select(func.min(column))
                    latest_query = select(func.max(column))
                    if base_filters:
                        earliest_query = earliest_query.where(*base_filters)
                        latest_query = latest_query.where(*base_filters)
                    bucket_dates = self._actual_bucket_dates_for_observation(date_model, open_trade_dates)
                    if bucket_dates is not None:
                        if not bucket_dates:
                            observed_ranges[projection.dataset_key] = (None, None)
                            observed_sync_dates[projection.dataset_key] = None
                            observed_at_ranges[projection.dataset_key] = (None, None)
                            continue
                        latest_query = latest_query.where(column.in_(bucket_dates))
                    earliest_raw = session.scalar(earliest_query)
                    latest_raw = session.scalar(latest_query)
                    normalized_earliest = OpsFreshnessQueryService._normalize_observed_date(earliest_raw)
                    normalized_latest = OpsFreshnessQueryService._normalize_observed_date(latest_raw)
                    observed_ranges[projection.dataset_key] = (normalized_earliest, normalized_latest)
                    observed_sync_dates[projection.dataset_key] = normalized_latest
                    observed_at_ranges[projection.dataset_key] = (
                        self._normalize_observed_datetime(earliest_raw),
                        self._normalize_observed_datetime(latest_raw),
                    )
                except SQLAlchemyError:
                    observed_ranges[projection.dataset_key] = (None, None)
                    observed_sync_dates[projection.dataset_key] = None
                    observed_at_ranges[projection.dataset_key] = (None, None)
                continue
            try:
                if not hasattr(model, "updated_at"):
                    observed_sync_dates[projection.dataset_key] = None
                    observed_at_ranges[projection.dataset_key] = (None, None)
                    continue
                latest_updated_at = session.scalar(select(func.max(getattr(model, "updated_at"))))
                observed_sync_dates[projection.dataset_key] = OpsFreshnessQueryService._normalize_observed_date(latest_updated_at)
                observed_at_ranges[projection.dataset_key] = (None, None)
            except SQLAlchemyError:
                observed_sync_dates[projection.dataset_key] = None
                observed_at_ranges[projection.dataset_key] = (None, None)
        return observed_ranges, observed_sync_dates, observed_at_ranges

    @staticmethod
    def _build_from_snapshot(session: Session) -> OpsFreshnessResponse | None:
        try:
            rows = list(session.scalars(select(DatasetStatusSnapshot).order_by(DatasetStatusSnapshot.domain_key, DatasetStatusSnapshot.display_name)))
            if not rows:
                return None
            items: list[DatasetFreshnessItem] = []
            for row in rows:
                projection = get_dataset_freshness_projection(row.resource_key)
                items.append(
                    snapshot_row_to_freshness_item(
                        row,
                        raw_table=projection.raw_table if projection is not None else None,
                    )
                )
            groups = OpsFreshnessQueryService._group_items(items)
            summary = OpsFreshnessQueryService._build_summary(items)
            return OpsFreshnessResponse(summary=summary, groups=groups)
        except SQLAlchemyError:
            session.rollback()
            return None

    @staticmethod
    def _normalize_observed_date(value: object) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            text = value.strip()
            if len(text) == 6 and text.isdigit():
                return date(int(text[:4]), int(text[4:6]), 1)
            try:
                return date.fromisoformat(text)
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalize_observed_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return OpsFreshnessQueryService._normalize_datetime(value)
        return None

    @staticmethod
    def _date_model_for_projection(projection: DatasetFreshnessProjection) -> DatasetDateModel | None:
        try:
            return get_dataset_definition(projection.resource_key).date_model
        except KeyError:
            return None

    @staticmethod
    def _open_trade_dates(session: Session) -> list[date]:
        try:
            return list(
                session.scalars(
                    select(TradeCalendar.trade_date)
                    .where(TradeCalendar.exchange == "SSE")
                    .where(TradeCalendar.is_open.is_(True))
                    .order_by(TradeCalendar.trade_date.asc())
                )
            )
        except SQLAlchemyError:
            session.rollback()
            return []

    @staticmethod
    def _latest_due_week_bucket(*, reference_date: date, open_trade_dates: list[date]) -> date | None:
        candidates = [value for value in open_trade_dates if value <= reference_date]
        if not candidates:
            return None
        latest = candidates[-1]
        latest_week = OpsFreshnessQueryService._iso_week_key(latest)
        future_same_week = [
            value
            for value in open_trade_dates
            if value > latest and OpsFreshnessQueryService._iso_week_key(value) == latest_week
        ]
        if not future_same_week or reference_date.weekday() == 6:
            return latest
        previous_weeks = [
            value
            for value in open_trade_dates
            if value < latest and OpsFreshnessQueryService._iso_week_key(value) != latest_week
        ]
        return previous_weeks[-1] if previous_weeks else None

    @staticmethod
    def _latest_due_month_bucket(*, reference_date: date, open_trade_dates: list[date]) -> date | None:
        candidates = [value for value in open_trade_dates if value <= reference_date]
        if not candidates:
            return None
        current_month = (reference_date.year, reference_date.month)
        month_end_day = monthrange(reference_date.year, reference_date.month)[1]
        include_current_month = reference_date.day >= month_end_day
        if include_current_month:
            return candidates[-1]
        previous_month_candidates = [
            value for value in candidates if (value.year, value.month) != current_month
        ]
        return previous_month_candidates[-1] if previous_month_candidates else None

    @staticmethod
    def _actual_bucket_dates_for_observation(
        date_model: DatasetDateModel | None,
        open_trade_dates: list[date],
    ) -> list[date] | None:
        if date_model is None or date_model.date_axis != "trade_open_day":
            return None
        if date_model.bucket_rule == "week_last_open_day":
            return OpsFreshnessQueryService._last_open_day_by_bucket(open_trade_dates, bucket="week")
        if date_model.bucket_rule == "month_last_open_day":
            return OpsFreshnessQueryService._last_open_day_by_bucket(open_trade_dates, bucket="month")
        return None

    @staticmethod
    def _last_open_day_by_bucket(open_trade_dates: list[date], *, bucket: str) -> list[date]:
        grouped: dict[tuple[int, int], date] = {}
        for value in open_trade_dates:
            key = OpsFreshnessQueryService._iso_week_key(value) if bucket == "week" else (value.year, value.month)
            current = grouped.get(key)
            if current is None or value > current:
                grouped[key] = value
        return sorted(grouped.values())

    @staticmethod
    def _iso_week_key(value: date) -> tuple[int, int]:
        iso = value.isocalendar()
        return (iso.year, iso.week)

    @staticmethod
    def _visible_failure_snapshot(
        failure: FailureSnapshot | None,
        latest_success_at: datetime | None,
    ) -> FailureSnapshot | None:
        if failure is None:
            return None
        if latest_success_at is None:
            return failure
        if failure.occurred_at is None:
            return None
        if failure.occurred_at <= latest_success_at:
            return None
        return failure

    @staticmethod
    def _summarize_failure_message(message: str | None) -> str | None:
        if not message:
            return None

        normalized = " ".join(message.split())

        undefined_column_match = UNDEFINED_COLUMN_RE.search(normalized)
        if undefined_column_match:
            column_name, relation_name = undefined_column_match.groups()
            return f"数据库字段缺失：表 {relation_name} 缺少列 {column_name}"

        not_null_match = NOT_NULL_RE.search(normalized)
        if not_null_match:
            column_name, relation_name = not_null_match.groups()
            return f"数据库约束错误：表 {relation_name} 的列 {column_name} 不能为空"

        if ON_CONFLICT_RE.search(normalized):
            return "数据库约束错误：缺少可用于 ON CONFLICT 的唯一约束"

        if normalized.startswith("Tushare API error: "):
            return normalized.replace("Tushare API error: ", "Tushare 接口错误：", 1)

        return normalized[:120] + ("..." if len(normalized) > 120 else "")

    @staticmethod
    def _get_latest_open_date(session: Session, *, before_or_on: date) -> date:
        latest_open_date = session.scalar(
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.exchange == "SSE")
            .where(TradeCalendar.trade_date <= before_or_on)
            .where(TradeCalendar.is_open.is_(True))
            .order_by(desc(TradeCalendar.trade_date))
            .limit(1)
        )
        return latest_open_date or before_or_on
