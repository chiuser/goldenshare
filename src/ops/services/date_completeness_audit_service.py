from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
import re

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.datasets.models import DatasetCompletenessDefinition, DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_exclusion import DatasetDateCompletenessExclusion
from src.ops.models.ops.dataset_date_completeness_gap import DatasetDateCompletenessGap
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.dataset_subject_completeness_gap import DatasetSubjectCompletenessGap
from src.ops.models.ops.dataset_subject_completeness_gap_detail import DatasetSubjectCompletenessGapDetail


DATE_SUBJECT_MATRIX_SAFE_BUCKET_LIMIT = 400


class DateSubjectMatrixRangeTooLargeError(ValueError):
    def __init__(self, *, expected_bucket_count: int) -> None:
        self.expected_bucket_count = expected_bucket_count
        self.operator_message = (
            "对象矩阵审计范围超过当前单次安全上限，已停止执行。请缩小日期范围后再运行。"
        )
        super().__init__(
            "date_subject_matrix range contains "
            f"{expected_bucket_count} buckets, limit is {DATE_SUBJECT_MATRIX_SAFE_BUCKET_LIMIT}"
        )


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


@dataclass(frozen=True, slots=True)
class SubjectCompletenessGapSummary:
    bucket_kind: str
    bucket_value: date
    subject_kind: str
    missing_cell_count: int
    affected_subject_count: int
    sample_subjects: tuple[dict[str, str | None], ...]


@dataclass(frozen=True, slots=True)
class SubjectCompletenessGapDetail:
    bucket_kind: str
    bucket_value: date
    subject_kind: str
    subject_key: str
    subject_name: str | None
    subject_key_json: dict[str, str]
    actual_key_json: dict[str, str]
    lifecycle_start: date | None
    lifecycle_end: date | None
    reason_code: str
    reason_message: str
    target_table: str


@dataclass(frozen=True, slots=True)
class SubjectCompletenessMatrixResult:
    subject_key_fields: tuple[str, ...]
    actual_key_fields: tuple[str, ...]
    expected_cell_count: int
    actual_cell_count: int
    missing_cell_count: int
    affected_bucket_count: int
    affected_subject_count: int
    actual_bucket_count: int
    gap_summaries: tuple[SubjectCompletenessGapSummary, ...]
    details: tuple[SubjectCompletenessGapDetail, ...]
    detail_truncated: bool


@dataclass(frozen=True, slots=True)
class SubjectCompletenessBucketResult:
    expected_cell_count: int
    actual_cell_count: int
    missing_cell_count: int
    missing_subject_keys: tuple[str, ...]
    detail_count: int


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


class SubjectCompletenessMatrixExecutor:
    DETAIL_LIMIT = 5000
    PROGRESS_COMMIT_INTERVAL = 1
    STATEMENT_TIMEOUT_SQL = "set local statement_timeout = '60s'"
    SQL_IDENTIFIER_PATTERN = ActualBucketReader.SQL_IDENTIFIER_PATTERN
    SQL_COLUMN_PATTERN = ActualBucketReader.SQL_COLUMN_PATTERN

    def execute(
        self,
        session: Session,
        *,
        run: DatasetDateCompletenessRun,
        definition: DatasetDefinition,
        expected_buckets: list[DateCompletenessBucket],
    ) -> SubjectCompletenessMatrixResult:
        completeness = definition.completeness
        self._validate_supported(run=run, completeness=completeness)
        self._clear_existing_result_rows(session, run)
        if not expected_buckets:
            return self._empty_result(actual_bucket_count=0)

        context = self._build_bucket_context(run=run, completeness=completeness)
        expected_cell_count = 0
        actual_cell_count = 0
        missing_cell_count = 0
        affected_bucket_count = 0
        actual_bucket_count = 0
        affected_subject_keys: set[str] = set()
        written_detail_count = 0
        detail_truncated = False

        for index, bucket in enumerate(expected_buckets, start=1):
            self._mark_bucket_started(
                session,
                run=run,
                bucket=bucket,
                processed_bucket_count=index - 1,
                total_bucket_count=len(expected_buckets),
            )
            bucket_result = self._execute_bucket(
                session,
                run=run,
                completeness=completeness,
                context=context,
                bucket=bucket,
                detail_remaining=max(self.DETAIL_LIMIT - written_detail_count, 0),
            )
            expected_cell_count += bucket_result.expected_cell_count
            actual_cell_count += bucket_result.actual_cell_count
            missing_cell_count += bucket_result.missing_cell_count
            if bucket_result.missing_cell_count:
                affected_bucket_count += 1
            if bucket_result.actual_cell_count:
                actual_bucket_count += 1
            affected_subject_keys.update(bucket_result.missing_subject_keys)
            written_detail_count += bucket_result.detail_count
            if bucket_result.detail_count < bucket_result.missing_cell_count:
                detail_truncated = True
            if index % self.PROGRESS_COMMIT_INTERVAL == 0 or index == len(expected_buckets):
                self._mark_bucket_completed(
                    session,
                    run=run,
                    bucket=bucket,
                    processed_bucket_count=index,
                    total_bucket_count=len(expected_buckets),
                    expected_cell_count=expected_cell_count,
                    actual_cell_count=actual_cell_count,
                    missing_cell_count=missing_cell_count,
                    affected_bucket_count=affected_bucket_count,
                    affected_subject_count=len(affected_subject_keys),
                    actual_bucket_count=actual_bucket_count,
                    detail_truncated=detail_truncated,
                )

        return SubjectCompletenessMatrixResult(
            subject_key_fields=tuple(completeness.subject_key_fields),
            actual_key_fields=tuple(dict.fromkeys((*completeness.actual_key_fields, run.observed_field))),
            expected_cell_count=expected_cell_count,
            actual_cell_count=actual_cell_count,
            missing_cell_count=missing_cell_count,
            affected_bucket_count=affected_bucket_count,
            affected_subject_count=len(affected_subject_keys),
            actual_bucket_count=actual_bucket_count,
            gap_summaries=(),
            details=(),
            detail_truncated=detail_truncated,
        )

    @classmethod
    def _validate_supported(cls, *, run: DatasetDateCompletenessRun, completeness: DatasetCompletenessDefinition) -> None:
        if completeness.scope != "date_subject_matrix":
            raise ValueError(f"数据集 {run.dataset_key} 未配置对象矩阵完整性审计")
        if completeness.universe_strategy != "stock_basic_active_lifecycle":
            raise ValueError(f"暂不支持的对象池策略：{completeness.universe_strategy}")
        if completeness.subject_kind != "stock":
            raise ValueError(f"暂不支持的对象类型：{completeness.subject_kind}")
        if len(completeness.subject_key_fields) != 1 or len(completeness.actual_key_fields) != 1:
            raise ValueError("对象矩阵审计第一期只支持单字段对象键")
        required_columns = [
            completeness.universe_key_field,
            completeness.universe_name_field,
            completeness.lifecycle_start_field,
            completeness.lifecycle_end_field,
            completeness.status_field,
            *completeness.subject_key_fields,
            *completeness.actual_key_fields,
            run.observed_field,
        ]
        for column in required_columns:
            if column:
                cls._sql_column_identifier(str(column))
        cls._sql_table_identifier(str(completeness.universe_source_table))
        cls._sql_table_identifier(run.target_table)

    def _build_bucket_context(
        self,
        *,
        run: DatasetDateCompletenessRun,
        completeness: DatasetCompletenessDefinition,
    ) -> dict[str, object]:
        status_sql, status_params = self._status_filter(completeness)
        filter_sql, filter_params = ActualBucketReader()._row_identity_filter_clause(run.row_identity_filters_json or {})
        universe_table = self._sql_table_identifier(str(completeness.universe_source_table))
        target_table = self._sql_table_identifier(run.target_table)
        actual_key_field = self._sql_column_identifier(str(completeness.actual_key_fields[0]))
        observed_field = self._sql_column_identifier(run.observed_field)
        universe_key_field = self._sql_column_identifier(str(completeness.universe_key_field))
        universe_name_field = self._sql_column_identifier(str(completeness.universe_name_field or completeness.universe_key_field))
        lifecycle_start_field = self._sql_column_identifier(str(completeness.lifecycle_start_field or completeness.universe_key_field))
        lifecycle_end_field = self._sql_column_identifier(str(completeness.lifecycle_end_field or completeness.universe_key_field))
        bucket_sql = f"""
            with expected as (
                select
                    u.{universe_key_field} as subject_key,
                    u.{universe_name_field} as subject_name,
                    u.{lifecycle_start_field} as lifecycle_start,
                    u.{lifecycle_end_field} as lifecycle_end
                from {universe_table} u
                where u.{universe_key_field} is not null
                  and (u.{lifecycle_start_field} is null or u.{lifecycle_start_field} <= :bucket_value)
                  and (u.{lifecycle_end_field} is null or u.{lifecycle_end_field} >= :bucket_value)
                  {status_sql}
            ),
            actual as (
                select distinct
                    {actual_key_field} as subject_key
                from {target_table}
                where {observed_field} = :bucket_value
                  and {actual_key_field} is not null
                  {filter_sql}
            ),
            checked as (
                select
                    e.subject_key,
                    e.subject_name,
                    e.lifecycle_start,
                    e.lifecycle_end,
                    a.subject_key as actual_subject_key
                from expected e
                left join actual a on a.subject_key = e.subject_key
            )
            select
                subject_key,
                subject_name,
                lifecycle_start,
                lifecycle_end,
                actual_subject_key
            from checked
            order by subject_key asc
        """
        return {
            "bucket_sql": bucket_sql,
            "params": {**status_params, **filter_params},
        }

    def _execute_bucket(
        self,
        session: Session,
        *,
        run: DatasetDateCompletenessRun,
        completeness: DatasetCompletenessDefinition,
        context: dict[str, object],
        bucket: DateCompletenessBucket,
        detail_remaining: int,
    ) -> SubjectCompletenessBucketResult:
        self._set_local_statement_timeout(session)
        rows = session.execute(
            text(str(context["bucket_sql"])),
            {**dict(context["params"]), "bucket_value": bucket.value},
        ).all()
        expected_cell_count = len(rows)
        missing_rows = [row for row in rows if row.actual_subject_key is None]
        missing_cell_count = len(missing_rows)
        actual_cell_count = expected_cell_count - missing_cell_count
        if not missing_rows:
            return SubjectCompletenessBucketResult(
                expected_cell_count=expected_cell_count,
                actual_cell_count=actual_cell_count,
                missing_cell_count=0,
                missing_subject_keys=(),
                detail_count=0,
            )

        missing_subject_keys = tuple(str(row.subject_key) for row in missing_rows)
        detail_rows = missing_rows[:detail_remaining]
        sample_subjects = tuple(
            {"subject_key": str(row.subject_key), "subject_name": row.subject_name}
            for row in detail_rows[:20]
        )
        gap_row = DatasetSubjectCompletenessGap(
            run_id=run.id,
            dataset_key=run.dataset_key,
            bucket_kind=bucket.bucket_kind,
            bucket_value=bucket.value,
            subject_kind=str(completeness.subject_kind),
            subject_key_fields_json=list(completeness.subject_key_fields),
            actual_key_fields_json=list(dict.fromkeys((*completeness.actual_key_fields, run.observed_field))),
            missing_cell_count=missing_cell_count,
            affected_subject_count=len(set(missing_subject_keys)),
            sample_subjects_json=list(sample_subjects),
        )
        session.add(gap_row)
        session.flush()

        subject_key_field = str(completeness.subject_key_fields[0])
        actual_key_field = str(completeness.actual_key_fields[0])
        observed_field = str(run.observed_field)
        for row in detail_rows:
            subject_key = str(row.subject_key)
            session.add(
                DatasetSubjectCompletenessGapDetail(
                    run_id=run.id,
                    gap_id=gap_row.id,
                    dataset_key=run.dataset_key,
                    bucket_kind=bucket.bucket_kind,
                    bucket_value=bucket.value,
                    subject_kind=str(completeness.subject_kind),
                    subject_key=subject_key,
                    subject_name=row.subject_name,
                    subject_key_json={subject_key_field: subject_key},
                    actual_key_json={actual_key_field: subject_key, observed_field: bucket.value.isoformat()},
                    lifecycle_start=ActualBucketReader._value_to_date(row.lifecycle_start) if row.lifecycle_start is not None else None,
                    lifecycle_end=ActualBucketReader._value_to_date(row.lifecycle_end) if row.lifecycle_end is not None else None,
                    reason_code="missing_subject_bucket",
                    reason_message="该对象在该日期桶处于有效生命周期内，但目标表缺少对应行。",
                    target_table=run.target_table,
                )
            )
        return SubjectCompletenessBucketResult(
            expected_cell_count=expected_cell_count,
            actual_cell_count=actual_cell_count,
            missing_cell_count=missing_cell_count,
            missing_subject_keys=missing_subject_keys,
            detail_count=len(detail_rows),
        )

    @staticmethod
    def _clear_existing_result_rows(session: Session, run: DatasetDateCompletenessRun) -> None:
        session.execute(delete(DatasetDateCompletenessGap).where(DatasetDateCompletenessGap.run_id == run.id))
        session.execute(delete(DatasetDateCompletenessExclusion).where(DatasetDateCompletenessExclusion.run_id == run.id))
        session.execute(delete(DatasetSubjectCompletenessGapDetail).where(DatasetSubjectCompletenessGapDetail.run_id == run.id))
        session.execute(delete(DatasetSubjectCompletenessGap).where(DatasetSubjectCompletenessGap.run_id == run.id))
        session.commit()

    @classmethod
    def _set_local_statement_timeout(cls, session: Session) -> None:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        session.execute(text(cls.STATEMENT_TIMEOUT_SQL))

    @staticmethod
    def _mark_bucket_started(
        session: Session,
        *,
        run: DatasetDateCompletenessRun,
        bucket: DateCompletenessBucket,
        processed_bucket_count: int,
        total_bucket_count: int,
    ) -> None:
        run.current_stage = "reading_actual"
        run.current_bucket_value = bucket.value
        run.current_bucket_label = bucket.label
        run.processed_bucket_count = processed_bucket_count
        run.progress_message = f"正在处理第 {processed_bucket_count + 1}/{total_bucket_count} 个日期桶：{bucket.label}。"
        run.heartbeat_at = _utcnow()
        session.commit()

    @staticmethod
    def _mark_bucket_completed(
        session: Session,
        *,
        run: DatasetDateCompletenessRun,
        bucket: DateCompletenessBucket,
        processed_bucket_count: int,
        total_bucket_count: int,
        expected_cell_count: int,
        actual_cell_count: int,
        missing_cell_count: int,
        affected_bucket_count: int,
        affected_subject_count: int,
        actual_bucket_count: int,
        detail_truncated: bool,
    ) -> None:
        run.current_stage = "reading_actual"
        run.current_bucket_value = bucket.value
        run.current_bucket_label = bucket.label
        run.processed_bucket_count = processed_bucket_count
        run.expected_cell_count = expected_cell_count
        run.actual_cell_count = actual_cell_count
        run.missing_cell_count = missing_cell_count
        run.affected_bucket_count = affected_bucket_count
        run.affected_subject_count = affected_subject_count
        run.actual_bucket_count = actual_bucket_count
        run.detail_truncated = detail_truncated
        run.progress_message = (
            f"已处理 {processed_bucket_count}/{total_bucket_count} 个日期桶，"
            f"当前 {bucket.label}，已发现 {missing_cell_count} 个缺失对象日期单元。"
        )
        run.heartbeat_at = _utcnow()
        session.commit()

    @classmethod
    def _status_filter(cls, completeness: DatasetCompletenessDefinition) -> tuple[str, dict[str, str]]:
        if not completeness.status_field or not completeness.active_status_values:
            return "", {}
        status_field = cls._sql_column_identifier(completeness.status_field)
        params = {f"active_status_{index}": value for index, value in enumerate(completeness.active_status_values)}
        placeholders = ", ".join(f":{name}" for name in params)
        return f"and u.{status_field} in ({placeholders})", params

    @staticmethod
    def _empty_result(*, actual_bucket_count: int) -> SubjectCompletenessMatrixResult:
        return SubjectCompletenessMatrixResult(
            subject_key_fields=(),
            actual_key_fields=(),
            expected_cell_count=0,
            actual_cell_count=0,
            missing_cell_count=0,
            affected_bucket_count=0,
            affected_subject_count=0,
            actual_bucket_count=actual_bucket_count,
            gap_summaries=(),
            details=(),
            detail_truncated=False,
        )

    @classmethod
    def _sql_table_identifier(cls, value: str) -> str:
        if not cls.SQL_IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(f"对象矩阵审计表标识符无效：{value!r}")
        return value

    @classmethod
    def _sql_column_identifier(cls, value: str) -> str:
        if not cls.SQL_COLUMN_PATTERN.fullmatch(value):
            raise ValueError(f"对象矩阵审计字段标识符无效：{value!r}")
        return value


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
            self._mark_planned(session, run, expected=expected, excluded=excluded)

            if run.audit_scope == "date_subject_matrix":
                if len(expected) > DATE_SUBJECT_MATRIX_SAFE_BUCKET_LIMIT:
                    raise DateSubjectMatrixRangeTooLargeError(expected_bucket_count=len(expected))
                definition = get_dataset_definition(run.dataset_key)
                result = SubjectCompletenessMatrixExecutor().execute(
                    session,
                    run=run,
                    definition=definition,
                    expected_buckets=expected,
                )
                self._mark_subject_matrix_succeeded(
                    session,
                    run,
                    expected=expected,
                    excluded=excluded,
                    result=result,
                )
                return run

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
        now = _utcnow()
        run.run_status = "running"
        run.result_status = None
        run.current_stage = "planning"
        run.operator_message = "正在生成期望日期桶。"
        run.processed_bucket_count = 0
        run.current_bucket_value = None
        run.current_bucket_label = None
        run.progress_message = "正在生成应检查的日期桶。"
        run.heartbeat_at = now
        run.started_at = run.started_at or now
        session.commit()
        session.refresh(run)

    @staticmethod
    def _mark_planned(
        session: Session,
        run: DatasetDateCompletenessRun,
        *,
        expected: list[DateCompletenessBucket],
        excluded: list[DateCompletenessExcludedBucket],
    ) -> None:
        run.current_stage = "reading_actual"
        run.expected_bucket_count = len(expected)
        run.excluded_bucket_count = len(excluded)
        run.processed_bucket_count = 0
        first_bucket = expected[0] if expected else None
        run.current_bucket_value = first_bucket.value if first_bucket else None
        run.current_bucket_label = first_bucket.label if first_bucket else None
        if run.audit_scope == "date_subject_matrix":
            run.progress_message = (
                f"已规划 {len(expected)} 个日期桶，正在读取并比对日期 × 对象矩阵。"
            )
        else:
            run.progress_message = f"已规划 {len(expected)} 个日期桶，正在读取实际数据。"
        run.heartbeat_at = _utcnow()
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
        session.execute(delete(DatasetSubjectCompletenessGapDetail).where(DatasetSubjectCompletenessGapDetail.run_id == run.id))
        session.execute(delete(DatasetSubjectCompletenessGap).where(DatasetSubjectCompletenessGap.run_id == run.id))
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
        run.expected_cell_count = 0
        run.actual_cell_count = 0
        run.missing_cell_count = 0
        run.affected_bucket_count = 0
        run.affected_subject_count = 0
        run.detail_truncated = False
        run.processed_bucket_count = len(expected)
        last_bucket = expected[-1] if expected else None
        run.current_bucket_value = last_bucket.value if last_bucket else None
        run.current_bucket_label = last_bucket.label if last_bucket else None
        if gaps:
            run.operator_message = "审计发现日期缺口。"
        elif excluded:
            run.operator_message = f"审计通过，已按规则排除 {len(excluded)} 个不可产出日期桶。"
        else:
            run.operator_message = "审计通过，未发现日期缺口。"
        run.technical_message = None
        run.progress_message = f"审计完成，已处理 {len(expected)} 个日期桶。"
        now = _utcnow()
        run.heartbeat_at = now
        run.finished_at = now
        session.commit()
        session.refresh(run)

    @staticmethod
    def _mark_subject_matrix_succeeded(
        session: Session,
        run: DatasetDateCompletenessRun,
        *,
        expected: list[DateCompletenessBucket],
        excluded: list[DateCompletenessExcludedBucket],
        result: SubjectCompletenessMatrixResult,
    ) -> None:
        session.execute(delete(DatasetDateCompletenessGap).where(DatasetDateCompletenessGap.run_id == run.id))
        session.execute(delete(DatasetDateCompletenessExclusion).where(DatasetDateCompletenessExclusion.run_id == run.id))
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
        run.result_status = "failed" if result.missing_cell_count else "passed"
        run.current_stage = "finished"
        run.expected_bucket_count = len(expected)
        run.actual_bucket_count = result.actual_bucket_count
        run.missing_bucket_count = 0
        run.excluded_bucket_count = len(excluded)
        run.gap_range_count = 0
        run.expected_cell_count = result.expected_cell_count
        run.actual_cell_count = result.actual_cell_count
        run.missing_cell_count = result.missing_cell_count
        run.affected_bucket_count = result.affected_bucket_count
        run.affected_subject_count = result.affected_subject_count
        run.detail_truncated = result.detail_truncated
        run.processed_bucket_count = len(expected)
        last_bucket = expected[-1] if expected else None
        run.current_bucket_value = last_bucket.value if last_bucket else None
        run.current_bucket_label = last_bucket.label if last_bucket else None
        if result.missing_cell_count:
            run.operator_message = "审计发现对象矩阵缺口。"
        elif result.expected_cell_count == 0:
            run.operator_message = "审计通过，对象池在本窗口内为空。"
        elif excluded:
            run.operator_message = f"审计通过，已按规则排除 {len(excluded)} 个不可产出日期桶。"
        else:
            run.operator_message = "审计通过，未发现对象矩阵缺口。"
        run.technical_message = None
        run.progress_message = f"审计完成，已处理 {len(expected)} 个日期桶。"
        now = _utcnow()
        run.heartbeat_at = now
        run.finished_at = now
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
        run.operator_message = getattr(error, "operator_message", "审计执行失败，请查看技术诊断。")
        run.technical_message = str(error)
        run.progress_message = run.operator_message
        now = _utcnow()
        run.heartbeat_at = now
        run.finished_at = now
        session.commit()


class DateCompletenessAuditWorker:
    def run_next(self, session: Session) -> DatasetDateCompletenessRun | None:
        return DateCompletenessAuditExecutor().run_next(session)


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
