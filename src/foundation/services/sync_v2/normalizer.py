from __future__ import annotations

from decimal import InvalidOperation

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, FetchResult, NormalizedBatch
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2NormalizeError
from src.foundation.services.sync_v2.sentinel_guard import (
    find_forbidden_business_sentinel_in_row_context,
    should_guard_dataset_rows,
)
from src.utils import coerce_row


class SyncV2Normalizer:
    def normalize(self, *, contract: DatasetSyncContract, fetch_result: FetchResult) -> NormalizedBatch:
        rows_normalized: list[dict] = []
        rejected_reasons: dict[str, int] = {}
        for raw_row in fetch_result.rows_raw:
            try:
                normalized = coerce_row(raw_row, contract.normalization_spec.date_fields, contract.normalization_spec.decimal_fields)
            except Exception as exc:
                self._increase_reason(rejected_reasons, self._map_coerce_error(exc))
                continue

            try:
                if contract.normalization_spec.row_transform is not None:
                    normalized = contract.normalization_spec.row_transform(normalized)
            except Exception:
                self._increase_reason(rejected_reasons, "normalize.row_transform_failed")
                continue

            if should_guard_dataset_rows(contract.dataset_key):
                sentinel = find_forbidden_business_sentinel_in_row_context(normalized, path="normalized_row")
                if sentinel is not None:
                    path, value = sentinel
                    raise SyncV2NormalizeError(
                        StructuredError(
                            error_code="forbidden_sentinel",
                            error_type="normalize",
                            phase="normalizer",
                            message=f"forbidden business sentinel {value} at {path}",
                            retryable=False,
                            unit_id=fetch_result.unit_id,
                        )
                    )

            required_violation = self._resolve_required_field_violation(
                row=normalized,
                required_fields=contract.normalization_spec.required_fields,
            )
            if required_violation is not None:
                self._increase_reason(rejected_reasons, required_violation)
                continue

            rows_normalized.append(normalized)
        return NormalizedBatch(
            unit_id=fetch_result.unit_id,
            rows_normalized=rows_normalized,
            rows_rejected=sum(rejected_reasons.values()),
            rejected_reasons=rejected_reasons,
        )

    @staticmethod
    def raise_if_all_rejected(batch: NormalizedBatch) -> None:
        if not batch.rows_normalized and batch.rows_rejected > 0:
            reason = ", ".join(f"{key}={count}" for key, count in sorted(batch.rejected_reasons.items()))
            raise SyncV2NormalizeError(
                StructuredError(
                    error_code="all_rows_rejected",
                    error_type="normalize",
                    phase="normalizer",
                    message=f"all rows rejected: {reason}",
                    retryable=False,
                    unit_id=batch.unit_id,
                    details={"rejected_reasons": batch.rejected_reasons},
                )
            )

    @staticmethod
    def _increase_reason(counter: dict[str, int], reason_code: str) -> None:
        counter[reason_code] = counter.get(reason_code, 0) + 1

    @staticmethod
    def _with_field(reason_code: str, field: str) -> str:
        normalized_field = str(field).strip()
        if not normalized_field:
            return reason_code
        return f"{reason_code}:{normalized_field}"

    @classmethod
    def _resolve_required_field_violation(
        cls,
        *,
        row: dict[str, object],
        required_fields: tuple[str, ...],
    ) -> str | None:
        for field_name in required_fields:
            if field_name not in row or row[field_name] is None:
                return cls._with_field("normalize.required_field_missing", field_name)
            if isinstance(row[field_name], str) and not row[field_name].strip():
                return cls._with_field("normalize.empty_not_allowed", field_name)
        return None

    @staticmethod
    def _map_coerce_error(exc: Exception) -> str:
        if isinstance(exc, InvalidOperation):
            return "normalize.invalid_decimal"
        if isinstance(exc, ValueError | TypeError):
            return "normalize.invalid_date"
        return "reason.unknown"
