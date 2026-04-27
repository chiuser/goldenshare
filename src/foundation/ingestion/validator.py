from __future__ import annotations

from datetime import date
from uuid import uuid4

from src.foundation.datasets.models import DatasetDateModel, DatasetDefinition, DatasetInputField
from src.foundation.ingestion.errors import IngestionValidationError, StructuredError
from src.foundation.ingestion.execution_plan import DatasetActionRequest, ValidatedDatasetActionRequest
from src.foundation.ingestion.sentinel_guard import find_forbidden_business_sentinel
from src.utils import parse_tushare_date


class DatasetRequestValidator:
    def validate(
        self,
        *,
        request: DatasetActionRequest,
        definition: DatasetDefinition,
        run_profile: str,
        strict: bool = True,
    ) -> ValidatedDatasetActionRequest:
        if request.dataset_key != definition.dataset_key:
            raise self._error(
                error_code="dataset_mismatch",
                message=f"request.dataset_key={request.dataset_key} does not match definition={definition.dataset_key}",
            )
        action = definition.capabilities.get_action(request.action)
        if action is None:
            raise self._error(
                error_code="run_profile_unsupported",
                message=f"dataset={definition.dataset_key} does not support action={request.action}",
            )
        if run_profile == "point_incremental" and "point" not in action.supported_time_modes:
            raise self._error(
                error_code="run_profile_unsupported",
                message=f"dataset={definition.dataset_key} does not support point maintain",
            )
        if run_profile == "range_rebuild" and "range" not in action.supported_time_modes:
            raise self._error(
                error_code="run_profile_unsupported",
                message=f"dataset={definition.dataset_key} does not support range maintain",
            )
        if run_profile == "snapshot_refresh" and "none" not in action.supported_time_modes and action.supported_time_modes:
            # Snapshot datasets often model point mode in UI, but the execution profile
            # is still a no-time refresh. We only reject when the action advertises a
            # constrained set that explicitly excludes snapshot usage.
            pass

        normalized_params = self._normalize_input_params(request.filters, definition, strict=strict)
        time_input = request.time_input
        trade_date = self._to_optional_date(time_input.trade_date)
        start_date = self._to_optional_date(time_input.start_date)
        end_date = self._to_optional_date(time_input.end_date)
        date_model = definition.date_model

        if run_profile == "point_incremental":
            if date_model.window_mode not in {"point", "point_or_range"}:
                raise self._error(
                    "invalid_window_for_profile",
                    f"run_profile=point_incremental is not allowed for window_mode={date_model.window_mode}",
                )
            trade_date, start_date, end_date = self._validate_point_incremental_anchor(
                date_model=date_model,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                params=normalized_params,
            )
        elif run_profile == "range_rebuild":
            if date_model.window_mode not in {"range", "point_or_range"}:
                raise self._error(
                    "invalid_window_for_profile",
                    f"run_profile=range_rebuild is not allowed for window_mode={date_model.window_mode}",
                )
            trade_date, start_date, end_date = self._validate_range_rebuild_anchor(
                date_model=date_model,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                params=normalized_params,
            )
        elif run_profile == "snapshot_refresh":
            month_key = self._normalize_month_key(normalized_params.get("month"))
            if trade_date is None:
                trade_date = self._to_optional_date(normalized_params.get("trade_date"))
            if start_date is None:
                start_date = self._to_optional_date(normalized_params.get("start_date"))
            if end_date is None:
                end_date = self._to_optional_date(normalized_params.get("end_date"))
            if any(value is not None for value in (trade_date, start_date, end_date, month_key)):
                raise self._error("time_anchor_not_allowed", "snapshot_refresh does not accept time anchors")
            normalized_params.pop("trade_date", None)
            normalized_params.pop("start_date", None)
            normalized_params.pop("end_date", None)
            normalized_params.pop("month", None)

        source_key = self._to_optional_text(normalized_params.get("source_key")) or None
        request_id = uuid4().hex
        return ValidatedDatasetActionRequest(
            request_id=request_id,
            dataset_key=request.dataset_key,
            action=request.action,
            run_profile=run_profile,
            trigger_source=request.trigger_source,
            params=normalized_params,
            source_key=source_key,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            run_id=request.run_id,
        )

    def _validate_point_incremental_anchor(
        self,
        *,
        date_model: DatasetDateModel,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
        params: dict,
    ) -> tuple[date | None, date | None, date | None]:
        if start_date is not None or end_date is not None:
            raise self._error("range_not_allowed", "point_incremental does not allow start_date/end_date")
        if date_model.input_shape == "month_or_range":
            month_key = self._normalize_month_key(params.get("month"))
            if month_key is None:
                if trade_date is not None:
                    month_key = trade_date.strftime("%Y%m")
                elif self._to_optional_date(params.get("trade_date")) is not None:
                    month_key = self._to_optional_date(params.get("trade_date")).strftime("%Y%m")
            if month_key is None:
                raise self._error("missing_anchor_fields", "month_or_range requires month or trade_date")
            params["month"] = month_key
            return trade_date, start_date, end_date

        if date_model.date_axis in {"trade_open_day", "natural_day", "month_window"} or date_model.input_shape in {
            "trade_date_or_start_end",
            "ann_date_or_start_end",
        }:
            if trade_date is None:
                trade_date = self._to_optional_date(params.get("trade_date"))
            if trade_date is None and date_model.input_shape == "ann_date_or_start_end":
                trade_date = self._to_optional_date(params.get("ann_date"))
            if trade_date is None:
                raise self._error("missing_anchor_fields", f"dataset requires point date input for {date_model.input_shape}")
            if date_model.input_shape == "ann_date_or_start_end":
                params["ann_date"] = trade_date
            else:
                params["trade_date"] = trade_date
            return trade_date, start_date, end_date

        if date_model.date_axis == "none":
            return trade_date, start_date, end_date

        raise self._error("invalid_anchor_type", f"unsupported date model input_shape={date_model.input_shape}")

    def _validate_range_rebuild_anchor(
        self,
        *,
        date_model: DatasetDateModel,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
        params: dict,
    ) -> tuple[date | None, date | None, date | None]:
        if start_date is None:
            start_date = self._to_optional_date(params.get("start_date"))
        if end_date is None:
            end_date = self._to_optional_date(params.get("end_date"))
        if start_date is None or end_date is None:
            raise self._error("range_required", "区间维护必须同时填写开始日期和结束日期")
        if start_date > end_date:
            raise self._error("invalid_range", "开始日期不能晚于结束日期")
        params["start_date"] = start_date
        params["end_date"] = end_date
        return trade_date, start_date, end_date

    def _normalize_input_params(self, params: dict, definition: DatasetDefinition, *, strict: bool) -> dict:
        normalized = dict(params or {})
        fields = {field.name: field for field in (*definition.input_model.time_fields, *definition.input_model.filters)}

        for field in fields.values():
            if field.name not in normalized and field.default is not None:
                normalized[field.name] = field.default
            if field.required and field.name not in normalized:
                raise self._error("required_param_missing", f"缺少必填参数：{field.label or field.name}")
            if field.name in normalized:
                normalized[field.name] = self._coerce_value(field, normalized[field.name])

        if strict:
            unknown = sorted(set(normalized) - set(fields))
            if unknown:
                joined = ", ".join(unknown)
                raise self._error("unknown_params", f"{definition.display_name} 存在未定义参数：{joined}")

        for group in definition.input_model.required_groups:
            if not any(normalized.get(key) not in (None, "", []) for key in group):
                labels = [fields[key].label or fields[key].name for key in group if key in fields]
                joined = "、".join(labels or group)
                raise self._error("required_group_unsatisfied", f"至少需要填写其中一个参数：{joined}")

        for group in definition.input_model.mutually_exclusive_groups:
            present = [key for key in group if normalized.get(key) not in (None, "", [])]
            if len(present) > 1:
                labels = [fields[key].label or fields[key].name for key in present if key in fields]
                joined = "、".join(labels or present)
                raise self._error("mutually_exclusive_violation", f"这些参数不能同时填写：{joined}")

        for left, right in definition.input_model.dependencies:
            if normalized.get(left) not in (None, "", []) and normalized.get(right) in (None, "", []):
                raise self._error("dependency_violation", f"{left} requires {right}")

        sentinel = find_forbidden_business_sentinel(normalized, path="params")
        if sentinel is not None:
            path, value = sentinel
            raise self._error("forbidden_sentinel", f"forbidden business sentinel {value} at {path}")
        return normalized

    def _coerce_value(self, field: DatasetInputField, value):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if field.field_type == "date":
            parsed = self._to_optional_date(value)
            if parsed is None:
                raise self._error("invalid_date", f"invalid date for {field.name}")
            return parsed
        if field.field_type == "integer":
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise self._error("invalid_integer", f"invalid integer for {field.name}") from exc
        if field.field_type == "boolean":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in {"1", "true", "yes"}:
                return True
            if text in {"0", "false", "no"}:
                return False
            raise self._error("invalid_boolean", f"invalid boolean for {field.name}")
        if field.field_type in {"enum", "string"}:
            text = str(value).strip()
            if field.enum_values and text not in field.enum_values:
                raise self._error("invalid_enum", f"invalid enum for {field.name}: {text}")
            if not text and field.required:
                raise self._error("empty_not_allowed", f"empty value is not allowed for {field.name}")
            return text
        if field.field_type == "list":
            if isinstance(value, list):
                values = value
            elif isinstance(value, tuple):
                values = list(value)
            else:
                text = str(value).strip()
                values = [] if not text else [part.strip() for part in text.split(",") if part.strip()]
            normalized_values = [str(item).strip() for item in values if str(item).strip()]
            if field.enum_values:
                invalid = [item for item in normalized_values if item not in field.enum_values]
                if invalid:
                    raise self._error("invalid_enum", f"invalid enum for {field.name}: {', '.join(invalid)}")
            return normalized_values
        return value

    @staticmethod
    def _to_optional_date(value) -> date | None:  # type: ignore[no-untyped-def]
        return parse_tushare_date(value)

    @staticmethod
    def _to_optional_text(value) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_month_key(value) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        text = str(value).strip().replace("-", "")
        if not text:
            return None
        if len(text) == 6 and text.isdigit():
            return text
        parsed = parse_tushare_date(text)
        if parsed is not None:
            return parsed.strftime("%Y%m")
        raise DatasetRequestValidator._error("invalid_month_key", "月份必须是 YYYYMM 或 YYYY-MM")

    @staticmethod
    def _error(error_code: str, message: str) -> IngestionValidationError:
        return IngestionValidationError(
            StructuredError(
                error_code=error_code,
                error_type="validation",
                phase="validator",
                message=message,
                retryable=False,
            )
        )
