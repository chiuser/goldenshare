from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.foundation.datasets.models import DatasetDefinition, DatasetInputField
from src.foundation.datasets.registry import list_dataset_definitions
from src.foundation.services.sync_v2.contracts import DatasetDateModel
from src.ops.schemas.catalog import ParameterSpecResponse
from src.ops.schemas.manual_action import (
    ManualActionDateModelResponse,
    ManualActionGroupResponse,
    ManualActionItemResponse,
    ManualActionListResponse,
    ManualActionTimeFormResponse,
)
from src.ops.specs import ParameterSpec, WorkflowSpec, list_workflow_specs


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
    "workflow": ("workflow", "工作流", 80),
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
    filters: tuple[ParameterSpec, ...]
    route_spec_keys: tuple[str, ...]
    workflow_spec: WorkflowSpec | None = None


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
        routes.extend(self._build_workflow_route(workflow) for workflow in list_workflow_specs() if workflow.supports_manual_run)
        return sorted(routes, key=lambda item: (item.group_order, item.action_order, item.display_name))

    def get_action_route(self, action_key: str) -> ManualActionRoute | None:
        return next((route for route in self.build_action_routes() if route.action_key == action_key), None)

    def _build_resource_route(self, definition: DatasetDefinition) -> ManualActionRoute:
        date_model = definition.date_model
        group_key, group_label, group_order = self._group_meta_for_definition(definition)
        display_name = f"维护{definition.display_name}"
        filters = self._collect_dataset_filters(definition.input_model.filters)
        action = definition.capabilities.get_action("maintain")
        supported_modes = set(action.supported_time_modes if action else ())
        time_form = self._time_form_from_date_model(
            date_model,
            supports_point_route="point" in supported_modes,
            supports_range_route="range" in supported_modes,
        )
        return ManualActionRoute(
            action_key=definition.dataset_key,
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
            route_spec_keys=(f"{definition.dataset_key}.maintain",),
        )

    def _build_workflow_route(self, workflow: WorkflowSpec) -> ManualActionRoute:
        group_key, group_label, group_order = GROUP_CONFIG["workflow"]
        return ManualActionRoute(
            action_key=f"workflow:{workflow.key}",
            action_type="workflow",
            group_key=group_key,
            group_label=group_label,
            group_order=group_order,
            action_order=100,
            display_name=workflow.display_name,
            description=workflow.description,
            resource_key=None,
            resource_display_name=None,
            date_model=None,
            time_form=self._time_form_from_params(workflow.supported_params),
            filters=self._collect_filters((workflow.supported_params,)),
            route_spec_keys=(workflow.key,),
            workflow_spec=workflow,
        )

    @staticmethod
    def _collect_filters(param_sets: Iterable[Iterable[ParameterSpec]]) -> tuple[ParameterSpec, ...]:
        filters: dict[str, ParameterSpec] = {}
        for params in param_sets:
            for param in params:
                if param.key in TIME_PARAM_KEYS or param.key in INTERNAL_PARAM_KEYS:
                    continue
                if param.key not in filters:
                    filters[param.key] = param
        return tuple(filters.values())

    @staticmethod
    def _collect_dataset_filters(fields: Iterable[DatasetInputField]) -> tuple[ParameterSpec, ...]:
        filters: dict[str, ParameterSpec] = {}
        for field in fields:
            if field.name in TIME_PARAM_KEYS or field.name in INTERNAL_PARAM_KEYS:
                continue
            filters[field.name] = ManualActionQueryService._field_to_param_spec(field)
        return tuple(filters.values())

    @staticmethod
    def _time_form_from_params(params: Iterable[ParameterSpec]) -> ManualActionTimeFormResponse:
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
        if date_model.bucket_rule == "week_last_open_day":
            return "week_last_trading_day"
        if date_model.bucket_rule == "month_last_open_day":
            return "month_last_trading_day"
        if date_model.bucket_rule == "every_natural_day":
            return "calendar_day"
        if date_model.bucket_rule == "every_natural_month":
            return "month_key"
        if date_model.bucket_rule == "month_window_has_data":
            return "month_window"
        if date_model.bucket_rule == "not_applicable":
            return "none"
        return "trading_day_only"

    @staticmethod
    def _group_meta_for_definition(definition: DatasetDefinition) -> tuple[str, str, int]:
        return GROUP_CONFIG.get(definition.domain.domain_key, GROUP_CONFIG["other"])

    @staticmethod
    def _field_to_param_spec(field: DatasetInputField) -> ParameterSpec:
        return ParameterSpec(
            key=field.name,
            display_name=ManualActionQueryService._field_display_name(field.name),
            param_type=ManualActionQueryService._field_param_type(field),
            description=field.description,
            required=field.required,
            options=tuple(field.enum_values),
            multi_value=field.multi_value,
        )

    @staticmethod
    def _field_param_type(field: DatasetInputField) -> str:
        if field.name in {"month", "start_month", "end_month"}:
            return "month"
        if field.field_type == "date" or field.name.endswith("_date") or field.name in {"date", "cal_date"}:
            return "date"
        if field.field_type in {"integer", "int"}:
            return "integer"
        if field.field_type in {"boolean", "bool"}:
            return "boolean"
        if field.enum_values:
            return "enum"
        return "string"

    @staticmethod
    def _field_display_name(field_name: str) -> str:
        labels = {
            "ts_code": "证券代码",
            "index_code": "指数代码",
            "con_code": "板块代码",
            "market": "市场",
            "hot_type": "热点类型",
            "is_new": "日终标记",
            "limit_type": "榜单类型",
            "exchange": "交易所",
            "exchange_id": "交易所",
            "content_type": "板块类型",
            "tag": "榜单标签",
            "date_field": "日期字段",
            "suspend_type": "停复牌类型",
            "idx_type": "板块类型",
            "type": "指数类型",
            "list_status": "上市状态",
            "classify": "分类",
        }
        return labels.get(field_name, field_name)

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
    def _to_param_response(param: ParameterSpec) -> ParameterSpecResponse:
        return ParameterSpecResponse(
            key=param.key,
            display_name=param.display_name,
            param_type=param.param_type,
            description=param.description,
            required=param.required,
            options=list(param.options),
            multi_value=param.multi_value,
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
            route_spec_keys=list(route.route_spec_keys),
        )
