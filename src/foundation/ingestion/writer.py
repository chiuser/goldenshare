from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import math
from typing import Any

from sqlalchemy import Date as SqlDate
from sqlalchemy import DateTime as SqlDateTime
from sqlalchemy import and_, delete, func, or_, select, text, tuple_
from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.errors import IngestionWriteError, StructuredError
from src.foundation.ingestion.etf_basic_snapshot import (
    ETF_BASIC_BUSINESS_FIELDS,
    EtfBasicSnapshotValidationError,
    compute_etf_basic_snapshot_hash,
    diff_etf_basic_snapshots,
    extract_etf_basic_business_row,
    validate_etf_basic_snapshot,
)
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.moneyflow_publish import publish_moneyflow_serving_for_keys
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.observed_snapshot import (
    ObservedSnapshotHashError,
    SourceFieldMissingError,
    compute_source_content_hash,
    utc_now,
)
from src.foundation.ingestion.pre_write_validators import (
    PreWriteValidationError,
    get_pre_write_validator,
)
from src.foundation.ingestion.sentinel_guard import (
    find_forbidden_business_sentinel_in_row_context,
    should_guard_dataset_rows,
)
from src.foundation.services.transform.normalize_moneyflow_service import NormalizeMoneyflowService
from src.foundation.services.transform.normalize_security_service import NormalizeSecurityService
from src.utils import parse_tushare_date
from src.foundation.serving.publish_service import ServingPublishService


ETF_BASIC_SNAPSHOT_ADVISORY_LOCK_KEY = 8_491_716_204


@dataclass(slots=True, frozen=True)
class WriteResult:
    unit_id: str
    rows_written: int
    rows_upserted: int
    rows_skipped: int
    target_table: str
    conflict_strategy: str
    rows_rejected: int = 0
    rows_inserted: int = 0
    rows_matched: int = 0
    scope_existing_count: int = 0
    scope_source_unique_count: int = 0
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)
    rejected_reason_samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    persistence_diagnostics: dict[str, Any] = field(default_factory=dict)


class DatasetWriter:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self._moneyflow_normalizer = NormalizeMoneyflowService()
        self._security_normalizer = NormalizeSecurityService()

    def write(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None = None,
        run_profile: str | None = None,
    ) -> WriteResult:
        if should_guard_dataset_rows(definition.dataset_key):
            for index, row in enumerate(batch.rows_normalized):
                sentinel = find_forbidden_business_sentinel_in_row_context(row, path=f"rows_normalized[{index}]")
                if sentinel is not None:
                    path, value = sentinel
                    raise IngestionWriteError(
                        StructuredError(
                            error_code="forbidden_sentinel",
                            error_type="write",
                            phase="writer",
                            message=f"检测到非法业务占位值：{value}，位置：{path}",
                            retryable=False,
                            unit_id=batch.unit_id,
                        )
                    )
        if (
            definition.storage.write_path == "raw_only_upsert"
            and definition.quality.reject_policy == "fail_unit_on_any_rejection"
            and batch.rows_rejected > 0
        ):
            raise IngestionWriteError(
                StructuredError(
                    error_code="write.unit_rows_rejected",
                    error_type="write",
                    phase="writer",
                    message="执行单元存在拒绝行，已在业务写入前终止",
                    retryable=False,
                    unit_id=batch.unit_id,
                    details={
                        "rows_rejected": batch.rows_rejected,
                        "rejected_reasons": dict(batch.rejected_reasons),
                        "rejected_samples": dict(batch.rejected_samples),
                    },
                )
            )
        try:
            if definition.storage.write_path == "raw_etf_basic_snapshot_replace":
                return self._write_etf_basic_snapshot_replace(
                    definition=definition,
                    batch=batch,
                    plan_unit=plan_unit,
                )
            if definition.storage.write_path == "serving_direct_scope_replace":
                return self._write_serving_direct_scope_replace(
                    definition=definition,
                    batch=batch,
                    plan_unit=plan_unit,
                )
            if definition.storage.write_path == "serving_observed_snapshot_refresh":
                return self._write_serving_observed_snapshot_refresh(
                    definition=definition,
                    batch=batch,
                )
            if definition.storage.write_path == "serving_observed_fact_scope_refresh":
                return self._write_serving_observed_fact_scope_refresh(
                    definition=definition,
                    batch=batch,
                    plan_unit=plan_unit,
                )
            if definition.storage.write_path == "serving_immutable_fact_insert":
                return self._write_serving_immutable_fact_insert(
                    definition=definition,
                    batch=batch,
                    plan_unit=plan_unit,
                )

            raw_dao, core_dao = self._resolve_write_daos(definition=definition, unit_id=batch.unit_id)
            if definition.storage.write_path == "raw_index_period_serving_upsert":
                return self._write_index_period_serving(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    core_dao=core_dao,
                    plan_unit=plan_unit,
                    run_profile=run_profile,
                )
            if definition.storage.write_path == "raw_index_daily_serving_upsert":
                return self._write_index_daily_serving(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    core_dao=core_dao,
                )
            if definition.storage.write_path == "raw_fund_daily_etf_active_serving_upsert":
                return self._write_fund_daily_etf_active_serving(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    core_dao=core_dao,
                )
            if not batch.rows_normalized:
                return WriteResult(
                    unit_id=batch.unit_id,
                    rows_written=0,
                    rows_upserted=0,
                    rows_skipped=batch.rows_rejected,
                    target_table=definition.storage.target_table,
                    conflict_strategy="upsert",
                )
            if definition.storage.write_path == "serving_direct_upsert":
                return self._write_serving_direct_upsert(
                    definition=definition,
                    batch=batch,
                    core_dao=core_dao,
                )
            if definition.storage.write_path == "raw_std_publish_moneyflow":
                return self._write_moneyflow_std_publish(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    std_dao=core_dao,
                )
            if definition.storage.write_path == "raw_std_publish_stock_basic":
                return self._write_stock_basic_std_publish(
                    definition=definition,
                    batch=batch,
                    plan_unit=plan_unit,
                )
            if definition.storage.write_path == "raw_std_publish_moneyflow_biying":
                return self._write_moneyflow_std_publish_biying(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    std_dao=core_dao,
                )
            if definition.storage.write_path == "raw_core_snapshot_insert_by_trade_date":
                return self._write_snapshot_insert_by_trade_date(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    core_dao=core_dao,
                )
            if definition.storage.write_path == "raw_only_upsert":
                return self._write_raw_only_upsert(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                )
            if definition.storage.write_path != "raw_core_upsert":
                raise ValueError(f"不支持的写入路径：{definition.storage.write_path}")
            rows_upserted = self._write_raw_and_core(
                batch=batch,
                raw_dao=raw_dao,
                core_dao=core_dao,
                raw_conflict_columns=definition.storage.raw_conflict_columns,
                conflict_columns=definition.storage.conflict_columns,
                serving_conflict_resolution_policy=definition.storage.serving_conflict_resolution_policy,
            )
            rejected_reason_counts, rejected_reason_samples = self._duplicate_reason_diagnostics(
                rows=batch.rows_normalized,
                conflict_columns=self._resolve_effective_raw_conflict_columns(
                    raw_dao,
                    definition.storage.raw_conflict_columns,
                    definition.storage.conflict_columns,
                ),
                unit_id=batch.unit_id,
            )
        except IngestionWriteError:
            raise
        except Exception as exc:
            raise IngestionWriteError(
                StructuredError(
                    error_code="write_failed",
                    error_type="write",
                    phase="writer",
                    message=str(exc),
                    retryable=False,
                    unit_id=batch.unit_id,
                )
            ) from exc

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_upserted,
            rows_upserted=rows_upserted,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    def _resolve_write_daos(self, *, definition: DatasetDefinition, unit_id: str):  # type: ignore[no-untyped-def]
        if definition.storage.write_path == "serving_direct_upsert":
            core_dao = getattr(self.dao, definition.storage.core_dao_name, None)
            if core_dao is not None:
                return None, core_dao
            raise self._dao_not_found_error(definition=definition, unit_id=unit_id)

        raw_dao = getattr(self.dao, definition.storage.raw_dao_name, None)
        core_dao = getattr(self.dao, definition.storage.core_dao_name, None)
        if raw_dao is not None and core_dao is not None:
            return raw_dao, core_dao
        raise self._dao_not_found_error(definition=definition, unit_id=unit_id)

    def _resolve_observed_snapshot_daos(self, *, definition: DatasetDefinition, unit_id: str):  # type: ignore[no-untyped-def]
        current_dao = getattr(self.dao, definition.storage.core_dao_name, None)
        observation_dao = getattr(self.dao, definition.storage.observation_dao_name, None)
        if current_dao is not None and observation_dao is not None:
            return current_dao, observation_dao
        raise self._dao_not_found_error(definition=definition, unit_id=unit_id)

    @staticmethod
    def _dao_not_found_error(*, definition: DatasetDefinition, unit_id: str) -> IngestionWriteError:
        return IngestionWriteError(
            StructuredError(
                error_code="dao_not_found",
                error_type="write",
                phase="writer",
                message=(
                    f"DAO not found: raw={definition.storage.raw_dao_name} "
                    f"core={definition.storage.core_dao_name} "
                    f"observation={definition.storage.observation_dao_name}"
                ),
                retryable=False,
                unit_id=unit_id,
            )
        )

    def _write_etf_basic_snapshot_replace(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None,
    ) -> WriteResult:
        source_row_count = (
            len(batch.rows_normalized)
            + int(batch.rows_rejected or 0)
            + int(batch.rows_deduplicated or 0)
        )
        if batch.rows_rejected or batch.rows_deduplicated:
            raise self._etf_basic_snapshot_error(
                unit_id=batch.unit_id,
                message="ETF Basic 完整快照存在拒绝行或静默去重，已在业务写入前终止",
                details={
                    "source_rows": source_row_count,
                    "normalized_rows": len(batch.rows_normalized),
                    "rows_rejected": batch.rows_rejected,
                    "rows_deduplicated": batch.rows_deduplicated,
                    "rejected_reasons": dict(batch.rejected_reasons),
                    "rejected_samples": dict(batch.rejected_samples),
                },
            )

        validator_key = definition.quality.pre_write_validator_key
        try:
            get_pre_write_validator(str(validator_key or ""))(
                self.session,
                batch.rows_normalized,
                definition,
                plan_unit,
            )
            source_summary = validate_etf_basic_snapshot(
                batch.rows_normalized,
                source_row_count=source_row_count,
                normalized_row_count=len(batch.rows_normalized),
            )
        except (PreWriteValidationError, EtfBasicSnapshotValidationError) as exc:
            raise self._etf_basic_snapshot_error(
                unit_id=batch.unit_id,
                message=str(exc),
                details=getattr(exc, "details", {}),
            ) from exc

        raw_dao, serving_dao = self._resolve_write_daos(
            definition=definition,
            unit_id=batch.unit_id,
        )
        raw_model = raw_dao.model
        serving_model = serving_dao.model
        self._lock_etf_basic_snapshot()

        lock_rows = self.session.get_bind().dialect.name == "postgresql"
        raw_before_rows = self._select_etf_basic_business_rows(raw_model, lock_rows=lock_rows)
        serving_before_rows = self._select_etf_basic_business_rows(serving_model, lock_rows=lock_rows)
        snapshot_diff = diff_etf_basic_snapshots(raw_before_rows, batch.rows_normalized)
        raw_before_hash = compute_etf_basic_snapshot_hash(raw_before_rows)
        serving_before_hash = compute_etf_basic_snapshot_hash(serving_before_rows)

        raw_rows = self._coerce_rows_for_dao(
            [extract_etf_basic_business_row(row) for row in batch.rows_normalized],
            raw_dao,
        )
        serving_source_rows = [
            extract_etf_basic_business_row(row)
            for row in batch.rows_normalized
            if str(row.get("ts_code") or "").endswith((".SH", ".SZ"))
        ]
        serving_rows = self._coerce_rows_for_dao(serving_source_rows, serving_dao)
        expected_raw_codes = {str(row["ts_code"]) for row in raw_rows}
        expected_serving_codes = {str(row["ts_code"]) for row in serving_rows}
        expected_serving_hash = compute_etf_basic_snapshot_hash(serving_rows)

        self.session.execute(delete(raw_model))
        raw_rows_inserted = raw_dao.bulk_insert(raw_rows)
        self.session.execute(delete(serving_model))
        serving_rows_inserted = serving_dao.bulk_insert(serving_rows)
        self.session.flush()

        raw_after_rows = self._select_etf_basic_business_rows(raw_model)
        serving_after_rows = self._select_etf_basic_business_rows(serving_model)
        actual_raw_codes = {str(row["ts_code"]) for row in raw_after_rows}
        actual_serving_codes = {str(row["ts_code"]) for row in serving_after_rows}
        raw_business_hash = compute_etf_basic_snapshot_hash(raw_after_rows)
        serving_business_hash = compute_etf_basic_snapshot_hash(serving_after_rows)

        reconciliation_failed = (
            raw_rows_inserted != len(raw_rows)
            or serving_rows_inserted != len(serving_rows)
            or actual_raw_codes != expected_raw_codes
            or actual_serving_codes != expected_serving_codes
            or raw_business_hash != source_summary.snapshot_hash
            or serving_business_hash != expected_serving_hash
        )
        if reconciliation_failed:
            raise self._etf_basic_snapshot_error(
                unit_id=batch.unit_id,
                message="ETF Basic 快照写后主键集合或业务内容 hash 对账失败",
                details={
                    "expected_raw_count": len(raw_rows),
                    "raw_rows_inserted": raw_rows_inserted,
                    "raw_after_count": len(raw_after_rows),
                    "expected_serving_count": len(serving_rows),
                    "serving_rows_inserted": serving_rows_inserted,
                    "serving_after_count": len(serving_after_rows),
                    "source_snapshot_hash": source_summary.snapshot_hash,
                    "raw_business_hash": raw_business_hash,
                    "expected_serving_hash": expected_serving_hash,
                    "serving_business_hash": serving_business_hash,
                },
            )

        snapshot_diagnostics = {
            "source_rows": source_row_count,
            "normalized_rows": len(batch.rows_normalized),
            "raw_rows_written": raw_rows_inserted,
            "raw_before_count": len(raw_before_rows),
            "raw_after_count": len(raw_after_rows),
            "serving_before_count": len(serving_before_rows),
            "serving_after_count": len(serving_after_rows),
            "source_snapshot_hash": source_summary.snapshot_hash,
            "raw_before_business_hash": raw_before_hash,
            "raw_business_hash": raw_business_hash,
            "serving_before_business_hash": serving_before_hash,
            "serving_business_hash": serving_business_hash,
            "status_counts": dict(source_summary.status_counts),
            "list_date_null_counts": dict(source_summary.list_date_null_counts),
            **snapshot_diff.to_diagnostics(),
        }
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=len(serving_after_rows),
            rows_upserted=0,
            rows_skipped=0,
            target_table=definition.storage.target_table,
            conflict_strategy="raw_etf_basic_snapshot_replace",
            rows_inserted=serving_rows_inserted,
            scope_existing_count=len(serving_before_rows),
            scope_source_unique_count=len(serving_rows),
            persistence_diagnostics={"etf_basic_snapshot": snapshot_diagnostics},
        )

    def _lock_etf_basic_snapshot(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": ETF_BASIC_SNAPSHOT_ADVISORY_LOCK_KEY},
        )

    def _select_etf_basic_business_rows(
        self,
        model,
        *,
        lock_rows: bool = False,
    ) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        columns = [getattr(model, field_name) for field_name in ETF_BASIC_BUSINESS_FIELDS]
        statement = select(*columns).order_by(getattr(model, "ts_code"))
        if lock_rows:
            statement = statement.with_for_update()
        return [dict(row) for row in self.session.execute(statement).mappings()]

    @staticmethod
    def _etf_basic_snapshot_error(
        *,
        unit_id: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> IngestionWriteError:
        return IngestionWriteError(
            StructuredError(
                error_code="etf_basic_snapshot_invalid",
                error_type="write",
                phase="writer",
                message=message,
                retryable=False,
                unit_id=unit_id,
                details=dict(details or {}),
            )
        )

    def _write_serving_direct_upsert(self, *, definition: DatasetDefinition, batch: NormalizedBatch, core_dao) -> WriteResult:  # type: ignore[no-untyped-def]
        rows = self._coerce_rows_for_dao(batch.rows_normalized, core_dao)
        conflict_columns = self._materialize_conflict_columns(core_dao, definition.storage.conflict_columns)
        rows_upserted = core_dao.bulk_upsert(rows, conflict_columns=list(conflict_columns) or None)
        rejected_reason_counts, rejected_reason_samples = self._duplicate_reason_diagnostics(
            rows=batch.rows_normalized,
            conflict_columns=conflict_columns,
            unit_id=batch.unit_id,
        )
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_upserted,
            rows_upserted=rows_upserted,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="serving_direct_upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    def _write_serving_direct_scope_replace(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None,
    ) -> WriteResult:
        if batch.rows_rejected:
            raise self._scope_replace_error(
                code="write.scope_rows_rejected",
                unit_id=batch.unit_id,
                message="完整范围存在归一化拒绝行，禁止发布部分结果",
                details={"rows_rejected": batch.rows_rejected},
            )
        if not batch.rows_normalized:
            if definition.quality.empty_result_policy == "allow":
                return WriteResult(
                    unit_id=batch.unit_id,
                    rows_written=0,
                    rows_upserted=0,
                    rows_skipped=0,
                    target_table=definition.storage.target_table,
                    conflict_strategy="serving_direct_scope_replace_empty_noop",
                )
            raise self._scope_replace_error(
                code="write.scope_empty",
                unit_id=batch.unit_id,
                message="完整范围为空，拒绝清空目标范围",
            )

        core_dao = getattr(self.dao, definition.storage.core_dao_name, None)
        if core_dao is None:
            raise self._dao_not_found_error(definition=definition, unit_id=batch.unit_id)

        validator_key = definition.quality.pre_write_validator_key
        try:
            get_pre_write_validator(str(validator_key or ""))(
                self.session,
                batch.rows_normalized,
                definition,
                plan_unit,
            )
        except PreWriteValidationError as exc:
            raise self._scope_replace_error(
                code="write.scope_preflight_failed",
                unit_id=batch.unit_id,
                message=str(exc),
                details=exc.details,
            ) from exc

        scope_fields = definition.storage.replacement_scope_fields
        scopes = {
            tuple(row.get(field_name) for field_name in scope_fields)
            for row in batch.rows_normalized
        }
        if len(scopes) != 1 or any(value is None for value in next(iter(scopes), ())):
            raise self._scope_replace_error(
                code="write.scope_invalid",
                unit_id=batch.unit_id,
                message="完整范围替换必须且只能从批次中解析出一个非空 scope",
                details={"scope_fields": list(scope_fields), "scope_count": len(scopes)},
            )
        scope_values = next(iter(scopes))
        scope = dict(zip(scope_fields, scope_values, strict=True))
        if "trade_date" in scope and plan_unit is not None and scope["trade_date"] != plan_unit.trade_date:
            raise self._scope_replace_error(
                code="write.scope_unit_mismatch",
                unit_id=batch.unit_id,
                message="批次 trade_date scope 与执行单元不一致",
            )

        model = core_dao.model
        filters = [getattr(model, field_name) == value for field_name, value in scope.items()]
        self._lock_scope(model=model, filters=filters, scope=scope)

        rows = self._coerce_rows_for_dao(batch.rows_normalized, core_dao)
        conflict_columns = self._materialize_conflict_columns(core_dao, definition.storage.conflict_columns)
        expected_by_key = self._rows_by_key(
            rows=rows,
            key_fields=conflict_columns,
            unit_id=batch.unit_id,
        )
        existing_count = int(
            self.session.scalar(select(func.count()).select_from(model).where(and_(*filters))) or 0
        )
        self.session.execute(delete(model).where(and_(*filters)))
        rows_inserted = core_dao.bulk_insert(rows)
        self.session.flush()
        actual_objects = list(self.session.scalars(select(model).where(and_(*filters))))
        column_names = tuple(
            column.name
            for column in model.__table__.columns
            if column.name not in {"created_at", "updated_at"}
        )
        actual_rows = [
            {column_name: getattr(item, column_name) for column_name in column_names}
            for item in actual_objects
        ]
        actual_by_key = self._rows_by_key(
            rows=actual_rows,
            key_fields=conflict_columns,
            unit_id=batch.unit_id,
        )
        expected_hash = self._scope_rows_hash(expected_by_key.values(), column_names=column_names)
        actual_hash = self._scope_rows_hash(actual_by_key.values(), column_names=column_names)
        if (
            rows_inserted != len(expected_by_key)
            or set(actual_by_key) != set(expected_by_key)
            or actual_hash != expected_hash
        ):
            raise self._scope_replace_error(
                code="write.scope_reconciliation_failed",
                unit_id=batch.unit_id,
                message="完整范围替换后的键集或内容摘要与已验证批次不一致",
                details={
                    "expected_rows": len(expected_by_key),
                    "inserted_rows": rows_inserted,
                    "actual_rows": len(actual_by_key),
                    "expected_hash": expected_hash,
                    "actual_hash": actual_hash,
                },
            )
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=len(expected_by_key),
            rows_upserted=0,
            rows_skipped=0,
            target_table=definition.storage.target_table,
            conflict_strategy="serving_direct_scope_replace",
            rows_inserted=len(expected_by_key),
            scope_existing_count=existing_count,
            scope_source_unique_count=len(expected_by_key),
        )

    def _lock_scope(self, *, model, filters: list[Any], scope: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
        bind = self.session.get_bind()
        if bind.dialect.name == "postgresql":
            lock_payload = f"{model.__table__.fullname}:{self._canonical_value(scope)}"
            lock_key = int.from_bytes(hashlib.sha256(lock_payload.encode("utf-8")).digest()[:8], "big", signed=True)
            self.session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
        self.session.execute(select(model).where(and_(*filters)).with_for_update())

    def _rows_by_key(
        self,
        *,
        rows: list[dict[str, Any]],
        key_fields: tuple[str, ...],
        unit_id: str,
    ) -> dict[tuple[Any, ...], dict[str, Any]]:
        result: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            key = tuple(row.get(field_name) for field_name in key_fields)
            if any(value is None for value in key) or key in result:
                raise self._scope_replace_error(
                    code="write.scope_identity_invalid",
                    unit_id=unit_id,
                    message="完整范围存在空或重复业务键",
                    details={"key_fields": list(key_fields), "key": [str(value) for value in key]},
                )
            result[key] = row
        return result

    @classmethod
    def _scope_rows_hash(cls, rows, *, column_names: tuple[str, ...]) -> str:  # type: ignore[no-untyped-def]
        payload = [
            {column_name: cls._canonical_value(row.get(column_name)) for column_name in column_names}
            for row in rows
        ]
        payload.sort(key=lambda row: json.dumps(row, ensure_ascii=True, sort_keys=True))
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _canonical_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._canonical_value(item) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [cls._canonical_value(item) for item in value]
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
            return value
        if isinstance(value, (Decimal, float)):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("范围替换内容摘要不支持非有限数值")
            return format(number, ".15g")
        return str(value)

    @staticmethod
    def _scope_replace_error(
        *,
        code: str,
        unit_id: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> IngestionWriteError:
        return IngestionWriteError(
            StructuredError(
                error_code=code,
                error_type="write",
                phase="writer",
                message=message,
                retryable=False,
                unit_id=unit_id,
                details=dict(details or {}),
            )
        )

    def _write_serving_observed_snapshot_refresh(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
    ) -> WriteResult:
        if batch.rows_rejected:
            raise self._observed_snapshot_error(
                code="write.snapshot_rows_rejected",
                unit_id=batch.unit_id,
                message="完整观察快照存在归一化拒绝行，不能用部分结果替换 current projection",
                details={"rows_rejected": batch.rows_rejected},
            )
        if not batch.rows_normalized:
            raise self._observed_snapshot_error(
                code="write.snapshot_empty",
                unit_id=batch.unit_id,
                message="完整观察快照为空，拒绝清空现有 current projection",
            )

        current_dao, observation_dao = self._resolve_observed_snapshot_daos(
            definition=definition,
            unit_id=batch.unit_id,
        )
        self._validate_observed_snapshot_dao_contract(
            definition=definition,
            current_dao=current_dao,
            observation_dao=observation_dao,
            unit_id=batch.unit_id,
        )

        snapshot_rows: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        for row in batch.rows_normalized:
            source_entity_key = row.get("source_entity_key")
            if not isinstance(source_entity_key, str) or not source_entity_key.strip():
                raise self._observed_snapshot_error(
                    code="write.source_entity_key_missing",
                    unit_id=batch.unit_id,
                    message="完整观察快照行缺少非空 source_entity_key",
                )
            try:
                source_content_hash = compute_source_content_hash(
                    row=row,
                    source_fields=definition.source.source_fields,
                )
            except SourceFieldMissingError as exc:
                raise self._observed_snapshot_error(
                    code="write.source_field_missing",
                    unit_id=batch.unit_id,
                    message=str(exc),
                    details={"field": exc.field},
                ) from exc
            except ObservedSnapshotHashError as exc:
                raise self._observed_snapshot_error(
                    code="write.snapshot_content_hash_invalid",
                    unit_id=batch.unit_id,
                    message=str(exc),
                ) from exc

            identity = (source_entity_key, source_content_hash)
            if identity in seen_keys:
                raise self._observed_snapshot_error(
                    code="write.snapshot_duplicate_record",
                    unit_id=batch.unit_id,
                    message="完整观察快照存在无法表示的重复源记录",
                    details={"source_entity_key": source_entity_key, "source_content_hash": source_content_hash},
                )
            seen_keys.add(identity)
            snapshot_rows.append({**row, "source_content_hash": source_content_hash})

        current_rows = self._coerce_rows_for_dao(snapshot_rows, current_dao)
        observation_rows = self._coerce_rows_for_dao(snapshot_rows, observation_dao)
        observed_at = utc_now()
        observation_result = observation_dao.record_observations(observation_rows, observed_at=observed_at)
        current_written = current_dao.replace_current_snapshot(current_rows, observed_at=observed_at)
        expected_rows = len(snapshot_rows)
        if observation_result.rows_observed != expected_rows or current_written != expected_rows:
            raise self._observed_snapshot_error(
                code="write.snapshot_persistence_incomplete",
                unit_id=batch.unit_id,
                message="完整观察快照写入行数与已验证源记录数不一致",
                details={
                    "expected_rows": expected_rows,
                    "observation_rows_observed": observation_result.rows_observed,
                    "current_rows_written": current_written,
                },
            )
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=expected_rows,
            rows_upserted=expected_rows,
            rows_skipped=0,
            target_table=definition.storage.target_table,
            conflict_strategy="serving_observed_snapshot_refresh",
        )

    def _write_serving_observed_fact_scope_refresh(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None,
    ) -> WriteResult:
        scope_field = definition.quality.unit_date_field
        scope_value = plan_unit.trade_date if plan_unit is not None else None
        if not scope_field or scope_value is None:
            raise self._observed_snapshot_error(
                code="write.fact_scope_invalid",
                unit_id=batch.unit_id,
                message="按范围观察事实写入缺少执行单元日期范围",
            )
        if batch.rows_rejected:
            raise self._observed_snapshot_error(
                code="write.fact_rows_rejected",
                unit_id=batch.unit_id,
                message="按范围观察事实存在归一化拒绝行，不能用部分结果替换 current projection",
                details={"rows_rejected": batch.rows_rejected},
            )
        if not batch.rows_normalized:
            return WriteResult(
                unit_id=batch.unit_id,
                rows_written=0,
                rows_upserted=0,
                rows_skipped=0,
                target_table=definition.storage.target_table,
                conflict_strategy="serving_observed_fact_scope_refresh",
            )

        current_dao, observation_dao = self._resolve_observed_snapshot_daos(
            definition=definition,
            unit_id=batch.unit_id,
        )
        self._validate_observed_snapshot_dao_contract(
            definition=definition,
            current_dao=current_dao,
            observation_dao=observation_dao,
            unit_id=batch.unit_id,
            error_code="write.fact_storage_invalid",
        )
        current_columns = {column.name for column in current_dao.model.__table__.columns}
        observation_columns = {column.name for column in observation_dao.model.__table__.columns}
        if scope_field not in current_columns or scope_field not in observation_columns:
            raise self._observed_snapshot_error(
                code="write.fact_storage_invalid",
                unit_id=batch.unit_id,
                message=f"按范围观察事实目标表缺少 scope 列：{scope_field}",
            )

        fact_rows: list[dict[str, Any]] = []
        seen_entity_keys: set[str] = set()
        for row in batch.rows_normalized:
            if row.get(scope_field) != scope_value:
                raise self._observed_snapshot_error(
                    code="write.fact_scope_invalid",
                    unit_id=batch.unit_id,
                    message="按范围观察事实行日期与执行单元范围不一致",
                    details={"scope_field": scope_field, "expected": str(scope_value), "actual": str(row.get(scope_field))},
                )
            source_entity_key = row.get("source_entity_key")
            if not isinstance(source_entity_key, str) or not source_entity_key.strip():
                raise self._observed_snapshot_error(
                    code="write.source_entity_key_missing",
                    unit_id=batch.unit_id,
                    message="按范围观察事实行缺少非空 source_entity_key",
                )
            if source_entity_key in seen_entity_keys:
                raise self._observed_snapshot_error(
                    code="write.fact_duplicate_record",
                    unit_id=batch.unit_id,
                    message="按范围观察事实中同一逻辑实体出现多条源记录",
                    details={"source_entity_key": source_entity_key},
                )
            seen_entity_keys.add(source_entity_key)
            try:
                source_content_hash = compute_source_content_hash(
                    row=row,
                    source_fields=definition.source.source_fields,
                )
            except SourceFieldMissingError as exc:
                raise self._observed_snapshot_error(
                    code="write.source_field_missing",
                    unit_id=batch.unit_id,
                    message=str(exc),
                    details={"field": exc.field},
                ) from exc
            except ObservedSnapshotHashError as exc:
                raise self._observed_snapshot_error(
                    code="write.fact_content_hash_invalid",
                    unit_id=batch.unit_id,
                    message=str(exc),
                ) from exc
            fact_rows.append({**row, "source_content_hash": source_content_hash})

        current_rows = self._coerce_rows_for_dao(fact_rows, current_dao)
        observation_rows = self._coerce_rows_for_dao(fact_rows, observation_dao)
        current_dao.acquire_scope_lock(scope_field=scope_field, scope_value=scope_value)
        observed_at = utc_now()
        observation_result = observation_dao.record_observations(observation_rows, observed_at=observed_at)
        current_written = current_dao.replace_current_scope(
            current_rows,
            observed_at=observed_at,
            scope_field=scope_field,
            scope_value=scope_value,
            scope_lock_acquired=True,
        )
        expected_rows = len(fact_rows)
        if observation_result.rows_observed != expected_rows or current_written != expected_rows:
            raise self._observed_snapshot_error(
                code="write.fact_persistence_incomplete",
                unit_id=batch.unit_id,
                message="按范围观察事实写入行数与已验证源记录数不一致",
                details={
                    "expected_rows": expected_rows,
                    "observation_rows_observed": observation_result.rows_observed,
                    "current_rows_written": current_written,
                },
            )
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=expected_rows,
            rows_upserted=expected_rows,
            rows_skipped=0,
            target_table=definition.storage.target_table,
            conflict_strategy="serving_observed_fact_scope_refresh",
        )

    def _write_serving_immutable_fact_insert(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None,
    ) -> WriteResult:
        scope_field = definition.quality.unit_date_field
        scope_value = plan_unit.trade_date if plan_unit is not None else None
        if not scope_field or scope_value is None:
            raise self._observed_snapshot_error(
                code="write.immutable_scope_invalid",
                unit_id=batch.unit_id,
                message="不可变事实写入缺少执行单元日期范围",
            )
        if batch.rows_rejected:
            raise self._observed_snapshot_error(
                code="write.immutable_rows_rejected",
                unit_id=batch.unit_id,
                message="不可变事实存在归一化拒绝行，不能写入部分日期范围",
                details={"rows_rejected": batch.rows_rejected},
            )

        fact_dao = getattr(self.dao, definition.storage.core_dao_name, None)
        if fact_dao is None:
            raise self._dao_not_found_error(definition=definition, unit_id=batch.unit_id)
        table = getattr(getattr(fact_dao, "model", None), "__table__", None)
        if table is None or not all(
            callable(getattr(fact_dao, method_name, None))
            for method_name in ("acquire_scope_lock", "fetch_scope_identity_hashes", "insert_new_rows")
        ):
            raise self._observed_snapshot_error(
                code="write.immutable_storage_invalid",
                unit_id=batch.unit_id,
                message="不可变事实 DAO 未实现只插入协议",
            )
        required_columns = {
            *definition.source.source_fields,
            "source_entity_key",
            "source_content_hash",
            "identity_basis",
            scope_field,
        }
        missing_columns = sorted(required_columns - {column.name for column in table.columns})
        if missing_columns:
            raise self._observed_snapshot_error(
                code="write.immutable_storage_invalid",
                unit_id=batch.unit_id,
                message="不可变事实目标表缺少协议或显式 source field 列",
                details={"missing_columns": missing_columns},
            )

        validated_rows: list[dict[str, Any]] = []
        incoming_hashes: dict[str, str] = {}
        for row in batch.rows_normalized:
            if row.get(scope_field) != scope_value:
                raise self._observed_snapshot_error(
                    code="write.immutable_scope_invalid",
                    unit_id=batch.unit_id,
                    message="不可变事实行日期与执行单元范围不一致",
                    details={"scope_field": scope_field, "expected": str(scope_value), "actual": str(row.get(scope_field))},
                )
            source_entity_key = row.get("source_entity_key")
            if not isinstance(source_entity_key, str) or not source_entity_key.strip():
                raise self._observed_snapshot_error(
                    code="write.source_entity_key_missing",
                    unit_id=batch.unit_id,
                    message="不可变事实行缺少非空 source_entity_key",
                )
            identity_basis = row.get("identity_basis")
            if not isinstance(identity_basis, str) or not identity_basis.strip():
                raise self._observed_snapshot_error(
                    code="write.immutable_identity_invalid",
                    unit_id=batch.unit_id,
                    message="不可变事实行缺少非空 identity_basis",
                )
            try:
                source_content_hash = compute_source_content_hash(
                    row=row,
                    source_fields=definition.source.source_fields,
                )
            except SourceFieldMissingError as exc:
                raise self._observed_snapshot_error(
                    code="write.source_field_missing",
                    unit_id=batch.unit_id,
                    message=str(exc),
                    details={"field": exc.field},
                ) from exc
            except ObservedSnapshotHashError as exc:
                raise self._observed_snapshot_error(
                    code="write.immutable_content_hash_invalid",
                    unit_id=batch.unit_id,
                    message=str(exc),
                ) from exc
            if source_entity_key in incoming_hashes:
                raise self._observed_snapshot_error(
                    code="write.immutable_identity_conflict",
                    unit_id=batch.unit_id,
                    message="不可变事实中同一实体键出现多条不同源事实",
                    details={"source_entity_key": source_entity_key},
                )
            incoming_hashes[source_entity_key] = source_content_hash
            validated_rows.append({**row, "source_content_hash": source_content_hash})

        fact_dao.acquire_scope_lock(scope_field=scope_field, scope_value=scope_value)
        existing_hashes = fact_dao.fetch_scope_identity_hashes(scope_field=scope_field, scope_value=scope_value)
        if not validated_rows:
            if existing_hashes:
                raise self._observed_snapshot_error(
                    code="write.immutable_scope_regression",
                    unit_id=batch.unit_id,
                    message="源端空结果会使已入库日期范围回退，拒绝接受",
                    details={"existing_rows": len(existing_hashes)},
                )
            return WriteResult(
                unit_id=batch.unit_id,
                rows_written=0,
                rows_upserted=0,
                rows_skipped=0,
                target_table=definition.storage.target_table,
                conflict_strategy="serving_immutable_fact_insert",
            )

        missing_existing = sorted(set(existing_hashes) - set(incoming_hashes))
        if missing_existing:
            raise self._observed_snapshot_error(
                code="write.immutable_scope_regression",
                unit_id=batch.unit_id,
                message="本次源端范围缺少已入库不可变事实，拒绝范围回退",
                details={"missing_count": len(missing_existing), "sample_keys": missing_existing[:3]},
            )
        conflicting_keys = sorted(
            key for key, content_hash in existing_hashes.items() if incoming_hashes.get(key) != content_hash
        )
        if conflicting_keys:
            raise self._observed_snapshot_error(
                code="write.immutable_fact_conflict",
                unit_id=batch.unit_id,
                message="已入库不可变事实与本次源事实内容冲突，拒绝覆盖",
                details={"conflict_count": len(conflicting_keys), "sample_keys": conflicting_keys[:3]},
            )

        ingested_at = utc_now()
        new_rows = [
            {**row, "ingested_at": ingested_at}
            for row in validated_rows
            if row["source_entity_key"] not in existing_hashes
        ]
        rows_inserted = fact_dao.insert_new_rows(self._coerce_rows_for_dao(new_rows, fact_dao))
        if rows_inserted != len(new_rows):
            raise self._observed_snapshot_error(
                code="write.immutable_persistence_incomplete",
                unit_id=batch.unit_id,
                message="不可变事实插入行数与已验证新事实数不一致",
                details={"expected_inserted": len(new_rows), "actual_inserted": rows_inserted},
            )
        persisted_hashes = fact_dao.fetch_scope_identity_hashes(scope_field=scope_field, scope_value=scope_value)
        if persisted_hashes != incoming_hashes:
            raise self._observed_snapshot_error(
                code="write.immutable_persistence_incomplete",
                unit_id=batch.unit_id,
                message="不可变事实写后核对未与本次完整范围一致",
                details={"expected_rows": len(incoming_hashes), "actual_rows": len(persisted_hashes)},
            )
        rows_matched = len(existing_hashes)
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=len(validated_rows),
            rows_upserted=rows_inserted,
            rows_skipped=0,
            target_table=definition.storage.target_table,
            conflict_strategy="serving_immutable_fact_insert",
            rows_inserted=rows_inserted,
            rows_matched=rows_matched,
            scope_existing_count=len(persisted_hashes),
            scope_source_unique_count=len(incoming_hashes),
        )

    @classmethod
    def _validate_observed_snapshot_dao_contract(
        cls,
        *,
        definition: DatasetDefinition,
        current_dao,
        observation_dao,
        unit_id: str,
        error_code: str = "write.snapshot_storage_invalid",
    ) -> None:  # type: ignore[no-untyped-def]
        current_table = getattr(getattr(current_dao, "model", None), "__table__", None)
        observation_table = getattr(getattr(observation_dao, "model", None), "__table__", None)
        if current_table is None or observation_table is None:
            raise cls._observed_snapshot_error(
                code=error_code,
                unit_id=unit_id,
                message="观察快照 DAO 必须显式绑定 ORM model",
            )
        if current_table.fullname == observation_table.fullname:
            raise cls._observed_snapshot_error(
                code=error_code,
                unit_id=unit_id,
                message="current 与 observation DAO 不能绑定同一张表",
            )
        source_fields = set(definition.source.source_fields)
        current_columns = {column.name for column in current_table.columns}
        observation_columns = {column.name for column in observation_table.columns}
        protocol_columns = {"source_entity_key", "source_content_hash"}
        current_missing = sorted((source_fields | protocol_columns | {"observed_at"}) - current_columns)
        observation_missing = sorted(
            (source_fields | protocol_columns | {"first_observed_at", "last_observed_at"}) - observation_columns
        )
        if current_missing or observation_missing:
            raise cls._observed_snapshot_error(
                code=error_code,
                unit_id=unit_id,
                message="观察快照目标表缺少协议或显式 source field 列",
                details={"current_missing": current_missing, "observation_missing": observation_missing},
            )

    @staticmethod
    def _observed_snapshot_error(
        *,
        code: str,
        unit_id: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> IngestionWriteError:
        return IngestionWriteError(
            StructuredError(
                error_code=code,
                error_type="write",
                phase="writer",
                message=message,
                retryable=False,
                unit_id=unit_id,
                details=details or {},
            )
        )

    def _write_index_daily_serving(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
    ) -> WriteResult:
        if not batch.rows_normalized:
            return WriteResult(
                unit_id=batch.unit_id,
                rows_written=0,
                rows_upserted=0,
                rows_skipped=batch.rows_rejected,
                target_table=definition.storage.target_table,
                conflict_strategy="index_daily_active_gate",
            )

        raw_rows = self._coerce_rows_for_dao(batch.rows_normalized, raw_dao)
        if definition.storage.conflict_columns:
            raw_dao.bulk_upsert(raw_rows, conflict_columns=list(definition.storage.conflict_columns))
        else:
            raw_dao.bulk_upsert(raw_rows)

        active_rows = self._filter_index_rows_by_active_pool(
            rows=batch.rows_normalized,
            active_codes=self._resolve_active_index_codes(),
        )
        rows_written = 0
        rejected_reason_counts, rejected_reason_samples = self._duplicate_reason_diagnostics(
            rows=active_rows,
            conflict_columns=self._resolve_conflict_columns(
                core_dao,
                definition.storage.conflict_columns,
            ),
            unit_id=batch.unit_id,
        )
        if active_rows:
            core_rows = self._coerce_rows_for_dao(active_rows, core_dao)
            if definition.storage.conflict_columns:
                rows_written = core_dao.bulk_upsert(core_rows, conflict_columns=list(definition.storage.conflict_columns))
            else:
                rows_written = core_dao.bulk_upsert(core_rows)

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_written,
            rows_upserted=rows_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="index_daily_active_gate",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    def _write_fund_daily_etf_active_serving(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
    ) -> WriteResult:
        if not batch.rows_normalized:
            return WriteResult(
                unit_id=batch.unit_id,
                rows_written=0,
                rows_upserted=0,
                rows_skipped=batch.rows_rejected,
                target_table=definition.storage.target_table,
                conflict_strategy="fund_daily_etf_active_gate",
            )

        raw_rows = self._coerce_rows_for_dao(batch.rows_normalized, raw_dao)
        if definition.storage.conflict_columns:
            raw_dao.bulk_upsert(raw_rows, conflict_columns=list(definition.storage.conflict_columns))
        else:
            raw_dao.bulk_upsert(raw_rows)

        active_rows = self._filter_fund_daily_rows_by_etf_active_pool(
            rows=batch.rows_normalized,
            active_codes=self._resolve_active_etf_codes("fund_daily"),
        )
        rows_written = 0
        rejected_reason_counts, rejected_reason_samples = self._duplicate_reason_diagnostics(
            rows=active_rows,
            conflict_columns=self._resolve_conflict_columns(
                core_dao,
                definition.storage.conflict_columns,
            ),
            unit_id=batch.unit_id,
        )
        if active_rows:
            core_rows = self._coerce_rows_for_dao(active_rows, core_dao)
            if definition.storage.conflict_columns:
                rows_written = core_dao.bulk_upsert(core_rows, conflict_columns=list(definition.storage.conflict_columns))
            else:
                rows_written = core_dao.bulk_upsert(core_rows)

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_written,
            rows_upserted=rows_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="fund_daily_etf_active_gate",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    def _write_index_period_serving(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
        plan_unit: PlanUnitSnapshot | None,
        run_profile: str | None,
    ) -> WriteResult:
        rows_written = 0
        conflict_strategy = "upsert"
        rejected_reason_counts: dict[str, int] = {}
        rejected_reason_samples: dict[str, list[dict[str, Any]]] = {}
        active_codes = self._resolve_active_index_codes()
        explicit_ts_code = bool(
            plan_unit is not None and str(plan_unit.request_params.get("ts_code") or "").strip()
        )
        full_date_refresh = (not explicit_ts_code) and run_profile in {"point_incremental", "range_rebuild"}
        if batch.rows_normalized:
            if full_date_refresh:
                self._purge_index_period_raw_rows_by_trade_dates(raw_dao=raw_dao, rows=batch.rows_normalized)
            if definition.storage.conflict_columns:
                raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(definition.storage.conflict_columns))
            else:
                raw_dao.bulk_upsert(batch.rows_normalized)
            filtered_rows = self._filter_index_rows_by_active_pool(
                rows=batch.rows_normalized,
                active_codes=active_codes,
            )
            duplicate_counts, duplicate_samples = self._duplicate_reason_diagnostics(
                rows=batch.rows_normalized,
                conflict_columns=self._resolve_conflict_columns(
                    raw_dao,
                    definition.storage.conflict_columns,
                ),
                unit_id=batch.unit_id,
            )
            self._merge_reason_counts(rejected_reason_counts, duplicate_counts)
            self._merge_reason_samples(rejected_reason_samples, duplicate_samples)
            serving_rows = self._build_index_period_serving_rows(
                rows=filtered_rows,
                dataset_key=definition.dataset_key,
            )
            if full_date_refresh and plan_unit is not None and not explicit_ts_code:
                trade_date = plan_unit.trade_date
                if isinstance(trade_date, date):
                    existing_codes = {
                        str(row.get("ts_code")).strip().upper()
                        for row in serving_rows
                        if row.get("ts_code")
                    }
                    missing_codes = sorted(active_codes - existing_codes)
                    if missing_codes:
                        serving_rows.extend(
                            self._build_index_period_derived_rows_for_codes(
                                definition=definition,
                                trade_date=trade_date,
                                ts_codes=missing_codes,
                            )
                        )
            if not serving_rows:
                rows_written = 0
            elif full_date_refresh:
                rows_written = self._replace_index_period_serving_rows_by_trade_dates(
                    core_dao=core_dao,
                    rows=serving_rows,
                )
            else:
                rows_written = self._replace_index_period_serving_rows(
                    core_dao=core_dao,
                    rows=serving_rows,
                    keep_api=False,
                )
            conflict_strategy = "index_period_upsert"
        elif plan_unit is not None and (run_profile == "point_incremental" or full_date_refresh):
            if explicit_ts_code:
                ts_code = str(plan_unit.request_params.get("ts_code") or "").strip().upper()
                derived_rows = (
                    self._build_index_period_derived_rows(
                        definition=definition,
                        plan_unit=plan_unit,
                    )
                    if ts_code in active_codes
                    else []
                )
            else:
                trade_date = plan_unit.trade_date
                derived_rows = (
                    self._build_index_period_derived_rows_for_codes(
                        definition=definition,
                        trade_date=trade_date,
                        ts_codes=sorted(active_codes),
                    )
                    if isinstance(trade_date, date)
                    else []
                )
            if full_date_refresh:
                rows_written = self._replace_index_period_serving_rows_by_trade_dates(
                    core_dao=core_dao,
                    rows=derived_rows,
                )
            else:
                rows_written = self._replace_index_period_derived_rows_preserving_api(
                    core_dao=core_dao,
                    rows=derived_rows,
                )
            conflict_strategy = "derived_daily_fallback"

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_written,
            rows_upserted=rows_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy=conflict_strategy,
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    def _build_index_period_serving_rows(
        self,
        *,
        rows: list[dict[str, Any]],
        dataset_key: str,
    ) -> list[dict[str, Any]]:
        period_start_cache: dict[date, date] = {}
        serving_rows: list[dict[str, Any]] = []
        for row in rows:
            trade_date = row.get("trade_date")
            ts_code = row.get("ts_code")
            if not isinstance(trade_date, date) or ts_code in (None, ""):
                continue
            transformed = dict(row)
            transformed["period_start_date"] = self._resolve_index_period_start_date(
                dataset_key=dataset_key,
                trade_date=trade_date,
                cache=period_start_cache,
            )
            transformed["source"] = "api"
            transformed.setdefault("change_amount", transformed.get("change"))
            serving_rows.append(transformed)
        return serving_rows

    def _build_index_period_derived_rows(
        self,
        *,
        definition: DatasetDefinition,
        plan_unit: PlanUnitSnapshot,
    ) -> list[dict[str, Any]]:
        ts_code = str(plan_unit.request_params.get("ts_code") or "").strip().upper()
        trade_date = plan_unit.trade_date
        if not ts_code or not isinstance(trade_date, date):
            return []
        return self._build_index_period_derived_rows_for_codes(
            definition=definition,
            trade_date=trade_date,
            ts_codes=[ts_code],
        )

    def _build_index_period_derived_rows_for_codes(
        self,
        *,
        definition: DatasetDefinition,
        trade_date: date,
        ts_codes: list[str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for code in ts_codes:
            ts_code = str(code or "").strip().upper()
            if not ts_code:
                continue
            results.extend(
                self._build_index_period_derived_rows_for_single_code(
                    definition=definition,
                    trade_date=trade_date,
                    ts_code=ts_code,
                )
            )
        return results

    def _build_index_period_derived_rows_for_single_code(
        self,
        *,
        definition: DatasetDefinition,
        trade_date: date,
        ts_code: str,
    ) -> list[dict[str, Any]]:
        period_start_date = self._resolve_index_period_start_date(
            dataset_key=definition.dataset_key,
            trade_date=trade_date,
            cache={},
        )
        sql = text(
            """
            with win as (
                select
                    d.ts_code,
                    d.trade_date,
                    d.open,
                    d.high,
                    d.low,
                    d.close,
                    d.pre_close,
                    d.vol,
                    d.amount,
                    row_number() over (partition by d.ts_code order by d.trade_date asc) as rn_first,
                    row_number() over (partition by d.ts_code order by d.trade_date desc) as rn_last
                from core_serving.index_daily_serving d
                where d.trade_date between :start_date and :trade_date
                  and d.ts_code = :ts_code
            ),
            agg as (
                select
                    ts_code,
                    max(case when rn_first = 1 then open end) as open,
                    max(high) as high,
                    min(low) as low,
                    max(case when rn_last = 1 then close end) as close,
                    max(case when rn_first = 1 then pre_close end) as pre_close,
                    sum(vol) as vol,
                    sum(amount) as amount
                from win
                group by ts_code
            )
            select
                a.ts_code as ts_code,
                :period_start_date as period_start_date,
                :trade_date as trade_date,
                a.open as open,
                a.high as high,
                a.low as low,
                a.close as close,
                a.pre_close as pre_close,
                case when a.pre_close is null or a.close is null then null else a.close - a.pre_close end as change_amount,
                case
                    when a.pre_close is null or a.pre_close = 0 or a.close is null then null
                    else round(((a.close / a.pre_close) - 1), 4)
                end as pct_chg,
                a.vol * 100 as vol,
                a.amount * 1000 as amount,
                'derived_daily' as source
            from agg a
            """
        )
        rows = self.session.execute(
            sql,
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "period_start_date": period_start_date,
                "start_date": period_start_date,
            },
        ).mappings()
        return [dict(row) for row in rows]

    def _replace_index_period_serving_rows(
        self,
        *,
        core_dao,
        rows: list[dict[str, Any]],
        keep_api: bool,
    ) -> int:
        if not rows:
            return 0
        deduped_rows = self._dedupe_index_period_rows(rows)
        if not deduped_rows:
            return 0
        model = core_dao.model
        period_keys = [(row["ts_code"], row["period_start_date"]) for row in deduped_rows]
        trade_keys = [(row["ts_code"], row["trade_date"]) for row in deduped_rows]
        stmt = delete(model).where(
            or_(
                tuple_(model.ts_code, model.period_start_date).in_(period_keys),
                tuple_(model.ts_code, model.trade_date).in_(trade_keys),
            )
        )
        if keep_api:
            stmt = stmt.where(model.source != "api")
        self.session.execute(stmt)
        return core_dao.bulk_insert(deduped_rows)

    def _replace_index_period_serving_rows_by_trade_dates(
        self,
        *,
        core_dao,
        rows: list[dict[str, Any]],
    ) -> int:
        trade_dates = sorted(
            {
                row["trade_date"]
                for row in rows
                if isinstance(row.get("trade_date"), date)
            }
        )
        if not trade_dates:
            return 0
        model = core_dao.model
        self.session.execute(delete(model).where(model.trade_date.in_(trade_dates)))
        deduped_rows = self._dedupe_index_period_rows(rows)
        if not deduped_rows:
            return 0
        return core_dao.bulk_insert(deduped_rows)

    def _replace_index_period_derived_rows_preserving_api(
        self,
        *,
        core_dao,
        rows: list[dict[str, Any]],
    ) -> int:
        """Refresh derived rows only when no API row already owns the same period."""
        deduped_rows = self._dedupe_index_period_rows(rows)
        if not deduped_rows:
            return 0
        model = core_dao.model
        period_keys = [(row["ts_code"], row["period_start_date"]) for row in deduped_rows]
        trade_keys = [(row["ts_code"], row["trade_date"]) for row in deduped_rows]
        api_rows = self.session.execute(
            select(model.ts_code, model.period_start_date, model.trade_date).where(
                model.source == "api",
                or_(
                    tuple_(model.ts_code, model.period_start_date).in_(period_keys),
                    tuple_(model.ts_code, model.trade_date).in_(trade_keys),
                ),
            )
        ).all()
        api_period_keys = {
            (str(ts_code).strip().upper(), period_start_date)
            for ts_code, period_start_date, _trade_date in api_rows
        }
        api_trade_keys = {
            (str(ts_code).strip().upper(), trade_date)
            for ts_code, _period_start_date, trade_date in api_rows
        }
        derived_rows = [
            row
            for row in deduped_rows
            if (
                str(row["ts_code"]).strip().upper(),
                row["period_start_date"],
            )
            not in api_period_keys
            and (
                str(row["ts_code"]).strip().upper(),
                row["trade_date"],
            )
            not in api_trade_keys
        ]
        if not derived_rows:
            return 0
        period_keys = [(row["ts_code"], row["period_start_date"]) for row in derived_rows]
        trade_keys = [(row["ts_code"], row["trade_date"]) for row in derived_rows]
        self.session.execute(
            delete(model).where(
                or_(
                    tuple_(model.ts_code, model.period_start_date).in_(period_keys),
                    tuple_(model.ts_code, model.trade_date).in_(trade_keys),
                )
            ).where(model.source != "api")
        )
        # A concurrent writer may win after the API check; never fail or overwrite it.
        return core_dao.bulk_insert_ignore_conflicts(derived_rows)

    @staticmethod
    def _dedupe_index_period_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped_by_key: dict[tuple[str, date], dict[str, Any]] = {}
        for row in rows:
            ts_code = row.get("ts_code")
            period_start_date = row.get("period_start_date")
            trade_date = row.get("trade_date")
            if ts_code in (None, "") or not isinstance(period_start_date, date) or not isinstance(trade_date, date):
                continue
            deduped_by_key[(str(ts_code), period_start_date)] = row
        return list(deduped_by_key.values())

    @staticmethod
    def _filter_index_rows_by_active_pool(
        *,
        rows: list[dict[str, Any]],
        active_codes: set[str],
    ) -> list[dict[str, Any]]:
        if not active_codes:
            return []
        filtered_rows: list[dict[str, Any]] = []
        for row in rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if ts_code and ts_code in active_codes:
                filtered_rows.append(row)
        return filtered_rows

    def _resolve_active_index_codes(self) -> set[str]:
        active_codes = self.dao.index_series_active.list_active_codes("index_daily")
        return {
            str(code).strip().upper()
            for code in active_codes
            if str(code).strip()
        }

    @staticmethod
    def _filter_fund_daily_rows_by_etf_active_pool(
        *,
        rows: list[dict[str, Any]],
        active_codes: set[str],
    ) -> list[dict[str, Any]]:
        if not active_codes:
            return []
        filtered_rows: list[dict[str, Any]] = []
        for row in rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if ts_code and ts_code in active_codes:
                filtered_rows.append(row)
        return filtered_rows

    def _resolve_active_etf_codes(self, resource: str) -> set[str]:
        active_codes = self.dao.etf_series_active.list_active_codes(resource)
        return {
            str(code).strip().upper()
            for code in active_codes
            if str(code).strip()
        }

    @staticmethod
    def _purge_index_period_raw_rows_by_trade_dates(*, raw_dao, rows: list[dict[str, Any]]) -> None:
        trade_dates = sorted({row["trade_date"] for row in rows if isinstance(row.get("trade_date"), date)})
        for current_date in trade_dates:
            raw_dao.delete_by_date_range(current_date, current_date)

    def _resolve_index_period_start_date(
        self,
        *,
        dataset_key: str,
        trade_date: date,
        cache: dict[date, date] | None,
    ) -> date:
        natural_start = self._resolve_natural_period_start(dataset_key=dataset_key, trade_date=trade_date)
        if cache is not None and natural_start in cache:
            return cache[natural_start]
        exchange = self.dao.trade_calendar.settings.default_exchange
        open_dates = self.dao.trade_calendar.get_open_dates(exchange, natural_start, trade_date)
        period_start = open_dates[0] if open_dates else natural_start
        if cache is not None:
            cache[natural_start] = period_start
        return period_start

    @staticmethod
    def _resolve_natural_period_start(*, dataset_key: str, trade_date: date) -> date:
        if dataset_key == "index_monthly":
            return trade_date.replace(day=1)
        if dataset_key == "index_weekly":
            return trade_date - timedelta(days=trade_date.weekday())
        raise ValueError(f"不支持生成指数周期服务数据：{dataset_key}")

    @classmethod
    def _write_raw_and_core(
        cls,
        *,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
        raw_conflict_columns: tuple[str, ...] | None,
        conflict_columns: tuple[str, ...] | None,
        serving_conflict_resolution_policy: str = "none",
    ) -> int:
        raw_rows = cls._coerce_rows_for_dao(batch.rows_normalized, raw_dao)
        core_rows = cls._coerce_rows_for_dao(batch.rows_normalized, core_dao)
        if conflict_columns:
            raw_conflict_columns = cls._resolve_effective_raw_conflict_columns(
                raw_dao,
                raw_conflict_columns,
                conflict_columns,
            )
            core_conflict_columns = cls._materialize_conflict_columns(core_dao, conflict_columns)
            core_rows = cls._apply_serving_conflict_resolution(
                rows=core_rows,
                conflict_columns=core_conflict_columns,
                resolution_policy=serving_conflict_resolution_policy,
            )
            if raw_conflict_columns:
                raw_dao.bulk_upsert(raw_rows, conflict_columns=list(raw_conflict_columns))
            else:
                raw_dao.bulk_upsert(raw_rows)
            if core_conflict_columns:
                return core_dao.bulk_upsert(core_rows, conflict_columns=list(core_conflict_columns))
            return core_dao.bulk_upsert(core_rows)
        raw_dao.bulk_upsert(raw_rows)
        return core_dao.bulk_upsert(core_rows)

    @classmethod
    def _apply_serving_conflict_resolution(
        cls,
        *,
        rows: list[dict[str, Any]],
        conflict_columns: tuple[str, ...],
        resolution_policy: str,
    ) -> list[dict[str, Any]]:
        if resolution_policy == "none" or not rows or not conflict_columns:
            return rows
        if resolution_policy != "top_list_variant_resolution_v1":
            return rows
        grouped_payload_rows: dict[tuple[Any, ...], dict[str, dict[str, Any]]] = {}
        ordered_groups: list[tuple[Any, ...]] = []
        ordered_payload_hashes: dict[tuple[Any, ...], list[str]] = {}
        passthrough_rows: list[dict[str, Any]] = []
        for row in rows:
            if any(column not in row or row[column] is None for column in conflict_columns):
                passthrough_rows.append(cls._annotate_top_list_variant(row, variant_count=1))
                continue
            payload_hash = str(row.get("payload_hash") or "").strip()
            if not payload_hash:
                passthrough_rows.append(cls._annotate_top_list_variant(row, variant_count=1))
                continue
            key = tuple(row[column] for column in conflict_columns)
            if key not in grouped_payload_rows:
                grouped_payload_rows[key] = {}
                ordered_payload_hashes[key] = []
                ordered_groups.append(key)
            if payload_hash not in grouped_payload_rows[key]:
                ordered_payload_hashes[key].append(payload_hash)
            grouped_payload_rows[key][payload_hash] = row

        resolved_rows = list(passthrough_rows)
        for key in ordered_groups:
            payload_rows = grouped_payload_rows[key]
            ordered_hashes = ordered_payload_hashes[key]
            selected = payload_rows[ordered_hashes[0]]
            for payload_hash in ordered_hashes[1:]:
                selected = cls._prefer_non_null_float_values_row(selected, payload_rows[payload_hash])
            resolved_rows.append(
                cls._annotate_top_list_variant(
                    selected,
                    variant_count=len(ordered_hashes),
                )
            )
        return resolved_rows

    @staticmethod
    def _annotate_top_list_variant(row: dict[str, Any], *, variant_count: int) -> dict[str, Any]:
        annotated = dict(row)
        payload_hash = str(annotated.get("payload_hash") or "").strip()
        annotated["selected_payload_hash"] = payload_hash or None
        annotated["variant_count"] = max(int(variant_count), 1)
        annotated["resolution_policy_version"] = "top_list_variant_resolution_v1"
        return annotated

    @staticmethod
    def _prefer_non_null_float_values_row(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        current_is_null = DatasetWriter._is_effective_null_float_values(current.get("float_values"))
        candidate_is_null = DatasetWriter._is_effective_null_float_values(candidate.get("float_values"))
        if current_is_null and not candidate_is_null:
            return candidate
        if not current_is_null and candidate_is_null:
            return current
        return candidate

    @staticmethod
    def _is_effective_null_float_values(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, Decimal):
            return value.is_nan()
        if isinstance(value, float):
            return value != value
        text = str(value).strip().lower()
        return text in {"", "nan", "nat", "none", "null"}

    @staticmethod
    def _coerce_rows_for_dao(rows: list[dict[str, Any]], dao) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        model = getattr(dao, "model", None)
        table = getattr(model, "__table__", None)
        if table is None:
            return [dict(row) for row in rows]
        date_columns = {
            column.name
            for column in table.columns
            if isinstance(column.type, SqlDate) and not isinstance(column.type, SqlDateTime)
        }
        if not date_columns:
            return [dict(row) for row in rows]
        prepared: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for column_name in date_columns:
                if column_name in normalized:
                    normalized[column_name] = parse_tushare_date(normalized[column_name])
            prepared.append(normalized)
        return prepared

    @staticmethod
    def _resolve_conflict_columns(dao, explicit_columns: tuple[str, ...] | None) -> tuple[str, ...]:
        if explicit_columns:
            return tuple(explicit_columns)
        model = getattr(dao, "model", None)
        table = getattr(model, "__table__", None)
        primary_key = getattr(table, "primary_key", None)
        if primary_key is None:
            return ()
        return tuple(column.name for column in primary_key.columns)

    @classmethod
    def _materialize_conflict_columns(
        cls,
        dao,
        explicit_columns: tuple[str, ...] | None,
    ) -> tuple[str, ...]:
        if not explicit_columns:
            return ()
        model = getattr(dao, "model", None)
        table = getattr(model, "__table__", None)
        if table is None:
            return tuple(explicit_columns)
        table_columns = {column.name for column in table.columns}
        if all(column in table_columns for column in explicit_columns):
            return tuple(explicit_columns)
        return cls._resolve_conflict_columns(dao, None)

    @classmethod
    def _resolve_effective_raw_conflict_columns(
        cls,
        raw_dao,
        raw_conflict_columns: tuple[str, ...] | None,
        serving_conflict_columns: tuple[str, ...] | None,
    ) -> tuple[str, ...]:
        if raw_conflict_columns:
            return cls._materialize_conflict_columns(raw_dao, raw_conflict_columns)
        return cls._materialize_conflict_columns(raw_dao, serving_conflict_columns)

    @classmethod
    def _duplicate_reason_counts(
        cls,
        *,
        rows: list[dict[str, Any]],
        conflict_columns: tuple[str, ...] | list[str] | None,
    ) -> dict[str, int]:
        counts, _ = cls._duplicate_reason_diagnostics(
            rows=rows,
            conflict_columns=conflict_columns,
            unit_id=None,
        )
        return counts

    @classmethod
    def _duplicate_reason_diagnostics(
        cls,
        *,
        rows: list[dict[str, Any]],
        conflict_columns: tuple[str, ...] | list[str] | None,
        unit_id: str | None,
    ) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
        columns = tuple(conflict_columns or ())
        if not rows or not columns:
            return {}, {}
        seen: set[tuple[Any, ...]] = set()
        duplicate_count = 0
        reason_key = f"write.duplicate_conflict_key_in_batch:{','.join(columns)}"
        samples: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if any(column not in row or row[column] is None for column in columns):
                continue
            key = tuple(row[column] for column in columns)
            if key in seen:
                duplicate_count += 1
                cls._record_duplicate_sample(
                    samples=samples,
                    reason_key=reason_key,
                    row=row,
                    columns=columns,
                    key=key,
                    unit_id=unit_id,
                )
                continue
            seen.add(key)
        return cls._reason_count(reason_key, duplicate_count), samples

    @classmethod
    def _record_duplicate_sample(
        cls,
        *,
        samples: dict[str, list[dict[str, Any]]],
        reason_key: str,
        row: dict[str, Any],
        columns: tuple[str, ...],
        key: tuple[Any, ...],
        unit_id: str | None,
    ) -> None:
        bucket = samples.setdefault(reason_key, [])
        if len(bucket) >= DatasetNormalizer.MAX_SAMPLES_PER_REASON:
            return
        field = ",".join(columns)
        value: Any
        if len(columns) == 1:
            value = key[0]
        else:
            value = {column: key[index] for index, column in enumerate(columns)}
        bucket.append(
            {
                "unit_id": DatasetNormalizer._sample_scalar(unit_id),
                "field": DatasetNormalizer._sample_scalar(field),
                "value": DatasetNormalizer._sample_scalar(value),
                "message": "同批次出现重复冲突键，当前样本为重复行。",
                "row": DatasetNormalizer._sample_row(row=row, field=field),
            }
        )

    @staticmethod
    def _reason_count(reason_key: str, count: int) -> dict[str, int]:
        normalized_count = int(count or 0)
        if normalized_count <= 0:
            return {}
        return {reason_key: normalized_count}

    @staticmethod
    def _merge_reason_counts(target: dict[str, int], source: dict[str, int]) -> None:
        for key, count in source.items():
            normalized_key = str(key or "").strip()
            normalized_count = int(count or 0)
            if not normalized_key or normalized_count <= 0:
                continue
            target[normalized_key] = target.get(normalized_key, 0) + normalized_count

    @staticmethod
    def _merge_reason_samples(target: dict[str, list[dict[str, Any]]], source: dict[str, list[dict[str, Any]]]) -> None:
        for key, samples in source.items():
            normalized_key = str(key or "").strip()
            if not normalized_key or not isinstance(samples, list):
                continue
            bucket = target.setdefault(normalized_key, [])
            for sample in samples:
                if len(bucket) >= DatasetNormalizer.MAX_SAMPLES_PER_REASON:
                    break
                if isinstance(sample, dict):
                    bucket.append(dict(sample))

    def _write_stock_basic_std_publish(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None,
    ) -> WriteResult:
        source_key = str(plan_unit.source_key if plan_unit is not None else "tushare").strip().lower()
        requested_source_key = str(
            plan_unit.requested_source_key if plan_unit is not None else source_key
        ).strip().lower()
        if source_key not in {"tushare", "biying"}:
            raise ValueError(f"股票基础信息不支持该数据来源：{source_key}")

        raw_dao = self.dao.raw_tushare_stock_basic if source_key == "tushare" else self.dao.raw_biying_stock_basic
        raw_rows = self._prepare_stock_basic_raw_rows(rows=batch.rows_normalized, source_key=source_key)
        if raw_rows:
            raw_dao.bulk_upsert(raw_rows)

        std_rows = [self._security_normalizer.to_std(row, source_key=source_key) for row in batch.rows_normalized]
        if std_rows:
            self.dao.security_std.bulk_upsert(std_rows)

        written = 0
        conflict_strategy = "upsert"
        rejected_reason_counts: dict[str, int] = {}
        if requested_source_key == "all":
            touched_ts_codes = {
                str(row.get("ts_code")).strip().upper()
                for row in std_rows
                if str(row.get("ts_code") or "").strip()
            }
            std_rows_by_source = self._load_security_std_rows_by_source(touched_ts_codes=touched_ts_codes)
            publish_result = ServingPublishService(self.dao).publish_dataset(
                dataset_key="stock_basic",
                std_rows_by_source=std_rows_by_source,
            )
            written = int(publish_result.written)
            conflict_strategy = "resolution_publish"
        elif source_key == "biying":
            ts_codes = [str(row["ts_code"]) for row in std_rows if row.get("ts_code")]
            existing = self.dao.security.get_existing_ts_codes(ts_codes)
            serving_rows = [
                {key: value for key, value in row.items() if key != "source_key"}
                for row in std_rows
                if str(row.get("ts_code") or "") and str(row["ts_code"]) not in existing
            ]
            written = self.dao.security.upsert_many(serving_rows) if serving_rows else 0
            conflict_strategy = "biying_missing_only"
            rejected_reason_counts = self._reason_count(
                "write.filtered_by_business_rule:ts_code",
                len(std_rows) - len(serving_rows),
            )
        else:
            serving_rows = [{key: value for key, value in row.items() if key != "source_key"} for row in std_rows]
            written = self.dao.security.upsert_many(serving_rows) if serving_rows else 0
            conflict_strategy = "tushare_direct_upsert"

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=written,
            rows_upserted=written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy=conflict_strategy,
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
        )

    @staticmethod
    def _prepare_stock_basic_raw_rows(*, rows: list[dict[str, Any]], source_key: str) -> list[dict[str, Any]]:
        if source_key == "tushare":
            prepared: list[dict[str, Any]] = []
            for row in rows:
                ts_code = str(row.get("ts_code") or "").strip().upper()
                if not ts_code:
                    continue
                normalized = dict(row)
                normalized["ts_code"] = ts_code
                prepared.append(normalized)
            return prepared

        prepared = []
        for row in rows:
            dm = str(row.get("dm") or row.get("ts_code") or "").strip().upper()
            if not dm:
                continue
            prepared.append(
                {
                    "dm": dm,
                    "mc": row.get("mc") or row.get("name"),
                    "jys": row.get("jys") or row.get("exchange"),
                }
            )
        return prepared

    def _load_security_std_rows_by_source(self, *, touched_ts_codes: set[str]) -> dict[str, list[dict[str, Any]]]:
        if not touched_ts_codes:
            return {}
        model = self.dao.security_std.model
        columns = [column.name for column in model.__table__.columns if column.name not in {"created_at", "updated_at"}]
        stmt = select(model).where(model.ts_code.in_(sorted(touched_ts_codes)))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in self.session.scalars(stmt):
            source = str(getattr(item, "source_key", "") or "").strip()
            if not source:
                continue
            payload = {column_name: getattr(item, column_name) for column_name in columns}
            grouped.setdefault(source, []).append(payload)
        return grouped

    def _write_moneyflow_std_publish(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        std_dao,
    ) -> WriteResult:
        rejected_reason_counts, rejected_reason_samples = self._duplicate_reason_diagnostics(
            rows=batch.rows_normalized,
            conflict_columns=self._resolve_conflict_columns(std_dao, definition.storage.conflict_columns),
            unit_id=batch.unit_id,
        )
        if definition.storage.conflict_columns:
            raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(definition.storage.conflict_columns))
        else:
            raw_dao.bulk_upsert(batch.rows_normalized)
        std_rows = [self._moneyflow_normalizer.to_std_from_tushare(row) for row in batch.rows_normalized]
        if definition.storage.conflict_columns:
            std_dao.bulk_upsert(std_rows, conflict_columns=list(definition.storage.conflict_columns))
        else:
            std_dao.bulk_upsert(std_rows)
        touched_keys = {
            (str(row["ts_code"]), row["trade_date"])
            for row in std_rows
            if row.get("ts_code") and isinstance(row.get("trade_date"), date)
        }
        serving_written = publish_moneyflow_serving_for_keys(
            self.dao,
            self.session,
            touched_keys,
        )
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=serving_written,
            rows_upserted=serving_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    def _write_moneyflow_std_publish_biying(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        std_dao,
    ) -> WriteResult:
        rejected_reason_counts, rejected_reason_samples = self._duplicate_reason_diagnostics(
            rows=batch.rows_normalized,
            conflict_columns=self._resolve_conflict_columns(std_dao, definition.storage.conflict_columns),
            unit_id=batch.unit_id,
        )
        if definition.storage.conflict_columns:
            raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(definition.storage.conflict_columns))
        else:
            raw_dao.bulk_upsert(batch.rows_normalized)
        std_rows = [self._moneyflow_normalizer.to_std_from_biying_raw(row) for row in batch.rows_normalized]
        if definition.storage.conflict_columns:
            std_dao.bulk_upsert(std_rows, conflict_columns=list(definition.storage.conflict_columns))
        else:
            std_dao.bulk_upsert(std_rows)
        touched_keys = {
            (str(row["ts_code"]), row["trade_date"])
            for row in std_rows
            if row.get("ts_code") and isinstance(row.get("trade_date"), date)
        }
        serving_written = publish_moneyflow_serving_for_keys(
            self.dao,
            self.session,
            touched_keys,
        )
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=serving_written,
            rows_upserted=serving_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    @staticmethod
    def _write_raw_only_upsert(
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
    ) -> WriteResult:
        if definition.storage.conflict_columns:
            rejected_reason_counts, rejected_reason_samples = DatasetWriter._duplicate_reason_diagnostics(
                rows=batch.rows_normalized,
                conflict_columns=definition.storage.conflict_columns,
                unit_id=batch.unit_id,
            )
            rows_written = raw_dao.bulk_upsert(
                batch.rows_normalized,
                conflict_columns=list(definition.storage.conflict_columns),
            )
        else:
            rejected_reason_counts, rejected_reason_samples = DatasetWriter._duplicate_reason_diagnostics(
                rows=batch.rows_normalized,
                conflict_columns=DatasetWriter._resolve_conflict_columns(raw_dao, None),
                unit_id=batch.unit_id,
            )
            rows_written = raw_dao.bulk_upsert(batch.rows_normalized)
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_written,
            rows_upserted=rows_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
            rejected_reason_samples=rejected_reason_samples,
        )

    @staticmethod
    def _write_snapshot_insert_by_trade_date(
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
    ) -> WriteResult:
        target_dates = sorted({row["trade_date"] for row in batch.rows_normalized if row.get("trade_date") is not None})
        for current_date in target_dates:
            raw_dao.delete_by_date_range(current_date, current_date)
            core_dao.delete_by_date_range(current_date, current_date)

        raw_dao.bulk_insert(batch.rows_normalized)
        written = core_dao.bulk_insert(batch.rows_normalized)
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=written,
            rows_upserted=written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="snapshot_insert_by_trade_date",
            rows_rejected=0,
            rejected_reason_counts={},
        )
