from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.ingestion.plan_helpers import split_multi_values
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.index_daily_reconciliation_policy import (
    INDEX_DAILY_ACTIVATION_REQUIRED_OPEN_DAYS,
    INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
    INDEX_DAILY_MAX_TERMINAL_REPAIR_ATTEMPTS,
    INDEX_DAILY_RECONCILIATION_TIMEZONE,
    INDEX_DAILY_SOURCE_DELAY_OPEN_DAY_LIMIT,
)


TERMINAL_REPAIR_STATUSES = ("success", "partial_success", "failed", "canceled")
SOURCE_SERVICEABILITY_PRESENTATION = {
    "ready": ("正常", "无需处理"),
    "source_delayed": ("等待源站", "系统将在受控窗口继续补漏"),
    "serviceability_review_required": ("待审查", "请审查并决定是否移出激活池"),
}


@dataclass(frozen=True)
class IndexDailyGapClassification:
    ts_code: str
    target_trade_date: date
    latest_raw_trade_date: date | None
    raw_has_target_trade_date: bool
    terminal_repair_attempt_count: int
    internal_status: str
    public_serviceability_status: str
    automatic_repair_eligible: bool


@dataclass(frozen=True)
class IndexDailyActivationEligibility:
    ts_code: str
    reference_trade_date: date | None
    latest_raw_trade_date: date | None
    eligible: bool
    message: str


@dataclass(frozen=True)
class IndexDailyActiveServiceability:
    ts_code: str
    reference_trade_date: date | None
    latest_raw_trade_date: date | None
    internal_status: str
    public_serviceability_status: str


class IndexDailySourceServiceabilityService:
    """Derive index_daily source serviceability from live raw, serving, calendar, and TaskRun facts."""

    def missing_active_codes(self, session: Session, *, target_trade_date: date) -> list[str]:
        rows = session.scalars(
            select(IndexSeriesActive.ts_code)
            .where(IndexSeriesActive.resource == "index_daily")
            .where(
                ~IndexSeriesActive.ts_code.in_(
                    select(IndexDailyServing.ts_code).where(IndexDailyServing.trade_date == target_trade_date)
                )
            )
            .order_by(IndexSeriesActive.ts_code.asc())
        )
        return [str(code) for code in rows if str(code).strip()]

    @staticmethod
    def presentation_for_status(status: str) -> tuple[str, str]:
        return SOURCE_SERVICEABILITY_PRESENTATION.get(
            status,
            SOURCE_SERVICEABILITY_PRESENTATION["serviceability_review_required"],
        )

    def classify_active_gaps(
        self,
        session: Session,
        *,
        target_trade_date: date,
    ) -> list[IndexDailyGapClassification]:
        missing_codes = self.missing_active_codes(session, target_trade_date=target_trade_date)
        return self.classify_codes(session, target_trade_date=target_trade_date, ts_codes=missing_codes)

    def active_serviceability(
        self,
        session: Session,
        *,
        now: datetime | None = None,
    ) -> list[IndexDailyActiveServiceability]:
        active_codes = self._active_codes(session)
        if not active_codes:
            return []
        reference_trade_date = self.latest_completed_open_trade_date(session, now=now)
        latest_raw_by_code = self._latest_raw_trade_dates(session, ts_codes=active_codes)
        if reference_trade_date is None:
            return [
                IndexDailyActiveServiceability(
                    ts_code=ts_code,
                    reference_trade_date=None,
                    latest_raw_trade_date=latest_raw_by_code.get(ts_code),
                    internal_status="missing_completed_open_trade_date",
                    public_serviceability_status="serviceability_review_required",
                )
                for ts_code in active_codes
            ]

        classifications_by_code = {
            classification.ts_code: classification
            for classification in self.classify_active_gaps(session, target_trade_date=reference_trade_date)
        }
        serviceability: list[IndexDailyActiveServiceability] = []
        for ts_code in active_codes:
            classification = classifications_by_code.get(ts_code)
            if classification is not None:
                serviceability.append(
                    IndexDailyActiveServiceability(
                        ts_code=ts_code,
                        reference_trade_date=reference_trade_date,
                        latest_raw_trade_date=classification.latest_raw_trade_date,
                        internal_status=classification.internal_status,
                        public_serviceability_status=classification.public_serviceability_status,
                    )
                )
                continue
            latest_raw_trade_date = latest_raw_by_code.get(ts_code)
            is_ready = latest_raw_trade_date is not None and latest_raw_trade_date >= reference_trade_date
            serviceability.append(
                IndexDailyActiveServiceability(
                    ts_code=ts_code,
                    reference_trade_date=reference_trade_date,
                    latest_raw_trade_date=latest_raw_trade_date,
                    internal_status="ready" if is_ready else "serviceability_review_required",
                    public_serviceability_status="ready" if is_ready else "serviceability_review_required",
                )
            )
        return serviceability

    def classify_codes(
        self,
        session: Session,
        *,
        target_trade_date: date,
        ts_codes: list[str],
    ) -> list[IndexDailyGapClassification]:
        normalized_codes = sorted({str(code).strip() for code in ts_codes if str(code).strip()})
        if not normalized_codes:
            return []

        raw_latest_by_code = self._latest_raw_trade_dates(session, ts_codes=normalized_codes)
        raw_target_codes = self._raw_codes_for_trade_date(
            session,
            ts_codes=normalized_codes,
            target_trade_date=target_trade_date,
        )
        repair_attempts_by_code = self._terminal_repair_attempts_by_code(
            session,
            target_trade_date=target_trade_date,
        )
        allowed_delay_dates = set(
            self._open_trade_dates_on_or_before(
                session,
                trade_date=target_trade_date,
                limit=INDEX_DAILY_SOURCE_DELAY_OPEN_DAY_LIMIT,
            )
        )

        classifications: list[IndexDailyGapClassification] = []
        for ts_code in normalized_codes:
            latest_raw_trade_date = raw_latest_by_code.get(ts_code)
            raw_has_target_trade_date = ts_code in raw_target_codes
            terminal_repair_attempt_count = repair_attempts_by_code.get(ts_code, 0)
            if raw_has_target_trade_date:
                classifications.append(
                    IndexDailyGapClassification(
                        ts_code=ts_code,
                        target_trade_date=target_trade_date,
                        latest_raw_trade_date=latest_raw_trade_date,
                        raw_has_target_trade_date=True,
                        terminal_repair_attempt_count=terminal_repair_attempt_count,
                        internal_status="serving_projection_gap",
                        public_serviceability_status="ready",
                        automatic_repair_eligible=True,
                    )
                )
                continue

            is_recent_delay = latest_raw_trade_date is not None and latest_raw_trade_date in allowed_delay_dates
            if is_recent_delay and terminal_repair_attempt_count < INDEX_DAILY_MAX_TERMINAL_REPAIR_ATTEMPTS:
                internal_status = "source_delayed"
                public_status = "source_delayed"
                repair_eligible = True
            elif is_recent_delay:
                internal_status = "source_retry_exhausted"
                public_status = "serviceability_review_required"
                repair_eligible = False
            else:
                internal_status = "serviceability_review_required"
                public_status = "serviceability_review_required"
                repair_eligible = False
            classifications.append(
                IndexDailyGapClassification(
                    ts_code=ts_code,
                    target_trade_date=target_trade_date,
                    latest_raw_trade_date=latest_raw_trade_date,
                    raw_has_target_trade_date=False,
                    terminal_repair_attempt_count=terminal_repair_attempt_count,
                    internal_status=internal_status,
                    public_serviceability_status=public_status,
                    automatic_repair_eligible=repair_eligible,
                )
            )
        return classifications

    def activation_eligibility(
        self,
        session: Session,
        *,
        ts_code: str,
        now: datetime | None = None,
    ) -> IndexDailyActivationEligibility:
        reference_trade_date = self.latest_completed_open_trade_date(session, now=now)
        latest_raw_trade_date = session.scalar(
            select(func.max(RawIndexDaily.trade_date)).where(RawIndexDaily.ts_code == ts_code)
        )
        if reference_trade_date is None:
            return IndexDailyActivationEligibility(
                ts_code=ts_code,
                reference_trade_date=None,
                latest_raw_trade_date=latest_raw_trade_date,
                eligible=False,
                message="暂时无法确定最近已结束开市日，请稍后再试。",
            )

        required_dates = self._open_trade_dates_on_or_before(
            session,
            trade_date=reference_trade_date,
            limit=INDEX_DAILY_ACTIVATION_REQUIRED_OPEN_DAYS,
        )
        if len(required_dates) != INDEX_DAILY_ACTIVATION_REQUIRED_OPEN_DAYS:
            return IndexDailyActivationEligibility(
                ts_code=ts_code,
                reference_trade_date=reference_trade_date,
                latest_raw_trade_date=latest_raw_trade_date,
                eligible=False,
                message="交易日历不足，暂时无法完成源站连续供数校验。",
            )
        raw_dates = set(
            session.scalars(
                select(RawIndexDaily.trade_date)
                .where(RawIndexDaily.ts_code == ts_code)
                .where(RawIndexDaily.trade_date.in_(required_dates))
            )
        )
        if all(required_date in raw_dates for required_date in required_dates):
            return IndexDailyActivationEligibility(
                ts_code=ts_code,
                reference_trade_date=reference_trade_date,
                latest_raw_trade_date=latest_raw_trade_date,
                eligible=True,
                message="已连续 3 个已结束开市日取得源站日线，可以加入激活池。",
            )
        return IndexDailyActivationEligibility(
            ts_code=ts_code,
            reference_trade_date=reference_trade_date,
            latest_raw_trade_date=latest_raw_trade_date,
            eligible=False,
            message="该指数尚未连续 3 个已结束开市日取得源站日线，请先在 raw 请求池观察后再加入激活池。",
        )

    def latest_completed_open_trade_date(self, session: Session, *, now: datetime | None = None) -> date | None:
        current = now or datetime.now(timezone.utc)
        local_today = current.astimezone(INDEX_DAILY_RECONCILIATION_TIMEZONE).date()
        return session.scalar(
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.exchange == get_settings().default_exchange)
            .where(TradeCalendar.is_open.is_(True))
            .where(TradeCalendar.trade_date < local_today)
            .order_by(TradeCalendar.trade_date.desc())
            .limit(1)
        )

    @staticmethod
    def _active_codes(session: Session) -> list[str]:
        return [
            str(ts_code)
            for ts_code in session.scalars(
                select(IndexSeriesActive.ts_code)
                .where(IndexSeriesActive.resource == "index_daily")
                .order_by(IndexSeriesActive.ts_code.asc())
            )
            if str(ts_code).strip()
        ]

    @staticmethod
    def _latest_raw_trade_dates(session: Session, *, ts_codes: list[str]) -> dict[str, date]:
        rows = session.execute(
            select(RawIndexDaily.ts_code, func.max(RawIndexDaily.trade_date))
            .where(RawIndexDaily.ts_code.in_(ts_codes))
            .group_by(RawIndexDaily.ts_code)
        )
        return {str(row.ts_code): row[1] for row in rows if row[1] is not None}

    @staticmethod
    def _raw_codes_for_trade_date(session: Session, *, ts_codes: list[str], target_trade_date: date) -> set[str]:
        return set(
            session.scalars(
                select(RawIndexDaily.ts_code)
                .where(RawIndexDaily.ts_code.in_(ts_codes))
                .where(RawIndexDaily.trade_date == target_trade_date)
            )
        )

    @staticmethod
    def _terminal_repair_attempts_by_code(
        session: Session,
        *,
        target_trade_date: date,
    ) -> dict[str, int]:
        candidates = session.scalars(
            select(TaskRun)
            .where(TaskRun.task_type == "dataset_action")
            .where(TaskRun.resource_key == "index_daily")
            .where(TaskRun.action == "maintain")
            .where(TaskRun.status.in_(TERMINAL_REPAIR_STATUSES))
        )
        counts: dict[str, int] = {}
        expected_trade_date = target_trade_date.isoformat()
        for task_run in candidates:
            payload = task_run.request_payload_json if isinstance(task_run.request_payload_json, dict) else {}
            time_input = task_run.time_input_json if isinstance(task_run.time_input_json, dict) else {}
            if payload.get("run_scope") != INDEX_DAILY_GAP_REPAIR_RUN_SCOPE:
                continue
            if time_input.get("mode") != "point" or time_input.get("trade_date") != expected_trade_date:
                continue
            filters = task_run.filters_json if isinstance(task_run.filters_json, dict) else {}
            for ts_code in split_multi_values(filters.get("ts_code")):
                counts[ts_code] = counts.get(ts_code, 0) + 1
        return counts

    @staticmethod
    def _open_trade_dates_on_or_before(session: Session, *, trade_date: date, limit: int) -> list[date]:
        return list(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(TradeCalendar.exchange == get_settings().default_exchange)
                .where(TradeCalendar.is_open.is_(True))
                .where(TradeCalendar.trade_date <= trade_date)
                .order_by(TradeCalendar.trade_date.desc())
                .limit(limit)
            )
        )
