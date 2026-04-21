from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, NormalizedBatch, WriteResult
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2WriteError
from src.foundation.services.sync.sync_moneyflow_service import publish_moneyflow_serving_for_keys
from src.foundation.services.transform.normalize_moneyflow_service import NormalizeMoneyflowService


class SyncV2Writer:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self._moneyflow_normalizer = NormalizeMoneyflowService()

    def write(self, *, contract: DatasetSyncContract, batch: NormalizedBatch) -> WriteResult:
        raw_dao = getattr(self.dao, contract.write_spec.raw_dao_name, None)
        core_dao = getattr(self.dao, contract.write_spec.core_dao_name, None)
        if raw_dao is None or core_dao is None:
            raise SyncV2WriteError(
                StructuredError(
                    error_code="dao_not_found",
                    error_type="write",
                    phase="writer",
                    message=(
                        f"DAO not found: raw={contract.write_spec.raw_dao_name} "
                        f"core={contract.write_spec.core_dao_name}"
                    ),
                    retryable=False,
                    unit_id=batch.unit_id,
                )
            )

        if not batch.rows_normalized:
            return WriteResult(
                unit_id=batch.unit_id,
                rows_written=0,
                rows_upserted=0,
                rows_skipped=batch.rows_rejected,
                target_table=contract.write_spec.target_table,
                conflict_strategy="upsert",
            )

        try:
            if contract.write_spec.write_path == "raw_std_publish_moneyflow":
                return self._write_moneyflow_std_publish(
                    contract=contract,
                    batch=batch,
                    raw_dao=raw_dao,
                    std_dao=core_dao,
                )
            if contract.write_spec.write_path != "raw_core_upsert":
                raise ValueError(f"unsupported write_path: {contract.write_spec.write_path}")
            rows_upserted = self._write_raw_and_core(
                batch=batch,
                raw_dao=raw_dao,
                core_dao=core_dao,
                conflict_columns=contract.write_spec.conflict_columns,
            )
        except Exception as exc:
            raise SyncV2WriteError(
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
            target_table=contract.write_spec.target_table,
            conflict_strategy="upsert",
        )

    @staticmethod
    def _write_raw_and_core(
        *,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
        conflict_columns: tuple[str, ...] | None,
    ) -> int:
        if conflict_columns:
            raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(conflict_columns))
            return core_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(conflict_columns))
        raw_dao.bulk_upsert(batch.rows_normalized)
        return core_dao.bulk_upsert(batch.rows_normalized)

    def _write_moneyflow_std_publish(
        self,
        *,
        contract: DatasetSyncContract,
        batch: NormalizedBatch,
        raw_dao,
        std_dao,
    ) -> WriteResult:
        if contract.write_spec.conflict_columns:
            raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(contract.write_spec.conflict_columns))
        else:
            raw_dao.bulk_upsert(batch.rows_normalized)
        std_rows = [self._moneyflow_normalizer.to_std_from_tushare(row) for row in batch.rows_normalized]
        if contract.write_spec.conflict_columns:
            std_dao.bulk_upsert(std_rows, conflict_columns=list(contract.write_spec.conflict_columns))
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
            target_table=contract.write_spec.target_table,
            conflict_strategy="upsert",
        )
