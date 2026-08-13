import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import duckdb

from orchestrator.defs.assets.stock_daily_qfq_nineturn_prod_core import (
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PATH_TEMPLATE,
    load_gold_stock_daily_qfq_nineturn_rows_for_prod_sync,
    prod_core_stock_daily_qfq_nineturn,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.prod_db.stock_daily_qfq_nineturn import (
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INSERT_SQL,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL,
    replace_prod_core_stock_daily_qfq_nineturn_partition,
    validate_prod_core_stock_daily_qfq_nineturn_sql_contract,
)
from orchestrator.defs.resources import DuckDBResource


class StockDailyQfqNineTurnProdCoreSyncTests(unittest.TestCase):
    def test_asset_definition_freezes_qfq_source_and_serving_target(self) -> None:
        asset_key = prod_core_stock_daily_qfq_nineturn.key
        self.assertEqual(
            asset_key.to_user_string(),
            "prod_core_stock_daily_qfq_nineturn",
        )
        spec = prod_core_stock_daily_qfq_nineturn.get_asset_spec(asset_key)
        self.assertEqual(spec.group_name, "quote")
        self.assertEqual(
            spec.metadata["goldenshare/path_template"],
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PATH_TEMPLATE,
        )
        self.assertEqual(
            spec.metadata["goldenshare/source_asset"],
            "gold_stock_daily_qfq_nineturn",
        )
        self.assertEqual(
            spec.metadata["goldenshare/target_table"],
            "core_serving.equity_qfq_nineturn_daily",
        )
        self.assertEqual(spec.metadata["goldenshare/formula_version"], 1)

    def test_load_rows_validates_schema_and_source_key_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            partition_key = "2026-08-12"
            source_path = gold_stock_daily_qfq_nineturn_path(root, partition_key)
            qfq_source_path = gold_stock_daily_qfq_path(root, partition_key)
            _write_qfq_file(qfq_source_path, partition_key)
            _write_nine_turn_file(source_path, partition_key)

            rows = load_gold_stock_daily_qfq_nineturn_rows_for_prod_sync(
                duckdb_resource=DuckDBResource(),
                source_path=source_path,
                qfq_source_path=qfq_source_path,
                partition_key=partition_key,
            )

        self.assertEqual([row["ts_code"] for row in rows], ["000001.SZ", "600000.SH"])
        self.assertEqual(rows[0]["up_count"], 10)
        self.assertEqual(rows[0]["nine_up_turn"], "+9")

    def test_load_rows_fails_closed_when_source_key_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            partition_key = "2026-08-12"
            source_path = gold_stock_daily_qfq_nineturn_path(root, partition_key)
            qfq_source_path = gold_stock_daily_qfq_path(root, partition_key)
            _write_qfq_file(qfq_source_path, partition_key, include_second=False)
            _write_nine_turn_file(source_path, partition_key)

            with self.assertRaisesRegex(RuntimeError, "contract failed"):
                load_gold_stock_daily_qfq_nineturn_rows_for_prod_sync(
                    duckdb_resource=DuckDBResource(),
                    source_path=source_path,
                    qfq_source_path=qfq_source_path,
                    partition_key=partition_key,
                )

    def test_replace_partition_bulk_inserts_and_hashes_read_back(self) -> None:
        published_at = datetime(2026, 8, 13, 1, 2, 3, tzinfo=timezone.utc)
        rows = _sample_rows("2026-08-12")
        cursor = _FakeCursor(
            read_back_rows=_read_back_rows(rows, published_at=published_at)
        )
        connection = _FakeConnection(cursor)
        captured: dict[str, object] = {}

        def fake_execute_values(
            observed_cursor,
            sql: str,
            args: list[tuple[object, ...]],
            *,
            page_size: int,
        ) -> None:
            captured.update(
                cursor=observed_cursor,
                sql=sql,
                args=args,
                page_size=page_size,
            )

        with patch(
            "orchestrator.defs.prod_db.stock_daily_qfq_nineturn.execute_values",
            side_effect=fake_execute_values,
        ):
            audit = replace_prod_core_stock_daily_qfq_nineturn_partition(
                connection=connection,
                rows=rows,
                partition_key="2026-08-12",
                published_at=published_at,
            )

        self.assertEqual(audit.row_count, 2)
        self.assertEqual(audit.inserted_row_count, 2)
        self.assertEqual(audit.read_back_row_count, 2)
        self.assertEqual(len(audit.content_hash), 64)
        self.assertEqual(captured["cursor"], cursor)
        self.assertEqual(captured["sql"], PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INSERT_SQL)
        self.assertEqual(captured["page_size"], 1_000)
        self.assertEqual(len(captured["args"]), 2)
        self.assertEqual(
            cursor.execute_calls,
            [
                (
                    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL,
                    ("2026-08-12",),
                ),
                (
                    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL,
                    ("2026-08-12",),
                ),
            ],
        )
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(cursor.close_count, 1)

    def test_replace_partition_rejects_duplicate_key_before_write(self) -> None:
        rows = _sample_rows("2026-08-12")
        rows[1]["ts_code"] = rows[0]["ts_code"]
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(ValueError, "duplicate keys"):
            replace_prod_core_stock_daily_qfq_nineturn_partition(
                connection=connection,
                rows=rows,
                partition_key="2026-08-12",
            )

        self.assertEqual(cursor.execute_calls, [])
        self.assertEqual(connection.rollback_count, 0)

    def test_replace_partition_rolls_back_on_read_back_drift(self) -> None:
        published_at = datetime(2026, 8, 13, 1, 2, 3, tzinfo=timezone.utc)
        rows = _sample_rows("2026-08-12")
        read_back = _read_back_rows(rows, published_at=published_at)
        read_back[0] = (*read_back[0][:2], 999.0, *read_back[0][3:])
        cursor = _FakeCursor(read_back_rows=read_back)
        connection = _FakeConnection(cursor)

        with patch(
            "orchestrator.defs.prod_db.stock_daily_qfq_nineturn.execute_values"
        ), self.assertRaisesRegex(RuntimeError, "read-back audit failed"):
            replace_prod_core_stock_daily_qfq_nineturn_partition(
                connection=connection,
                rows=rows,
                partition_key="2026-08-12",
                published_at=published_at,
            )

        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(cursor.close_count, 1)

    def test_sql_contract_has_no_tushare_or_wildcard_fallback(self) -> None:
        validate_prod_core_stock_daily_qfq_nineturn_sql_contract()
        sql = (
            f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL}\n"
            f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INSERT_SQL}\n"
            f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL}"
        ).lower()
        self.assertNotIn("select *", sql)
        self.assertNotIn("equity_nineturn", sql)
        self.assertNotIn("tushare", sql)


class _FakeConnection:
    def __init__(self, cursor: "_FakeCursor") -> None:
        self._cursor = cursor
        self.rollback_count = 0

    def cursor(self) -> "_FakeCursor":
        return self._cursor

    def rollback(self) -> None:
        self.rollback_count += 1


class _FakeCursor:
    def __init__(self, read_back_rows: list[tuple[object, ...]] | None = None) -> None:
        self.read_back_rows = read_back_rows or []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = -1
        self.close_count = 0

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.execute_calls.append((sql, params))
        self.rowcount = 2 if sql == PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL else -1

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.read_back_rows

    def close(self) -> None:
        self.close_count += 1


def _sample_rows(partition_key: str) -> list[dict[str, object]]:
    return [
        {
            "ts_code": "000001.SZ",
            "trade_date": partition_key,
            "close_qfq": 12.5,
            "up_count": 10,
            "down_count": 0,
            "nine_up_turn": "+9",
            "nine_down_turn": None,
        },
        {
            "ts_code": "600000.SH",
            "trade_date": partition_key,
            "close_qfq": 8.2,
            "up_count": 0,
            "down_count": 4,
            "nine_up_turn": None,
            "nine_down_turn": None,
        },
    ]


def _read_back_rows(
    rows: list[dict[str, object]],
    *,
    published_at: datetime,
) -> list[tuple[object, ...]]:
    return [
        (
            row["ts_code"],
            row["trade_date"],
            row["close_qfq"],
            row["up_count"],
            row["down_count"],
            row["nine_up_turn"],
            row["nine_down_turn"],
            1,
            published_at,
        )
        for row in rows
    ]


def _write_qfq_file(
    path: Path,
    partition_key: str,
    *,
    include_second: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    codes = ["000001.SZ", "600000.SH"] if include_second else ["000001.SZ"]
    values = ",".join(
        f"('{code}', DATE '{partition_key}', 10.0, 13.0, 9.0, 12.5, "
        "12.0, 0.5, 4.2, 1000.0, 12000.0)"
        for code in codes
    )
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES {values}) AS source(
                ts_code, trade_date, open, high, low, close, pre_close,
                change_amount, pct_chg, vol, amount
              )
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )
    finally:
        connection.close()


def _write_nine_turn_file(path: Path, partition_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('000001.SZ', DATE '{partition_key}', 12.5::DOUBLE,
                  10::INTEGER, 0::INTEGER, '+9'::VARCHAR, NULL::VARCHAR),
                ('600000.SH', DATE '{partition_key}', 8.2::DOUBLE,
                  0::INTEGER, 4::INTEGER, NULL::VARCHAR, NULL::VARCHAR)
              ) AS source(
                ts_code, trade_date, close_qfq, up_count, down_count,
                nine_up_turn, nine_down_turn
              )
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )
    finally:
        connection.close()
