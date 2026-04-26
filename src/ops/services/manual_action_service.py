from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.foundation.services.sync_v2.dataset_strategies.dc_hot import (
    DC_HOT_DEFAULT_HOT_TYPES,
    DC_HOT_DEFAULT_IS_NEW,
    DC_HOT_DEFAULT_MARKETS,
)
from src.ops.queries.manual_action_query_service import ManualActionQueryService, ManualActionRoute
from src.ops.schemas.manual_action import ManualActionTaskRunCreateRequest, ManualActionTimeInput
from src.ops.services.task_run_service import TaskRunCommandService
from src.ops.specs import ParameterSpec


class ManualActionCommandService:
    def __init__(self) -> None:
        self.query_service = ManualActionQueryService()
        self.task_run_service = TaskRunCommandService()

    def create_task_run_for_action(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        action_key: str,
        body: ManualActionTaskRunCreateRequest,
    ) -> int:
        route = self.query_service.get_action_route(action_key)
        if route is None:
            raise WebAppError(status_code=404, code="not_found", message="Manual action does not exist")
        spec_type, spec_key, params_json = ManualActionTaskRunResolver(route).resolve(body)
        task_run = self.task_run_service.create_from_spec(
            session,
            spec_type=spec_type,
            spec_key=spec_key,
            params_json=params_json,
            trigger_source="manual",
            requested_by_user_id=user.id,
        )
        return task_run.id


class ManualActionTaskRunResolver:
    def __init__(self, route: ManualActionRoute) -> None:
        self.route = route

    def resolve(self, body: ManualActionTaskRunCreateRequest) -> tuple[str, str, dict[str, Any]]:
        filters = self._normalize_filters(body.filters)
        filters = self._apply_default_filters(filters)
        time_input = body.time_input
        mode = (time_input.mode or "none").strip()
        if mode not in self.route.time_form.allowed_modes:
            raise WebAppError(status_code=422, code="validation_error", message=f"Unsupported time mode: {mode}")

        if self.route.action_type == "dataset_action":
            time_params = self._resolve_dataset_action_time(mode=mode, time_input=time_input)
            params_json = {
                **filters,
                **time_params,
                "dataset_key": self.route.resource_key,
                "action": "maintain",
                "time_input": {"mode": mode, **time_params},
                "filters": filters,
            }
            if self.route.resource_key is None:
                raise WebAppError(status_code=422, code="validation_error", message="Manual action resource route is not configured")
            return "dataset_action", f"{self.route.resource_key}.maintain", params_json

        if self.route.action_type == "workflow":
            workflow_spec = self.route.workflow_spec
            if workflow_spec is None:
                raise WebAppError(status_code=422, code="validation_error", message="Manual action workflow route is not configured")
            params_json = {**filters, **self._resolve_workflow_time(mode=mode, time_input=time_input)}
            return "workflow", workflow_spec.key, params_json
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported manual action type")

    def _resolve_dataset_action_time(self, *, mode: str, time_input: ManualActionTimeInput) -> dict[str, Any]:
        if mode == "none":
            return {}
        input_shape = self._input_shape()
        if mode == "point":
            if input_shape == "month_or_range":
                return {"month": self._require_month(time_input.month, "month")}
            param_key = "ann_date" if input_shape == "ann_date_or_start_end" else "trade_date"
            return {param_key: self._require_date_text(getattr(time_input, param_key), param_key)}
        if mode == "range":
            if input_shape == "month_or_range":
                start_month = self._require_month(time_input.start_month, "start_month")
                end_month = self._require_month(time_input.end_month, "end_month")
                self._validate_month_order(start_month, end_month)
                return {"start_month": start_month, "end_month": end_month}
            if input_shape == "start_end_month_window":
                start_month = self._require_month(time_input.start_month, "start_month")
                end_month = self._require_month(time_input.end_month, "end_month")
                self._validate_month_order(start_month, end_month)
                return {
                    "start_date": self._month_start_date(start_month),
                    "end_date": self._month_end_date(end_month),
                }
            start_date = self._require_date_text(time_input.start_date, "start_date")
            end_date = self._require_date_text(time_input.end_date, "end_date")
            self._validate_date_order(start_date, end_date)
            return {"start_date": start_date, "end_date": end_date}
        raise WebAppError(status_code=422, code="validation_error", message=f"Unsupported time mode: {mode}")

    def _resolve_workflow_time(self, *, mode: str, time_input: ManualActionTimeInput) -> dict[str, Any]:
        if mode == "none":
            return {}
        if mode == "point":
            if self.route.time_form.control == "month_or_range":
                return {"month": self._require_month(time_input.month, "month")}
            return {"trade_date": self._require_date_text(time_input.trade_date, "trade_date")}
        if mode == "range":
            if self.route.time_form.control == "month_or_range":
                start_month = self._require_month(time_input.start_month, "start_month")
                end_month = self._require_month(time_input.end_month, "end_month")
                self._validate_month_order(start_month, end_month)
                return {"start_month": start_month, "end_month": end_month}
            start_date = self._require_date_text(time_input.start_date, "start_date")
            end_date = self._require_date_text(time_input.end_date, "end_date")
            self._validate_date_order(start_date, end_date)
            return {"start_date": start_date, "end_date": end_date}
        return {}

    def _normalize_filters(self, raw_filters: dict[str, Any]) -> dict[str, Any]:
        allowed = {param.key: param for param in self.route.filters}
        normalized: dict[str, Any] = {}
        for key, value in (raw_filters or {}).items():
            if self._is_empty(value):
                continue
            param = allowed.get(key)
            if param is None:
                raise WebAppError(status_code=422, code="validation_error", message=f"Unsupported filter: {key}")
            normalized_value = self._normalize_filter_value(param, value)
            if self._is_empty(normalized_value):
                continue
            normalized[key] = normalized_value
        return normalized

    def _apply_default_filters(self, filters: dict[str, Any]) -> dict[str, Any]:
        if self.route.resource_key != "dc_hot":
            return filters
        with_defaults = dict(filters)
        self._fill_default_filter(with_defaults, "market", DC_HOT_DEFAULT_MARKETS)
        self._fill_default_filter(with_defaults, "hot_type", DC_HOT_DEFAULT_HOT_TYPES)
        self._fill_default_filter(with_defaults, "is_new", DC_HOT_DEFAULT_IS_NEW)
        return with_defaults

    @staticmethod
    def _fill_default_filter(filters: dict[str, Any], key: str, values: tuple[str, ...]) -> None:
        current = filters.get(key)
        if current in (None, "", []):
            filters[key] = list(values) if len(values) > 1 else values[0]

    def _normalize_filter_value(self, param: ParameterSpec, value: Any) -> Any:
        if param.multi_value:
            if isinstance(value, list):
                values = [str(item).strip() for item in value if str(item).strip()]
            else:
                values = [item.strip() for item in str(value).split(",") if item.strip()]
            self._validate_options(param, values)
            return values
        single_value = value[0] if isinstance(value, list) and value else value
        if param.param_type == "integer":
            try:
                return int(single_value)
            except (TypeError, ValueError) as exc:
                raise WebAppError(status_code=422, code="validation_error", message=f"Invalid integer filter: {param.key}") from exc
        text = str(single_value).strip()
        self._validate_options(param, [text])
        return text

    @staticmethod
    def _validate_options(param: ParameterSpec, values: list[str]) -> None:
        if not param.options:
            return
        invalid = [value for value in values if value not in param.options]
        if invalid:
            raise WebAppError(status_code=422, code="validation_error", message=f"Invalid option for {param.key}: {invalid[0]}")

    def _input_shape(self) -> str:
        if self.route.date_model is None:
            return self.route.time_form.control
        return self.route.date_model.input_shape

    @staticmethod
    def _require_date_text(value: str | None, field: str) -> str:
        if not value:
            raise WebAppError(status_code=422, code="validation_error", message=f"{field} is required")
        parsed = ManualActionTaskRunResolver._parse_date(value, field)
        return parsed.isoformat()

    @staticmethod
    def _require_month(value: str | None, field: str) -> str:
        if not value:
            raise WebAppError(status_code=422, code="validation_error", message=f"{field} is required")
        cleaned = value.strip().replace("-", "")
        if len(cleaned) != 6 or not cleaned.isdigit():
            raise WebAppError(status_code=422, code="validation_error", message=f"{field} must be YYYY-MM or YYYYMM")
        month = int(cleaned[4:6])
        if month < 1 or month > 12:
            raise WebAppError(status_code=422, code="validation_error", message=f"{field} must be a valid month")
        return cleaned

    @staticmethod
    def _validate_date_order(start_date: str, end_date: str) -> None:
        if ManualActionTaskRunResolver._parse_date(start_date, "start_date") > ManualActionTaskRunResolver._parse_date(end_date, "end_date"):
            raise WebAppError(status_code=422, code="validation_error", message="start_date must be <= end_date")

    @staticmethod
    def _validate_month_order(start_month: str, end_month: str) -> None:
        if int(start_month) > int(end_month):
            raise WebAppError(status_code=422, code="validation_error", message="start_month must be <= end_month")

    @staticmethod
    def _parse_date(value: str, field: str) -> date:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise WebAppError(status_code=422, code="validation_error", message=f"{field} must be YYYY-MM-DD") from exc

    @staticmethod
    def _month_start_date(month: str) -> str:
        year = int(month[:4])
        month_value = int(month[4:6])
        return date(year, month_value, 1).isoformat()

    @staticmethod
    def _month_end_date(month: str) -> str:
        year = int(month[:4])
        month_value = int(month[4:6])
        return date(year, month_value, monthrange(year, month_value)[1]).isoformat()

    @staticmethod
    def _is_empty(value: Any) -> bool:
        return value is None or value == "" or value == []
