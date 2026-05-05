from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.ops.action_catalog import (
    ActionParameter,
    WorkflowDefinition,
    dataset_field_default_value,
    list_workflow_definitions,
)
from src.foundation.datasets.models import DatasetDateModel, DatasetDefinition, DatasetInputField
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.catalog.dataset_catalog_view_resolver import DatasetCatalogViewResolver
from src.ops.schemas.catalog import ActionParameterResponse
from src.ops.schemas.manual_action import (
    ManualActionDateModelResponse,
    ManualActionGroupResponse,
    ManualActionItemResponse,
    ManualActionListResponse,
    ManualActionTimeFormResponse,
    ManualActionTimeModeResponse,
)


TIME_PARAM_KEYS = {
    "trade_date",
    "start_date",
    "end_date",
    "month",
    "start_month",
    "end_month",
    "ann_date",
}
INTERNAL_PARAM_KEYS = {"offset", "limit"}

@dataclass(frozen=True, slots=True)
class ManualActionRoute:
    action_key: str
    action_type: str
    group_key: str
    group_label: str
    group_order: int
    action_order: int
    display_name: str
    description: str
    resource_key: str | None
    resource_display_name: str | None
    date_model: DatasetDateModel | None
    time_form: ManualActionTimeFormResponse
    filters: tuple[ActionParameter, ...]
    workflow: WorkflowDefinition | None = None


class ManualActionQueryService:
    def build_manual_actions(self) -> ManualActionListResponse:
        groups: dict[str, ManualActionGroupResponse] = {}
        for route in self.build_action_routes():
            group = groups.get(route.group_key)
            item = self._to_response_item(route)
            if group is None:
                groups[route.group_key] = ManualActionGroupResponse(
                    group_key=route.group_key,
                    group_label=route.group_label,
                    group_order=route.group_order,
                    actions=[item],
                )
            else:
                group.actions.append(item)

        sorted_groups = sorted(groups.values(), key=lambda item: (item.group_order, item.group_label))
        for group in sorted_groups:
            group.actions.sort(key=lambda item: (item.action_order, item.display_name))
        return ManualActionListResponse(groups=sorted_groups)

    def build_action_routes(self) -> list[ManualActionRoute]:
        routes = [self._build_resource_route(definition) for definition in list_dataset_definitions()]
        routes.extend(self._build_workflow_route(workflow) for workflow in list_workflow_definitions() if workflow.manual_enabled)
        return sorted(routes, key=lambda item: (item.group_order, item.action_order, item.display_name))

    def get_action_route(self, action_key: str) -> ManualActionRoute | None:
        return next((route for route in self.build_action_routes() if route.action_key == action_key), None)

    def _build_resource_route(self, definition: DatasetDefinition) -> ManualActionRoute:
        date_model = definition.date_model
        catalog_item = DatasetCatalogViewResolver().resolve_item(definition.dataset_key)
        action_key = definition.action_key("maintain")
        display_name = definition.action_display_name("maintain")
        filters = self._collect_dataset_filters(
            definition.input_model.filters,
            enum_fanout_defaults=definition.planning.enum_fanout_defaults,
        )
        action = definition.capabilities.get_action("maintain")
        supported_modes = tuple(action.supported_time_modes if action else ())
        time_form = self._time_form_from_date_model(date_model, supported_time_modes=supported_modes)
        return ManualActionRoute(
            action_key=action_key,
            action_type="dataset_action",
            group_key=catalog_item.group_key,
            group_label=catalog_item.group_label,
            group_order=catalog_item.group_order,
            action_order=catalog_item.item_order,
            display_name=display_name,
            description=definition.identity.description,
            resource_key=definition.dataset_key,
            resource_display_name=definition.display_name,
            date_model=date_model,
            time_form=time_form,
            filters=filters,
        )

    def _build_workflow_route(self, workflow: WorkflowDefinition) -> ManualActionRoute:
        return ManualActionRoute(
            action_key=f"workflow:{workflow.key}",
            action_type="workflow",
            group_key=workflow.domain_key,
            group_label=workflow.domain_display_name,
            group_order=workflow.group_order,
            action_order=100,
            display_name=workflow.display_name,
            description=workflow.description,
            resource_key=None,
            resource_display_name=None,
            date_model=None,
            time_form=self._time_form_from_workflow(workflow),
            filters=self._collect_filters((workflow.parameters,)),
            workflow=workflow,
        )

    @staticmethod
    def _collect_filters(param_sets: Iterable[Iterable[ActionParameter]]) -> tuple[ActionParameter, ...]:
        filters: dict[str, ActionParameter] = {}
        for params in param_sets:
            for param in params:
                if param.key in TIME_PARAM_KEYS or param.key in INTERNAL_PARAM_KEYS:
                    continue
                if param.key not in filters:
                    filters[param.key] = param
        return tuple(filters.values())

    @staticmethod
    def _collect_dataset_filters(
        fields: Iterable[DatasetInputField],
        *,
        enum_fanout_defaults: dict[str, tuple[str, ...]],
    ) -> tuple[ActionParameter, ...]:
        filters: dict[str, ActionParameter] = {}
        for field in fields:
            if field.name in TIME_PARAM_KEYS or field.name in INTERNAL_PARAM_KEYS:
                continue
            filters[field.name] = ManualActionQueryService._field_to_action_parameter(
                field,
                enum_fanout_defaults=enum_fanout_defaults,
            )
        return tuple(filters.values())

    @staticmethod
    def _mode_response(
        *,
        mode: str,
        label: str,
        description: str,
        control: str,
        selection_rule: str,
        date_field: str | None = None,
    ) -> ManualActionTimeModeResponse:
        return ManualActionTimeModeResponse(
            mode=mode,
            label=label,
            description=description,
            control=control,
            selection_rule=selection_rule,
            date_field=date_field,
        )

    @classmethod
    def _none_mode_response(cls, *, description: str) -> ManualActionTimeModeResponse:
        return cls._mode_response(
            mode="none",
            label="按默认策略处理",
            description=description,
            control="none",
            selection_rule="none",
        )

    @staticmethod
    def _time_form(modes: list[ManualActionTimeModeResponse]) -> ManualActionTimeFormResponse:
        return ManualActionTimeFormResponse(
            default_mode=modes[0].mode,
            modes=modes,
        )

    @classmethod
    def _time_form_from_workflow(cls, workflow: WorkflowDefinition) -> ManualActionTimeFormResponse:
        keys = {param.key for param in workflow.parameters}
        modes: list[ManualActionTimeModeResponse] = []
        natural_day_mode = workflow.time_regime == "natural_day"
        if "trade_date" in keys:
            modes.append(
                cls._mode_response(
                    mode="point",
                    label="只处理一天",
                    description="指定单个自然日。" if natural_day_mode else "指定单个交易日。",
                    control="calendar_date" if natural_day_mode else "trade_date",
                    selection_rule="calendar_day" if natural_day_mode else "trading_day_only",
                    date_field="trade_date",
                )
            )
        if {"start_date", "end_date"}.issubset(keys):
            modes.append(
                cls._mode_response(
                    mode="range",
                    label="处理一个时间区间",
                    description="指定开始和结束自然日。" if natural_day_mode else "指定开始和结束交易日。",
                    control="calendar_date_range" if natural_day_mode else "trade_date_range",
                    selection_rule="calendar_day" if natural_day_mode else "trading_day_only",
                    date_field="trade_date",
                )
            )
        if "month" in keys:
            modes.append(
                cls._mode_response(
                    mode="point",
                    label="只处理一个月",
                    description="指定单个月份。",
                    control="month",
                    selection_rule="month_key",
                )
            )
        if {"start_month", "end_month"}.issubset(keys):
            modes.append(
                cls._mode_response(
                    mode="range",
                    label="处理一个月份区间",
                    description="指定开始月份和结束月份。",
                    control="month_range",
                    selection_rule="month_key",
                )
            )
        if not modes:
            modes = [cls._none_mode_response(description="不填写时间条件，按该工作流默认策略执行。")]
        return cls._time_form(modes)

    @classmethod
    def _time_form_from_date_model(
        cls,
        date_model: DatasetDateModel,
        *,
        supported_time_modes: tuple[str, ...],
    ) -> ManualActionTimeFormResponse:
        if date_model.input_shape == "none" or date_model.window_mode == "none":
            return cls._time_form([cls._none_mode_response(description="不填写时间条件，按该维护对象默认策略执行。")])

        modes = [
            mode_item
            for mode in supported_time_modes
            if (mode_item := cls._dataset_mode_from_date_model(date_model, mode)) is not None
        ]
        if not modes:
            return cls._time_form([cls._none_mode_response(description="不填写时间条件，按该维护对象默认策略执行。")])
        return cls._time_form(modes)

    @classmethod
    def _dataset_mode_from_date_model(
        cls,
        date_model: DatasetDateModel,
        mode: str,
    ) -> ManualActionTimeModeResponse | None:
        if mode == "none":
            return cls._none_mode_response(description="不填写日期，按该维护对象的默认 no-time 语义执行。")

        selection_rule = cls._selection_rule(date_model)
        natural_day_mode = date_model.date_axis == "natural_day" or date_model.input_shape == "ann_date_or_start_end"
        point_date_field = "ann_date" if date_model.input_shape == "ann_date_or_start_end" else "trade_date"

        if mode == "point":
            if date_model.input_shape == "month_or_range":
                return cls._mode_response(
                    mode="point",
                    label="只处理一个月",
                    description="指定单个月份。",
                    control="month",
                    selection_rule=selection_rule,
                )
            if date_model.window_mode not in {"point", "point_or_range"}:
                return None
            return cls._mode_response(
                mode="point",
                label="只处理一天",
                description="指定单个日期。",
                control="calendar_date" if natural_day_mode else "trade_date",
                selection_rule=selection_rule,
                date_field=point_date_field,
            )

        if mode == "range":
            if date_model.input_shape == "month_or_range":
                return cls._mode_response(
                    mode="range",
                    label="处理一个月份区间",
                    description="指定开始月份和结束月份。",
                    control="month_range",
                    selection_rule=selection_rule,
                )
            if date_model.input_shape == "start_end_month_window":
                return cls._mode_response(
                    mode="range",
                    label="处理一个自然月窗口",
                    description="指定开始月份和结束月份，系统会自动换算为自然月日期区间。",
                    control="month_window_range",
                    selection_rule=selection_rule,
                )
            if date_model.window_mode not in {"range", "point_or_range"}:
                return None
            return cls._mode_response(
                mode="range",
                label="处理一个时间区间",
                description="指定开始日期和结束日期。",
                control="calendar_date_range" if natural_day_mode else "trade_date_range",
                selection_rule=selection_rule,
                date_field=point_date_field,
            )
        return None

    @staticmethod
    def _selection_rule(date_model: DatasetDateModel) -> str:
        return date_model.selection_rule()

    @staticmethod
    def _field_to_action_parameter(
        field: DatasetInputField,
        *,
        enum_fanout_defaults: dict[str, tuple[str, ...]],
    ) -> ActionParameter:
        return ActionParameter(
            key=field.name,
            display_name=field.display_label,
            param_type=field.input_control_type,
            description=field.description,
            required=field.required,
            options=tuple(field.enum_values),
            multi_value=field.multi_value,
            default_value=dataset_field_default_value(field, enum_fanout_defaults),
        )

    @staticmethod
    def _to_date_model_response(date_model: DatasetDateModel | None) -> ManualActionDateModelResponse | None:
        if date_model is None:
            return None
        return ManualActionDateModelResponse(
            date_axis=date_model.date_axis,
            bucket_rule=date_model.bucket_rule,
            window_mode=date_model.window_mode,
            input_shape=date_model.input_shape,
            observed_field=date_model.observed_field,
            audit_applicable=date_model.audit_applicable,
            not_applicable_reason=date_model.not_applicable_reason,
        )

    @staticmethod
    def _to_param_response(param: ActionParameter) -> ActionParameterResponse:
        return ActionParameterResponse(
            key=param.key,
            display_name=param.display_name,
            param_type=param.param_type,
            description=param.description,
            required=param.required,
            options=list(param.options),
            multi_value=param.multi_value,
            default_value=param.default_value,
        )

    def _to_response_item(self, route: ManualActionRoute) -> ManualActionItemResponse:
        keywords = [route.action_key, route.display_name]
        if route.resource_key:
            keywords.append(route.resource_key)
        if route.resource_display_name:
            keywords.append(route.resource_display_name)
        return ManualActionItemResponse(
            action_key=route.action_key,
            action_type=route.action_type,
            display_name=route.display_name,
            description=route.description,
            resource_key=route.resource_key,
            resource_display_name=route.resource_display_name,
            date_model=self._to_date_model_response(route.date_model),
            time_form=route.time_form,
            filters=[self._to_param_response(param) for param in route.filters],
            search_keywords=list(dict.fromkeys(keywords)),
            action_order=route.action_order,
        )
