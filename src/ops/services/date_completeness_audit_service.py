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


DATE_SUBJECT_MATRIX_SAFE_BUCKET_LIMIT = 30


class DateSubjectMatrixRangeTooLargeError(ValueError):
    def __init__(self, *, expected_bucket_count: int) -> None:
        self.expected_bucket_count = expected_bucket_count
        self.operator_message = (
            "对象矩阵审计范围超过当前安全上限，已停止执行。请缩小日期范围，或等待分桶执行能力上线后再运行大范围审计。"
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
        if not expected_buckets:
            return self._empty_result(actual_bucket_count=0)

        sql_context = self._build_sql_context(run=run, completeness=completeness, expected_buckets=expected_buckets)
        summary = self._read_summary(session, sql_context=sql_context)
        gap_summaries = self._read_gap_summaries(session, sql_context=sql_context, completeness=completeness)
        details, detail_truncated = self._read_details(
            session,
            sql_context=sql_context,
            completeness=completeness,
            target_table=run.target_table,
        )
        samples_by_bucket: dict[date, list[dict[str, str | None]]] = {}
        for detail in details:
            samples = samples_by_bucket.setdefault(detail.bucket_value, [])
            if len(samples) < 20:
                samples.append({"subject_key": detail.subject_key, "subject_name": detail.subject_name})

        gap_summaries = tuple(
            SubjectCompletenessGapSummary(
                bucket_kind=item.bucket_kind,
                bucket_value=item.bucket_value,
                subject_kind=item.subject_kind,
                missing_cell_count=item.missing_cell_count,
                affected_subject_count=item.affected_subject_count,
                sample_subjects=tuple(samples_by_bucket.get(item.bucket_value, [])),
            )
            for item in gap_summaries
        )

        return SubjectCompletenessMatrixResult(
            subject_key_fields=tuple(completeness.subject_key_fields),
            actual_key_fields=tuple(dict.fromkeys((*completeness.actual_key_fields, str(run.observed_field)))),
            expected_cell_count=int(summary["expected_cell_count"]),
            actual_cell_count=int(summary["actual_cell_count"]),
            missing_cell_count=int(summary["missing_cell_count"]),
            affected_bucket_count=int(summary["affected_bucket_count"]),
            affected_subject_count=int(summary["affected_subject_count"]),
            actual_bucket_count=int(summary["actual_bucket_count"]),
            gap_summaries=gap_summaries,
            details=tuple(details[: self.DETAIL_LIMIT]),
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

    def _build_sql_context(
        self,
        *,
        run: DatasetDateCompletenessRun,
        completeness: DatasetCompletenessDefinition,
        expected_buckets: list[DateCompletenessBucket],
    ) -> dict[str, object]:
        expected_sql, expected_params = self._expected_buckets_values(expected_buckets)
        status_sql, status_params = self._status_filter(completeness)
        universe_table = self._sql_table_identifier(str(completeness.universe_source_table))
        target_table = self._sql_table_identifier(run.target_table)
        subject_key_field = self._sql_column_identifier(str(completeness.subject_key_fields[0]))
        actual_key_field = self._sql_column_identifier(str(completeness.actual_key_fields[0]))
        observed_field = self._sql_column_identifier(run.observed_field)
        universe_key_field = self._sql_column_identifier(str(completeness.universe_key_field))
        universe_name_field = self._sql_column_identifier(str(completeness.universe_name_field or completeness.universe_key_field))
        lifecycle_start_field = self._sql_column_identifier(str(completeness.lifecycle_start_field or completeness.universe_key_field))
        lifecycle_end_field = self._sql_column_identifier(str(completeness.lifecycle_end_field or completeness.universe_key_field))
        subject_kind = str(completeness.subject_kind)
        bucket_kind = expected_buckets[0].bucket_kind
        matrix_cte = f"""
            with expected_buckets(bucket_value) as (
                values {expected_sql}
            ),
            expected_matrix as (
                select
                    b.bucket_value as bucket_value,
                    u.{universe_key_field} as subject_key,
                    u.{universe_name_field} as subject_name,
                    u.{lifecycle_start_field} as lifecycle_start,
                    u.{lifecycle_end_field} as lifecycle_end
                from expected_buckets b
                join {universe_table} u
                  on (u.{lifecycle_start_field} is null or u.{lifecycle_start_field} <= b.bucket_value)
                 and (u.{lifecycle_end_field} is null or u.{lifecycle_end_field} >= b.bucket_value)
                where u.{universe_key_field} is not null
                {status_sql}
            ),
            actual_matrix as (
                select distinct
                    {observed_field} as bucket_value,
                    {actual_key_field} as subject_key
                from {target_table}
                where {observed_field} between :start_date and :end_date
                  and {actual_key_field} is not null
            ),
            covered_matrix as (
                select e.bucket_value, e.subject_key
                from expected_matrix e
                join actual_matrix a
                  on a.bucket_value = e.bucket_value
                 and a.subject_key = e.subject_key
            ),
            missing_matrix as (
                select
                    e.bucket_value,
                    e.subject_key,
                    e.subject_name,
                    e.lifecycle_start,
                    e.lifecycle_end
                from expected_matrix e
                left join actual_matrix a
                  on a.bucket_value = e.bucket_value
                 and a.subject_key = e.subject_key
                where a.subject_key is null
            )
        """
        return {
            "matrix_cte": matrix_cte,
            "params": {
                "start_date": run.start_date,
                "end_date": run.end_date,
                **expected_params,
                **status_params,
            },
            "bucket_kind": bucket_kind,
            "subject_kind": subject_kind,
            "subject_key_field": subject_key_field,
            "actual_key_field": actual_key_field,
            "observed_field": observed_field,
        }

    def _read_summary(self, session: Session, *, sql_context: dict[str, object]) -> dict[str, int]:
        row = session.execute(
            text(
                f"""
                {sql_context["matrix_cte"]}
                select
                    (select count(*) from expected_matrix) as expected_cell_count,
                    (select count(*) from covered_matrix) as actual_cell_count,
                    (select count(*) from missing_matrix) as missing_cell_count,
                    (select count(distinct bucket_value) from missing_matrix) as affected_bucket_count,
                    (select count(distinct subject_key) from missing_matrix) as affected_subject_count,
                    (select count(distinct bucket_value) from covered_matrix) as actual_bucket_count
                """
            ),
            sql_context["params"],
        ).one()
        return {
            "expected_cell_count": int(row.expected_cell_count or 0),
            "actual_cell_count": int(row.actual_cell_count or 0),
            "missing_cell_count": int(row.missing_cell_count or 0),
            "affected_bucket_count": int(row.affected_bucket_count or 0),
            "affected_subject_count": int(row.affected_subject_count or 0),
            "actual_bucket_count": int(row.actual_bucket_count or 0),
        }

    def _read_gap_summaries(
        self,
        session: Session,
        *,
        sql_context: dict[str, object],
        completeness: DatasetCompletenessDefinition,
    ) -> tuple[SubjectCompletenessGapSummary, ...]:
        rows = session.execute(
            text(
                f"""
                {sql_context["matrix_cte"]}
                select
                    bucket_value,
                    count(*) as missing_cell_count,
                    count(distinct subject_key) as affected_subject_count
                from missing_matrix
                group by bucket_value
                order by bucket_value asc
                """
            ),
            sql_context["params"],
        ).all()
        return tuple(
            SubjectCompletenessGapSummary(
                bucket_kind=str(sql_context["bucket_kind"]),
                bucket_value=ActualBucketReader._value_to_date(row.bucket_value),
                subject_kind=str(completeness.subject_kind),
                missing_cell_count=int(row.missing_cell_count or 0),
                affected_subject_count=int(row.affected_subject_count or 0),
                sample_subjects=(),
            )
            for row in rows
        )

    def _read_details(
        self,
        session: Session,
        *,
        sql_context: dict[str, object],
        completeness: DatasetCompletenessDefinition,
        target_table: str,
    ) -> tuple[list[SubjectCompletenessGapDetail], bool]:
        rows = session.execute(
            text(
                f"""
                {sql_context["matrix_cte"]}
                select
                    bucket_value,
                    subject_key,
                    subject_name,
                    lifecycle_start,
                    lifecycle_end
                from missing_matrix
                order by bucket_value asc, subject_key asc
                limit :detail_limit
                """
            ),
            {**dict(sql_context["params"]), "detail_limit": self.DETAIL_LIMIT + 1},
        ).all()
        detail_rows = rows[: self.DETAIL_LIMIT]
        details: list[SubjectCompletenessGapDetail] = []
        subject_key_field = str(completeness.subject_key_fields[0])
        actual_key_field = str(completeness.actual_key_fields[0])
        observed_field = str(sql_context["observed_field"])
        for row in detail_rows:
            bucket_value = ActualBucketReader._value_to_date(row.bucket_value)
            subject_key = str(row.subject_key)
            details.append(
                SubjectCompletenessGapDetail(
                    bucket_kind=str(sql_context["bucket_kind"]),
                    bucket_value=bucket_value,
                    subject_kind=str(completeness.subject_kind),
                    subject_key=subject_key,
                    subject_name=row.subject_name,
                    subject_key_json={subject_key_field: subject_key},
                    actual_key_json={actual_key_field: subject_key, observed_field: bucket_value.isoformat()},
                    lifecycle_start=ActualBucketReader._value_to_date(row.lifecycle_start) if row.lifecycle_start is not None else None,
                    lifecycle_end=ActualBucketReader._value_to_date(row.lifecycle_end) if row.lifecycle_end is not None else None,
                    reason_code="missing_subject_bucket",
                    reason_message="该对象在该日期桶处于有效生命周期内，但目标表缺少对应行。",
                    target_table=target_table,
                )
            )
        return details, len(rows) > self.DETAIL_LIMIT

    @staticmethod
    def _expected_buckets_values(expected_buckets: list[DateCompletenessBucket]) -> tuple[str, dict[str, date]]:
        values_sql: list[str] = []
        params: dict[str, date] = {}
        for index, bucket in enumerate(expected_buckets):
            param_name = f"expected_bucket_{index}"
            values_sql.append(f"(:{param_name})")
            params[param_name] = bucket.value
        return ", ".join(values_sql), params

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
        session.execute(delete(DatasetSubjectCompletenessGapDetail).where(DatasetSubjectCompletenessGapDetail.run_id == run.id))
        session.execute(delete(DatasetSubjectCompletenessGap).where(DatasetSubjectCompletenessGap.run_id == run.id))

        gap_rows_by_bucket: dict[date, DatasetSubjectCompletenessGap] = {}
        for gap in result.gap_summaries:
            gap_row = DatasetSubjectCompletenessGap(
                run_id=run.id,
                dataset_key=run.dataset_key,
                bucket_kind=gap.bucket_kind,
                bucket_value=gap.bucket_value,
                subject_kind=gap.subject_kind,
                subject_key_fields_json=list(result.subject_key_fields),
                actual_key_fields_json=list(result.actual_key_fields),
                missing_cell_count=gap.missing_cell_count,
                affected_subject_count=gap.affected_subject_count,
                sample_subjects_json=list(gap.sample_subjects),
            )
            session.add(gap_row)
            gap_rows_by_bucket[gap.bucket_value] = gap_row
        session.flush()

        for detail in result.details:
            gap_row = gap_rows_by_bucket.get(detail.bucket_value)
            if gap_row is None:
                continue
            session.add(
                DatasetSubjectCompletenessGapDetail(
                    run_id=run.id,
                    gap_id=gap_row.id,
                    dataset_key=run.dataset_key,
                    bucket_kind=detail.bucket_kind,
                    bucket_value=detail.bucket_value,
                    subject_kind=detail.subject_kind,
                    subject_key=detail.subject_key,
                    subject_name=detail.subject_name,
                    subject_key_json=detail.subject_key_json,
                    actual_key_json=detail.actual_key_json,
                    lifecycle_start=detail.lifecycle_start,
                    lifecycle_end=detail.lifecycle_end,
                    reason_code=detail.reason_code,
                    reason_message=detail.reason_message,
                    target_table=detail.target_table,
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
