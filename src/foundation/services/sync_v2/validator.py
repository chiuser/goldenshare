from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    InputField,
    RunRequest,
    ValidatedRunRequest,
    resolve_contract_anchor_type,
    resolve_contract_window_policy,
)
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2ValidationError
from src.foundation.services.sync_v2.sentinel_guard import find_forbidden_business_sentinel
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
        anchor_type = resolve_contract_anchor_type(contract)
        window_policy = resolve_contract_window_policy(contract)

        if request.run_profile == "point_incremental":
            if window_policy not in {"point", "point_or_range"}:
                raise self._error(
                    "invalid_window_for_profile",
                    f"run_profile=point_incremental is not allowed for window_policy={window_policy}",
                )
            month_key = self._normalize_month_key(normalized_params.get("month"))
            if month_key is not None:
                normalized_params["month"] = month_key
            trade_date, start_date, end_date = self._validate_point_incremental_anchor(
                anchor_type=anchor_type,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                params=normalized_params,
            )
        elif request.run_profile == "range_rebuild":
            if window_policy not in {"range", "point_or_range"}:
                raise self._error(
                    "invalid_window_for_profile",
                    f"run_profile=range_rebuild is not allowed for window_policy={window_policy}",
                )
            month_key = self._normalize_month_key(normalized_params.get("month"))
            if month_key is not None:
                normalized_params["month"] = month_key
            trade_date, start_date, end_date = self._validate_range_rebuild_anchor(
                anchor_type=anchor_type,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                params=normalized_params,
            )
        elif request.run_profile == "snapshot_refresh":
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

    def _validate_point_incremental_anchor(
        self,
        *,
        anchor_type: str,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
        params: dict,
    ) -> tuple[date | None, date | None, date | None]:
        if start_date is not None or end_date is not None:
            raise self._error("range_not_allowed", "point_incremental does not allow start_date/end_date")

        if anchor_type in {"trade_date", "week_end_trade_date", "month_end_trade_date"}:
            if trade_date is None:
                trade_date = self._to_optional_date(params.get("trade_date"))
            if trade_date is None:
                raise self._error("missing_anchor_fields", f"anchor_type={anchor_type} requires trade_date")
            params["trade_date"] = trade_date
            return trade_date, start_date, end_date

        if anchor_type == "month_key_yyyymm":
            month_key = self._normalize_month_key(params.get("month"))
            if month_key is None:
                if trade_date is None:
                    trade_date = self._to_optional_date(params.get("trade_date"))
                if trade_date is not None:
                    month_key = trade_date.strftime("%Y%m")
            if month_key is None:
                raise self._error("missing_anchor_fields", "anchor_type=month_key_yyyymm requires month or trade_date")
            params["month"] = month_key
            if trade_date is not None:
                params["trade_date"] = trade_date
            return trade_date, start_date, end_date

        if anchor_type in {"month_range_natural", "natural_date_range"}:
            if trade_date is None:
                trade_date = self._to_optional_date(params.get("trade_date"))
            if trade_date is None:
                raise self._error("missing_anchor_fields", f"anchor_type={anchor_type} requires trade_date")
            params["trade_date"] = trade_date
            return trade_date, start_date, end_date

        if anchor_type == "none":
            if trade_date is None:
                trade_date = self._to_optional_date(params.get("trade_date"))
            if trade_date is not None:
                params["trade_date"] = trade_date
            return trade_date, start_date, end_date

        raise self._error("invalid_anchor_type", f"unsupported anchor_type={anchor_type}")

    def _validate_range_rebuild_anchor(
        self,
        *,
        anchor_type: str,
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
            raise self._error("range_required", "range_rebuild requires start_date and end_date")
        if start_date > end_date:
            raise self._error("invalid_range", "start_date must be <= end_date")

        if anchor_type not in {
            "trade_date",
            "week_end_trade_date",
            "month_end_trade_date",
            "month_key_yyyymm",
            "month_range_natural",
            "natural_date_range",
            "none",
        }:
            raise self._error("invalid_anchor_type", f"unsupported anchor_type={anchor_type}")

        params["start_date"] = start_date
        params["end_date"] = end_date
        return trade_date, start_date, end_date

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
        sentinel = find_forbidden_business_sentinel(normalized, path="params")
        if sentinel is not None:
            path, value = sentinel
            raise self._error("forbidden_sentinel", f"forbidden business sentinel {value} at {path}")
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
        raise ContractValidator._error("invalid_month_key", "month must be YYYYMM or YYYY-MM")

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
