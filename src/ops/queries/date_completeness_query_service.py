from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.catalog.dataset_catalog_view_resolver import DatasetCatalogViewResolver
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.schemas.date_completeness import (
    DateCompletenessRuleDataRange,
    DateCompletenessRuleGroup,
    DateCompletenessRuleItem,
    DateCompletenessRuleListResponse,
    DateCompletenessRuleSummary,
)


class DateCompletenessRuleQueryService:
    GROUP_SUPPORTED = "supported"
    GROUP_UNSUPPORTED = "unsupported"

    def list_rules(self, session: Session) -> DateCompletenessRuleListResponse:
        supported: list[DateCompletenessRuleItem] = []
        unsupported: list[DateCompletenessRuleItem] = []
        resolver = DatasetCatalogViewResolver()
        snapshots_by_key = self._snapshots_by_dataset_key(session)
        sorted_definitions = sorted(
            list_dataset_definitions(),
            key=lambda item: (
                resolver.resolve_item(item.dataset_key).group_order,
                resolver.resolve_item(item.dataset_key).item_order,
                item.display_name,
                item.dataset_key,
            ),
        )
        for definition in sorted_definitions:
            item = self._to_rule_item(definition, snapshot=snapshots_by_key.get(definition.dataset_key))
            if item.audit_applicable:
                supported.append(item)
            else:
                unsupported.append(item)
        return DateCompletenessRuleListResponse(
            summary=DateCompletenessRuleSummary(
                total=len(supported) + len(unsupported),
                supported=len(supported),
                unsupported=len(unsupported),
            ),
            groups=[
                DateCompletenessRuleGroup(group_key=self.GROUP_SUPPORTED, group_label="支持审计", items=supported),
                DateCompletenessRuleGroup(group_key=self.GROUP_UNSUPPORTED, group_label="不支持审计", items=unsupported),
            ],
        )

    @classmethod
    def _to_rule_item(cls, definition: DatasetDefinition, *, snapshot: DatasetStatusSnapshot | None) -> DateCompletenessRuleItem:
        date_model = definition.date_model
        catalog_item = DatasetCatalogViewResolver().resolve_item(definition.dataset_key)
        return DateCompletenessRuleItem(
            dataset_key=definition.dataset_key,
            display_name=definition.display_name,
            group_key=catalog_item.group_key,
            group_label=catalog_item.group_label,
            group_order=catalog_item.group_order,
            item_order=catalog_item.item_order,
            domain_key=definition.domain.domain_key,
            domain_display_name=definition.domain.domain_display_name,
            target_table=definition.storage.target_table,
            date_axis=date_model.date_axis,
            bucket_rule=date_model.bucket_rule,
            window_mode=date_model.window_mode,
            input_shape=date_model.input_shape,
            observed_field=date_model.observed_field,
            bucket_window_rule=date_model.bucket_window_rule,
            bucket_applicability_rule=date_model.bucket_applicability_rule,
            audit_applicable=date_model.audit_applicable,
            not_applicable_reason=date_model.not_applicable_reason,
            rule_label=cls._rule_label(date_axis=date_model.date_axis, bucket_rule=date_model.bucket_rule),
            data_range=cls._data_range(snapshot),
        )

    @staticmethod
    def _snapshots_by_dataset_key(session: Session) -> dict[str, DatasetStatusSnapshot]:
        return {row.dataset_key: row for row in session.scalars(select(DatasetStatusSnapshot)).all()}

    @classmethod
    def _data_range(cls, snapshot: DatasetStatusSnapshot | None) -> DateCompletenessRuleDataRange:
        if snapshot is None:
            return DateCompletenessRuleDataRange(range_type="none", label="—")
        if snapshot.latest_business_date is not None:
            start_date = snapshot.earliest_business_date or snapshot.latest_business_date
            return DateCompletenessRuleDataRange(
                range_type="business_date",
                start_date=start_date,
                end_date=snapshot.latest_business_date,
                label=cls._date_range_label(start_date, snapshot.latest_business_date),
            )
        if snapshot.latest_observed_at is not None:
            start_at = snapshot.earliest_observed_at or snapshot.latest_observed_at
            return DateCompletenessRuleDataRange(
                range_type="observed_time",
                start_at=start_at,
                end_at=snapshot.latest_observed_at,
                label=cls._datetime_range_label(start_at, snapshot.latest_observed_at),
            )
        if snapshot.last_sync_date is not None:
            return DateCompletenessRuleDataRange(
                range_type="sync_date",
                start_date=snapshot.last_sync_date,
                end_date=snapshot.last_sync_date,
                label=f"最近同步：{cls._format_date(snapshot.last_sync_date)}",
            )
        return DateCompletenessRuleDataRange(range_type="none", label="—")

    @classmethod
    def _date_range_label(cls, start_date: date, end_date: date) -> str:
        if start_date == end_date:
            return f"最新业务日：{cls._format_date(end_date)}"
        return f"{cls._format_date(start_date)} 至 {cls._format_date(end_date)}"

    @classmethod
    def _datetime_range_label(cls, start_at: datetime, end_at: datetime) -> str:
        if start_at == end_at:
            return f"最新时间：{cls._format_datetime(end_at)}"
        return f"{cls._format_datetime(start_at)} 至 {cls._format_datetime(end_at)}"

    @staticmethod
    def _format_date(value: date) -> str:
        return value.strftime("%Y/%m/%d")

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        return value.strftime("%Y/%m/%d %H:%M:%S")

    @staticmethod
    def _rule_label(*, date_axis: str, bucket_rule: str) -> str:
        labels = {
            ("trade_open_day", "every_open_day"): "每个开市交易日",
            ("trade_open_day", "week_last_open_day"): "每周最后一个开市交易日",
            ("trade_open_day", "month_last_open_day"): "每月最后一个开市交易日",
            ("natural_day", "every_natural_day"): "每个自然日",
            ("natural_day", "week_friday"): "每个自然周周五",
            ("natural_day", "month_last_calendar_day"): "每个自然月最后一天",
            ("month_key", "every_natural_month"): "每个自然月",
            ("month_window", "month_window_has_data"): "每个自然月窗口至少有数据",
            ("none", "not_applicable"): "不适用日期完整性审计",
        }
        return labels.get((date_axis, bucket_rule), f"{date_axis} / {bucket_rule}")
