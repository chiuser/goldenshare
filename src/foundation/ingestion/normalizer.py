from __future__ import annotations

from decimal import InvalidOperation
from typing import Any

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.errors import IngestionNormalizeError, StructuredError
from src.foundation.ingestion.row_transforms import *  # noqa: F403
from src.foundation.ingestion.sentinel_guard import (
    find_forbidden_business_sentinel_in_row_context,
    should_guard_dataset_rows,
)
from src.foundation.ingestion.source_client import SourceFetchResult
from src.utils import CoerceRowError, coerce_row, truncate_text


class NormalizedBatch:
    def __init__(
        self,
        *,
        unit_id: str,
        rows_normalized: list[dict],
        rows_rejected: int,
        rejected_reasons: dict[str, int],
        rejected_samples: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.rows_normalized = rows_normalized
        self.rows_rejected = rows_rejected
        self.rejected_reasons = rejected_reasons
        self.rejected_samples = rejected_samples or {}


class DatasetNormalizer:
    MAX_SAMPLES_PER_REASON = 3
    MAX_SAMPLE_ROW_FIELDS = 12
    MAX_SAMPLE_VALUE_LENGTH = 240
    SAMPLE_IDENTITY_FIELDS = (
        "ts_code",
        "trade_date",
        "cal_date",
        "ann_date",
        "pub_date",
        "end_date",
        "start_date",
        "month",
        "name",
        "symbol",
        "exchange",
        "market",
        "freq",
        "hot_type",
        "concept_name",
        "code",
        "title",
        "url",
        "list_date",
    )

    def normalize(self, *, definition: DatasetDefinition, fetch_result: SourceFetchResult) -> NormalizedBatch:
        row_transform = None
        if definition.normalization.row_transform_name:
            row_transform = globals().get(definition.normalization.row_transform_name)
            if not callable(row_transform):
                raise IngestionNormalizeError(
                    StructuredError(
                        error_code="normalize.row_transform_failed",
                        error_type="normalize",
                        phase="normalizer",
                        message=f"未知行转换：{definition.normalization.row_transform_name}",
                        retryable=False,
                        unit_id=fetch_result.unit_id,
                    )
                )

        rows_normalized: list[dict] = []
        rejected_reasons: dict[str, int] = {}
        rejected_samples: dict[str, list[dict[str, Any]]] = {}
        for raw_row in fetch_result.rows_raw:
            try:
                normalized = coerce_row(
                    raw_row,
                    definition.normalization.date_fields,
                    definition.normalization.decimal_fields,
                )
            except Exception as exc:
                reason_key = self._map_coerce_error(exc)
                self._record_rejection(
                    rejected_reasons,
                    rejected_samples,
                    reason_key,
                    row=raw_row,
                    unit_id=fetch_result.unit_id,
                    field=getattr(exc, "field", None),
                    value=getattr(exc, "value", None),
                    message=str(exc),
                )
                continue

            try:
                if row_transform is not None:
                    normalized = row_transform(normalized)
            except RowTransformReject as exc:  # noqa: F405
                field = self._field_from_reason_key(exc.reason_code)
                self._record_rejection(
                    rejected_reasons,
                    rejected_samples,
                    exc.reason_code,
                    row=normalized,
                    unit_id=fetch_result.unit_id,
                    field=field,
                    value=normalized.get(field) if field else None,
                    message=str(exc),
                )
                continue
            except Exception as exc:
                self._record_rejection(
                    rejected_reasons,
                    rejected_samples,
                    "normalize.row_transform_failed",
                    row=normalized,
                    unit_id=fetch_result.unit_id,
                    message=str(exc),
                )
                continue

            if should_guard_dataset_rows(definition.dataset_key):
                sentinel = find_forbidden_business_sentinel_in_row_context(normalized, path="normalized_row")
                if sentinel is not None:
                    path, value = sentinel
                    raise IngestionNormalizeError(
                        StructuredError(
                            error_code="forbidden_sentinel",
                            error_type="normalize",
                            phase="normalizer",
                            message=f"检测到非法业务占位值：{value}，位置：{path}",
                            retryable=False,
                            unit_id=fetch_result.unit_id,
                        )
                    )

            required_violation = self._resolve_required_field_violation(
                row=normalized,
                required_fields=definition.normalization.required_fields,
            )
            if required_violation is not None:
                field = self._field_from_reason_key(required_violation)
                self._record_rejection(
                    rejected_reasons,
                    rejected_samples,
                    required_violation,
                    row=normalized,
                    unit_id=fetch_result.unit_id,
                    field=field,
                    value=normalized.get(field) if field else None,
                )
                continue

            rows_normalized.append(normalized)
        return NormalizedBatch(
            unit_id=fetch_result.unit_id,
            rows_normalized=rows_normalized,
            rows_rejected=sum(rejected_reasons.values()),
            rejected_reasons=rejected_reasons,
            rejected_samples=rejected_samples,
        )

    @staticmethod
    def raise_if_all_rejected(batch: NormalizedBatch) -> None:
        if not batch.rows_normalized and batch.rows_rejected > 0:
            reason = ", ".join(f"{key}={count}" for key, count in sorted(batch.rejected_reasons.items()))
            raise IngestionNormalizeError(
                StructuredError(
                    error_code="all_rows_rejected",
                    error_type="normalize",
                    phase="normalizer",
                    message=f"all rows rejected: {reason}",
                    retryable=False,
                    unit_id=batch.unit_id,
                    details={
                        "rejected_reasons": batch.rejected_reasons,
                        "rejected_samples": batch.rejected_samples,
                    },
                )
            )

    @staticmethod
    def _increase_reason(counter: dict[str, int], reason_code: str) -> None:
        counter[reason_code] = counter.get(reason_code, 0) + 1

    @classmethod
    def _record_rejection(
        cls,
        counter: dict[str, int],
        samples: dict[str, list[dict[str, Any]]],
        reason_key: str,
        *,
        row: dict[str, Any],
        unit_id: str,
        field: str | None = None,
        value: Any | None = None,
        message: str | None = None,
    ) -> None:
        cls._increase_reason(counter, reason_key)
        bucket = samples.setdefault(reason_key, [])
        if len(bucket) >= cls.MAX_SAMPLES_PER_REASON:
            return
        try:
            bucket.append(
                {
                    "unit_id": cls._sample_scalar(unit_id),
                    "field": cls._sample_scalar(field),
                    "value": cls._sample_scalar(value),
                    "message": cls._sample_scalar(message),
                    "row": cls._sample_row(row=row, field=field),
                }
            )
        except Exception:
            return

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
        if isinstance(exc, CoerceRowError):
            return DatasetNormalizer._with_field(exc.reason_code, exc.field)
        if isinstance(exc, InvalidOperation):
            return "normalize.invalid_decimal"
        if isinstance(exc, ValueError | TypeError):
            return "normalize.invalid_date"
        return "reason.unknown"

    @staticmethod
    def _field_from_reason_key(reason_key: str) -> str | None:
        if ":" not in reason_key:
            return None
        field = reason_key.split(":", 1)[1].strip()
        return field or None

    @classmethod
    def _sample_row(cls, *, row: dict[str, Any], field: str | None) -> dict[str, Any]:
        selected: dict[str, Any] = {}
        for key in cls.SAMPLE_IDENTITY_FIELDS:
            if key in row:
                selected[key] = cls._sample_scalar(row.get(key))
        if field and field in row:
            selected[field] = cls._sample_scalar(row.get(field))
        if selected:
            return dict(list(selected.items())[: cls.MAX_SAMPLE_ROW_FIELDS])
        for key, value in row.items():
            selected[str(key)] = cls._sample_scalar(value)
            if len(selected) >= cls.MAX_SAMPLE_ROW_FIELDS:
                break
        return selected

    @classmethod
    def _sample_scalar(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool | int | float):
            return value
        text = truncate_text(str(value), cls.MAX_SAMPLE_VALUE_LENGTH, suffix="... [截断]")
        return text
