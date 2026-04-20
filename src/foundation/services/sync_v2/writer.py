from __future__ import annotations

from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, NormalizedBatch, WriteResult
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2WriteError


class SyncV2Writer:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)

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
            if contract.write_spec.conflict_columns:
                raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(contract.write_spec.conflict_columns))
                rows_upserted = core_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(contract.write_spec.conflict_columns))
            else:
                raw_dao.bulk_upsert(batch.rows_normalized)
                rows_upserted = core_dao.bulk_upsert(batch.rows_normalized)
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
