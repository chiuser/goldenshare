from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RawTushareTableBootstrapResult:
    table_name: str
    created: bool
    migrated: bool
    inserted_rows: int


@dataclass(frozen=True)
class RawTushareBootstrapResult:
    tables: list[RawTushareTableBootstrapResult]

    @property
    def created_count(self) -> int:
        return sum(1 for item in self.tables if item.created)

    @property
    def migrated_count(self) -> int:
        return sum(1 for item in self.tables if item.migrated)

    @property
    def inserted_rows_total(self) -> int:
        return sum(item.inserted_rows for item in self.tables)


class RawTushareBootstrapService:
    def list_legacy_raw_tables(self, session: Session) -> list[str]:
        rows = session.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'raw'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).scalars()
        return [str(item) for item in rows]

    def run(
        self,
        session: Session,
        *,
        table_names: list[str] | None = None,
        migrate_data: bool,
        drop_if_exists: bool = False,
        progress_callback: Callable[[str], None] | None = None,
    ) -> RawTushareBootstrapResult:
        emit = progress_callback or (lambda _: None)
        session.execute(text("CREATE SCHEMA IF NOT EXISTS raw_tushare"))
        legacy_tables = self.list_legacy_raw_tables(session)
        if table_names:
            requested = [name.strip() for name in table_names if name.strip()]
            unknown = sorted(set(requested) - set(legacy_tables))
            if unknown:
                raise ValueError(f"未知 raw 表：{', '.join(unknown)}")
            target_tables = requested
        else:
            target_tables = legacy_tables

        emit(f"raw_tushare 初始化开始：表数量={len(target_tables)} 迁移数据={migrate_data} 覆盖已有表={drop_if_exists}")
        results: list[RawTushareTableBootstrapResult] = []
        for index, table_name in enumerate(target_tables, start=1):
            ident = self._quote_ident(table_name)
            emit(f"[{index}/{len(target_tables)}] {table_name}：创建目标表")
            if drop_if_exists:
                session.execute(text(f"DROP TABLE IF EXISTS raw_tushare.{ident}"))
            session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS raw_tushare.{ident} "
                    f"(LIKE raw.{ident} INCLUDING ALL)"
                )
            )

            inserted_rows = 0
            if migrate_data:
                emit(f"[{index}/{len(target_tables)}] {table_name}：校验表结构一致性")
                source_columns = self._list_columns(session, schema="raw", table_name=table_name)
                target_columns = self._list_columns(session, schema="raw_tushare", table_name=table_name)
                self._ensure_same_columns(table_name, source_columns=source_columns, target_columns=target_columns)
                emit(f"[{index}/{len(target_tables)}] {table_name}：清空目标表")
                session.execute(text(f"TRUNCATE TABLE raw_tushare.{ident} RESTART IDENTITY"))
                emit(f"[{index}/{len(target_tables)}] {table_name}：复制数据")
                inserted_rows = int(
                    session.execute(
                        text(f"INSERT INTO raw_tushare.{ident} SELECT * FROM raw.{ident}")
                    ).rowcount
                    or 0
                )
            session.commit()
            emit(f"[{index}/{len(target_tables)}] {table_name}：完成，写入行数={inserted_rows}")
            results.append(
                RawTushareTableBootstrapResult(
                    table_name=table_name,
                    created=True,
                    migrated=migrate_data,
                    inserted_rows=inserted_rows,
                )
            )
        return RawTushareBootstrapResult(tables=results)

    @staticmethod
    def _quote_ident(identifier: str) -> str:
        return f"\"{identifier.replace('\"', '\"\"')}\""

    def _list_columns(self, session: Session, *, schema: str, table_name: str) -> list[str]:
        rows = session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema
                  AND table_name = :table_name
                ORDER BY ordinal_position
                """
            ),
            {"schema": schema, "table_name": table_name},
        ).scalars()
        return [str(item) for item in rows]

    @staticmethod
    def _ensure_same_columns(table_name: str, *, source_columns: list[str], target_columns: list[str]) -> None:
        if source_columns == target_columns:
            return
        source_extra_columns = [column for column in source_columns if column not in set(target_columns)]
        target_extra_columns = [column for column in target_columns if column not in set(source_columns)]
        raise ValueError(
            f"raw 与 raw_tushare 表结构不一致：{table_name}，仅源表存在={source_extra_columns}，仅目标表存在={target_extra_columns}"
        )
