from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.raw.raw_cctv_news import RawCctvNews
from src.utils import chunked


class RawCctvNewsDAO(BaseDAO[RawCctvNews]):
    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session, RawCctvNews)

    def bulk_upsert(self, rows: list[dict[str, Any]], conflict_columns: list[str] | None = None) -> int:
        if not rows:
            return 0
        table_columns = {column.name for column in self.model.__table__.columns}
        filtered_rows = [{key: value for key, value in row.items() if key in table_columns} for row in rows]
        pk_columns = [column.name for column in self.model.__table__.primary_key.columns]
        conflict_target = conflict_columns or pk_columns
        deduped_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in filtered_rows:
            missing_columns = [column for column in conflict_target if column not in row or row[column] is None]
            if missing_columns:
                missing_text = ", ".join(missing_columns)
                raise ValueError(f"{self.model.__name__} 缺少写入主键字段：{missing_text}；row={row}")
            key = tuple(row[column] for column in conflict_target)
            deduped_by_key[key] = row
        deduped_rows = list(deduped_by_key.values())
        mutable_columns = [
            column.name
            for column in self.model.__table__.columns
            if column.name not in conflict_target and column.name not in pk_columns and column.name != "created_at"
        ]
        batch_size = self._resolve_batch_size(deduped_rows)
        written = 0
        for batch in chunked(deduped_rows, batch_size):
            statement = insert(self.model).values(batch)
            update_mapping = {column: getattr(statement.excluded, column) for column in mutable_columns}
            if "updated_at" in self.model.__table__.columns:
                update_mapping["updated_at"] = func.now()
            statement = statement.on_conflict_do_update(index_elements=conflict_target, set_=update_mapping)
            result = self.session.execute(statement)
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return written
