from __future__ import annotations

import hashlib
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select

from src.foundation.dao.base_dao import BaseDAO
from src.utils import chunked


ModelT = TypeVar("ModelT")


class ImmutableFactDAO(BaseDAO[ModelT], Generic[ModelT]):
    """Minimal persistence contract for scope-reconciled immutable facts.

    This DAO never commits and deliberately exposes no update, delete, upsert,
    or conflict-ignore operation.
    """

    def acquire_scope_lock(self, *, scope_field: str, scope_value: Any) -> None:
        self._require_scope_column(scope_field)
        if self.session.get_bind().dialect.name != "postgresql":
            return
        lock_material = f"{self.model.__table__.fullname}\x1f{scope_field}\x1f{scope_value}"
        unsigned_key = int.from_bytes(hashlib.sha256(lock_material.encode("utf-8")).digest()[:8], "big")
        signed_key = unsigned_key if unsigned_key < 2**63 else unsigned_key - 2**64
        self.session.execute(select(func.pg_advisory_xact_lock(signed_key)))

    def fetch_scope_identity_hashes(self, *, scope_field: str, scope_value: Any) -> dict[str, str]:
        self._require_scope_column(scope_field)
        statement = select(self.model.source_entity_key, self.model.source_content_hash).where(
            getattr(self.model, scope_field) == scope_value
        )
        return {str(entity_key): str(content_hash) for entity_key, content_hash in self.session.execute(statement)}

    def insert_new_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        table_columns = {column.name for column in self.model.__table__.columns}
        filtered_rows = [{key: value for key, value in row.items() if key in table_columns} for row in rows]
        for row in filtered_rows:
            missing = [
                key
                for key in ("source_entity_key", "source_content_hash")
                if key not in row or row[key] in (None, "")
            ]
            if missing:
                raise ValueError(f"{self.model.__name__} 不可变事实身份为空：{', '.join(missing)}")
        written = 0
        for batch in chunked(filtered_rows, self._resolve_batch_size(filtered_rows)):
            result = self.session.execute(self.model.__table__.insert().values(batch))
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return written

    def _require_scope_column(self, scope_field: str) -> None:
        if not scope_field or scope_field not in self.model.__table__.columns:
            raise ValueError(f"{self.model.__name__} 缺少不可变事实范围列：{scope_field}")
