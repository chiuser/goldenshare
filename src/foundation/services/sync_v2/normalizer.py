from __future__ import annotations

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, FetchResult, NormalizedBatch
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2NormalizeError
from src.utils import coerce_row


class SyncV2Normalizer:
    def normalize(self, *, contract: DatasetSyncContract, fetch_result: FetchResult) -> NormalizedBatch:
        rows_normalized: list[dict] = []
        rejected_reasons: dict[str, int] = {}
        for raw_row in fetch_result.rows_raw:
            try:
                normalized = coerce_row(raw_row, contract.normalization_spec.date_fields, contract.normalization_spec.decimal_fields)
                if contract.normalization_spec.row_transform is not None:
                    normalized = contract.normalization_spec.row_transform(normalized)
                for field_name in contract.normalization_spec.required_fields:
                    if field_name not in normalized or normalized[field_name] in (None, ""):
                        raise ValueError(f"required field missing: {field_name}")
                rows_normalized.append(normalized)
            except Exception as exc:
                key = exc.__class__.__name__
                rejected_reasons[key] = rejected_reasons.get(key, 0) + 1
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
