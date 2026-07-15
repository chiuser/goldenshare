"""Bounded metadata contract for Silver repairs consumed by derived Gold jobs.

This module is deliberately Dagster-free.  A Silver repair producer can build
an in-memory batch, validate it against an expected trade calendar, and then
pass ``to_payload()`` through an existing materialization/check metadata
builder.  No event history or persistence is used to infer a repair scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Any

from orchestrator.defs.run_contracts.run_keys import build_batch_id


SILVER_REPAIR_BATCH_PROTOCOL_VERSION = "v1"
SILVER_REPAIR_READY_STATUS = "ready"
SILVER_REPAIR_METADATA_PREFIX = "goldenshare/"


class SilverRepairBatchValidationError(ValueError):
    """Raised when an upstream Silver repair batch is unsafe to consume."""


@dataclass(frozen=True, slots=True)
class SilverRepairBatch:
    """Explicit, bounded identity and range of one Silver repair batch."""

    source_asset: str
    producer_run_id: str
    upstream_batch_id: str
    status: str
    source_revision: str
    source_repair_start_trade_date: str
    source_repair_end_trade_date: str
    indicator_recompute_start_trade_date: str
    indicator_recompute_end_trade_date: str
    context_start_trade_date: str
    target_frontier_trade_date: str
    affected_date_count: int
    affected_series_count: int
    affected_series_hash: str
    truncated: bool
    selected_partition_count: int
    protocol_version: str = SILVER_REPAIR_BATCH_PROTOCOL_VERSION

    @property
    def ready(self) -> bool:
        return self.status == SILVER_REPAIR_READY_STATUS

    def to_payload(self) -> dict[str, object]:
        """Return plain keys suitable for an existing metadata builder."""

        return {
            "protocol_version": self.protocol_version,
            "source_asset": self.source_asset,
            "producer_run_id": self.producer_run_id,
            "upstream_batch_id": self.upstream_batch_id,
            "status": self.status,
            "source_revision": self.source_revision,
            "source_repair_start_trade_date": self.source_repair_start_trade_date,
            "source_repair_end_trade_date": self.source_repair_end_trade_date,
            "indicator_recompute_start_trade_date": self.indicator_recompute_start_trade_date,
            "indicator_recompute_end_trade_date": self.indicator_recompute_end_trade_date,
            "context_start_trade_date": self.context_start_trade_date,
            "target_frontier_trade_date": self.target_frontier_trade_date,
            "affected_date_count": self.affected_date_count,
            "affected_series_count": self.affected_series_count,
            "affected_series_hash": self.affected_series_hash,
            "truncated": self.truncated,
            "selected_partition_count": self.selected_partition_count,
        }

    def to_metadata(self) -> dict[str, object]:
        """Return namespaced keys for direct event metadata use."""

        return {
            f"{SILVER_REPAIR_METADATA_PREFIX}{key}": value
            for key, value in self.to_payload().items()
        }


def normalize_trade_date(value: object, *, field_name: str) -> str:
    raw_value = str(value).strip()
    try:
        return date.fromisoformat(raw_value).isoformat()
    except (TypeError, ValueError) as error:
        raise SilverRepairBatchValidationError(
            f"{field_name} must use YYYY-MM-DD format."
        ) from error


def normalize_expected_trade_dates(values: Sequence[object]) -> tuple[str, ...]:
    normalized = tuple(
        normalize_trade_date(value, field_name="expected_trade_date") for value in values
    )
    if not normalized:
        raise SilverRepairBatchValidationError("expected_trade_dates must not be empty.")
    if len(set(normalized)) != len(normalized):
        raise SilverRepairBatchValidationError(
            "expected_trade_dates must not contain duplicates."
        )
    return tuple(sorted(normalized))


def hash_affected_series(series: Sequence[object]) -> str:
    """Hash normalized series identities without retaining them in metadata."""

    normalized_values: list[str] = []
    for value in series:
        if not isinstance(value, str) or not value.strip():
            raise SilverRepairBatchValidationError(
                "affected series identities must be non-empty strings."
            )
        normalized_values.append(value.strip().upper())
    normalized = tuple(sorted(set(normalized_values)))
    if not normalized:
        raise SilverRepairBatchValidationError("affected series must not be empty.")
    return sha256("\n".join(normalized).encode("utf-8")).hexdigest()


def build_silver_repair_upstream_batch_id(
    *,
    source_asset: str,
    producer_run_id: str,
    source_revision: str,
    source_repair_start_trade_date: str,
    source_repair_end_trade_date: str,
    affected_series_hash: str,
) -> str:
    """Build a deterministic batch identity from source facts and scope."""

    normalized_start = normalize_trade_date(
        source_repair_start_trade_date,
        field_name="source_repair_start_trade_date",
    )
    normalized_end = normalize_trade_date(
        source_repair_end_trade_date,
        field_name="source_repair_end_trade_date",
    )
    if normalized_start > normalized_end:
        raise SilverRepairBatchValidationError(
            "source repair start must not be later than source repair end."
        )
    if (
        not str(source_asset).strip()
        or not str(producer_run_id).strip()
        or not str(source_revision).strip()
    ):
        raise SilverRepairBatchValidationError(
            "source_asset, producer_run_id and source_revision must be non-empty."
        )
    _validate_sha256(affected_series_hash, field_name="affected_series_hash")
    return build_batch_id(
        producer=f"{str(source_asset).strip()}_repair",
        scope=f"{normalized_start}_{normalized_end}",
        payload={
            "protocol_version": SILVER_REPAIR_BATCH_PROTOCOL_VERSION,
            "source_asset": str(source_asset).strip(),
            "producer_run_id": str(producer_run_id).strip(),
            "source_revision": str(source_revision).strip(),
            "source_repair_start_trade_date": normalized_start,
            "source_repair_end_trade_date": normalized_end,
            "affected_series_hash": affected_series_hash,
        },
    )


def build_silver_repair_batch(
    *,
    source_asset: str,
    producer_run_id: str,
    source_revision: str,
    source_repair_start_trade_date: str,
    source_repair_end_trade_date: str,
    indicator_recompute_start_trade_date: str,
    indicator_recompute_end_trade_date: str,
    context_start_trade_date: str,
    target_frontier_trade_date: str,
    affected_date_count: int,
    affected_series_count: int,
    affected_series_hash: str,
    truncated: bool,
    selected_partition_count: int,
    upstream_batch_id: str | None = None,
    status: str = SILVER_REPAIR_READY_STATUS,
    expected_trade_dates: Sequence[object] | None = None,
    registered_trade_dates: Sequence[object] | None = None,
) -> SilverRepairBatch:
    """Build and validate one explicit Silver repair batch."""

    normalized_source_asset = str(source_asset).strip()
    normalized_producer_run_id = str(producer_run_id).strip()
    normalized_source_revision = str(source_revision).strip()
    normalized_status = str(status).strip()
    if not normalized_source_asset:
        raise SilverRepairBatchValidationError("source_asset must be non-empty.")
    if not normalized_producer_run_id:
        raise SilverRepairBatchValidationError("producer_run_id must be non-empty.")
    if not normalized_source_revision:
        raise SilverRepairBatchValidationError("source_revision must be non-empty.")
    if not normalized_status:
        raise SilverRepairBatchValidationError("status must be non-empty.")
    normalized_hash = str(affected_series_hash).strip().lower()
    _validate_sha256(normalized_hash, field_name="affected_series_hash")
    if upstream_batch_id is None:
        normalized_upstream_batch_id = build_silver_repair_upstream_batch_id(
            source_asset=normalized_source_asset,
            producer_run_id=normalized_producer_run_id,
            source_revision=normalized_source_revision,
            source_repair_start_trade_date=source_repair_start_trade_date,
            source_repair_end_trade_date=source_repair_end_trade_date,
            affected_series_hash=normalized_hash,
        )
    else:
        normalized_upstream_batch_id = str(upstream_batch_id).strip()
        if not normalized_upstream_batch_id:
            raise SilverRepairBatchValidationError(
                "upstream_batch_id must be non-empty when supplied."
            )
    batch = SilverRepairBatch(
        source_asset=normalized_source_asset,
        producer_run_id=normalized_producer_run_id,
        upstream_batch_id=normalized_upstream_batch_id,
        status=normalized_status,
        source_revision=normalized_source_revision,
        source_repair_start_trade_date=normalize_trade_date(
            source_repair_start_trade_date,
            field_name="source_repair_start_trade_date",
        ),
        source_repair_end_trade_date=normalize_trade_date(
            source_repair_end_trade_date,
            field_name="source_repair_end_trade_date",
        ),
        indicator_recompute_start_trade_date=normalize_trade_date(
            indicator_recompute_start_trade_date,
            field_name="indicator_recompute_start_trade_date",
        ),
        indicator_recompute_end_trade_date=normalize_trade_date(
            indicator_recompute_end_trade_date,
            field_name="indicator_recompute_end_trade_date",
        ),
        context_start_trade_date=normalize_trade_date(
            context_start_trade_date,
            field_name="context_start_trade_date",
        ),
        target_frontier_trade_date=normalize_trade_date(
            target_frontier_trade_date,
            field_name="target_frontier_trade_date",
        ),
        affected_date_count=_require_non_negative_int(
            affected_date_count,
            field_name="affected_date_count",
        ),
        affected_series_count=_require_non_negative_int(
            affected_series_count,
            field_name="affected_series_count",
        ),
        affected_series_hash=normalized_hash,
        truncated=truncated if isinstance(truncated, bool) else _invalid_bool("truncated"),
        selected_partition_count=_require_non_negative_int(
            selected_partition_count,
            field_name="selected_partition_count",
        ),
    )
    _validate_intrinsic(batch)
    if expected_trade_dates is not None:
        validate_silver_repair_batch(
            batch,
            expected_trade_dates=expected_trade_dates,
            registered_trade_dates=registered_trade_dates,
        )
    return batch


def validate_silver_repair_batch(
    batch: SilverRepairBatch,
    *,
    expected_trade_dates: Sequence[object],
    registered_trade_dates: Sequence[object] | None = None,
    max_indicator_recompute_dates: int | None = None,
) -> None:
    """Validate ranges and counts against a bounded expected calendar."""

    _validate_intrinsic(batch)

    expected = normalize_expected_trade_dates(expected_trade_dates)
    expected_set = set(expected)
    required_dates = (
        batch.source_repair_start_trade_date,
        batch.source_repair_end_trade_date,
        batch.indicator_recompute_start_trade_date,
        batch.indicator_recompute_end_trade_date,
        batch.context_start_trade_date,
        batch.target_frontier_trade_date,
    )
    missing_dates = tuple(sorted(set(required_dates) - expected_set))
    if missing_dates:
        raise SilverRepairBatchValidationError(
            "Silver repair range contains dates outside expected calendar: "
            f"{missing_dates[:5]}"
        )

    source_count = _date_count(
        expected,
        batch.source_repair_start_trade_date,
        batch.source_repair_end_trade_date,
    )
    indicator_count = _date_count(
        expected,
        batch.indicator_recompute_start_trade_date,
        batch.indicator_recompute_end_trade_date,
    )
    if batch.affected_date_count != source_count:
        raise SilverRepairBatchValidationError(
            "affected_date_count does not match the source repair range: "
            f"expected={source_count}, actual={batch.affected_date_count}"
        )
    if batch.selected_partition_count != indicator_count:
        raise SilverRepairBatchValidationError(
            "selected_partition_count does not match the indicator recompute range: "
            f"expected={indicator_count}, actual={batch.selected_partition_count}"
        )
    if batch.context_start_trade_date > batch.indicator_recompute_start_trade_date:
        raise SilverRepairBatchValidationError(
            "context_start_trade_date must not be later than indicator recompute start."
        )
    if batch.indicator_recompute_start_trade_date > batch.source_repair_start_trade_date:
        raise SilverRepairBatchValidationError(
            "indicator recompute range must cover the source repair start."
        )
    if batch.source_repair_end_trade_date > batch.indicator_recompute_end_trade_date:
        raise SilverRepairBatchValidationError(
            "indicator recompute range must cover the source repair end."
        )
    if batch.indicator_recompute_end_trade_date > batch.target_frontier_trade_date:
        raise SilverRepairBatchValidationError(
            "target_frontier_trade_date must cover indicator recompute end."
        )
    if max_indicator_recompute_dates is not None:
        if max_indicator_recompute_dates <= 0:
            raise SilverRepairBatchValidationError(
                "max_indicator_recompute_dates must be positive."
            )
        if indicator_count > max_indicator_recompute_dates:
            raise SilverRepairBatchValidationError(
                "indicator recompute range exceeds the configured bounded budget: "
                f"count={indicator_count}, max={max_indicator_recompute_dates}"
            )

    if registered_trade_dates is not None:
        registered = set(normalize_expected_trade_dates(registered_trade_dates))
        indicator_dates = _dates_between(
            expected,
            batch.indicator_recompute_start_trade_date,
            batch.indicator_recompute_end_trade_date,
        )
        missing_registered = tuple(date_key for date_key in indicator_dates if date_key not in registered)
        if missing_registered:
            raise SilverRepairBatchValidationError(
                "indicator recompute range contains unregistered dates: "
                f"{missing_registered[:5]}"
            )


def parse_silver_repair_batch(
    payload: Mapping[str, Any],
    *,
    expected_trade_dates: Sequence[object] | None = None,
    registered_trade_dates: Sequence[object] | None = None,
    max_indicator_recompute_dates: int | None = None,
) -> SilverRepairBatch:
    """Parse plain or ``goldenshare/`` metadata and fail closed on omissions."""

    def value(key: str) -> object:
        if key in payload:
            return payload[key]
        return payload.get(f"{SILVER_REPAIR_METADATA_PREFIX}{key}")

    required_keys = tuple(SilverRepairBatch.__dataclass_fields__)  # type: ignore[attr-defined]
    missing = tuple(key for key in required_keys if value(key) is None)
    if missing:
        raise SilverRepairBatchValidationError(
            f"Silver repair metadata is missing required keys: {missing}"
        )

    batch = SilverRepairBatch(
        source_asset=_require_text(value("source_asset"), "source_asset"),
        producer_run_id=_require_text(value("producer_run_id"), "producer_run_id"),
        upstream_batch_id=_require_text(value("upstream_batch_id"), "upstream_batch_id"),
        status=_require_text(value("status"), "status"),
        source_revision=_require_text(value("source_revision"), "source_revision"),
        source_repair_start_trade_date=normalize_trade_date(
            value("source_repair_start_trade_date"),
            field_name="source_repair_start_trade_date",
        ),
        source_repair_end_trade_date=normalize_trade_date(
            value("source_repair_end_trade_date"),
            field_name="source_repair_end_trade_date",
        ),
        indicator_recompute_start_trade_date=normalize_trade_date(
            value("indicator_recompute_start_trade_date"),
            field_name="indicator_recompute_start_trade_date",
        ),
        indicator_recompute_end_trade_date=normalize_trade_date(
            value("indicator_recompute_end_trade_date"),
            field_name="indicator_recompute_end_trade_date",
        ),
        context_start_trade_date=normalize_trade_date(
            value("context_start_trade_date"),
            field_name="context_start_trade_date",
        ),
        target_frontier_trade_date=normalize_trade_date(
            value("target_frontier_trade_date"),
            field_name="target_frontier_trade_date",
        ),
        affected_date_count=_require_int(value("affected_date_count"), "affected_date_count"),
        affected_series_count=_require_int(value("affected_series_count"), "affected_series_count"),
        affected_series_hash=_require_text(value("affected_series_hash"), "affected_series_hash"),
        truncated=_require_bool(value("truncated"), "truncated"),
        selected_partition_count=_require_int(
            value("selected_partition_count"),
            "selected_partition_count",
        ),
        protocol_version=_require_text(value("protocol_version"), "protocol_version"),
    )
    _validate_intrinsic(batch)
    if expected_trade_dates is not None:
        validate_silver_repair_batch(
            batch,
            expected_trade_dates=expected_trade_dates,
            registered_trade_dates=registered_trade_dates,
            max_indicator_recompute_dates=max_indicator_recompute_dates,
        )
    return batch


def _validate_ordering(batch: SilverRepairBatch) -> None:
    if batch.source_repair_start_trade_date > batch.source_repair_end_trade_date:
        raise SilverRepairBatchValidationError(
            "source repair start must not be later than source repair end."
        )
    if batch.indicator_recompute_start_trade_date > batch.indicator_recompute_end_trade_date:
        raise SilverRepairBatchValidationError(
            "indicator recompute start must not be later than indicator recompute end."
        )


def _validate_intrinsic(batch: SilverRepairBatch) -> None:
    if batch.protocol_version != SILVER_REPAIR_BATCH_PROTOCOL_VERSION:
        raise SilverRepairBatchValidationError(
            f"unsupported Silver repair protocol version: {batch.protocol_version}"
        )
    for field_name in (
        "source_asset",
        "producer_run_id",
        "upstream_batch_id",
        "source_revision",
    ):
        _require_text(getattr(batch, field_name), field_name)
    if not batch.ready:
        raise SilverRepairBatchValidationError(
            f"Silver repair batch status is not ready: {batch.status}"
        )
    if batch.truncated:
        raise SilverRepairBatchValidationError(
            "truncated Silver repair batches are not consumable."
        )
    if batch.affected_date_count <= 0:
        raise SilverRepairBatchValidationError("affected_date_count must be positive.")
    if batch.affected_series_count <= 0:
        raise SilverRepairBatchValidationError("affected_series_count must be positive.")
    if batch.selected_partition_count <= 0:
        raise SilverRepairBatchValidationError(
            "selected_partition_count must be positive."
        )
    _validate_ordering(batch)
    _validate_sha256(batch.affected_series_hash, field_name="affected_series_hash")


def _date_count(expected: Sequence[str], start: str, end: str) -> int:
    return len(_dates_between(expected, start, end))


def _dates_between(expected: Sequence[str], start: str, end: str) -> tuple[str, ...]:
    return tuple(date_key for date_key in expected if start <= date_key <= end)


def _validate_sha256(value: object, *, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise SilverRepairBatchValidationError(f"{field_name} must be a SHA-256 hex string.")
    if any(character not in "0123456789abcdef" for character in value.lower()):
        raise SilverRepairBatchValidationError(f"{field_name} must be a SHA-256 hex string.")


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SilverRepairBatchValidationError(f"{field_name} must be non-empty text.")
    return value.strip()


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SilverRepairBatchValidationError(f"{field_name} must be an integer.")
    return _require_non_negative_int(value, field_name=field_name)


def _require_non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SilverRepairBatchValidationError(
            f"{field_name} must be a non-negative integer."
        )
    return value


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SilverRepairBatchValidationError(f"{field_name} must be boolean.")
    return value


def _invalid_bool(field_name: str) -> bool:
    raise SilverRepairBatchValidationError(f"{field_name} must be boolean.")


__all__ = [
    "SILVER_REPAIR_BATCH_PROTOCOL_VERSION",
    "SILVER_REPAIR_READY_STATUS",
    "SilverRepairBatch",
    "SilverRepairBatchValidationError",
    "build_silver_repair_batch",
    "build_silver_repair_upstream_batch_id",
    "hash_affected_series",
    "normalize_expected_trade_dates",
    "normalize_trade_date",
    "parse_silver_repair_batch",
    "validate_silver_repair_batch",
]
