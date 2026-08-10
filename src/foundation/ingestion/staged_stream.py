from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.errors import IngestionWriteError, StructuredError


class StagedStreamPublisher(AbstractContextManager["StagedStreamPublisher"]):
    """Generic connection/transaction owner for opt-in staged-stream DAOs.

    Dataset-specific identity and reconciliation semantics remain behind the DAO
    named by ``DatasetStorageDefinition.stage_dao_name``.
    """

    def __init__(self, *, outer_session: Session, definition: DatasetDefinition) -> None:
        self.outer_session = outer_session
        self.definition = definition
        self.connection = None
        self.session: Session | None = None
        self.dao = None
        self.stage_run_ids: list[UUID] = []
        self.cleanup_errors: list[str] = []
        self._lock_acquired = False

    def __enter__(self) -> "StagedStreamPublisher":
        bind = self.outer_session.get_bind()
        engine = getattr(bind, "engine", bind)
        self.connection = engine.connect()
        self.session = Session(bind=self.connection, expire_on_commit=False)
        dao_name = str(self.definition.storage.stage_dao_name or "").strip()
        self.dao = getattr(DAOFactory(self.session), dao_name, None)
        if self.dao is None:
            self._close_resources()
            raise self._error("dao_not_found", f"staged DAO 不存在：{dao_name}")
        try:
            self.dao.acquire_execution_lock(dataset_key=self.definition.dataset_key)
            self._lock_acquired = True
            self.dao.clear_stage()
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            self._close_resources()
            raise self._map_error(exc) from exc
        return self

    def begin_unit(self) -> UUID:
        stage_run_id = uuid4()
        self.stage_run_ids.append(stage_run_id)
        return stage_run_id

    def stage_page(
        self,
        *,
        stage_run_id: UUID,
        period,
        repair_ts_code: str | None,
        rows: list[dict[str, Any]],
        page_number: int,
        offset: int | None,
    ) -> Any:
        assert self.session is not None and self.dao is not None
        try:
            result = self.dao.stage_page(
                stage_run_id=stage_run_id,
                period=period,
                repair_ts_code=repair_ts_code,
                rows=rows,
            )
            self.session.commit()
            return result
        except Exception as exc:
            self.session.rollback()
            raise self._map_error(exc, details={"page_number": page_number, "offset": offset}) from exc

    def finalize_unit(self, *, stage_run_id: UUID, period, repair_ts_code: str | None) -> Any:
        assert self.session is not None and self.dao is not None
        try:
            result = self.dao.finalize_scope(
                stage_run_id=stage_run_id,
                period=period,
                repair_ts_code=repair_ts_code,
            )
            self.session.commit()
            return result
        except Exception as exc:
            self.session.rollback()
            raise self._map_error(exc) from exc

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, traceback
        if self.session is not None and self.dao is not None:
            for stage_run_id in self.stage_run_ids:
                try:
                    self.dao.cleanup_stage_run(stage_run_id=stage_run_id)
                    self.session.commit()
                except Exception as cleanup_exc:
                    self.session.rollback()
                    self.cleanup_errors.append(str(cleanup_exc))
            if self._lock_acquired:
                try:
                    self.dao.release_execution_lock(dataset_key=self.definition.dataset_key)
                    self.session.commit()
                except Exception as unlock_exc:
                    self.session.rollback()
                    self.cleanup_errors.append(str(unlock_exc))
        self._close_resources()
        return False

    def _close_resources(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _map_error(self, exc: Exception, *, details: dict[str, Any] | None = None) -> IngestionWriteError:
        if isinstance(exc, IngestionWriteError):
            return exc
        mapped_details = dict(details or {})
        dao_error_code = getattr(exc, "code", None)
        if isinstance(dao_error_code, str) and dao_error_code:
            dao_details = getattr(exc, "details", None)
            if isinstance(dao_details, dict):
                mapped_details.update(dao_details)
            return self._error(f"write.{dao_error_code}", str(exc), details=mapped_details)
        return self._error("write.staged_scope_write_failed", str(exc), details=mapped_details)

    def _error(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> IngestionWriteError:
        return IngestionWriteError(
            StructuredError(
                error_code=code,
                error_type="write",
                phase="staged_publisher",
                message=message,
                retryable=False,
                details=dict(details or {}),
            )
        )
