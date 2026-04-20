from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    InputField,
    RunRequest,
    ValidatedRunRequest,
)
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2ValidationError
from src.utils import parse_tushare_date


class ContractValidator:
    def validate(self, request: RunRequest, contract: DatasetSyncContract, *, strict: bool = True) -> ValidatedRunRequest:
        if request.dataset_key != contract.dataset_key:
            raise self._error(
                error_code="dataset_mismatch",
                message=f"request.dataset_key={request.dataset_key} does not match contract={contract.dataset_key}",
            )
        if request.run_profile not in contract.run_profiles_supported:
            raise self._error(
                error_code="run_profile_unsupported",
                message=f"run_profile={request.run_profile} is not supported by dataset={contract.dataset_key}",
            )
        normalized_params = self._normalize_input_params(request.params, contract, strict=strict)
        trade_date = self._to_optional_date(request.trade_date)
        start_date = self._to_optional_date(request.start_date)
        end_date = self._to_optional_date(request.end_date)

        if request.run_profile == "point_incremental":
            if trade_date is None:
                trade_date = self._to_optional_date(normalized_params.get("trade_date"))
            if trade_date is None:
                raise self._error("trade_date_required", "point_incremental requires trade_date")
            if start_date is not None or end_date is not None:
                raise self._error("range_not_allowed", "point_incremental does not allow start_date/end_date")
            normalized_params["trade_date"] = trade_date
        elif request.run_profile == "range_rebuild":
            if start_date is None:
                start_date = self._to_optional_date(normalized_params.get("start_date"))
            if end_date is None:
                end_date = self._to_optional_date(normalized_params.get("end_date"))
            if start_date is None or end_date is None:
                raise self._error("range_required", "range_rebuild requires start_date and end_date")
            if start_date > end_date:
                raise self._error("invalid_range", "start_date must be <= end_date")
            normalized_params["start_date"] = start_date
            normalized_params["end_date"] = end_date
        elif request.run_profile == "snapshot_refresh":
            if trade_date is None:
                trade_date = self._to_optional_date(normalized_params.get("trade_date"))
            if start_date is None:
                start_date = self._to_optional_date(normalized_params.get("start_date"))
            if end_date is None:
                end_date = self._to_optional_date(normalized_params.get("end_date"))
            if any(value is not None for value in (trade_date, start_date, end_date)):
                raise self._error("time_anchor_not_allowed", "snapshot_refresh does not accept time anchors")
            normalized_params.pop("trade_date", None)
            normalized_params.pop("start_date", None)
            normalized_params.pop("end_date", None)

        correlation_id = request.correlation_id or uuid4().hex
        return ValidatedRunRequest(
            request_id=request.request_id,
            dataset_key=request.dataset_key,
            run_profile=request.run_profile,
            trigger_source=request.trigger_source,
            params=normalized_params,
            source_key=request.source_key,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            correlation_id=correlation_id,
            rerun_id=request.rerun_id,
            execution_id=request.execution_id,
            validated_at=datetime.now(timezone.utc),
        )

    def _normalize_input_params(self, params: dict, contract: DatasetSyncContract, *, strict: bool) -> dict:
        normalized = dict(params or {})
        by_name = {field.name: field for field in contract.input_schema.fields}

        for field in contract.input_schema.fields:
            if field.name not in normalized and field.default is not None:
                normalized[field.name] = field.default
            if field.required and field.name not in normalized:
                raise self._error("required_param_missing", f"missing required param: {field.name}")
            if field.name in normalized:
                normalized[field.name] = self._coerce_value(field, normalized[field.name])

        if strict:
            unknown = sorted(set(normalized) - set(by_name))
            if unknown:
                joined = ", ".join(unknown)
                raise self._error("unknown_params", f"unknown params for {contract.dataset_key}: {joined}")

        for group in contract.input_schema.required_groups:
            if not any(normalized.get(key) not in (None, "", []) for key in group):
                joined = ", ".join(group)
                raise self._error("required_group_unsatisfied", f"at least one of [{joined}] is required")

        for group in contract.input_schema.mutually_exclusive_groups:
            present = [key for key in group if normalized.get(key) not in (None, "", [])]
            if len(present) > 1:
                joined = ", ".join(present)
                raise self._error("mutually_exclusive_violation", f"mutually exclusive params present: {joined}")

        for left, right in contract.input_schema.dependencies:
            if normalized.get(left) not in (None, "", []) and normalized.get(right) in (None, "", []):
                raise self._error("dependency_violation", f"{left} requires {right}")
        return normalized

    def _coerce_value(self, field: InputField, value):  # type: ignore[no-untyped-def]
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
        if field.field_type == "enum":
            text = str(value).strip()
            if field.enum_values and text not in field.enum_values:
                raise self._error("invalid_enum", f"invalid enum for {field.name}: {text}")
            return text
        if field.field_type == "list":
            if isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
            text = str(value).strip()
            if not text:
                return []
            return [part.strip() for part in text.split(",") if part.strip()]
        text = str(value).strip()
        if not text and not field.allow_empty:
            raise self._error("empty_not_allowed", f"empty value is not allowed for {field.name}")
        return text

    @staticmethod
    def _to_optional_date(value) -> date | None:  # type: ignore[no-untyped-def]
        return parse_tushare_date(value)

    @staticmethod
    def _error(error_code: str, message: str) -> SyncV2ValidationError:
        return SyncV2ValidationError(
            StructuredError(
                error_code=error_code,
                error_type="validation",
                phase="validator",
                message=message,
                retryable=False,
            )
        )
