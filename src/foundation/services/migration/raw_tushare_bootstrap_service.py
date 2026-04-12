from __future__ import annotations

from dataclasses import dataclass

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
    ) -> RawTushareBootstrapResult:
        session.execute(text("CREATE SCHEMA IF NOT EXISTS raw_tushare"))
        legacy_tables = self.list_legacy_raw_tables(session)
        if table_names:
            requested = [name.strip() for name in table_names if name.strip()]
            unknown = sorted(set(requested) - set(legacy_tables))
            if unknown:
                raise ValueError(f"Unknown raw tables: {', '.join(unknown)}")
            target_tables = requested
        else:
            target_tables = legacy_tables

        results: list[RawTushareTableBootstrapResult] = []
        for table_name in target_tables:
            ident = self._quote_ident(table_name)
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
                session.execute(text(f"TRUNCATE TABLE raw_tushare.{ident} RESTART IDENTITY"))
                inserted_rows = int(
                    session.execute(
                        text(f"INSERT INTO raw_tushare.{ident} SELECT * FROM raw.{ident}")
                    ).rowcount
                    or 0
                )
            session.commit()
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
