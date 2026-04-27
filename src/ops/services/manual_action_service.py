from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.exceptions import WebAppError
from src.ops.action_catalog import ActionParameter
from src.ops.queries.manual_action_query_service import ManualActionQueryService, ManualActionRoute
from src.ops.schemas.manual_action import ManualActionTaskRunCreateRequest, ManualActionTimeInput
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


@dataclass(frozen=True, slots=True)
class ResolvedManualTaskRun:
    task_type: str
    resource_key: str | None
    action: str
    time_input: dict[str, Any]
    filters: dict[str, Any]
    request_payload: dict[str, Any]
    target_type: str | None = None
    target_key: str | None = None


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
        resolved = ManualActionTaskRunResolver(route).resolve(body)
        if resolved.task_type == "workflow":
            if not resolved.target_type or not resolved.target_key:
                raise WebAppError(status_code=422, code="validation_error", message="Manual workflow route is not configured")
            task_run = self.task_run_service.create_from_schedule_target(
                session,
                target_type=resolved.target_type,
                target_key=resolved.target_key,
                params_json=resolved.request_payload,
                trigger_source="manual",
                requested_by_user_id=user.id,
            )
            return task_run.id
        task_run = self.task_run_service.create_task_run(
            session,
            context=TaskRunCreateContext(
                task_type=resolved.task_type,
                resource_key=resolved.resource_key,
                action=resolved.action,
                time_input=resolved.time_input,
                filters=resolved.filters,
                request_payload=resolved.request_payload,
                trigger_source="manual",
                requested_by_user_id=user.id,
            ),
        )
        return task_run.id


class ManualActionTaskRunResolver:
    def __init__(self, route: ManualActionRoute) -> None:
        self.route = route

    def resolve(self, body: ManualActionTaskRunCreateRequest) -> ResolvedManualTaskRun:
        filters = self._normalize_filters(body.filters)
        filters = self._apply_default_filters(filters)
        time_input = body.time_input
        mode = (time_input.mode or "none").strip()
        if mode not in self.route.time_form.allowed_modes:
            raise WebAppError(status_code=422, code="validation_error", message=f"不支持的时间模式：{mode}")

        if self.route.action_type == "dataset_action":
            time_params = self._resolve_dataset_action_time(mode=mode, time_input=time_input)
            if self.route.resource_key is None:
                raise WebAppError(status_code=422, code="validation_error", message="Manual action resource route is not configured")
            return ResolvedManualTaskRun(
                task_type="dataset_action",
                resource_key=self.route.resource_key,
                action="maintain",
                time_input=self._dataset_time_input_payload(mode=mode, time_params=time_params),
                filters=filters,
                request_payload={},
            )

        if self.route.action_type == "workflow":
            workflow = self.route.workflow
            if workflow is None:
                raise WebAppError(status_code=422, code="validation_error", message="Manual action workflow route is not configured")
            time_params = self._resolve_workflow_time(mode=mode, time_input=time_input)
            return ResolvedManualTaskRun(
                task_type="workflow",
                resource_key=None,
                action="maintain",
                time_input={"mode": mode, **time_params},
                filters=filters,
                request_payload={**filters, **time_params},
                target_type="workflow",
                target_key=workflow.key,
            )
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported manual action type")

    @staticmethod
    def _dataset_time_input_payload(*, mode: str, time_params: dict[str, Any]) -> dict[str, Any]:
        payload = {"mode": mode, **time_params}
        if "ann_date" in time_params:
            payload["trade_date"] = time_params["ann_date"]
            payload["date_field"] = "ann_date"
        return payload

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
        raise WebAppError(status_code=422, code="validation_error", message=f"不支持的时间模式：{mode}")

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
                raise WebAppError(status_code=422, code="validation_error", message=f"不支持的筛选项：{key}")
            normalized_value = self._normalize_filter_value(param, value)
            if self._is_empty(normalized_value):
                continue
            normalized[key] = normalized_value
        return normalized

    def _apply_default_filters(self, filters: dict[str, Any]) -> dict[str, Any]:
        with_defaults = dict(filters)
        for param in self.route.filters:
            self._fill_default_filter(with_defaults, param.key, param.default_value)
        return with_defaults

    @staticmethod
    def _fill_default_filter(filters: dict[str, Any], key: str, default_value: Any | None) -> None:
        if default_value in (None, "", []):
            return
        current = filters.get(key)
        if current in (None, "", []):
            filters[key] = default_value

    def _normalize_filter_value(self, param: ActionParameter, value: Any) -> Any:
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
                raise WebAppError(status_code=422, code="validation_error", message=f"{self._param_label(param)}必须是整数") from exc
        text = str(single_value).strip()
        self._validate_options(param, [text])
        return text

    @staticmethod
    def _validate_options(param: ActionParameter, values: list[str]) -> None:
        if not param.options:
            return
        invalid = [value for value in values if value not in param.options]
        if invalid:
            raise WebAppError(status_code=422, code="validation_error", message=f"{ManualActionTaskRunResolver._param_label(param)}不支持选项：{invalid[0]}")

    def _input_shape(self) -> str:
        if self.route.date_model is None:
            return self.route.time_form.control
        return self.route.date_model.input_shape

    @staticmethod
    def _require_date_text(value: str | None, field: str) -> str:
        if not value:
            raise WebAppError(status_code=422, code="validation_error", message=f"{ManualActionTaskRunResolver._field_label(field)}不能为空")
        parsed = ManualActionTaskRunResolver._parse_date(value, field)
        return parsed.isoformat()

    @staticmethod
    def _require_month(value: str | None, field: str) -> str:
        if not value:
            raise WebAppError(status_code=422, code="validation_error", message=f"{ManualActionTaskRunResolver._field_label(field)}不能为空")
        cleaned = value.strip().replace("-", "")
        if len(cleaned) != 6 or not cleaned.isdigit():
            raise WebAppError(status_code=422, code="validation_error", message=f"{ManualActionTaskRunResolver._field_label(field)}必须是 YYYY-MM 或 YYYYMM")
        month = int(cleaned[4:6])
        if month < 1 or month > 12:
            raise WebAppError(status_code=422, code="validation_error", message=f"{ManualActionTaskRunResolver._field_label(field)}不是有效月份")
        return cleaned

    @staticmethod
    def _validate_date_order(start_date: str, end_date: str) -> None:
        if ManualActionTaskRunResolver._parse_date(start_date, "start_date") > ManualActionTaskRunResolver._parse_date(end_date, "end_date"):
            raise WebAppError(status_code=422, code="validation_error", message="开始日期不能晚于结束日期")

    @staticmethod
    def _validate_month_order(start_month: str, end_month: str) -> None:
        if int(start_month) > int(end_month):
            raise WebAppError(status_code=422, code="validation_error", message="开始月份不能晚于结束月份")

    @staticmethod
    def _parse_date(value: str, field: str) -> date:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise WebAppError(status_code=422, code="validation_error", message=f"{ManualActionTaskRunResolver._field_label(field)}必须是 YYYY-MM-DD") from exc

    @staticmethod
    def _param_label(param: ActionParameter) -> str:
        return (param.display_name or param.key).strip()

    @staticmethod
    def _field_label(field: str) -> str:
        labels = {
            "trade_date": "处理日期",
            "start_date": "开始日期",
            "end_date": "结束日期",
            "month": "处理月份",
            "start_month": "开始月份",
            "end_month": "结束月份",
            "ann_date": "公告日期",
        }
        return labels.get(field, field)

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
