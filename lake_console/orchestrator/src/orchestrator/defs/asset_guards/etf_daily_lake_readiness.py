"""Bounded physical readiness for ETF daily Raw and Silver partitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import dagster as dg

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawSpec,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    EtfDailySilverSpec,
    audit_etf_daily_basic_coverage,
    audit_etf_daily_domain,
    audit_etf_daily_silver_relation,
    audit_etf_daily_source_filter,
    audit_etf_daily_source_parity,
    validate_etf_daily_basic_reference,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_SENSOR_WINDOW_LIMIT,
    normalize_etf_daily_trade_date,
)

_MATERIALIZATION_QUERY_LIMIT = ETF_DAILY_SENSOR_WINDOW_LIMIT * 10
_RAW_SPECS = (FUND_DAILY_RAW_SPEC, FUND_ADJ_RAW_SPEC)
_SILVER_SPECS = (FUND_DAILY_SILVER_SPEC, FUND_ADJ_SILVER_SPEC)


@dataclass(frozen=True, slots=True)
class EtfDailyPartitionReadiness:
    asset_key: str
    trade_date: str
    ready: bool
    materialized: bool
    file_exists: bool
    checks_passed: bool
    reason_code: str
    row_count: int | None
    content_hash: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trade_date",
            normalize_etf_daily_trade_date(self.trade_date),
        )
        if self.ready != (
            self.materialized and self.file_exists and self.checks_passed
        ):
            raise ValueError(
                "ETF daily ready must equal materialized, file_exists, and "
                "checks_passed."
            )
        if not self.reason_code or not self.reason_code.isascii():
            raise ValueError("ETF daily readiness reason_code must be non-empty ASCII.")
        if self.row_count is not None and self.row_count < 0:
            raise ValueError("ETF daily readiness row_count must not be negative.")


@dataclass(frozen=True, slots=True)
class EtfDailyBatchReadiness:
    asset_key: str
    statuses: tuple[EtfDailyPartitionReadiness, ...]
    materialization_query_count: int
    elapsed_ms: int

    def __post_init__(self) -> None:
        if self.materialization_query_count < 0 or self.materialization_query_count > 1:
            raise ValueError(
                "ETF daily readiness allows at most one materialization query per asset."
            )
        if self.elapsed_ms < 0:
            raise ValueError("ETF daily readiness elapsed_ms must not be negative.")
        dates = tuple(status.trade_date for status in self.statuses)
        if dates != tuple(sorted(set(dates))):
            raise ValueError(
                "ETF daily readiness statuses must use unique sorted dates."
            )
        if any(status.asset_key != self.asset_key for status in self.statuses):
            raise ValueError("ETF daily readiness statuses must use one asset key.")

    def status_for_trade_date(self, trade_date: str) -> EtfDailyPartitionReadiness:
        normalized = normalize_etf_daily_trade_date(trade_date)
        for status in self.statuses:
            if status.trade_date == normalized:
                return status
        return EtfDailyPartitionReadiness(
            asset_key=self.asset_key,
            trade_date=normalized,
            ready=False,
            materialized=False,
            file_exists=False,
            checks_passed=False,
            reason_code="readiness_status_missing",
            row_count=None,
            content_hash=None,
        )


@dataclass(frozen=True, slots=True)
class _MaterializationEvidence:
    metadata: Mapping[str, Any]


class _BorrowedDuckDBResource:
    """Expose one caller-owned connection to shared Basic audit code."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @contextmanager
    def connect(self):  # type: ignore[no-untyped-def]
        yield self._connection


def _metadata_scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _materialization_metadata(record: Any) -> dict[str, Any]:
    materialization = getattr(record, "asset_materialization", None)
    if materialization is None:
        raise ValueError("materialization_payload_missing")
    return {
        key: _metadata_scalar(value) for key, value in materialization.metadata.items()
    }


def _normalized_dates(values: Sequence[str]) -> tuple[str, ...]:
    dates = tuple(sorted({normalize_etf_daily_trade_date(value) for value in values}))
    if len(dates) > ETF_DAILY_SENSOR_WINDOW_LIMIT:
        raise ValueError("etf_daily_readiness_window_exceeds_ten_trade_dates")
    return dates


def _latest_materializations(
    *,
    instance: dg.DagsterInstance,
    asset_key: str,
    trade_dates: tuple[str, ...],
) -> tuple[dict[str, _MaterializationEvidence], int]:
    if not trade_dates:
        return {}, 0
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=list(trade_dates),
        ),
        limit=_MATERIALIZATION_QUERY_LIMIT,
    ).records
    latest: dict[str, _MaterializationEvidence] = {}
    for record in records:
        partition_key = str(
            getattr(record, "partition_key", None)
            or getattr(
                getattr(record, "asset_materialization", None), "partition", None
            )
            or ""
        ).strip()
        if partition_key not in trade_dates or partition_key in latest:
            continue
        # Dagster returns newest first. Never fall back if the latest payload is bad.
        try:
            metadata = _materialization_metadata(record)
        except (TypeError, ValueError):
            metadata = {}
        latest[partition_key] = _MaterializationEvidence(
            metadata=metadata,
        )
    missing = tuple(date for date in trade_dates if date not in latest)
    if missing and len(records) >= _MATERIALIZATION_QUERY_LIMIT:
        raise RuntimeError(
            "etf_daily_materialization_batch_truncated: "
            f"asset={asset_key}, missing={missing!r}"
        )
    return latest, 1


def _integer_metadata(metadata: Mapping[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _string_metadata(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _missing_status(
    *,
    asset_key: str,
    trade_date: str,
    file_exists: bool,
) -> EtfDailyPartitionReadiness:
    return EtfDailyPartitionReadiness(
        asset_key=asset_key,
        trade_date=trade_date,
        ready=False,
        materialized=False,
        file_exists=file_exists,
        checks_passed=False,
        reason_code=("materialized_check_failed" if file_exists else "missing"),
        row_count=None,
        content_hash=None,
    )


def _failed_status(
    *,
    asset_key: str,
    trade_date: str,
    file_exists: bool,
    row_count: int | None = None,
    content_hash: str | None = None,
) -> EtfDailyPartitionReadiness:
    return EtfDailyPartitionReadiness(
        asset_key=asset_key,
        trade_date=trade_date,
        ready=False,
        materialized=True,
        file_exists=file_exists,
        checks_passed=False,
        reason_code="materialized_check_failed",
        row_count=row_count,
        content_hash=content_hash,
    )


def _metadata_binding_errors(
    *,
    metadata: Mapping[str, Any],
    expected_path: Path,
    row_count: int,
    content_hash: str | None,
) -> tuple[str, ...]:
    errors: list[str] = []
    if _string_metadata(metadata, "dagster/uri") != str(expected_path):
        errors.append("materialization_uri_mismatch")
    if _integer_metadata(metadata, "dagster/row_count") != row_count:
        errors.append("materialization_row_count_mismatch")
    if (
        content_hash is None
        or _string_metadata(metadata, "goldenshare/content_hash") != content_hash
    ):
        errors.append("materialization_content_hash_mismatch")
    return tuple(errors)


def _raw_status(
    *,
    connection: Any,
    lake_root: Path,
    spec: EtfDailyRawSpec,
    trade_date: str,
    evidence: _MaterializationEvidence | None,
) -> EtfDailyPartitionReadiness:
    path = spec.target_path_builder(lake_root, trade_date)
    file_exists = path.is_file()
    if evidence is None:
        return _missing_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=file_exists,
        )
    if not file_exists:
        return _failed_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=False,
        )
    metadata = evidence.metadata
    source_row_count = _integer_metadata(metadata, "goldenshare/source_row_count")
    try:
        audit = audit_etf_daily_raw_relation(
            connection,
            relation_sql=read_parquet(path, hive_partitioning=False),
            spec=spec,
            partition_key=trade_date,
            expected_source_row_count=source_row_count,
        )
        errors = [*audit.error_codes]
        for key in (
            "goldenshare/source_row_count",
            "goldenshare/normalized_row_count",
            "goldenshare/written_row_count",
        ):
            if _integer_metadata(metadata, key) != audit.row_count:
                errors.append(f"{key}_mismatch")
        errors.extend(
            _metadata_binding_errors(
                metadata=metadata,
                expected_path=path,
                row_count=audit.row_count,
                content_hash=audit.content_hash,
            )
        )
    except Exception:  # noqa: BLE001 - corrupt files become failed readiness.
        return _failed_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=True,
        )
    if errors:
        return _failed_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=True,
            row_count=audit.row_count,
            content_hash=audit.content_hash,
        )
    return EtfDailyPartitionReadiness(
        asset_key=spec.asset_key,
        trade_date=trade_date,
        ready=True,
        materialized=True,
        file_exists=True,
        checks_passed=True,
        reason_code="ready",
        row_count=audit.row_count,
        content_hash=audit.content_hash,
    )


def _basic_reference(metadata: Mapping[str, Any]) -> EtfBasicSilverSnapshotReference:
    value = metadata.get("goldenshare/basic_reference")
    if not isinstance(value, Mapping):
        raise TypeError("basic_reference_metadata_missing")
    return EtfBasicSilverSnapshotReference.model_validate(
        dict(value)
    ).validate_contract()


def _silver_status(
    *,
    connection: Any,
    lake_root: Path,
    spec: EtfDailySilverSpec,
    trade_date: str,
    evidence: _MaterializationEvidence | None,
    validated_basic_references: dict[str, EtfBasicSilverSnapshotReference],
) -> EtfDailyPartitionReadiness:
    path = spec.target_path_builder(lake_root, trade_date)
    file_exists = path.is_file()
    if evidence is None:
        return _missing_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=file_exists,
        )
    if not file_exists:
        return _failed_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=False,
        )
    metadata = evidence.metadata
    row_count: int | None = None
    content_hash: str | None = None
    try:
        reference = _basic_reference(metadata)
        if reference.reference_fingerprint not in validated_basic_references:
            borrowed = cast(
                DuckDBResource,
                _BorrowedDuckDBResource(connection),
            )
            validated_basic_references[reference.reference_fingerprint] = (
                validate_etf_daily_basic_reference(
                    lake_root_path=lake_root,
                    duckdb_resource=borrowed,
                    basic_reference=reference,
                )
            )
        reference = validated_basic_references[reference.reference_fingerprint]
        raw_path = spec.raw_spec.target_path_builder(lake_root, trade_date)
        if not raw_path.is_file():
            raise ValueError("raw_file_missing")
        raw_sql = read_parquet(raw_path, hive_partitioning=False)
        silver_sql = read_parquet(path, hive_partitioning=False)
        basic_sql = read_parquet(Path(reference.silver_uri), hive_partitioning=False)
        raw_audit = audit_etf_daily_raw_relation(
            connection,
            relation_sql=raw_sql,
            spec=spec.raw_spec,
            partition_key=trade_date,
        )
        relation = audit_etf_daily_silver_relation(
            connection,
            relation_sql=silver_sql,
            spec=spec,
            partition_key=trade_date,
        )
        source_filter = audit_etf_daily_source_filter(
            connection,
            silver_relation_sql=silver_sql,
            basic_relation_sql=basic_sql,
        )
        parity = audit_etf_daily_source_parity(
            connection,
            raw_relation_sql=raw_sql,
            silver_relation_sql=silver_sql,
            basic_relation_sql=basic_sql,
            spec=spec,
        )
        domain = audit_etf_daily_domain(
            connection,
            silver_relation_sql=silver_sql,
            spec=spec,
        )
        row_count = relation.row_count
        content_hash = relation.content_hash
        errors = [
            *raw_audit.error_codes,
            *relation.error_codes,
            *source_filter.error_codes,
            *parity.error_codes,
            *domain.error_codes,
            *_metadata_binding_errors(
                metadata=metadata,
                expected_path=path,
                row_count=relation.row_count,
                content_hash=relation.content_hash,
            ),
        ]
        if spec.asset_key == FUND_ADJ_SILVER_SPEC.asset_key:
            coverage = audit_etf_daily_basic_coverage(
                connection,
                raw_relation_sql=raw_sql,
                silver_relation_sql=silver_sql,
                basic_relation_sql=basic_sql,
                partition_key=trade_date,
            )
            errors.extend(coverage.error_codes)
        expected_counts = {
            "goldenshare/raw_row_count": parity.raw_row_count,
            "goldenshare/selected_row_count": parity.selected_row_count,
            "goldenshare/rejected_row_count": parity.rejected_row_count,
            "goldenshare/written_row_count": relation.row_count,
        }
        errors.extend(
            f"{key}_mismatch"
            for key, expected in expected_counts.items()
            if _integer_metadata(metadata, key) != expected
        )
        expected_reference = {
            "goldenshare/basic_reference_fingerprint": (
                reference.reference_fingerprint
            ),
            "goldenshare/basic_raw_snapshot_hash": reference.raw_snapshot_hash,
            "goldenshare/basic_silver_content_hash": reference.silver_content_hash,
            "goldenshare/basic_raw_uri": reference.raw_uri,
            "goldenshare/basic_silver_uri": reference.silver_uri,
        }
        errors.extend(
            f"{key}_mismatch"
            for key, expected in expected_reference.items()
            if metadata.get(key) != expected
        )
    except Exception:  # noqa: BLE001 - corrupt lineage becomes failed readiness.
        return _failed_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=True,
            row_count=row_count,
            content_hash=content_hash,
        )
    if errors:
        return _failed_status(
            asset_key=spec.asset_key,
            trade_date=trade_date,
            file_exists=True,
            row_count=row_count,
            content_hash=content_hash,
        )
    return EtfDailyPartitionReadiness(
        asset_key=spec.asset_key,
        trade_date=trade_date,
        ready=True,
        materialized=True,
        file_exists=True,
        checks_passed=True,
        reason_code="ready",
        row_count=row_count,
        content_hash=content_hash,
    )


def _batch_readiness(
    *,
    instance: dg.DagsterInstance,
    connection: Any,
    lake_root: Path,
    spec: EtfDailyRawSpec | EtfDailySilverSpec,
    trade_dates: Sequence[str],
) -> EtfDailyBatchReadiness:
    started_at = perf_counter()
    dates = _normalized_dates(trade_dates)
    evidences, query_count = _latest_materializations(
        instance=instance,
        asset_key=spec.asset_key,
        trade_dates=dates,
    )
    validated_basic_references: dict[str, EtfBasicSilverSnapshotReference] = {}
    statuses: list[EtfDailyPartitionReadiness] = []
    for trade_date in dates:
        evidence = evidences.get(trade_date)
        if any(spec is approved for approved in _RAW_SPECS):
            statuses.append(
                _raw_status(
                    connection=connection,
                    lake_root=lake_root,
                    spec=cast(EtfDailyRawSpec, spec),
                    trade_date=trade_date,
                    evidence=evidence,
                )
            )
        elif any(spec is approved for approved in _SILVER_SPECS):
            statuses.append(
                _silver_status(
                    connection=connection,
                    lake_root=lake_root,
                    spec=cast(EtfDailySilverSpec, spec),
                    trade_date=trade_date,
                    evidence=evidence,
                    validated_basic_references=validated_basic_references,
                )
            )
        else:
            raise ValueError("ETF daily readiness requires one frozen dataset spec")
    return EtfDailyBatchReadiness(
        asset_key=spec.asset_key,
        statuses=tuple(statuses),
        materialization_query_count=query_count,
        elapsed_ms=int((perf_counter() - started_at) * 1000),
    )


def batch_fund_daily_raw_lake_readiness(**kwargs) -> EtfDailyBatchReadiness:  # type: ignore[no-untyped-def]
    return _batch_readiness(spec=FUND_DAILY_RAW_SPEC, **kwargs)


def batch_fund_adj_raw_lake_readiness(**kwargs) -> EtfDailyBatchReadiness:  # type: ignore[no-untyped-def]
    return _batch_readiness(spec=FUND_ADJ_RAW_SPEC, **kwargs)


def batch_etf_daily_silver_lake_readiness(**kwargs) -> EtfDailyBatchReadiness:  # type: ignore[no-untyped-def]
    return _batch_readiness(spec=FUND_DAILY_SILVER_SPEC, **kwargs)


def batch_etf_adj_factor_silver_lake_readiness(**kwargs) -> EtfDailyBatchReadiness:  # type: ignore[no-untyped-def]
    return _batch_readiness(spec=FUND_ADJ_SILVER_SPEC, **kwargs)


__all__ = [
    "EtfDailyBatchReadiness",
    "EtfDailyPartitionReadiness",
    "batch_etf_adj_factor_silver_lake_readiness",
    "batch_etf_daily_silver_lake_readiness",
    "batch_fund_adj_raw_lake_readiness",
    "batch_fund_daily_raw_lake_readiness",
]
