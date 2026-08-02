from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.foundation.services.migration.news_cold_storage.models import (
    NewsColdStorageCopyResult,
    NewsColdStorageCutoverResult,
    NewsColdStoragePreparation,
    NewsColdStorageSummary,
    NewsColdStorageVerification,
)


_COLD_TABLESPACE = "gs_raw_cold_hdd"
_COLD_YEARS = range(2022, 2026)
_ALL_YEARS = range(2022, 2031)
_SOURCE_RELATION = "raw_tushare.news"
_STAGE_RELATION = "raw_tushare.news_partitioned_stage"
_RETIRED_RELATION = "raw_tushare.news_retired"
_NEWS_COLUMNS = (
    "src",
    "news_time",
    "title",
    "content",
    "channels",
    "score",
    "row_key_hash",
    "api_name",
    "fetched_at",
    "raw_payload",
)
_MUTABLE_COLUMNS = tuple(column for column in _NEWS_COLUMNS if column not in {"news_time", "row_key_hash"})


class NewsColdStorageMigrationService:
    """One-off, explicitly invoked migration for the partitioned news target."""

    def prepare(self, session: Session) -> NewsColdStoragePreparation:
        self._require_relation(session, _SOURCE_RELATION)
        self._require_relation(session, _STAGE_RELATION)
        self._reject_existing_retired_relation(session)
        self._validate_stage_columns(session)

        partitions = self._load_stage_partitions(session)
        expected_partitions = {f"news_p{year}" for year in _ALL_YEARS}
        actual_partitions = {name for name, _ in partitions}
        if actual_partitions != expected_partitions:
            raise RuntimeError(
                "新闻快讯 stage 分区不完整或包含额外分区："
                f"expected={sorted(expected_partitions)} actual={sorted(actual_partitions)}"
            )

        expected_tablespaces = {
            f"news_p{year}": _COLD_TABLESPACE if year in _COLD_YEARS else "pg_default" for year in _ALL_YEARS
        }
        actual_tablespaces = dict(partitions)
        incorrect_tablespaces = {
            name: {"expected": expected_tablespaces[name], "actual": actual_tablespaces[name]}
            for name in expected_tablespaces
            if actual_tablespaces[name] != expected_tablespaces[name]
        }
        if incorrect_tablespaces:
            raise RuntimeError(f"新闻快讯 stage tablespace 不符合冷热分层约束：{incorrect_tablespaces}")

        indexes = self._load_stage_indexes(session)
        self._validate_stage_indexes(indexes)
        return NewsColdStoragePreparation(partition_tablespaces=tuple(partitions), partition_indexes=tuple(indexes))

    def copy(self, session: Session, *, apply: bool) -> NewsColdStorageCopyResult:
        self.prepare(session)
        source = self._load_summary(session, _SOURCE_RELATION)
        stage_before_copy = self._load_summary(session, _STAGE_RELATION)
        if not apply:
            return NewsColdStorageCopyResult(
                applied=False,
                copy_started_at=None,
                rows_affected=None,
                source=source,
                stage_before_copy=stage_before_copy,
            )

        try:
            copy_started_at = session.execute(text("SELECT clock_timestamp()")).scalar_one()
            result = session.execute(text(self._copy_statement()))
            session.commit()
        except Exception:
            session.rollback()
            raise
        return NewsColdStorageCopyResult(
            applied=True,
            copy_started_at=copy_started_at,
            rows_affected=self._affected_rows(result),
            source=source,
            stage_before_copy=stage_before_copy,
        )

    def verify(self, session: Session) -> NewsColdStorageVerification:
        self.prepare(session)
        return self._verify_data(session)

    def cutover(
        self,
        session: Session,
        *,
        apply: bool,
        copy_started_at: datetime | None,
        drop_retired_table: bool,
    ) -> NewsColdStorageCutoverResult | NewsColdStorageVerification:
        self.prepare(session)
        if not apply:
            return self._verify_data(session)
        if copy_started_at is None:
            raise ValueError("cutover 必须提供 --copy-started-at。")
        if copy_started_at.tzinfo is None:
            raise ValueError("--copy-started-at 必须包含时区偏移，例如 2026-08-02T19:00:00+08:00。")
        if not drop_retired_table:
            raise ValueError("cutover 必须显式提供 --drop-retired-table，禁止遗留旧表。")

        # Previous read-only preflight opens an implicit transaction. The cutover needs one fresh transaction.
        session.rollback()
        try:
            with session.begin():
                session.execute(text("SET LOCAL lock_timeout = '15s'"))
                session.execute(text(f"LOCK TABLE {_SOURCE_RELATION} IN ACCESS EXCLUSIVE MODE"))
                self._reject_existing_retired_relation(session)
                tail_result = session.execute(
                    text(self._copy_statement("WHERE fetched_at >= :copy_started_at")),
                    {"copy_started_at": copy_started_at},
                )
                verification = self._verify_data(session)
                if not verification.is_consistent:
                    raise RuntimeError(
                        "新闻快讯 stage 与旧表校验不一致，已回滚切换："
                        f"source_rows={verification.source.row_count} "
                        f"stage_rows={verification.stage.row_count} "
                        f"source_missing_from_stage={verification.source_missing_from_stage} "
                        f"stage_missing_from_source={verification.stage_missing_from_source}"
                    )
                session.execute(text("ALTER TABLE raw_tushare.news RENAME TO news_retired"))
                session.execute(text("ALTER TABLE raw_tushare.news_partitioned_stage RENAME TO news"))
                session.execute(text(self._news_view_statement()))
                session.execute(text("DROP TABLE raw_tushare.news_retired"))
        except Exception:
            session.rollback()
            raise

        return NewsColdStorageCutoverResult(
            copy_started_at=copy_started_at,
            tail_rows_affected=self._affected_rows(tail_result),
            verification=verification,
        )

    def _verify_data(self, session: Session) -> NewsColdStorageVerification:
        source = self._load_summary(session, _SOURCE_RELATION)
        stage = self._load_summary(session, _STAGE_RELATION)
        return NewsColdStorageVerification(
            source=source,
            stage=stage,
            source_missing_from_stage=self._count_missing_keys(
                session,
                source_relation=_SOURCE_RELATION,
                target_relation=_STAGE_RELATION,
            ),
            stage_missing_from_source=self._count_missing_keys(
                session,
                source_relation=_STAGE_RELATION,
                target_relation=_SOURCE_RELATION,
            ),
        )

    @staticmethod
    def _affected_rows(result: Any) -> int:
        return result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0

    @staticmethod
    def _require_relation(session: Session, relation_name: str) -> None:
        exists = session.execute(
            text("SELECT to_regclass(:relation_name) IS NOT NULL"),
            {"relation_name": relation_name},
        ).scalar_one()
        if not exists:
            raise RuntimeError(f"缺少必需 relation：{relation_name}")

    @staticmethod
    def _reject_existing_retired_relation(session: Session) -> None:
        exists = session.execute(
            text("SELECT to_regclass(:relation_name) IS NOT NULL"),
            {"relation_name": _RETIRED_RELATION},
        ).scalar_one()
        if exists:
            raise RuntimeError(f"检测到遗留 relation：{_RETIRED_RELATION}；禁止继续切换。")

    @staticmethod
    def _validate_stage_columns(session: Session) -> None:
        columns = session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'raw_tushare'
                  AND table_name = 'news_partitioned_stage'
                ORDER BY ordinal_position
                """
            )
        ).scalars().all()
        if tuple(columns) != _NEWS_COLUMNS:
            raise RuntimeError(f"新闻快讯 stage 列定义不符合最终模型：{columns}")

        primary_key = session.execute(
            text(
                """
                SELECT attribute.attname
                FROM pg_constraint constraint
                JOIN pg_class relation ON relation.oid = constraint.conrelid
                JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
                JOIN unnest(constraint.conkey) WITH ORDINALITY AS key_column(attnum, ordinal_position) ON TRUE
                JOIN pg_attribute attribute
                  ON attribute.attrelid = relation.oid AND attribute.attnum = key_column.attnum
                WHERE namespace.nspname = 'raw_tushare'
                  AND relation.relname = 'news_partitioned_stage'
                  AND constraint.contype = 'p'
                ORDER BY key_column.ordinal_position
                """
            )
        ).scalars().all()
        if tuple(primary_key) != ("news_time", "row_key_hash"):
            raise RuntimeError(f"新闻快讯 stage 主键不符合最终模型：{primary_key}")

    @staticmethod
    def _load_stage_partitions(session: Session) -> list[tuple[str, str]]:
        rows = session.execute(
            text(
                """
                SELECT child.relname AS partition_name,
                       COALESCE(tablespace.spcname, 'pg_default') AS tablespace_name
                FROM pg_inherits inheritance
                JOIN pg_class parent ON parent.oid = inheritance.inhparent
                JOIN pg_namespace parent_namespace ON parent_namespace.oid = parent.relnamespace
                JOIN pg_class child ON child.oid = inheritance.inhrelid
                LEFT JOIN pg_tablespace tablespace ON tablespace.oid = child.reltablespace
                WHERE parent_namespace.nspname = 'raw_tushare'
                  AND parent.relname = 'news_partitioned_stage'
                ORDER BY child.relname
                """
            )
        ).all()
        return [(str(row.partition_name), str(row.tablespace_name)) for row in rows]

    @staticmethod
    def _load_stage_indexes(session: Session) -> list[tuple[str, str, str]]:
        rows = session.execute(
            text(
                """
                SELECT partition.relname AS partition_name,
                       index_relation.relname AS index_name,
                       COALESCE(tablespace.spcname, 'pg_default') AS tablespace_name
                FROM pg_inherits inheritance
                JOIN pg_class parent ON parent.oid = inheritance.inhparent
                JOIN pg_namespace parent_namespace ON parent_namespace.oid = parent.relnamespace
                JOIN pg_class partition ON partition.oid = inheritance.inhrelid
                JOIN pg_index index_definition ON index_definition.indrelid = partition.oid
                JOIN pg_class index_relation ON index_relation.oid = index_definition.indexrelid
                LEFT JOIN pg_tablespace tablespace ON tablespace.oid = index_relation.reltablespace
                WHERE parent_namespace.nspname = 'raw_tushare'
                  AND parent.relname = 'news_partitioned_stage'
                ORDER BY partition.relname, index_relation.relname
                """
            )
        ).all()
        return [(str(row.partition_name), str(row.index_name), str(row.tablespace_name)) for row in rows]

    @staticmethod
    def _validate_stage_indexes(indexes: list[tuple[str, str, str]]) -> None:
        expected_indexes = {
            (f"news_p{year}", f"news_p{year}_pkey") for year in _ALL_YEARS
        } | {
            (f"news_p{year}", f"idx_raw_tushare_news_p{year}_time") for year in _ALL_YEARS
        } | {
            (f"news_p{year}", f"idx_raw_tushare_news_p{year}_src_time") for year in _ALL_YEARS
        }
        actual_indexes = {(partition_name, index_name) for partition_name, index_name, _ in indexes}
        if actual_indexes != expected_indexes:
            raise RuntimeError(
                "新闻快讯 stage 索引不完整或包含额外索引："
                f"expected={sorted(expected_indexes)} actual={sorted(actual_indexes)}"
            )

        incorrect_tablespaces = {
            f"{partition_name}.{index_name}": tablespace_name
            for partition_name, index_name, tablespace_name in indexes
            if tablespace_name != (_COLD_TABLESPACE if int(partition_name[-4:]) in _COLD_YEARS else "pg_default")
        }
        if incorrect_tablespaces:
            raise RuntimeError(f"新闻快讯 stage 索引 tablespace 不符合冷热分层约束：{incorrect_tablespaces}")

    @staticmethod
    def _load_summary(session: Session, relation_name: str) -> NewsColdStorageSummary:
        summary_row = session.execute(
            text(
                f"""
                SELECT COUNT(*) AS row_count,
                       MIN(news_time) AS earliest_news_time,
                       MAX(news_time) AS latest_news_time
                FROM {relation_name}
                """
            )
        ).mappings().one()
        year_rows = session.execute(
            text(
                f"""
                SELECT EXTRACT(YEAR FROM news_time AT TIME ZONE 'UTC')::integer AS year,
                       COUNT(*) AS row_count
                FROM {relation_name}
                GROUP BY 1
                ORDER BY 1
                """
            )
        ).mappings().all()
        return NewsColdStorageSummary(
            row_count=int(summary_row["row_count"]),
            earliest_news_time=summary_row["earliest_news_time"],
            latest_news_time=summary_row["latest_news_time"],
            rows_by_year=tuple((int(row["year"]), int(row["row_count"])) for row in year_rows),
        )

    @staticmethod
    def _count_missing_keys(session: Session, *, source_relation: str, target_relation: str) -> int:
        return int(
            session.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM {source_relation} source
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM {target_relation} target
                        WHERE target.news_time = source.news_time
                          AND target.row_key_hash = source.row_key_hash
                    )
                    """
                )
            ).scalar_one()
        )

    @staticmethod
    def _copy_statement(where_clause: str = "") -> str:
        columns = ", ".join(_NEWS_COLUMNS)
        update_columns = ", ".join(f"{column} = EXCLUDED.{column}" for column in _MUTABLE_COLUMNS)
        return f"""
            INSERT INTO {_STAGE_RELATION} ({columns})
            SELECT {columns}
            FROM {_SOURCE_RELATION}
            {where_clause}
            ON CONFLICT (news_time, row_key_hash) DO UPDATE SET
                {update_columns}
        """

    @staticmethod
    def _news_view_statement() -> str:
        return """
            CREATE OR REPLACE VIEW core_serving_light.news AS
            SELECT
                row_key_hash,
                src,
                news_time,
                title,
                content,
                channels,
                score,
                'tushare'::varchar(32) AS source,
                fetched_at
            FROM raw_tushare.news
        """
