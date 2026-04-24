from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.foundation.services.sync_v2.contracts import DatasetDateModel
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.ops.schemas.catalog import ParameterSpecResponse
from src.ops.schemas.manual_action import (
    ManualActionDateModelResponse,
    ManualActionGroupResponse,
    ManualActionItemResponse,
    ManualActionListResponse,
    ManualActionTimeFormResponse,
)
from src.ops.specs import JobSpec, ParameterSpec, WorkflowSpec, get_dataset_freshness_spec, list_job_specs, list_workflow_specs


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
    "equity": ("equity_market", "股票行情", 20),
    "moneyflow": ("moneyflow", "资金流向", 30),
    "fund": ("index_fund", "指数 / ETF", 40),
    "index": ("index_fund", "指数 / ETF", 40),
    "board": ("board_theme", "板块 / 题材", 50),
    "ranking": ("event_stats", "榜单 / 事件", 60),
    "event": ("event_stats", "榜单 / 事件", 60),
    "workflow": ("workflow", "工作流", 80),
    "other": ("other", "其他", 90),
}

BACKFILL_PRIORITY = {
    "backfill_equity_series": 90,
    "backfill_index_series": 90,
    "backfill_fund_series": 90,
    "backfill_by_month": 80,
    "backfill_trade_cal": 80,
    "backfill_by_date_range": 75,
    "backfill_by_trade_date": 70,
    "backfill_low_frequency": 20,
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
    sync_daily_spec: JobSpec | None = None
    backfill_spec: JobSpec | None = None
    direct_spec: JobSpec | None = None
    workflow_spec: WorkflowSpec | None = None


@dataclass(slots=True)
class _ResourceActionDraft:
    resource_key: str
    resource_display_name: str | None
    description: str
    sync_daily_spec: JobSpec | None = None
    backfill_spec: JobSpec | None = None
    direct_spec: JobSpec | None = None

    def route_specs(self) -> list[JobSpec]:
        specs: list[JobSpec] = []
        for item in (self.sync_daily_spec, self.backfill_spec, self.direct_spec):
            if item is not None and item.key not in {spec.key for spec in specs}:
                specs.append(item)
        return specs


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
        routes = [self._build_resource_route(draft) for draft in self._build_resource_drafts()]
        routes.extend(self._build_workflow_route(workflow) for workflow in list_workflow_specs() if workflow.supports_manual_run)
        return sorted(routes, key=lambda item: (item.group_order, item.action_order, item.display_name))

    def get_action_route(self, action_key: str) -> ManualActionRoute | None:
        return next((route for route in self.build_action_routes() if route.action_key == action_key), None)

    def _build_resource_drafts(self) -> list[_ResourceActionDraft]:
        drafts: dict[str, _ResourceActionDraft] = {}
        for job_spec in list_job_specs():
            if not job_spec.supports_manual_run:
                continue
            if "." not in job_spec.key:
                continue
            prefix, resource_key = job_spec.key.split(".", 1)
            if prefix == "maintenance":
                continue

            draft = drafts.get(resource_key)
            freshness_spec = get_dataset_freshness_spec(resource_key)
            if draft is None:
                draft = _ResourceActionDraft(
                    resource_key=resource_key,
                    resource_display_name=freshness_spec.display_name if freshness_spec is not None else None,
                    description=job_spec.description,
                )
                drafts[resource_key] = draft
            elif not draft.resource_display_name and freshness_spec is not None:
                draft.resource_display_name = freshness_spec.display_name

            if prefix == "sync_daily":
                draft.sync_daily_spec = job_spec
            elif prefix.startswith("backfill_"):
                draft.backfill_spec = self._select_backfill_spec(draft.backfill_spec, job_spec)
            else:
                draft.direct_spec = job_spec

            if draft.description.startswith("执行资源 ") or not draft.description:
                draft.description = job_spec.description

        return sorted(drafts.values(), key=lambda item: (self._group_meta_for_resource(item.resource_key)[2], self._display_name_for_resource(item)))

    def _build_resource_route(self, draft: _ResourceActionDraft) -> ManualActionRoute:
        contract = get_sync_v2_contract(draft.resource_key)
        date_model = contract.date_model
        group_key, group_label, group_order = self._group_meta_for_resource(draft.resource_key)
        display_name = f"维护{self._display_name_for_resource(draft)}"
        specs = draft.route_specs()
        filters = self._collect_filters(spec.supported_params for spec in specs)
        time_form = self._time_form_from_date_model(
            date_model,
            supports_point_route=self._resource_supports_point_route(draft, date_model),
            supports_range_route=self._resource_supports_range_route(draft, date_model),
        )
        return ManualActionRoute(
            action_key=draft.resource_key,
            action_type="job",
            group_key=group_key,
            group_label=group_label,
            group_order=group_order,
            action_order=100,
            display_name=display_name,
            description=draft.description,
            resource_key=draft.resource_key,
            resource_display_name=self._display_name_for_resource(draft),
            date_model=date_model,
            time_form=time_form,
            filters=filters,
            route_spec_keys=tuple(spec.key for spec in specs),
            sync_daily_spec=draft.sync_daily_spec,
            backfill_spec=draft.backfill_spec,
            direct_spec=draft.direct_spec,
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
    def _select_backfill_spec(current: JobSpec | None, candidate: JobSpec) -> JobSpec:
        if current is None:
            return candidate
        current_priority = BACKFILL_PRIORITY.get(current.category, 0)
        candidate_priority = BACKFILL_PRIORITY.get(candidate.category, 0)
        if candidate_priority > current_priority:
            return candidate
        if candidate_priority == current_priority and candidate.key < current.key:
            return candidate
        return current

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
    def _param_keys(spec: JobSpec | WorkflowSpec | None) -> set[str]:
        if spec is None:
            return set()
        return {param.key for param in spec.supported_params}

    def _resource_supports_point_route(self, draft: _ResourceActionDraft, date_model: DatasetDateModel) -> bool:
        if date_model.input_shape == "none":
            return True
        if draft.sync_daily_spec is not None:
            return True
        if date_model.input_shape == "month_or_range" and draft.backfill_spec is not None:
            return {"start_month", "end_month"}.issubset(self._param_keys(draft.backfill_spec))
        if date_model.input_shape in {"trade_date_or_start_end", "ann_date_or_start_end"}:
            if draft.direct_spec is not None and {"trade_date", "ann_date"} & self._param_keys(draft.direct_spec):
                return True
            if draft.backfill_spec is not None and {"start_date", "end_date"}.issubset(self._param_keys(draft.backfill_spec)):
                return True
        return False

    def _resource_supports_range_route(self, draft: _ResourceActionDraft, date_model: DatasetDateModel) -> bool:
        if date_model.input_shape == "none":
            return True
        if draft.backfill_spec is not None:
            backfill_keys = self._param_keys(draft.backfill_spec)
            if date_model.input_shape == "month_or_range":
                if {"start_month", "end_month"}.issubset(backfill_keys):
                    return True
            elif {"start_date", "end_date"}.issubset(backfill_keys):
                return True
        if draft.direct_spec is not None:
            return {"start_date", "end_date"}.issubset(self._param_keys(draft.direct_spec))
        return False

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
    def _group_meta_for_resource(resource_key: str) -> tuple[str, str, int]:
        freshness_spec = get_dataset_freshness_spec(resource_key)
        if freshness_spec is None:
            return GROUP_CONFIG["other"]
        return GROUP_CONFIG.get(freshness_spec.domain_key, GROUP_CONFIG["other"])

    @staticmethod
    def _display_name_for_resource(draft: _ResourceActionDraft) -> str:
        return draft.resource_display_name or draft.resource_key

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
