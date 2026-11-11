from __future__ import annotations

from datetime import date
from typing import Any, Generic, TypeVar

from sqlalchemy import and_, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.utils import chunked


ModelT = TypeVar("ModelT")


class BaseDAO(Generic[ModelT]):
    PG_MAX_BIND_PARAMS = 65_535
    PG_BIND_PARAM_RESERVE = 32

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
                    f"{self.model.__name__} 缺少写入主键字段：{missing_text}；row={row}"
                )
            key = tuple(row[column] for column in conflict_target)
            deduped_by_key[key] = row
        deduped_rows = list(deduped_by_key.values())
        mutable_columns = [
            column.name
            for column in self.model.__table__.columns
            if column.name not in conflict_target and column.name != "created_at"
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

    def bulk_update_columns(self, rows: list[dict[str, Any]], update_columns: tuple[str, ...]) -> int:
        """Update only named columns on existing keys; the caller owns the transaction."""
        if not rows:
            return 0
        table = self.model.__table__
        primary_keys = tuple(column.name for column in table.primary_key.columns)
        if not update_columns or any(name not in table.c or name in primary_keys for name in update_columns):
            raise ValueError("更新列必须是模型中真实的非主键列")
        columns = tuple(table.c[name] for name in (*primary_keys, *update_columns))
        dialect = self.session.get_bind().dialect
        quote = dialect.identifier_preparer.quote
        table_name = dialect.identifier_preparer.format_table(table)
        column_names = ", ".join(quote(column.name) for column in columns)
        assignments = ", ".join(f"{quote(name)} = incoming.{quote(name)}" for name in update_columns)
        key_match = " AND ".join(f"target.{quote(name)} = incoming.{quote(name)}" for name in primary_keys)
        changed = " OR ".join(
            f"target.{quote(name)} IS DISTINCT FROM incoming.{quote(name)}" for name in update_columns
        )
        batch_size = self._compute_batch_size(
            configured_batch_size=self.settings.sync_batch_size,
            row_param_count=len(columns),
        )
        written = 0
        for batch in chunked(rows, batch_size):
            values = []
            parameters = {}
            for row_index, row in enumerate(batch):
                bindings = []
                for column_index, column in enumerate(columns):
                    key = f"v_{row_index}_{column_index}"
                    parameters[key] = row[column.name]
                    bindings.append(f"CAST(:{key} AS {column.type.compile(dialect=dialect)})")
                values.append(f"({', '.join(bindings)})")
            statement = text(
                f"UPDATE {table_name} AS target SET {assignments} "
                f"FROM (VALUES {', '.join(values)}) AS incoming ({column_names}) "
                f"WHERE {key_match} AND ({changed})"
            )
            result = self.session.execute(statement, parameters)
            written += result.rowcount
        return written

    def bulk_insert(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        table_columns = {column.name for column in self.model.__table__.columns}
        filtered_rows = [{key: value for key, value in row.items() if key in table_columns} for row in rows]
        batch_size = self._resolve_batch_size(filtered_rows)
        written = 0
        for batch in chunked(filtered_rows, batch_size):
            statement = insert(self.model).values(batch)
            result = self.session.execute(statement)
            written += result.rowcount if result.rowcount and result.rowcount > 0 else len(batch)
        return written

    def bulk_insert_ignore_conflicts(self, rows: list[dict[str, Any]]) -> int:
        """Insert rows and leave conflicting records unchanged."""
        if not rows:
            return 0
        table_columns = {column.name for column in self.model.__table__.columns}
        filtered_rows = [{key: value for key, value in row.items() if key in table_columns} for row in rows]
        batch_size = self._resolve_batch_size(filtered_rows)
        written = 0
        for batch in chunked(filtered_rows, batch_size):
            statement = insert(self.model).values(batch).on_conflict_do_nothing()
            result = self.session.execute(statement)
            written += max(int(result.rowcount or 0), 0)
        return written

    def _resolve_batch_size(self, rows: list[dict[str, Any]]) -> int:
        configured_batch_size = max(int(self.settings.sync_batch_size), 1)
        if not rows:
            return configured_batch_size
        max_row_param_count = max(len(row) for row in rows)
        return self._compute_batch_size(
            configured_batch_size=configured_batch_size,
            row_param_count=max_row_param_count,
        )

    @classmethod
    def _compute_batch_size(cls, *, configured_batch_size: int, row_param_count: int) -> int:
        configured = max(configured_batch_size, 1)
        per_row_params = max(row_param_count, 1)
        allowed_by_params = (cls.PG_MAX_BIND_PARAMS - cls.PG_BIND_PARAM_RESERVE) // per_row_params
        return max(min(configured, allowed_by_params), 1)

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
