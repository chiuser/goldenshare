from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.foundation.dao.etf_basic_dao import (
    EtfBasicDAO,
    EtfRequestTarget,
    EtfRequestabilitySnapshot,
)
from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.ingestion.etf_minute_windows import (
    ETF_MINS_RANGE_WINDOW_MONTHS,
    build_etf_minute_windows,
)
from src.ops.models.ops.task_run import TaskRun


ETF_MINUTE_FREQUENCIES = tuple(ETF_MINS_RANGE_WINDOW_MONTHS)
_FREQUENCY_ORDER = {freq: index for index, freq in enumerate(ETF_MINUTE_FREQUENCIES)}
_CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_PAGE_REQUESTS_PER_UNIT_UPPER_BOUND = 4

_RAW_MONTHLY_COVERAGE_SQL = text(
    """
    SELECT
        raw.ts_code,
        raw.freq,
        COUNT(*) AS row_count,
        MIN(raw.trade_time) AS min_trade_time,
        MAX(raw.trade_time) AS max_trade_time
    FROM raw_tushare.etf_minute_bar AS raw
    WHERE raw.trade_time >= CAST(:month_start AS timestamp)
      AND raw.trade_time < CAST(:next_month_start AS timestamp)
      AND raw.freq IN ('1min', '5min', '15min', '30min', '60min')
    GROUP BY raw.ts_code, raw.freq
    """
)


def canonical_etf_minute_alignment_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def etf_minute_request_target_hash(
    targets: Sequence[EtfRequestTarget],
) -> str:
    payload = [
        {
            "ts_code": target.ts_code,
            "list_date": target.list_date.isoformat(),
            "exchange": target.exchange,
        }
        for target in sorted(targets, key=lambda item: item.ts_code)
    ]
    return canonical_etf_minute_alignment_hash(payload)


@dataclass(frozen=True, slots=True)
class EtfMinuteAlignmentInterval:
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class EtfMinuteRawMonthlyCoverage:
    ts_code: str
    frequency: str
    month_start: date
    row_count: int
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class EtfMinuteSuccessfulTaskCoverage:
    ts_code: str
    frequency: str
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class EtfMinuteHistoryAlignmentAction:
    ts_code: str
    frequencies: tuple[str, ...]
    start_date: date
    end_date: date
    planned_unit_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "ts_code": self.ts_code,
            "frequencies": list(self.frequencies),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "planned_unit_count": self.planned_unit_count,
        }


@dataclass(frozen=True, slots=True)
class EtfMinuteHistoryAlignmentFrequencySummary:
    frequency: str
    action_count: int
    planned_unit_count: int
    source_request_lower_bound: int
    page_request_upper_bound: int
    raw_covered_target_count: int
    successful_task_only_covered_target_count: int
    missing_prefix_target_count: int
    missing_suffix_target_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "frequency": self.frequency,
            "action_count": self.action_count,
            "planned_unit_count": self.planned_unit_count,
            "source_request_lower_bound": self.source_request_lower_bound,
            "page_request_upper_bound": self.page_request_upper_bound,
            "raw_covered_target_count": self.raw_covered_target_count,
            "successful_task_only_covered_target_count": (
                self.successful_task_only_covered_target_count
            ),
            "missing_prefix_target_count": self.missing_prefix_target_count,
            "missing_suffix_target_count": self.missing_suffix_target_count,
        }


@dataclass(frozen=True, slots=True)
class EtfMinuteHistoryAlignmentPlan:
    plan_id: str
    plan_content_hash: str
    generated_at: datetime
    request_target_hash: str
    eligibility_as_of: date
    alignment_start_date: date
    alignment_end_date: date
    requestable_etf_count: int
    alignment_target_etf_count: int
    list_date_after_alignment_end_count: int
    excluded_reason_counts: Mapping[str, int]
    frequency_summaries: tuple[EtfMinuteHistoryAlignmentFrequencySummary, ...]
    raw_covered_target_frequency_count: int
    successful_task_only_covered_target_frequency_count: int
    missing_prefix_target_frequency_count: int
    missing_suffix_target_frequency_count: int
    planned_action_count: int
    planned_unit_count: int
    source_request_lower_bound: int
    page_request_upper_bound: int
    interior_gap_not_audited: bool
    actions: tuple[EtfMinuteHistoryAlignmentAction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "excluded_reason_counts",
            MappingProxyType(dict(self.excluded_reason_counts)),
        )
        object.__setattr__(self, "frequency_summaries", tuple(self.frequency_summaries))
        object.__setattr__(self, "actions", tuple(self.actions))

    def to_payload(self, *, include_content_hash: bool = True) -> dict[str, Any]:
        payload = {
            "plan_id": self.plan_id,
            "generated_at": self.generated_at.isoformat(),
            "request_target_hash": self.request_target_hash,
            "eligibility_as_of": self.eligibility_as_of.isoformat(),
            "alignment_start_date": self.alignment_start_date.isoformat(),
            "alignment_end_date": self.alignment_end_date.isoformat(),
            "requestable_etf_count": self.requestable_etf_count,
            "alignment_target_etf_count": self.alignment_target_etf_count,
            "list_date_after_alignment_end_count": self.list_date_after_alignment_end_count,
            "excluded_reason_counts": dict(sorted(self.excluded_reason_counts.items())),
            "frequency_summaries": [item.to_payload() for item in self.frequency_summaries],
            "raw_covered_target_frequency_count": self.raw_covered_target_frequency_count,
            "successful_task_only_covered_target_frequency_count": (
                self.successful_task_only_covered_target_frequency_count
            ),
            "missing_prefix_target_frequency_count": self.missing_prefix_target_frequency_count,
            "missing_suffix_target_frequency_count": self.missing_suffix_target_frequency_count,
            "planned_action_count": self.planned_action_count,
            "planned_unit_count": self.planned_unit_count,
            "source_request_lower_bound": self.source_request_lower_bound,
            "page_request_upper_bound": self.page_request_upper_bound,
            "interior_gap_not_audited": self.interior_gap_not_audited,
            "actions": [item.to_payload() for item in self.actions],
        }
        if include_content_hash:
            payload["plan_content_hash"] = self.plan_content_hash
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    def render_summary(self) -> str:
        lines = [
            "ETF minute alignment preview",
            f"plan_id={self.plan_id}",
            f"alignment_start_date={self.alignment_start_date.isoformat()}",
            f"alignment_end_date={self.alignment_end_date.isoformat()}",
            f"eligibility_as_of={self.eligibility_as_of.isoformat()}",
            f"requestable_etf_count={self.requestable_etf_count}",
            f"alignment_target_etf_count={self.alignment_target_etf_count}",
            f"list_date_after_alignment_end_count={self.list_date_after_alignment_end_count}",
            f"planned_action_count={self.planned_action_count}",
            f"planned_unit_count={self.planned_unit_count}",
            f"source_request_lower_bound={self.source_request_lower_bound}",
            f"page_request_upper_bound={self.page_request_upper_bound}",
        ]
        for summary in self.frequency_summaries:
            lines.append(
                "frequency={frequency} actions={actions} units={units} "
                "requests={lower}..{upper} prefix={prefix} suffix={suffix}".format(
                    frequency=summary.frequency,
                    actions=summary.action_count,
                    units=summary.planned_unit_count,
                    lower=summary.source_request_lower_bound,
                    upper=summary.page_request_upper_bound,
                    prefix=summary.missing_prefix_target_count,
                    suffix=summary.missing_suffix_target_count,
                )
            )
        return "\n".join(lines)


class EtfMinuteHistoryAlignmentPlanError(ValueError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = MappingProxyType(dict(details or {}))


class EtfMinuteHistoryAlignmentPlanService:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._uuid_factory = uuid_factory or uuid4

    def build_plan(
        self,
        session: Session,
        *,
        alignment_start_date: date,
        alignment_end_date: date,
    ) -> EtfMinuteHistoryAlignmentPlan:
        generated_at = self._clock()
        if generated_at.tzinfo is None:
            raise ValueError("alignment preview clock must return a timezone-aware datetime")
        generated_at = generated_at.astimezone(timezone.utc)
        eligibility_as_of = generated_at.astimezone(_CHINA_TIMEZONE).date()
        if alignment_start_date > alignment_end_date:
            raise EtfMinuteHistoryAlignmentPlanError(
                code="alignment_start_date_after_end_date",
                message="对齐开始日晚于对齐截止日",
                details={
                    "alignment_start_date": alignment_start_date.isoformat(),
                    "alignment_end_date": alignment_end_date.isoformat(),
                },
            )

        calendar_dao = TradeCalendarDAO(session)
        latest_open_date = calendar_dao.get_latest_open_date("SSE", eligibility_as_of)
        alignment_open_dates = calendar_dao.get_open_dates(
            "SSE",
            alignment_start_date,
            alignment_end_date,
        )
        self._validate_alignment_window(
            alignment_end_date=alignment_end_date,
            latest_open_date=latest_open_date,
            alignment_open_dates=alignment_open_dates,
        )
        snapshot = EtfBasicDAO(session).load_requestability_snapshot(
            as_of_date=eligibility_as_of
        )
        return self._build_plan_for_snapshot_and_open_dates(
            session,
            snapshot=snapshot,
            generated_at=generated_at,
            alignment_start_date=alignment_start_date,
            alignment_end_date=alignment_end_date,
            alignment_open_dates=alignment_open_dates,
        )

    def build_plan_for_snapshot(
        self,
        session: Session,
        *,
        snapshot: EtfRequestabilitySnapshot,
        generated_at: datetime,
        alignment_start_date: date,
        alignment_end_date: date,
    ) -> EtfMinuteHistoryAlignmentPlan:
        if generated_at.tzinfo is None:
            raise ValueError("alignment preview clock must return a timezone-aware datetime")
        if alignment_start_date > alignment_end_date:
            raise EtfMinuteHistoryAlignmentPlanError(
                code="alignment_start_date_after_end_date",
                message="对齐开始日晚于对齐截止日",
                details={
                    "alignment_start_date": alignment_start_date.isoformat(),
                    "alignment_end_date": alignment_end_date.isoformat(),
                },
            )

        calendar_dao = TradeCalendarDAO(session)
        latest_open_date = calendar_dao.get_latest_open_date(
            "SSE",
            snapshot.as_of_date,
        )
        alignment_open_dates = calendar_dao.get_open_dates(
            "SSE",
            alignment_start_date,
            alignment_end_date,
        )
        self._validate_alignment_window(
            alignment_end_date=alignment_end_date,
            latest_open_date=latest_open_date,
            alignment_open_dates=alignment_open_dates,
        )

        return self._build_plan_for_snapshot_and_open_dates(
            session,
            snapshot=snapshot,
            generated_at=generated_at,
            alignment_start_date=alignment_start_date,
            alignment_end_date=alignment_end_date,
            alignment_open_dates=alignment_open_dates,
        )

    def _build_plan_for_snapshot_and_open_dates(
        self,
        session: Session,
        *,
        snapshot: EtfRequestabilitySnapshot,
        generated_at: datetime,
        alignment_start_date: date,
        alignment_end_date: date,
        alignment_open_dates: Sequence[date],
    ) -> EtfMinuteHistoryAlignmentPlan:

        if not snapshot.targets:
            raise EtfMinuteHistoryAlignmentPlanError(
                code="universe_empty",
                message="当前可请求 ETF 集合为空",
                details={"eligibility_as_of": snapshot.as_of_date.isoformat()},
            )

        alignment_targets = tuple(
            target for target in snapshot.targets if target.list_date <= alignment_end_date
        )
        desired_intervals = self._desired_intervals_by_code(
            alignment_targets,
            alignment_start_date=alignment_start_date,
            alignment_end_date=alignment_end_date,
            alignment_open_dates=alignment_open_dates,
        )
        raw_monthly_coverages: tuple[EtfMinuteRawMonthlyCoverage, ...] = ()
        successful_task_coverages: tuple[EtfMinuteSuccessfulTaskCoverage, ...] = ()
        if desired_intervals:
            raw_monthly_coverages = self._load_raw_monthly_coverages(
                session,
                earliest_alignment_date=min(
                    interval.start_date for interval in desired_intervals.values()
                ),
                alignment_end_date=alignment_end_date,
            )
            successful_task_coverages = self._load_successful_task_coverages(session)

        return self.build_plan_from_coverage(
            snapshot=snapshot,
            alignment_start_date=alignment_start_date,
            alignment_end_date=alignment_end_date,
            generated_at=generated_at,
            alignment_open_dates=alignment_open_dates,
            raw_monthly_coverages=raw_monthly_coverages,
            successful_task_coverages=successful_task_coverages,
        )

    def build_plan_from_coverage(
        self,
        *,
        snapshot: EtfRequestabilitySnapshot,
        alignment_start_date: date,
        alignment_end_date: date,
        generated_at: datetime,
        alignment_open_dates: Sequence[date],
        raw_monthly_coverages: Sequence[EtfMinuteRawMonthlyCoverage],
        successful_task_coverages: Sequence[EtfMinuteSuccessfulTaskCoverage],
    ) -> EtfMinuteHistoryAlignmentPlan:
        requestable_targets = tuple(sorted(snapshot.targets, key=lambda item: item.ts_code))
        alignment_targets = tuple(
            target for target in requestable_targets if target.list_date <= alignment_end_date
        )
        desired_by_code = self._desired_intervals_by_code(
            alignment_targets,
            alignment_start_date=alignment_start_date,
            alignment_end_date=alignment_end_date,
            alignment_open_dates=alignment_open_dates,
        )
        raw_by_pair = self._raw_intervals_by_pair(
            raw_monthly_coverages,
            desired_by_code=desired_by_code,
        )
        task_by_pair = self._task_intervals_by_pair(
            successful_task_coverages,
            desired_by_code=desired_by_code,
        )

        missing_ranges: list[tuple[str, str, date, date]] = []
        raw_pairs: set[tuple[str, str]] = set()
        task_only_pairs: set[tuple[str, str]] = set()
        prefix_pairs: set[tuple[str, str]] = set()
        suffix_pairs: set[tuple[str, str]] = set()
        for target in alignment_targets:
            desired = desired_by_code.get(target.ts_code)
            if desired is None:
                continue
            for frequency in ETF_MINUTE_FREQUENCIES:
                pair = (target.ts_code, frequency)
                raw_intervals = raw_by_pair.get(pair, ())
                task_intervals = task_by_pair.get(pair, ())
                if raw_intervals:
                    raw_pairs.add(pair)
                elif task_intervals:
                    task_only_pairs.add(pair)

                covered = self._merge_intervals((*raw_intervals, *task_intervals))
                if not covered:
                    missing_ranges.append(
                        (target.ts_code, frequency, desired.start_date, desired.end_date)
                    )
                    prefix_pairs.add(pair)
                    continue
                if covered[0].start_date > desired.start_date:
                    missing_ranges.append(
                        (
                            target.ts_code,
                            frequency,
                            desired.start_date,
                            covered[0].start_date - timedelta(days=1),
                        )
                    )
                    prefix_pairs.add(pair)
                if covered[-1].end_date < desired.end_date:
                    missing_ranges.append(
                        (
                            target.ts_code,
                            frequency,
                            covered[-1].end_date + timedelta(days=1),
                            desired.end_date,
                        )
                    )
                    suffix_pairs.add(pair)

        actions = self._build_actions(missing_ranges)
        summaries = self._build_frequency_summaries(
            actions=actions,
            raw_pairs=raw_pairs,
            task_only_pairs=task_only_pairs,
            prefix_pairs=prefix_pairs,
            suffix_pairs=suffix_pairs,
        )
        planned_unit_count = sum(action.planned_unit_count for action in actions)
        generated_at_utc = generated_at.astimezone(timezone.utc)
        base_plan = EtfMinuteHistoryAlignmentPlan(
            plan_id=f"etf-minute-alignment-{self._uuid_factory().hex}",
            plan_content_hash="",
            generated_at=generated_at_utc,
            request_target_hash=etf_minute_request_target_hash(requestable_targets),
            eligibility_as_of=snapshot.as_of_date,
            alignment_start_date=alignment_start_date,
            alignment_end_date=alignment_end_date,
            requestable_etf_count=len(requestable_targets),
            alignment_target_etf_count=len(alignment_targets),
            list_date_after_alignment_end_count=(
                len(requestable_targets) - len(alignment_targets)
            ),
            excluded_reason_counts=snapshot.excluded_reason_counts,
            frequency_summaries=summaries,
            raw_covered_target_frequency_count=len(raw_pairs),
            successful_task_only_covered_target_frequency_count=len(task_only_pairs),
            missing_prefix_target_frequency_count=len(prefix_pairs),
            missing_suffix_target_frequency_count=len(suffix_pairs),
            planned_action_count=len(actions),
            planned_unit_count=planned_unit_count,
            source_request_lower_bound=planned_unit_count,
            page_request_upper_bound=(
                planned_unit_count * _PAGE_REQUESTS_PER_UNIT_UPPER_BOUND
            ),
            interior_gap_not_audited=True,
            actions=actions,
        )
        content_hash = canonical_etf_minute_alignment_hash(
            base_plan.to_payload(include_content_hash=False)
        )
        return replace(base_plan, plan_content_hash=content_hash)

    @staticmethod
    def _validate_alignment_window(
        *,
        alignment_end_date: date,
        latest_open_date: date | None,
        alignment_open_dates: Sequence[date],
    ) -> None:
        if latest_open_date is None:
            raise EtfMinuteHistoryAlignmentPlanError(
                code="trade_calendar_not_ready",
                message="SSE 交易日历尚未提供最近开市日",
            )
        if alignment_end_date > latest_open_date:
            raise EtfMinuteHistoryAlignmentPlanError(
                code="alignment_end_date_after_latest_open",
                message="对齐截止日晚于当前最近 SSE 开市日",
                details={"latest_open_date": latest_open_date.isoformat()},
            )
        if alignment_end_date not in alignment_open_dates:
            raise EtfMinuteHistoryAlignmentPlanError(
                code="alignment_end_date_not_open",
                message="对齐截止日不是 SSE 开市日",
                details={"alignment_end_date": alignment_end_date.isoformat()},
            )

    @staticmethod
    def _load_raw_monthly_coverages(
        session: Session,
        *,
        earliest_alignment_date: date,
        alignment_end_date: date,
    ) -> tuple[EtfMinuteRawMonthlyCoverage, ...]:
        coverages: list[EtfMinuteRawMonthlyCoverage] = []
        for month_start in EtfMinuteHistoryAlignmentPlanService._month_starts(
            earliest_alignment_date,
            alignment_end_date,
        ):
            next_month_start = (
                EtfMinuteHistoryAlignmentPlanService._next_month_start(month_start)
            )
            rows = session.execute(
                _RAW_MONTHLY_COVERAGE_SQL,
                {
                    "month_start": month_start,
                    "next_month_start": next_month_start,
                },
            ).mappings()
            for row in rows:
                min_trade_time = row["min_trade_time"]
                max_trade_time = row["max_trade_time"]
                row_count = int(row["row_count"] or 0)
                if row_count <= 0 or min_trade_time is None or max_trade_time is None:
                    continue
                coverages.append(
                    EtfMinuteRawMonthlyCoverage(
                        ts_code=str(row["ts_code"]),
                        frequency=str(row["freq"]),
                        month_start=month_start,
                        row_count=row_count,
                        start_date=EtfMinuteHistoryAlignmentPlanService._coerce_date(
                            min_trade_time
                        ),
                        end_date=EtfMinuteHistoryAlignmentPlanService._coerce_date(
                            max_trade_time
                        ),
                    )
                )
        return tuple(coverages)

    @staticmethod
    def _load_successful_task_coverages(
        session: Session,
    ) -> tuple[EtfMinuteSuccessfulTaskCoverage, ...]:
        rows = session.execute(
            select(TaskRun.filters_json, TaskRun.time_input_json)
            .where(TaskRun.resource_key == "etf_mins")
            .where(TaskRun.status == "success")
            .order_by(TaskRun.id)
        ).all()
        coverages: list[EtfMinuteSuccessfulTaskCoverage] = []
        for filters_json, time_input_json in rows:
            parsed = EtfMinuteHistoryAlignmentPlanService._parse_task_coverage(
                filters_json=filters_json,
                time_input_json=time_input_json,
            )
            coverages.extend(parsed)
        return tuple(coverages)

    @staticmethod
    def _parse_task_coverage(
        *,
        filters_json: Any,
        time_input_json: Any,
    ) -> tuple[EtfMinuteSuccessfulTaskCoverage, ...]:
        if not isinstance(filters_json, dict) or not isinstance(time_input_json, dict):
            return ()
        ts_code_value = filters_json.get("ts_code")
        if isinstance(ts_code_value, str):
            raw_ts_codes = (ts_code_value,)
        elif (
            isinstance(ts_code_value, list)
            and ts_code_value
            and all(isinstance(value, str) and value.strip() for value in ts_code_value)
        ):
            raw_ts_codes = tuple(ts_code_value)
        else:
            return ()
        ts_codes = tuple(
            sorted({value.strip().upper() for value in raw_ts_codes if value.strip()})
        )
        if not ts_codes:
            return ()
        frequency_values = filters_json.get("freq")
        if not isinstance(frequency_values, list) or not frequency_values:
            return ()
        if any(
            not isinstance(value, str) or value not in _FREQUENCY_ORDER
            for value in frequency_values
        ):
            return ()
        frequencies = tuple(
            frequency
            for frequency in ETF_MINUTE_FREQUENCIES
            if frequency in set(frequency_values)
        )

        mode = time_input_json.get("mode")
        if mode == "point":
            trade_date = EtfMinuteHistoryAlignmentPlanService._parse_iso_date(
                time_input_json.get("trade_date")
            )
            if trade_date is None:
                return ()
            start_date = trade_date
            end_date = trade_date
        elif mode == "range":
            start_date = EtfMinuteHistoryAlignmentPlanService._parse_iso_date(
                time_input_json.get("start_date")
            )
            end_date = EtfMinuteHistoryAlignmentPlanService._parse_iso_date(
                time_input_json.get("end_date")
            )
            if start_date is None or end_date is None or start_date > end_date:
                return ()
        else:
            return ()

        return tuple(
            EtfMinuteSuccessfulTaskCoverage(
                ts_code=ts_code,
                frequency=frequency,
                start_date=start_date,
                end_date=end_date,
            )
            for ts_code in ts_codes
            for frequency in frequencies
        )

    @staticmethod
    def _raw_intervals_by_pair(
        boundaries: Sequence[EtfMinuteRawMonthlyCoverage],
        *,
        desired_by_code: Mapping[str, EtfMinuteAlignmentInterval],
    ) -> Mapping[tuple[str, str], tuple[EtfMinuteAlignmentInterval, ...]]:
        intervals: defaultdict[tuple[str, str], list[EtfMinuteAlignmentInterval]] = (
            defaultdict(list)
        )
        for boundary in boundaries:
            desired = desired_by_code.get(boundary.ts_code)
            if desired is None or boundary.frequency not in _FREQUENCY_ORDER:
                continue
            clipped = EtfMinuteHistoryAlignmentPlanService._intersect_interval(
                EtfMinuteAlignmentInterval(boundary.start_date, boundary.end_date),
                desired,
            )
            if clipped is not None:
                intervals[(boundary.ts_code, boundary.frequency)].append(clipped)
        return {
            pair: EtfMinuteHistoryAlignmentPlanService._merge_intervals(values)
            for pair, values in intervals.items()
        }

    @staticmethod
    def _task_intervals_by_pair(
        coverages: Sequence[EtfMinuteSuccessfulTaskCoverage],
        *,
        desired_by_code: Mapping[str, EtfMinuteAlignmentInterval],
    ) -> Mapping[tuple[str, str], tuple[EtfMinuteAlignmentInterval, ...]]:
        intervals: defaultdict[tuple[str, str], list[EtfMinuteAlignmentInterval]] = (
            defaultdict(list)
        )
        for coverage in coverages:
            desired = desired_by_code.get(coverage.ts_code)
            if desired is None or coverage.frequency not in _FREQUENCY_ORDER:
                continue
            clipped = EtfMinuteHistoryAlignmentPlanService._intersect_interval(
                EtfMinuteAlignmentInterval(coverage.start_date, coverage.end_date),
                desired,
            )
            if clipped is not None:
                intervals[(coverage.ts_code, coverage.frequency)].append(clipped)
        return {
            pair: EtfMinuteHistoryAlignmentPlanService._merge_intervals(values)
            for pair, values in intervals.items()
        }

    @staticmethod
    def _intersect_interval(
        left: EtfMinuteAlignmentInterval,
        right: EtfMinuteAlignmentInterval,
    ) -> EtfMinuteAlignmentInterval | None:
        start_date = max(left.start_date, right.start_date)
        end_date = min(left.end_date, right.end_date)
        if start_date > end_date:
            return None
        return EtfMinuteAlignmentInterval(start_date, end_date)

    @staticmethod
    def _merge_intervals(
        intervals: Iterable[EtfMinuteAlignmentInterval],
    ) -> tuple[EtfMinuteAlignmentInterval, ...]:
        ordered = sorted(intervals, key=lambda item: (item.start_date, item.end_date))
        if not ordered:
            return ()
        merged = [ordered[0]]
        for interval in ordered[1:]:
            previous = merged[-1]
            if interval.start_date <= previous.end_date + timedelta(days=1):
                merged[-1] = EtfMinuteAlignmentInterval(
                    previous.start_date,
                    max(previous.end_date, interval.end_date),
                )
            else:
                merged.append(interval)
        return tuple(merged)

    @staticmethod
    def _build_actions(
        missing_ranges: Sequence[tuple[str, str, date, date]],
    ) -> tuple[EtfMinuteHistoryAlignmentAction, ...]:
        grouped: defaultdict[tuple[str, date, date], set[str]] = defaultdict(set)
        for ts_code, frequency, start_date, end_date in missing_ranges:
            grouped[(ts_code, start_date, end_date)].add(frequency)

        actions: list[EtfMinuteHistoryAlignmentAction] = []
        for (ts_code, start_date, end_date), frequency_set in grouped.items():
            frequencies = tuple(
                frequency
                for frequency in ETF_MINUTE_FREQUENCIES
                if frequency in frequency_set
            )
            planned_unit_count = sum(
                len(
                    build_etf_minute_windows(
                        freq=frequency,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
                for frequency in frequencies
            )
            actions.append(
                EtfMinuteHistoryAlignmentAction(
                    ts_code=ts_code,
                    frequencies=frequencies,
                    start_date=start_date,
                    end_date=end_date,
                    planned_unit_count=planned_unit_count,
                )
            )
        return tuple(
            sorted(
                actions,
                key=lambda item: (
                    item.ts_code,
                    item.start_date,
                    item.end_date,
                    tuple(_FREQUENCY_ORDER[freq] for freq in item.frequencies),
                ),
            )
        )

    @staticmethod
    def _build_frequency_summaries(
        *,
        actions: Sequence[EtfMinuteHistoryAlignmentAction],
        raw_pairs: set[tuple[str, str]],
        task_only_pairs: set[tuple[str, str]],
        prefix_pairs: set[tuple[str, str]],
        suffix_pairs: set[tuple[str, str]],
    ) -> tuple[EtfMinuteHistoryAlignmentFrequencySummary, ...]:
        summaries: list[EtfMinuteHistoryAlignmentFrequencySummary] = []
        for frequency in ETF_MINUTE_FREQUENCIES:
            matching_actions = [
                action for action in actions if frequency in action.frequencies
            ]
            unit_count = sum(
                len(
                    build_etf_minute_windows(
                        freq=frequency,
                        start_date=action.start_date,
                        end_date=action.end_date,
                    )
                )
                for action in matching_actions
            )
            summaries.append(
                EtfMinuteHistoryAlignmentFrequencySummary(
                    frequency=frequency,
                    action_count=len(matching_actions),
                    planned_unit_count=unit_count,
                    source_request_lower_bound=unit_count,
                    page_request_upper_bound=(
                        unit_count * _PAGE_REQUESTS_PER_UNIT_UPPER_BOUND
                    ),
                    raw_covered_target_count=sum(
                        pair[1] == frequency for pair in raw_pairs
                    ),
                    successful_task_only_covered_target_count=sum(
                        pair[1] == frequency for pair in task_only_pairs
                    ),
                    missing_prefix_target_count=sum(
                        pair[1] == frequency for pair in prefix_pairs
                    ),
                    missing_suffix_target_count=sum(
                        pair[1] == frequency for pair in suffix_pairs
                    ),
                )
            )
        return tuple(summaries)

    @staticmethod
    def _desired_intervals_by_code(
        targets: Sequence[EtfRequestTarget],
        *,
        alignment_start_date: date,
        alignment_end_date: date,
        alignment_open_dates: Sequence[date],
    ) -> Mapping[str, EtfMinuteAlignmentInterval]:
        ordered_open_dates = tuple(
            sorted(
                {
                    open_date
                    for open_date in alignment_open_dates
                    if alignment_start_date <= open_date <= alignment_end_date
                }
            )
        )
        intervals: dict[str, EtfMinuteAlignmentInterval] = {}
        for target in targets:
            minimum_start = max(alignment_start_date, target.list_date)
            open_date_index = bisect_left(ordered_open_dates, minimum_start)
            if open_date_index >= len(ordered_open_dates):
                continue
            intervals[target.ts_code] = EtfMinuteAlignmentInterval(
                ordered_open_dates[open_date_index],
                alignment_end_date,
            )
        return intervals

    @staticmethod
    def _month_starts(start_date: date, end_date: date) -> tuple[date, ...]:
        if start_date > end_date:
            return ()
        end_month = date(end_date.year, end_date.month, 1)
        cursor = date(start_date.year, start_date.month, 1)
        months: list[date] = []
        while cursor <= end_month:
            months.append(cursor)
            cursor = EtfMinuteHistoryAlignmentPlanService._next_month_start(cursor)
        return tuple(months)

    @staticmethod
    def _next_month_start(month_start: date) -> date:
        if month_start.month == 12:
            return date(month_start.year + 1, 1, 1)
        return date(month_start.year, month_start.month + 1, 1)

    @staticmethod
    def _parse_iso_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return None
        if isinstance(value, date):
            return value
        if not isinstance(value, str) or not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _coerce_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))
