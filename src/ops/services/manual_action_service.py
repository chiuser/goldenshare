from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.ops.queries.manual_action_query_service import ManualActionQueryService, ManualActionRoute
from src.ops.schemas.manual_action import ManualActionExecutionCreateRequest, ManualActionTimeInput
from src.ops.services.execution_service import OpsExecutionCommandService
from src.ops.specs import JobSpec, ParameterSpec


class ManualActionCommandService:
    def __init__(self) -> None:
        self.query_service = ManualActionQueryService()
        self.execution_service = OpsExecutionCommandService()

    def create_execution_for_action(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        action_key: str,
        body: ManualActionExecutionCreateRequest,
    ) -> int:
        route = self.query_service.get_action_route(action_key)
        if route is None:
            raise WebAppError(status_code=404, code="not_found", message="Manual action does not exist")
        spec_type, spec_key, params_json = ManualActionExecutionResolver(route).resolve(body)
        return self.execution_service.create_manual_execution(
            session,
            user=user,
            spec_type=spec_type,
            spec_key=spec_key,
            params_json=params_json,
        )


class ManualActionExecutionResolver:
    def __init__(self, route: ManualActionRoute) -> None:
        self.route = route

    def resolve(self, body: ManualActionExecutionCreateRequest) -> tuple[str, str, dict[str, Any]]:
        filters = self._normalize_filters(body.filters)
        time_input = body.time_input
        mode = (time_input.mode or "none").strip()
        if mode not in self.route.time_form.allowed_modes:
            raise WebAppError(status_code=422, code="validation_error", message=f"Unsupported time mode: {mode}")

        time_params, spec_key = self._resolve_time_and_spec(mode=mode, time_input=time_input)
        params_json = {**filters, **time_params}
        if self.route.action_type == "workflow":
            workflow_spec = self.route.workflow_spec
            if workflow_spec is None:
                raise WebAppError(status_code=422, code="validation_error", message="Manual action workflow route is not configured")
            return "workflow", workflow_spec.key, params_json
        return "job", spec_key, params_json

    def _resolve_time_and_spec(self, *, mode: str, time_input: ManualActionTimeInput) -> tuple[dict[str, Any], str]:
        if self.route.action_type == "workflow":
            return self._resolve_workflow_time(mode=mode, time_input=time_input), self.route.workflow_spec.key if self.route.workflow_spec else ""

        if mode == "none":
            return {}, self._require_no_time_job_spec()
        if mode == "point":
            return self._resolve_point_time(time_input)
        if mode == "range":
            return self._resolve_range_time(time_input)
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

    def _resolve_point_time(self, time_input: ManualActionTimeInput) -> tuple[dict[str, Any], str]:
        input_shape = self._input_shape()
        if input_shape == "month_or_range":
            month = self._require_month(time_input.month, "month")
            if self.route.sync_daily_spec is not None:
                return {"month": month}, self.route.sync_daily_spec.key
            if self.route.direct_spec is not None and "month" in self._param_keys(self.route.direct_spec):
                return {"month": month}, self.route.direct_spec.key
            if self.route.backfill_spec is not None:
                return {"start_month": month, "end_month": month}, self.route.backfill_spec.key
        if input_shape in {"trade_date_or_start_end", "ann_date_or_start_end"}:
            param_key = "ann_date" if input_shape == "ann_date_or_start_end" else "trade_date"
            point_date = self._require_date_text(getattr(time_input, param_key), param_key)
            if self.route.sync_daily_spec is not None:
                return {param_key: point_date}, self.route.sync_daily_spec.key
            if self.route.direct_spec is not None and param_key in self._param_keys(self.route.direct_spec):
                return {param_key: point_date}, self.route.direct_spec.key
            if self.route.backfill_spec is not None and {"start_date", "end_date"}.issubset(self._param_keys(self.route.backfill_spec)):
                return {"start_date": point_date, "end_date": point_date}, self.route.backfill_spec.key
        raise WebAppError(status_code=422, code="validation_error", message="Current action does not support point time input")

    def _resolve_range_time(self, time_input: ManualActionTimeInput) -> tuple[dict[str, Any], str]:
        input_shape = self._input_shape()
        if input_shape == "month_or_range":
            start_month = self._require_month(time_input.start_month, "start_month")
            end_month = self._require_month(time_input.end_month, "end_month")
            self._validate_month_order(start_month, end_month)
            spec_key = self._prefer_backfill_then_direct()
            return {"start_month": start_month, "end_month": end_month}, spec_key
        if input_shape == "start_end_month_window":
            start_month = self._require_month(time_input.start_month, "start_month")
            end_month = self._require_month(time_input.end_month, "end_month")
            self._validate_month_order(start_month, end_month)
            spec_key = self._prefer_backfill_then_direct()
            return {
                "start_date": self._month_start_date(start_month),
                "end_date": self._month_end_date(end_month),
            }, spec_key
        if input_shape in {"trade_date_or_start_end", "ann_date_or_start_end"}:
            start_date = self._require_date_text(time_input.start_date, "start_date")
            end_date = self._require_date_text(time_input.end_date, "end_date")
            self._validate_date_order(start_date, end_date)
            if input_shape == "ann_date_or_start_end" and self.route.direct_spec is not None:
                return {"start_date": start_date, "end_date": end_date}, self.route.direct_spec.key
            return {"start_date": start_date, "end_date": end_date}, self._prefer_backfill_then_direct()
        raise WebAppError(status_code=422, code="validation_error", message="Current action does not support range time input")

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

    def _require_no_time_job_spec(self) -> str:
        if self.route.direct_spec is not None:
            return self.route.direct_spec.key
        if self.route.backfill_spec is not None:
            return self.route.backfill_spec.key
        if self.route.sync_daily_spec is not None:
            return self.route.sync_daily_spec.key
        raise WebAppError(status_code=422, code="validation_error", message="Current action is not executable")

    def _prefer_backfill_then_direct(self) -> str:
        if self.route.backfill_spec is not None:
            return self.route.backfill_spec.key
        if self.route.direct_spec is not None:
            return self.route.direct_spec.key
        raise WebAppError(status_code=422, code="validation_error", message="Current action does not support range time input")

    @staticmethod
    def _param_keys(spec: JobSpec | None) -> set[str]:
        if spec is None:
            return set()
        return {param.key for param in spec.supported_params}

    @staticmethod
    def _require_date_text(value: str | None, field: str) -> str:
        if not value:
            raise WebAppError(status_code=422, code="validation_error", message=f"{field} is required")
        parsed = ManualActionExecutionResolver._parse_date(value, field)
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
        if ManualActionExecutionResolver._parse_date(start_date, "start_date") > ManualActionExecutionResolver._parse_date(end_date, "end_date"):
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
