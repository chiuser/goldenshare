from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.foundation.dao.base_dao import BaseDAO
from src.utils import chunked


ModelT = TypeVar("ModelT")


@dataclass(frozen=True, slots=True)
class ObservationWriteResult:
    rows_observed: int
    versions_created: int


class ObservedSnapshotDAO(BaseDAO[ModelT], Generic[ModelT]):
    """Persistence operations for one table in the observed-snapshot protocol.

    A current-table DAO calls ``replace_current_snapshot``; an observation-table
    DAO calls ``record_observations``.  Both operations stay inside the caller's
    session and never commit or coordinate across models.
    """

    KEY_COLUMNS = ("source_entity_key", "source_content_hash")

    def record_observations(
        self,
        rows: list[dict[str, Any]],
        *,
        observed_at: datetime,
    ) -> ObservationWriteResult:
        if not rows:
            return ObservationWriteResult(rows_observed=0, versions_created=0)
        self._require_columns("first_observed_at", "last_observed_at")
        prepared = [
            {
                **row,
                "first_observed_at": observed_at,
                "last_observed_at": observed_at,
            }
            for row in rows
        ]
        filtered = self._filter_rows(prepared)
        keys = [(row["source_entity_key"], row["source_content_hash"]) for row in filtered]
        existing = self._existing_keys(keys)

        written = 0
        for batch in chunked(filtered, self._resolve_batch_size(filtered)):
            statement = self._insert_statement().values(batch)
            update_mapping = {"last_observed_at": statement.excluded.last_observed_at}
            if "updated_at" in self._table_columns:
                update_mapping["updated_at"] = func.now()
            statement = statement.on_conflict_do_update(
                index_elements=list(self.KEY_COLUMNS),
                set_=update_mapping,
            )
            result = self.session.execute(statement)
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return ObservationWriteResult(
            rows_observed=written,
            versions_created=sum(1 for key in keys if key not in existing),
        )

    def replace_current_snapshot(self, rows: list[dict[str, Any]], *, observed_at: datetime) -> int:
        self._require_columns("observed_at")
        prepared = [{**row, "observed_at": observed_at} for row in rows]
        filtered = self._filter_rows(prepared)
        self.session.execute(self.model.__table__.delete())
        written = 0
        for batch in chunked(filtered, self._resolve_batch_size(filtered)):
            result = self.session.execute(self._insert_statement().values(batch))
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return written

    def acquire_scope_lock(self, *, scope_field: str, scope_value: Any) -> None:
        """Serialize writers for one logical current-projection scope."""
        self._require_scope_column(scope_field)
        if self.session.get_bind().dialect.name != "postgresql":
            return
        lock_material = f"{self.model.__table__.fullname}\x1f{scope_field}\x1f{scope_value}"
        unsigned_key = int.from_bytes(hashlib.sha256(lock_material.encode("utf-8")).digest()[:8], "big")
        signed_key = unsigned_key if unsigned_key < 2**63 else unsigned_key - 2**64
        self.session.execute(select(func.pg_advisory_xact_lock(signed_key)))

    def replace_current_scope(
        self,
        rows: list[dict[str, Any]],
        *,
        observed_at: datetime,
        scope_field: str,
        scope_value: Any,
        scope_lock_acquired: bool = False,
    ) -> int:
        self._require_columns("observed_at")
        self._require_scope_column(scope_field)
        if not scope_lock_acquired:
            self.acquire_scope_lock(scope_field=scope_field, scope_value=scope_value)
        prepared = [{**row, "observed_at": observed_at} for row in rows]
        filtered = self._filter_rows(prepared)
        mismatched = [row.get(scope_field) for row in filtered if row.get(scope_field) != scope_value]
        if mismatched:
            raise ValueError(f"{self.model.__name__} 范围替换包含 scope 外记录：{scope_field}={mismatched[0]}")
        scope_column = getattr(self.model, scope_field)
        self.session.execute(self.model.__table__.delete().where(scope_column == scope_value))
        written = 0
        for batch in chunked(filtered, self._resolve_batch_size(filtered)):
            result = self.session.execute(self._insert_statement().values(batch))
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return written

    @property
    def _table_columns(self) -> set[str]:
        return {column.name for column in self.model.__table__.columns}

    def _require_columns(self, *required: str) -> None:
        columns = self._table_columns
        missing = [column for column in (*self.KEY_COLUMNS, *required) if column not in columns]
        if missing:
            raise ValueError(f"{self.model.__name__} 不满足观察快照协议，缺少列：{', '.join(missing)}")

    def _require_scope_column(self, scope_field: str) -> None:
        if not scope_field or scope_field not in self._table_columns:
            raise ValueError(f"{self.model.__name__} 缺少范围替换列：{scope_field}")

    def _filter_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        columns = self._table_columns
        filtered = [{key: value for key, value in row.items() if key in columns} for row in rows]
        for row in filtered:
            missing = [key for key in self.KEY_COLUMNS if key not in row or row[key] in (None, "")]
            if missing:
                raise ValueError(f"{self.model.__name__} 观察快照主键为空：{', '.join(missing)}")
        return filtered

    def _existing_keys(self, keys: list[tuple[Any, Any]]) -> set[tuple[Any, Any]]:
        if not keys:
            return set()
        entity_column = getattr(self.model, "source_entity_key")
        content_column = getattr(self.model, "source_content_hash")
        existing: set[tuple[Any, Any]] = set()
        for batch in chunked(keys, 1_000):
            statement = select(entity_column, content_column).where(tuple_(entity_column, content_column).in_(batch))
            existing.update((row[0], row[1]) for row in self.session.execute(statement))
        return existing

    def _insert_statement(self):  # type: ignore[no-untyped-def]
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            return postgresql_insert(self.model)
        if dialect_name == "sqlite":
            return sqlite_insert(self.model)
        raise ValueError(f"观察快照 DAO 不支持数据库方言：{dialect_name}")
