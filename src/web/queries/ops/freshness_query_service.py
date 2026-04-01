from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.models.core.equity_adj_factor import EquityAdjFactor
from src.models.core.equity_block_trade import EquityBlockTrade
from src.models.core.equity_daily_bar import EquityDailyBar
from src.models.core.equity_daily_basic import EquityDailyBasic
from src.models.core.equity_limit_list import EquityLimitList
from src.models.core.equity_moneyflow import EquityMoneyflow
from src.models.core.equity_top_list import EquityTopList
from src.models.core.fund_daily_bar import FundDailyBar
from src.models.core.index_daily_bar import IndexDailyBar
from src.models.core.index_daily_basic import IndexDailyBasic
from src.models.core.index_monthly_bar import IndexMonthlyBar
from src.models.core.index_weight import IndexWeight
from src.models.core.index_weekly_bar import IndexWeeklyBar
from src.models.core.stk_period_bar import StkPeriodBar
from src.models.core.stk_period_bar_adj import StkPeriodBarAdj
from src.models.core.trade_calendar import TradeCalendar
from src.models.ops.sync_job_state import SyncJobState
from src.models.ops.sync_run_log import SyncRunLog
from src.operations.specs import DatasetFreshnessSpec, get_dataset_freshness_spec_by_job_name, list_dataset_freshness_specs
from src.web.schemas.ops.freshness import DatasetFreshnessItem, FreshnessGroup, OpsFreshnessResponse, OpsFreshnessSummary


STATUS_PRIORITY = {"stale": 0, "lagging": 1, "fresh": 2, "unknown": 3}

UNDEFINED_COLUMN_RE = re.compile(r'column "([^"]+)" of relation "([^"]+)" does not exist', re.IGNORECASE)
NOT_NULL_RE = re.compile(
    r'null value in column "([^"]+)" of relation "([^"]+)" violates not-null constraint',
    re.IGNORECASE,
)
ON_CONFLICT_RE = re.compile(
    r"there is no unique or exclusion constraint matching the ON CONFLICT specification",
    re.IGNORECASE,
)

OBSERVED_DATE_MODEL_REGISTRY: dict[str, type] = {
    "core.trade_calendar": TradeCalendar,
    "core.equity_daily_bar": EquityDailyBar,
    "core.equity_adj_factor": EquityAdjFactor,
    "core.equity_daily_basic": EquityDailyBasic,
    "core.equity_moneyflow": EquityMoneyflow,
    "core.equity_top_list": EquityTopList,
    "core.equity_block_trade": EquityBlockTrade,
    "core.equity_limit_list": EquityLimitList,
    "core.stk_period_bar": StkPeriodBar,
    "core.stk_period_bar_adj": StkPeriodBarAdj,
    "core.fund_daily_bar": FundDailyBar,
    "core.index_daily_bar": IndexDailyBar,
    "core.index_weekly_bar": IndexWeeklyBar,
    "core.index_monthly_bar": IndexMonthlyBar,
    "core.index_daily_basic": IndexDailyBasic,
    "core.index_weight": IndexWeight,
}


class FailureSnapshot:
    def __init__(self, *, message: str | None, occurred_at: datetime | None) -> None:
        self.message = message
        self.occurred_at = occurred_at


class OpsFreshnessQueryService:
    def build_freshness(self, session: Session, *, today: date | None = None) -> OpsFreshnessResponse:
        reference_date = today or datetime.now(timezone.utc).date()
        latest_open_date = self._get_latest_open_date(session, before_or_on=reference_date)
        states = list(session.scalars(select(SyncJobState)))
        state_by_job_name = {state.job_name: state for state in states}
        failures_by_job_name = self._latest_failures_by_job_name(session)
        observed_business_ranges = self._observed_business_date_ranges(session)

        items = [
            self._build_item(
                spec=spec,
                state=state_by_job_name.pop(spec.job_name, None),
                latest_open_date=latest_open_date,
                reference_date=reference_date,
                recent_failure=failures_by_job_name.get(spec.job_name),
                observed_business_range=observed_business_ranges.get(spec.dataset_key),
            )
            for spec in list_dataset_freshness_specs()
        ]

        for job_name, state in sorted(state_by_job_name.items()):
            items.append(
                self._build_item(
                    spec=self._fallback_spec_for_state(state),
                    state=state,
                    latest_open_date=latest_open_date,
                    reference_date=reference_date,
                    recent_failure=failures_by_job_name.get(job_name),
                    observed_business_range=None,
                )
            )

        groups = self._group_items(items)
        summary = self._build_summary(items)
        return OpsFreshnessResponse(summary=summary, groups=groups)

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
        spec: DatasetFreshnessSpec,
        state: SyncJobState | None,
        latest_open_date: date,
        reference_date: date,
        recent_failure: FailureSnapshot | None,
        observed_business_range: tuple[date | None, date | None] | None,
    ) -> DatasetFreshnessItem:
        latest_success_at = self._normalize_datetime(state.last_success_at) if state is not None else None
        state_business_date = state.last_success_date if state is not None else None
        earliest_business_date = observed_business_range[0] if observed_business_range else None
        observed_business_date = observed_business_range[1] if observed_business_range else None
        latest_business_date = self._choose_latest_business_date(state_business_date, observed_business_date)
        business_date_source = self._business_date_source(
            state_business_date=state_business_date,
            observed_business_date=observed_business_date,
            latest_business_date=latest_business_date,
        )
        full_sync_done = bool(state.full_sync_done) if state is not None else False
        expected_business_date = self._expected_business_date(spec.cadence, reference_date, latest_open_date)
        effective_date = latest_business_date or (latest_success_at.date() if latest_success_at else None)
        lag_days = max((expected_business_date - effective_date).days, 0) if expected_business_date and effective_date else None
        freshness_status = self._freshness_status(spec.cadence, lag_days, full_sync_done, latest_success_at)
        visible_failure = self._visible_failure_snapshot(recent_failure, latest_success_at)

        return DatasetFreshnessItem(
            dataset_key=spec.dataset_key,
            resource_key=spec.resource_key,
            display_name=spec.display_name,
            domain_key=spec.domain_key,
            domain_display_name=spec.domain_display_name,
            job_name=spec.job_name,
            target_table=spec.target_table,
            cadence=spec.cadence,
            state_business_date=state_business_date,
            earliest_business_date=earliest_business_date,
            observed_business_date=observed_business_date,
            latest_business_date=latest_business_date,
            business_date_source=business_date_source,
            freshness_note=self._freshness_note(
                state_business_date=state_business_date,
                observed_business_date=observed_business_date,
                business_date_source=business_date_source,
            ),
            latest_success_at=latest_success_at,
            expected_business_date=expected_business_date,
            lag_days=lag_days,
            freshness_status=freshness_status,
            recent_failure_message=visible_failure.message if visible_failure else None,
            recent_failure_summary=self._summarize_failure_message(visible_failure.message) if visible_failure else None,
            recent_failure_at=visible_failure.occurred_at if visible_failure else None,
            primary_execution_spec_key=spec.primary_execution_spec_key,
            full_sync_done=full_sync_done,
        )

    @staticmethod
    def _choose_latest_business_date(state_business_date: date | None, observed_business_date: date | None) -> date | None:
        if state_business_date and observed_business_date:
            return max(state_business_date, observed_business_date)
        return observed_business_date or state_business_date

    @staticmethod
    def _business_date_source(
        *,
        state_business_date: date | None,
        observed_business_date: date | None,
        latest_business_date: date | None,
    ) -> str:
        if latest_business_date is None:
            return "none"
        sources: list[str] = []
        if state_business_date == latest_business_date:
            sources.append("state")
        if observed_business_date == latest_business_date:
            sources.append("observed")
        if not sources:
            return "none"
        if len(sources) == 2:
            return "state+observed"
        return sources[0]

    @staticmethod
    def _freshness_note(
        *,
        state_business_date: date | None,
        observed_business_date: date | None,
        business_date_source: str,
    ) -> str | None:
        if business_date_source == "observed" and state_business_date and observed_business_date:
            if observed_business_date > state_business_date:
                return "已按真实目标表的业务日期修正，状态表记录偏旧。"
        if business_date_source == "state+observed":
            return "最新业务日同时被状态表和真实目标表观测到。"
        if business_date_source == "observed":
            return "最新业务日当前来自真实目标表观测值。"
        if business_date_source == "state":
            return "最新业务日当前来自 sync_job_state。"
        return None

    @staticmethod
    def _freshness_status(cadence: str, lag_days: int | None, full_sync_done: bool, latest_success_at: datetime | None) -> str:
        if latest_success_at is None and not full_sync_done and lag_days is None:
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
    def _expected_business_date(cadence: str, reference_date: date, latest_open_date: date) -> date:
        if cadence in {"daily", "weekly", "monthly"}:
            return latest_open_date
        return reference_date

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
        counts = {"fresh": 0, "lagging": 0, "stale": 0, "unknown": 0}
        for item in items:
            counts[item.freshness_status] = counts.get(item.freshness_status, 0) + 1
        return OpsFreshnessSummary(
            total_datasets=len(items),
            fresh_datasets=counts["fresh"],
            lagging_datasets=counts["lagging"],
            stale_datasets=counts["stale"],
            unknown_datasets=counts["unknown"],
        )

    @staticmethod
    def _fallback_spec_for_state(state: SyncJobState) -> DatasetFreshnessSpec:
        return DatasetFreshnessSpec(
            dataset_key=state.job_name,
            resource_key=state.job_name,
            job_name=state.job_name,
            display_name=state.job_name,
            domain_key="other",
            domain_display_name="其他",
            target_table=state.target_table,
            cadence="reference",
        )

    @staticmethod
    def _latest_failures_by_job_name(session: Session) -> dict[str, FailureSnapshot]:
        rows = session.scalars(
            select(SyncRunLog)
            .where(SyncRunLog.status == "FAILED")
            .order_by(SyncRunLog.job_name.asc(), desc(SyncRunLog.ended_at), desc(SyncRunLog.id))
        )
        failures: dict[str, FailureSnapshot] = {}
        for row in rows:
            failures.setdefault(
                row.job_name,
                FailureSnapshot(
                    message=row.message,
                    occurred_at=OpsFreshnessQueryService._normalize_datetime(row.ended_at or row.started_at),
                ),
            )
        return failures

    @staticmethod
    def _observed_business_date_ranges(session: Session) -> dict[str, tuple[date | None, date | None]]:
        observed: dict[str, tuple[date | None, date | None]] = {}
        for spec in list_dataset_freshness_specs():
            if not spec.observed_date_column:
                continue
            model = OBSERVED_DATE_MODEL_REGISTRY.get(spec.target_table)
            if model is None or not hasattr(model, spec.observed_date_column):
                observed[spec.dataset_key] = (None, None)
                continue
            try:
                column = getattr(model, spec.observed_date_column)
                earliest_raw, latest_raw = session.execute(select(func.min(column), func.max(column))).one()
                observed[spec.dataset_key] = (
                    OpsFreshnessQueryService._normalize_observed_date(earliest_raw),
                    OpsFreshnessQueryService._normalize_observed_date(latest_raw),
                )
            except SQLAlchemyError:
                observed[spec.dataset_key] = (None, None)
        return observed

    @staticmethod
    def _normalize_observed_date(value: object) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

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
