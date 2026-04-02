from __future__ import annotations

from datetime import date
from typing import Any, Generic, TypeVar

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.utils import chunked


ModelT = TypeVar("ModelT")


class BaseDAO(Generic[ModelT]):
    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model
        self.settings = get_settings()

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
                raise ValueError(
                    f"{self.model.__name__}.bulk_upsert missing conflict key fields: {missing_text}; row={row}"
                )
            key = tuple(row[column] for column in conflict_target)
            deduped_by_key[key] = row
        deduped_rows = list(deduped_by_key.values())
        mutable_columns = [
            column.name
            for column in self.model.__table__.columns
            if column.name not in conflict_target and column.name != "created_at"
        ]
        written = 0
        for batch in chunked(deduped_rows, self.settings.sync_batch_size):
            statement = insert(self.model).values(batch)
            update_mapping = {column: getattr(statement.excluded, column) for column in mutable_columns}
            if "updated_at" in self.model.__table__.columns:
                update_mapping["updated_at"] = func.now()
            statement = statement.on_conflict_do_update(index_elements=conflict_target, set_=update_mapping)
            result = self.session.execute(statement)
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return written

    def bulk_insert(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        table_columns = {column.name for column in self.model.__table__.columns}
        filtered_rows = [{key: value for key, value in row.items() if key in table_columns} for row in rows]
        written = 0
        for batch in chunked(filtered_rows, self.settings.sync_batch_size):
            statement = insert(self.model).values(batch)
            result = self.session.execute(statement)
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return written

    def fetch_by_pk(self, *pk_values: Any) -> ModelT | None:
        return self.session.get(self.model, pk_values if len(pk_values) > 1 else pk_values[0])

    def fetch_by_date_range(self, start_date: date, end_date: date) -> list[ModelT]:
        date_column = self._date_column()
        stmt = select(self.model).where(and_(date_column >= start_date, date_column <= end_date))
        return list(self.session.scalars(stmt))

    def delete_by_date_range(self, start_date: date, end_date: date) -> int:
        date_column = self._date_column()
        stmt = self.model.__table__.delete().where(and_(date_column >= start_date, date_column <= end_date))
        result = self.session.execute(stmt)
        return result.rowcount or 0

    def _date_column(self):  # type: ignore[no-untyped-def]
        for name in ("trade_date", "ann_date", "cal_date", "ex_date"):
            if hasattr(self.model, name):
                return getattr(self.model, name)
        raise AttributeError(f"No date column found for {self.model.__name__}")
