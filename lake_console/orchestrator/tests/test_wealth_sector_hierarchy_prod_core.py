from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.assets.wealth_sector_hierarchy_prod_core import (
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_PATH_TEMPLATE,
    load_silver_wealth_sector_hierarchy_for_prod_sync,
    prod_core_wealth_sector_hierarchy,
)
from orchestrator.defs.prod_db.wealth_sector_hierarchy import (
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS,
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL,
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_INSERT_SQL,
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL,
    audit_wealth_sector_hierarchy_rows,
    replace_prod_core_wealth_sector_hierarchy,
    validate_prod_core_wealth_sector_hierarchy_sql_contract,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.seeds.board.eastmoney_dc_industry_hierarchy import (
    EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS,
    load_eastmoney_dc_industry_hierarchy_seed,
)


class WealthSectorHierarchyProdCoreTests(unittest.TestCase):
    def test_asset_definition_is_the_single_manual_hierarchy_publisher(self) -> None:
        asset_key = prod_core_wealth_sector_hierarchy.key
        self.assertEqual(
            asset_key.to_user_string(),
            "prod_core_wealth_sector_hierarchy",
        )
        self.assertIsNone(prod_core_wealth_sector_hierarchy.partitions_def)
        self.assertEqual(
            prod_core_wealth_sector_hierarchy.dependency_keys,
            {dg.AssetKey("silver_dc_industry_hierarchy")},
        )
        spec = prod_core_wealth_sector_hierarchy.get_asset_spec(asset_key)
        self.assertEqual(spec.group_name, "wealth")
        self.assertEqual(
            spec.metadata["goldenshare/path_template"],
            PROD_CORE_WEALTH_SECTOR_HIERARCHY_PATH_TEMPLATE,
        )
        self.assertEqual(
            spec.metadata["goldenshare/source_asset"],
            "silver_dc_industry_hierarchy",
        )
        self.assertEqual(
            spec.metadata["goldenshare/target_table"],
            "core_serving.wealth_sector_hierarchy",
        )

    def test_loader_accepts_exact_496_row_silver_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / "part-000.parquet"
            _write_silver_hierarchy_file(source_path, _silver_hierarchy_rows())

            snapshot = load_silver_wealth_sector_hierarchy_for_prod_sync(
                duckdb_resource=DuckDBResource(),
                source_path=source_path,
            )

        self.assertEqual(snapshot.content.row_count, 496)
        self.assertEqual(
            dict(snapshot.content.level_counts),
            EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS,
        )
        self.assertEqual(len(snapshot.content.content_hash), 64)
        self.assertEqual(
            snapshot.content.baseline_version,
            "eastmoney_dc_industry_hierarchy.cn_a.v1",
        )

    def test_loader_rejects_duplicate_code_before_prod_connection(self) -> None:
        rows = _silver_hierarchy_rows()
        rows[-1] = {**rows[-1], "ts_code": rows[0]["ts_code"]}
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / "part-000.parquet"
            _write_silver_hierarchy_file(source_path, rows)

            with self.assertRaisesRegex(ValueError, "duplicate sector_code"):
                load_silver_wealth_sector_hierarchy_for_prod_sync(
                    duckdb_resource=DuckDBResource(),
                    source_path=source_path,
                )

    def test_replace_full_snapshot_deletes_inserts_and_reads_back(self) -> None:
        content_rows = _target_content_rows()
        published_at = datetime(2026, 8, 13, 9, 30, tzinfo=timezone.utc)
        read_back_rows = _read_back_rows(content_rows, published_at=published_at)
        cursor = _FakeCursor(read_back_rows=read_back_rows)
        connection = _FakeConnection(cursor)

        audit = replace_prod_core_wealth_sector_hierarchy(
            connection=connection,
            rows=content_rows,
            published_at=published_at,
        )

        self.assertEqual(audit.row_count, 496)
        self.assertEqual(audit.read_back_row_count, 496)
        self.assertEqual(audit.inserted_row_count, 496)
        self.assertEqual(audit.content_hash, audit.read_back_content_hash)
        self.assertEqual(dict(audit.level_counts), {1: 31, 2: 128, 3: 337})
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(cursor.execute_calls[0][0], PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL)
        self.assertEqual(cursor.execute_calls[1][0], PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL)
        self.assertEqual(
            cursor.executemany_calls[0][0],
            PROD_CORE_WEALTH_SECTOR_HIERARCHY_INSERT_SQL,
        )
        self.assertEqual(len(cursor.executemany_calls[0][1]), 496)
        self.assertEqual(cursor.close_count, 1)

    def test_invalid_parent_closure_fails_before_any_dml(self) -> None:
        content_rows = _target_content_rows()
        content_rows[-1] = {
            **content_rows[-1],
            "parent_sector_code": "BK9999.DC",
        }
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(ValueError, "parent closure failed"):
            replace_prod_core_wealth_sector_hierarchy(
                connection=connection,
                rows=content_rows,
            )

        self.assertEqual(cursor.execute_calls, [])
        self.assertEqual(cursor.executemany_calls, [])
        self.assertEqual(connection.rollback_count, 0)

    def test_read_back_content_mismatch_rolls_back(self) -> None:
        content_rows = _target_content_rows()
        published_at = datetime(2026, 8, 13, 9, 30, tzinfo=timezone.utc)
        read_back_rows = _read_back_rows(content_rows, published_at=published_at)
        changed = list(read_back_rows[-1])
        changed[1] = "被篡改的行业名"
        read_back_rows[-1] = tuple(changed)
        cursor = _FakeCursor(read_back_rows=read_back_rows)
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "read-back audit failed"):
            replace_prod_core_wealth_sector_hierarchy(
                connection=connection,
                rows=content_rows,
                published_at=published_at,
            )

        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(cursor.close_count, 1)

    def test_insert_failure_rolls_back(self) -> None:
        cursor = _FakeCursor(fail_on_executemany=True)
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "insert failed"):
            replace_prod_core_wealth_sector_hierarchy(
                connection=connection,
                rows=_target_content_rows(),
            )

        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(cursor.close_count, 1)

    def test_sql_contract_is_explicit_and_hierarchy_only(self) -> None:
        validate_prod_core_wealth_sector_hierarchy_sql_contract()
        combined_sql = (
            f"{PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL}\n"
            f"{PROD_CORE_WEALTH_SECTOR_HIERARCHY_INSERT_SQL}\n"
            f"{PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL}"
        ).lower()
        self.assertNotIn("select *", combined_sql)
        self.assertNotIn("truncate", combined_sql)
        self.assertNotIn(" update ", f" {combined_sql} ")
        self.assertNotIn("wealth_sector_heat_daily", combined_sql)
        self.assertNotIn("dc_daily", combined_sql)

    def test_dg_definitions_contain_no_sector_heat_chain(self) -> None:
        defs_root = Path(__file__).parents[1] / "src" / "orchestrator" / "defs"
        offenders = []
        for path in defs_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8").lower()
            if "wealth_sector_heat" in source:
                offenders.append(path.relative_to(defs_root).as_posix())
        self.assertEqual(offenders, [])

        automated_publisher_consumers = []
        for relative_directory in ("jobs", "sensors", "checks", "bootstrap"):
            for path in (defs_root / relative_directory).rglob("*.py"):
                if "prod_core_wealth_sector_hierarchy" in path.read_text(
                    encoding="utf-8"
                ):
                    automated_publisher_consumers.append(
                        path.relative_to(defs_root).as_posix()
                    )
        self.assertEqual(automated_publisher_consumers, [])


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.rollback_count = 0

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def rollback(self) -> None:
        self.rollback_count += 1


class _FakeCursor:
    def __init__(
        self,
        *,
        read_back_rows: list[tuple[object, ...]] | None = None,
        fail_on_executemany: bool = False,
    ) -> None:
        self.read_back_rows = read_back_rows or []
        self.fail_on_executemany = fail_on_executemany
        self.execute_calls: list[tuple[str, tuple[object, ...] | None]] = []
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []
        self.rowcount = -1
        self.close_count = 0

    def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> None:
        self.execute_calls.append((sql, params))
        if sql == PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL:
            self.rowcount = 496
        elif sql == PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL:
            self.rowcount = len(self.read_back_rows)

    def executemany(
        self,
        sql: str,
        params: list[tuple[object, ...]],
    ) -> None:
        self.executemany_calls.append((sql, params))
        if self.fail_on_executemany:
            raise RuntimeError("insert failed")
        self.rowcount = len(params)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.read_back_rows

    def close(self) -> None:
        self.close_count += 1


def _silver_hierarchy_rows() -> list[dict[str, object]]:
    seed = load_eastmoney_dc_industry_hierarchy_seed()
    codes_by_path = {
        row.node_path: f"BK{row.display_order:04d}.DC" for row in seed.rows
    }
    rows_by_path = {row.node_path: row for row in seed.rows}
    parent_paths = {row.parent_path for row in seed.rows if row.parent_path}
    reference_date = date(2026, 7, 13)
    rows = []
    for row in seed.rows:
        root_path = row.node_path.split("/", maxsplit=1)[0]
        parent = rows_by_path.get(row.parent_path or "")
        root = rows_by_path[root_path]
        rows.append(
            {
                "ts_code": codes_by_path[row.node_path],
                "name": row.name,
                "industry_level": row.industry_level,
                "industry_level_name": f"东财{_level_name(row.industry_level)}行业",
                "parent_ts_code": (
                    codes_by_path[row.parent_path] if row.parent_path else None
                ),
                "parent_name": parent.name if parent else None,
                "root_ts_code": codes_by_path[root_path],
                "root_name": root.name,
                "hierarchy_path": row.node_path.replace("/", " > "),
                "is_leaf": row.node_path not in parent_paths,
                "display_order": row.display_order,
                "baseline_version": seed.version,
                "source_received_date": seed.source_received_date,
                "code_reference_trade_date": reference_date,
            }
        )
    return rows


def _target_content_rows() -> list[dict[str, object]]:
    mapped = []
    for row in _silver_hierarchy_rows():
        mapped.append(
            {
                "sector_code": row["ts_code"],
                "sector_name": row["name"],
                "industry_level": row["industry_level"],
                "industry_level_name": row["industry_level_name"],
                "parent_sector_code": row["parent_ts_code"],
                "parent_sector_name": row["parent_name"],
                "root_sector_code": row["root_ts_code"],
                "root_sector_name": row["root_name"],
                "hierarchy_path": row["hierarchy_path"],
                "is_leaf": row["is_leaf"],
                "display_order": row["display_order"],
                "baseline_version": row["baseline_version"],
                "source_received_date": row["source_received_date"],
                "code_reference_trade_date": row["code_reference_trade_date"],
            }
        )
    return list(audit_wealth_sector_hierarchy_rows(mapped).rows)


def _read_back_rows(
    rows: list[dict[str, object]],
    *,
    published_at: datetime,
) -> list[tuple[object, ...]]:
    return [
        tuple(
            ({**row, "published_at": published_at})[column]
            for column in PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS
        )
        for row in rows
    ]


def _write_silver_hierarchy_file(
    path: Path,
    rows: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source_columns = (
        "ts_code",
        "name",
        "industry_level",
        "industry_level_name",
        "parent_ts_code",
        "parent_name",
        "root_ts_code",
        "root_name",
        "hierarchy_path",
        "is_leaf",
        "display_order",
        "baseline_version",
        "source_received_date",
        "code_reference_trade_date",
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE hierarchy_rows (
              ts_code VARCHAR,
              name VARCHAR,
              industry_level INTEGER,
              industry_level_name VARCHAR,
              parent_ts_code VARCHAR,
              parent_name VARCHAR,
              root_ts_code VARCHAR,
              root_name VARCHAR,
              hierarchy_path VARCHAR,
              is_leaf BOOLEAN,
              display_order INTEGER,
              baseline_version VARCHAR,
              source_received_date DATE,
              code_reference_trade_date DATE
            )
            """
        )
        connection.executemany(
            "INSERT INTO hierarchy_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(row[column] for column in source_columns) for row in rows],
        )
        connection.execute(
            f"COPY hierarchy_rows TO '{path.as_posix()}' (FORMAT parquet)"
        )


def _level_name(industry_level: int) -> str:
    return {1: "一级", 2: "二级", 3: "三级"}[industry_level]


if __name__ == "__main__":
    unittest.main()
