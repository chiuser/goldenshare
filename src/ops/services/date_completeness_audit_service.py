from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
import re

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_exclusion import DatasetDateCompletenessExclusion
from src.ops.models.ops.dataset_date_completeness_gap import DatasetDateCompletenessGap
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun


@dataclass(frozen=True, slots=True)
class DateCompletenessBucket:
    bucket_kind: str
    value: date
    label: str


@dataclass(frozen=True, slots=True)
class DateCompletenessGap:
    bucket_kind: str
    range_start: date
    range_end: date
    missing_count: int
    sample_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DateCompletenessExcludedBucket:
    bucket_kind: str
    bucket_value: date
    window_start: date
    window_end: date
    reason_code: str
    reason_message: str


class ExpectedBucketPlanner:
    def plan(
        self,
        *,
        date_axis: str,
        bucket_rule: str,
        start_date: date,
        end_date: date,
        open_trade_dates: list[date] | None = None,
        bucket_window_rule: str | None = None,
        bucket_applicability_rule: str = "always",
    ) -> list[DateCompletenessBucket]:
        expected, _excluded = self.plan_with_exclusions(
            date_axis=date_axis,
            bucket_rule=bucket_rule,
            start_date=start_date,
            end_date=end_date,
            open_trade_dates=open_trade_dates,
            bucket_window_rule=bucket_window_rule,
            bucket_applicability_rule=bucket_applicability_rule,
        )
        return expected

    def plan_with_exclusions(
        self,
        *,
        date_axis: str,
        bucket_rule: str,
        start_date: date,
        end_date: date,
        open_trade_dates: list[date] | None = None,
        bucket_window_rule: str | None = None,
        bucket_applicability_rule: str = "always",
    ) -> tuple[list[DateCompletenessBucket], list[DateCompletenessExcludedBucket]]:
        if start_date > end_date:
            raise ValueError("审计开始日期不能晚于结束日期")
        if bucket_rule == "not_applicable" or date_axis == "none":
            return [], []
        if date_axis == "trade_open_day":
            buckets = self._trade_open_day_buckets(
                bucket_rule=bucket_rule,
                start_date=start_date,
                end_date=end_date,
                open_trade_dates=open_trade_dates or [],
            )
        elif date_axis == "natural_day" and bucket_rule == "every_natural_day":
            buckets = [
                DateCompletenessBucket(bucket_kind="natural_date", value=value, label=value.isoformat())
                for value in self._natural_days(start_date, end_date)
            ]
        elif date_axis == "natural_day" and bucket_rule == "week_friday":
            buckets = [
                DateCompletenessBucket(bucket_kind="natural_date", value=value, label=value.isoformat())
                for value in self._calendar_week_fridays(start_date, end_date)
            ]
        elif date_axis == "natural_day" and bucket_rule == "month_last_calendar_day":
            buckets = [
                DateCompletenessBucket(bucket_kind="natural_date", value=value, label=value.isoformat())
                for value in self._calendar_month_ends(start_date, end_date)
            ]
        elif date_axis == "month_key" and bucket_rule == "every_natural_month":
            buckets = [
                DateCompletenessBucket(bucket_kind="month_key", value=value, label=value.strftime("%Y%m"))
                for value in self._month_starts(start_date, end_date)
            ]
        elif date_axis == "month_window" and bucket_rule == "month_window_has_data":
            buckets = [
                DateCompletenessBucket(bucket_kind="month_window", value=value, label=value.strftime("%Y-%m"))
                for value in self._month_starts(start_date, end_date)
            ]
        else:
            raise ValueError(f"不支持的日期完整性规则：{date_axis}/{bucket_rule}")
        return self._apply_bucket_applicability(
            buckets=buckets,
            open_trade_dates=open_trade_dates or [],
            bucket_window_rule=bucket_window_rule,
            bucket_applicability_rule=bucket_applicability_rule,
        )

    def _trade_open_day_buckets(
        self,
        *,
        bucket_rule: str,
        start_date: date,
        end_date: date,
        open_trade_dates: list[date],
    ) -> list[DateCompletenessBucket]:
        dates = sorted({value for value in open_trade_dates if start_date <= value <= end_date})
        if bucket_rule == "every_open_day":
            selected = dates
        elif bucket_rule == "week_last_open_day":
            selected = self._last_open_day_by_bucket(dates, bucket="week")
        elif bucket_rule == "month_last_open_day":
            selected = self._last_open_day_by_bucket(dates, bucket="month")
        else:
            raise ValueError(f"不支持的交易日审计规则：{bucket_rule}")
        return [
            DateCompletenessBucket(bucket_kind="trade_date", value=value, label=value.isoformat())
            for value in selected
        ]

    @staticmethod
    def _natural_days(start_date: date, end_date: date) -> list[date]:
        days: list[date] = []
        current = start_date
        while current <= end_date:
            days.append(current)
            current += timedelta(days=1)
        return days

    @staticmethod
    def _month_starts(start_date: date, end_date: date) -> list[date]:
        current = date(start_date.year, start_date.month, 1)
        final = date(end_date.year, end_date.month, 1)
        months: list[date] = []
        while current <= final:
            months.append(current)
            next_month_day = monthrange(current.year, current.month)[1] + 1
            current = (current + timedelta(days=next_month_day)).replace(day=1)
        return months

    @staticmethod
    def _calendar_week_fridays(start_date: date, end_date: date) -> list[date]:
        days_until_friday = (4 - start_date.weekday()) % 7
        current = start_date + timedelta(days=days_until_friday)
        dates: list[date] = []
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=7)
        return dates

    @staticmethod
    def _calendar_month_ends(start_date: date, end_date: date) -> list[date]:
        current = date(
            start_date.year,
            start_date.month,
            monthrange(start_date.year, start_date.month)[1],
        )
        dates: list[date] = []
        while current <= end_date:
            if current >= start_date:
                dates.append(current)
            next_month = date(
                current.year + (1 if current.month == 12 else 0),
                1 if current.month == 12 else current.month + 1,
                1,
            )
            current = date(
                next_month.year,
                next_month.month,
                monthrange(next_month.year, next_month.month)[1],
            )
        return dates

    @staticmethod
    def _last_open_day_by_bucket(open_trade_dates: list[date], *, bucket: str) -> list[date]:
        grouped: dict[tuple[int, int], date] = {}
        for value in open_trade_dates:
            key = value.isocalendar()[:2] if bucket == "week" else (value.year, value.month)
            current = grouped.get(key)
            if current is None or value > current:
                grouped[key] = value
        return sorted(grouped.values())

    def _apply_bucket_applicability(
        self,
        *,
        buckets: list[DateCompletenessBucket],
        open_trade_dates: list[date],
        bucket_window_rule: str | None,
        bucket_applicability_rule: str,
    ) -> tuple[list[DateCompletenessBucket], list[DateCompletenessExcludedBucket]]:
        if bucket_applicability_rule == "always":
            return buckets, []
        if bucket_applicability_rule != "requires_open_trade_day_in_bucket":
            raise ValueError(f"不支持的日期桶可产出规则：{bucket_applicability_rule}")

        open_date_set = set(open_trade_dates)
        expected: list[DateCompletenessBucket] = []
        excluded: list[DateCompletenessExcludedBucket] = []
        for bucket in buckets:
            window_start, window_end = self._bucket_window(bucket.value, bucket_window_rule)
            if any(window_start <= open_date <= window_end for open_date in open_date_set):
                expected.append(bucket)
                continue
            excluded.append(
                DateCompletenessExcludedBucket(
                    bucket_kind=bucket.bucket_kind,
                    bucket_value=bucket.value,
                    window_start=window_start,
                    window_end=window_end,
                    reason_code="bucket_has_no_open_trade_day",
                    reason_message=self._exclusion_reason_message(bucket_window_rule),
                )
            )
        return expected, excluded

    @staticmethod
    def _bucket_window(bucket_value: date, bucket_window_rule: str | None) -> tuple[date, date]:
        if bucket_window_rule == "iso_week":
            window_start = bucket_value - timedelta(days=bucket_value.weekday())
            return window_start, window_start + timedelta(days=6)
        if bucket_window_rule == "natural_month":
            window_start = date(bucket_value.year, bucket_value.month, 1)
            return window_start, date(bucket_value.year, bucket_value.month, monthrange(bucket_value.year, bucket_value.month)[1])
        raise ValueError(f"不支持的日期桶窗口规则：{bucket_window_rule}")

    @staticmethod
    def _exclusion_reason_message(bucket_window_rule: str | None) -> str:
        if bucket_window_rule == "iso_week":
            return "该自然周内没有开市交易日，不应产出周线数据。"
        if bucket_window_rule == "natural_month":
            return "该自然月内没有开市交易日，不应产出月线数据。"
        return "该日期桶对应窗口内没有开市交易日，不应产出数据。"


class GapDetector:
    def detect(
        self,
        *,
        expected_buckets: list[DateCompletenessBucket],
        actual_bucket_values: set[date],
    ) -> list[DateCompletenessGap]:
        missing_indexes = [
            index
            for index, bucket in enumerate(expected_buckets)
            if bucket.value not in actual_bucket_values
        ]
        if not missing_indexes:
            return []

        gaps: list[DateCompletenessGap] = []
        current_group: list[int] = []
        for index in missing_indexes:
            if current_group and index != current_group[-1] + 1:
                gaps.append(self._to_gap(expected_buckets, current_group))
                current_group = []
            current_group.append(index)
        if current_group:
            gaps.append(self._to_gap(expected_buckets, current_group))
        return gaps

    @staticmethod
    def _to_gap(expected_buckets: list[DateCompletenessBucket], indexes: list[int]) -> DateCompletenessGap:
        buckets = [expected_buckets[index] for index in indexes]
        return DateCompletenessGap(
            bucket_kind=buckets[0].bucket_kind,
            range_start=buckets[0].value,
            range_end=buckets[-1].value,
            missing_count=len(buckets),
            sample_values=tuple(bucket.label for bucket in buckets[:20]),
        )


class ActualBucketReader:
    SQL_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
    SQL_COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def read(
        self,
        session: Session,
        *,
        target_table: str,
        observed_field: str,
        date_axis: str,
        start_date: date,
        end_date: date,
        row_identity_filters: dict | None = None,
    ) -> set[date]:
        table_sql = self._sql_table_identifier(target_table)
        field_sql = self._sql_column_identifier(observed_field)
        filter_sql, filter_params = self._row_identity_filter_clause(row_identity_filters or {})
        if date_axis == "month_key":
            rows = session.execute(
                text(
                    f"""
                    select distinct {field_sql} as bucket_value
                    from {table_sql}
                    where {field_sql} between :start_month and :end_month
                    {filter_sql}
                    """
                ),
                {
                    "start_month": start_date.strftime("%Y%m"),
                    "end_month": end_date.strftime("%Y%m"),
                    **filter_params,
                },
            ).all()
            return {self._month_key_to_date(row.bucket_value) for row in rows if row.bucket_value is not None}

        rows = session.execute(
            text(
                f"""
                select distinct {field_sql} as bucket_value
                from {table_sql}
                where {field_sql} between :start_date and :end_date
                {filter_sql}
                """
            ),
            {"start_date": start_date, "end_date": end_date, **filter_params},
        ).all()
        values = {self._value_to_date(row.bucket_value) for row in rows if row.bucket_value is not None}
        if date_axis == "month_window":
            return {date(value.year, value.month, 1) for value in values}
        return values

    def _row_identity_filter_clause(self, filters: dict) -> tuple[str, dict[str, object]]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        for index, key in enumerate(sorted(filters)):
            column_sql = self._sql_column_identifier(str(key))
            value = filters[key]
            if not isinstance(value, (str, int, bool)):
                raise ValueError(f"审计实际桶过滤值无效：{key}={value!r}")
            param_key = f"row_identity_filter_{index}"
            clauses.append(f"and {column_sql} = :{param_key}")
            params[param_key] = value
        if not clauses:
            return "", {}
        return "\n                    " + "\n                    ".join(clauses), params

    @classmethod
    def _sql_table_identifier(cls, value: str) -> str:
        if not cls.SQL_IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(f"审计目标表标识符无效：{value!r}")
        return value

    @classmethod
    def _sql_column_identifier(cls, value: str) -> str:
        if not cls.SQL_COLUMN_PATTERN.fullmatch(value):
            raise ValueError(f"审计观测字段标识符无效：{value!r}")
        return value

    @staticmethod
    def _value_to_date(value: object) -> date:
        if isinstance(value, date):
            return value
        text_value = str(value).strip()
        if len(text_value) >= 10 and text_value[4] == "-" and text_value[7] == "-":
            return date.fromisoformat(text_value[:10])
        if len(text_value) == 8 and text_value.isdigit():
            return date(int(text_value[:4]), int(text_value[4:6]), int(text_value[6:8]))
        raise ValueError(f"无法识别审计日期值：{value!r}")

    @staticmethod
    def _month_key_to_date(value: object) -> date:
        text_value = str(value).strip()
        if len(text_value) != 6 or not text_value.isdigit():
            raise ValueError(f"无法识别审计月份值：{value!r}")
        return date(int(text_value[:4]), int(text_value[4:6]), 1)


class DateCompletenessAuditExecutor:
    def execute_run(self, session: Session, run_id: int) -> DatasetDateCompletenessRun:
        run = session.get(DatasetDateCompletenessRun, run_id)
        if run is None:
            raise ValueError(f"日期完整性审计记录不存在：{run_id}")
        if run.run_status not in {"queued", "running"}:
            return run

        try:
            self._mark_running(session, run)
            open_trade_dates = self._load_open_trade_dates(session, run=run)
            expected, excluded = ExpectedBucketPlanner().plan_with_exclusions(
                date_axis=run.date_axis,
                bucket_rule=run.bucket_rule,
                start_date=run.start_date,
                end_date=run.end_date,
                open_trade_dates=open_trade_dates,
                bucket_window_rule=run.bucket_window_rule,
                bucket_applicability_rule=run.bucket_applicability_rule,
            )
            run.current_stage = "reading_actual"
            session.commit()

            actual = ActualBucketReader().read(
                session,
                target_table=run.target_table,
                observed_field=run.observed_field,
                date_axis=run.date_axis,
                start_date=run.start_date,
                end_date=run.end_date,
                row_identity_filters=run.row_identity_filters_json,
            )
            gaps = GapDetector().detect(expected_buckets=expected, actual_bucket_values=actual)
            self._mark_succeeded(session, run, expected=expected, actual=actual, gaps=gaps, excluded=excluded)
            return run
        except Exception as exc:
            session.rollback()
            self._mark_error(session, run_id=run_id, error=exc)
            failed = session.get(DatasetDateCompletenessRun, run_id)
            if failed is None:
                raise
            return failed

    def run_next(self, session: Session) -> DatasetDateCompletenessRun | None:
        run = session.scalar(
            select(DatasetDateCompletenessRun)
            .where(DatasetDateCompletenessRun.run_status == "queued")
            .order_by(DatasetDateCompletenessRun.requested_at.asc(), DatasetDateCompletenessRun.id.asc())
            .limit(1)
        )
        if run is None:
            return None
        return self.execute_run(session, run.id)

    @staticmethod
    def _mark_running(session: Session, run: DatasetDateCompletenessRun) -> None:
        run.run_status = "running"
        run.result_status = None
        run.current_stage = "planning"
        run.operator_message = "正在生成期望日期桶。"
        run.started_at = run.started_at or _utcnow()
        session.commit()
        session.refresh(run)

    @staticmethod
    def _load_open_trade_dates(session: Session, *, run: DatasetDateCompletenessRun) -> list[date] | None:
        needs_open_dates = run.date_axis == "trade_open_day" or run.bucket_applicability_rule == "requires_open_trade_day_in_bucket"
        if not needs_open_dates:
            return None
        exchange = get_settings().default_exchange
        start_date, end_date = DateCompletenessAuditExecutor._trade_calendar_range(run)
        return list(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(TradeCalendar.exchange == exchange)
                .where(TradeCalendar.trade_date >= start_date)
                .where(TradeCalendar.trade_date <= end_date)
                .where(TradeCalendar.is_open.is_(True))
                .order_by(TradeCalendar.trade_date.asc())
            )
        )

    @staticmethod
    def _trade_calendar_range(run: DatasetDateCompletenessRun) -> tuple[date, date]:
        if run.bucket_window_rule == "iso_week":
            start_date = run.start_date - timedelta(days=run.start_date.weekday())
            end_date = run.end_date + timedelta(days=6 - run.end_date.weekday())
            return start_date, end_date
        if run.bucket_window_rule == "natural_month":
            start_date = date(run.start_date.year, run.start_date.month, 1)
            end_date = date(run.end_date.year, run.end_date.month, monthrange(run.end_date.year, run.end_date.month)[1])
            return start_date, end_date
        return run.start_date, run.end_date

    @staticmethod
    def _mark_succeeded(
        session: Session,
        run: DatasetDateCompletenessRun,
        *,
        expected: list[DateCompletenessBucket],
        actual: set[date],
        gaps: list[DateCompletenessGap],
        excluded: list[DateCompletenessExcludedBucket],
    ) -> None:
        session.execute(delete(DatasetDateCompletenessGap).where(DatasetDateCompletenessGap.run_id == run.id))
        session.execute(delete(DatasetDateCompletenessExclusion).where(DatasetDateCompletenessExclusion.run_id == run.id))
        for gap in gaps:
            session.add(
                DatasetDateCompletenessGap(
                    run_id=run.id,
                    dataset_key=run.dataset_key,
                    bucket_kind=gap.bucket_kind,
                    range_start=gap.range_start,
                    range_end=gap.range_end,
                    missing_count=gap.missing_count,
                    sample_values_json=list(gap.sample_values),
                )
            )
        for item in excluded:
            session.add(
                DatasetDateCompletenessExclusion(
                    run_id=run.id,
                    dataset_key=run.dataset_key,
                    bucket_kind=item.bucket_kind,
                    bucket_value=item.bucket_value,
                    window_start=item.window_start,
                    window_end=item.window_end,
                    reason_code=item.reason_code,
                    reason_message=item.reason_message,
                )
            )

        run.run_status = "succeeded"
        run.result_status = "failed" if gaps else "passed"
        run.current_stage = "finished"
        run.expected_bucket_count = len(expected)
        run.actual_bucket_count = len(actual)
        run.missing_bucket_count = sum(gap.missing_count for gap in gaps)
        run.excluded_bucket_count = len(excluded)
        run.gap_range_count = len(gaps)
        if gaps:
            run.operator_message = "审计发现日期缺口。"
        elif excluded:
            run.operator_message = f"审计通过，已按规则排除 {len(excluded)} 个不可产出日期桶。"
        else:
            run.operator_message = "审计通过，未发现日期缺口。"
        run.technical_message = None
        run.finished_at = _utcnow()
        session.commit()
        session.refresh(run)

    @staticmethod
    def _mark_error(session: Session, *, run_id: int, error: Exception) -> None:
        run = session.get(DatasetDateCompletenessRun, run_id)
        if run is None:
            return
        run.run_status = "failed"
        run.result_status = "error"
        run.current_stage = "error"
        run.operator_message = "审计执行失败，请查看技术诊断。"
        run.technical_message = str(error)
        run.finished_at = _utcnow()
        session.commit()


class DateCompletenessAuditWorker:
    def run_next(self, session: Session) -> DatasetDateCompletenessRun | None:
        return DateCompletenessAuditExecutor().run_next(session)


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
