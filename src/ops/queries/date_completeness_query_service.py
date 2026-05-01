from __future__ import annotations

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.catalog.dataset_catalog_view_resolver import DatasetCatalogViewResolver
from src.ops.schemas.date_completeness import (
    DateCompletenessRuleGroup,
    DateCompletenessRuleItem,
    DateCompletenessRuleListResponse,
    DateCompletenessRuleSummary,
)


class DateCompletenessRuleQueryService:
    GROUP_SUPPORTED = "supported"
    GROUP_UNSUPPORTED = "unsupported"

    def list_rules(self) -> DateCompletenessRuleListResponse:
        supported: list[DateCompletenessRuleItem] = []
        unsupported: list[DateCompletenessRuleItem] = []
        resolver = DatasetCatalogViewResolver()
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
            item = self._to_rule_item(definition)
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
    def _to_rule_item(cls, definition: DatasetDefinition) -> DateCompletenessRuleItem:
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
            audit_applicable=date_model.audit_applicable,
            not_applicable_reason=date_model.not_applicable_reason,
            rule_label=cls._rule_label(date_axis=date_model.date_axis, bucket_rule=date_model.bucket_rule),
        )

    @staticmethod
    def _rule_label(*, date_axis: str, bucket_rule: str) -> str:
        labels = {
            ("trade_open_day", "every_open_day"): "每个开市交易日",
            ("trade_open_day", "week_last_open_day"): "每周最后一个开市交易日",
            ("trade_open_day", "month_last_open_day"): "每月最后一个开市交易日",
            ("natural_day", "every_natural_day"): "每个自然日",
            ("month_key", "every_natural_month"): "每个自然月",
            ("month_window", "month_window_has_data"): "每个自然月窗口至少有数据",
            ("none", "not_applicable"): "不适用日期完整性审计",
        }
        return labels.get((date_axis, bucket_rule), f"{date_axis} / {bucket_rule}")
