from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.ops.action_catalog import (
    ActionParameter,
    WORKFLOW_DOMAIN_KEY,
    WORKFLOW_DOMAIN_DISPLAY_NAME,
    WORKFLOW_GROUP_ORDER,
    WorkflowDefinition,
    dataset_field_default_value,
    list_workflow_definitions,
)
from src.foundation.datasets.models import DatasetDateModel, DatasetDefinition, DatasetInputField
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.schemas.catalog import ActionParameterResponse
from src.ops.schemas.manual_action import (
    ManualActionDateModelResponse,
    ManualActionGroupResponse,
    ManualActionItemResponse,
    ManualActionListResponse,
    ManualActionTimeFormResponse,
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

GROUP_CONFIG = {
    "reference_data": ("reference_data", "基础主数据", 10),
    "equity_market": ("equity_market", "股票行情", 20),
    "equity": ("equity_market", "股票行情", 20),
    "moneyflow": ("moneyflow", "资金流向", 30),
    "index_fund": ("index_fund", "指数 / ETF", 40),
    "fund": ("index_fund", "指数 / ETF", 40),
    "index": ("index_fund", "指数 / ETF", 40),
    "board_theme": ("board_theme", "板块 / 题材", 50),
    "board": ("board_theme", "板块 / 题材", 50),
    "ranking": ("event_stats", "榜单 / 事件", 60),
    "event": ("event_stats", "榜单 / 事件", 60),
    "low_frequency": ("event_stats", "榜单 / 事件", 60),
    WORKFLOW_DOMAIN_KEY: (WORKFLOW_DOMAIN_KEY, WORKFLOW_DOMAIN_DISPLAY_NAME, WORKFLOW_GROUP_ORDER),
    "other": ("other", "其他", 90),
}

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
        group_key, group_label, group_order = self._group_meta_for_definition(definition)
        action_key = definition.action_key("maintain")
        display_name = definition.action_display_name("maintain")
        filters = self._collect_dataset_filters(
            definition.input_model.filters,
            enum_fanout_defaults=definition.planning.enum_fanout_defaults,
        )
        action = definition.capabilities.get_action("maintain")
        supported_modes = set(action.supported_time_modes if action else ())
        time_form = self._time_form_from_date_model(
            date_model,
            supports_point_route="point" in supported_modes,
            supports_range_route="range" in supported_modes,
        )
        return ManualActionRoute(
            action_key=action_key,
            action_type="dataset_action",
            group_key=group_key,
            group_label=group_label,
            group_order=group_order,
            action_order=100,
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
            time_form=self._time_form_from_params(workflow.parameters),
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
    def _time_form_from_params(params: Iterable[ActionParameter]) -> ManualActionTimeFormResponse:
        keys = {param.key for param in params}
        allowed_modes: list[str] = []
        control = "none"
        selection_rule = "none"
        if "trade_date" in keys:
            control = "trade_date_or_range"
            selection_rule = "trading_day_only"
            allowed_modes.append("point")
        if {"start_date", "end_date"}.issubset(keys):
            control = "trade_date_or_range"
            selection_rule = "trading_day_only"
            allowed_modes.append("range")
        if "month" in keys:
            control = "month_or_range"
            selection_rule = "month_key"
            allowed_modes.append("point")
        if {"start_month", "end_month"}.issubset(keys):
            control = "month_or_range"
            selection_rule = "month_key"
            allowed_modes.append("range")
        if not allowed_modes:
            allowed_modes = ["none"]
        return ManualActionTimeFormResponse(
            control=control,
            default_mode=allowed_modes[0],
            allowed_modes=allowed_modes,
            selection_rule=selection_rule,
            point_label="只处理一天" if control != "month_or_range" else "只处理一个月",
            range_label="处理一个时间区间" if control != "month_or_range" else "处理一个月份区间",
        )

    @staticmethod
    def _time_form_from_date_model(
        date_model: DatasetDateModel,
        *,
        supports_point_route: bool,
        supports_range_route: bool,
    ) -> ManualActionTimeFormResponse:
        if date_model.input_shape == "none" or date_model.window_mode == "none":
            return ManualActionTimeFormResponse(
                control="none",
                default_mode="none",
                allowed_modes=["none"],
                selection_rule="none",
                point_label="",
                range_label="",
            )

        if date_model.input_shape == "month_or_range":
            control = "month_or_range"
            point_label = "只处理一个月"
            range_label = "处理一个月份区间"
        elif date_model.input_shape == "start_end_month_window":
            control = "month_window_range"
            point_label = ""
            range_label = "处理一个自然月窗口"
        elif date_model.date_axis == "natural_day" or date_model.input_shape == "ann_date_or_start_end":
            control = "calendar_date_or_range"
            point_label = "只处理一天"
            range_label = "处理一个时间区间"
        else:
            control = "trade_date_or_range"
            point_label = "只处理一天"
            range_label = "处理一个时间区间"

        allowed_modes: list[str] = []
        if date_model.window_mode in {"point", "point_or_range"} and supports_point_route:
            allowed_modes.append("point")
        if date_model.window_mode in {"range", "point_or_range"} and supports_range_route:
            allowed_modes.append("range")
        if not allowed_modes:
            allowed_modes = ["none"]

        return ManualActionTimeFormResponse(
            control=control,
            default_mode=allowed_modes[0],
            allowed_modes=allowed_modes,
            selection_rule=ManualActionQueryService._selection_rule(date_model),
            point_label=point_label,
            range_label=range_label,
        )

    @staticmethod
    def _selection_rule(date_model: DatasetDateModel) -> str:
        return date_model.selection_rule()

    @staticmethod
    def _group_meta_for_definition(definition: DatasetDefinition) -> tuple[str, str, int]:
        return GROUP_CONFIG.get(definition.domain.domain_key, GROUP_CONFIG["other"])

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
