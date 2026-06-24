from datetime import datetime
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from orchestrator.defs.prod_db.wealth_market_turnover import (
    PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL,
    PROD_CORE_WEALTH_MARKET_TURNOVER_INSERT_SQL,
    PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL,
    replace_prod_core_wealth_market_turnover_partition,
    validate_prod_core_wealth_market_turnover_sql_contract,
)
from orchestrator.defs.resources import ProdPostgresWriteResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


class GoldWealthMarketTurnoverProdCoreSyncTests(unittest.TestCase):
    def test_write_resource_uses_dedicated_env_and_commits_on_success(self) -> None:
        fake_connection = _FakeConnection(_FakeCursor())
        env = {
            "PROD_POSTGRES_WRITE_HOST": "prod-db",
            "PROD_POSTGRES_WRITE_PORT": "5432",
            "PROD_POSTGRES_WRITE_USER": "wealth_turnover_writer",
            "PROD_POSTGRES_WRITE_PASSWORD": "secret",
            "PROD_POSTGRES_WRITE_DATABASE": "goldenshare",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("psycopg2.connect", return_value=fake_connection) as connect:
                with ProdPostgresWriteResource().connect() as connection:
                    self.assertIs(connection, fake_connection)

        connect.assert_called_once()
        self.assertEqual(
            connect.call_args.kwargs,
            {
                "host": "prod-db",
                "port": 5432,
                "user": "wealth_turnover_writer",
                "password": "secret",
                "dbname": "goldenshare",
                "sslmode": "prefer",
                "connect_timeout": 10,
            },
        )
        self.assertEqual(fake_connection.set_session_calls, [(False, False)])
        self.assertEqual(fake_connection.commit_count, 1)
        self.assertEqual(fake_connection.rollback_count, 0)
        self.assertEqual(fake_connection.close_count, 1)

    def test_write_resource_rolls_back_on_error(self) -> None:
        fake_connection = _FakeConnection(_FakeCursor())
        env = {
            "PROD_POSTGRES_WRITE_HOST": "prod-db",
            "PROD_POSTGRES_WRITE_PORT": "5432",
            "PROD_POSTGRES_WRITE_USER": "wealth_turnover_writer",
            "PROD_POSTGRES_WRITE_PASSWORD": "secret",
            "PROD_POSTGRES_WRITE_DATABASE": "goldenshare",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("psycopg2.connect", return_value=fake_connection):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    with ProdPostgresWriteResource().connect():
                        raise RuntimeError("boom")

        self.assertEqual(fake_connection.set_session_calls, [(False, False)])
        self.assertEqual(fake_connection.commit_count, 0)
        self.assertEqual(fake_connection.rollback_count, 1)
        self.assertEqual(fake_connection.close_count, 1)

    def test_replace_partition_deletes_inserts_and_reads_back_five_rows(self) -> None:
        rows = _sample_rows("2026-06-23")
        cursor = _FakeCursor(read_back_rows=_read_back_rows(rows))
        connection = _FakeConnection(cursor)

        audit = replace_prod_core_wealth_market_turnover_partition(
            connection=connection,
            rows=rows,
            partition_key="2026-06-23",
        )

        self.assertEqual(audit.row_count, 5)
        self.assertEqual(audit.read_back_row_count, 5)
        self.assertEqual(audit.inserted_row_count, 5)
        self.assertEqual(len(audit.points_json_hash), 32)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(cursor.close_count, 1)
        self.assertEqual(cursor.execute_calls[0][0], PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL)
        self.assertEqual(
            cursor.execute_calls[0][1],
            ("stock", "CN_A", "2026-06-23"),
        )
        self.assertEqual(cursor.executemany_calls[0][0], PROD_CORE_WEALTH_MARKET_TURNOVER_INSERT_SQL)
        self.assertEqual(len(cursor.executemany_calls[0][1]), 5)
        self.assertTrue(hasattr(cursor.executemany_calls[0][1][0][10], "adapted"))
        self.assertEqual(cursor.execute_calls[1][0], PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL)

    def test_replace_partition_rejects_incomplete_freq_set_before_write(self) -> None:
        rows = _sample_rows("2026-06-23")[:-1]
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(ValueError, "exactly five rows"):
            replace_prod_core_wealth_market_turnover_partition(
                connection=connection,
                rows=rows,
                partition_key="2026-06-23",
            )

        self.assertEqual(cursor.execute_calls, [])
        self.assertEqual(cursor.executemany_calls, [])
        self.assertEqual(connection.rollback_count, 0)

    def test_replace_partition_rejects_date_mismatch_before_write(self) -> None:
        rows = _sample_rows("2026-06-23")
        rows[0]["trade_date"] = "2026-06-22"
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(ValueError, "trade_date does not match"):
            replace_prod_core_wealth_market_turnover_partition(
                connection=connection,
                rows=rows,
                partition_key="2026-06-23",
            )

        self.assertEqual(cursor.execute_calls, [])
        self.assertEqual(cursor.executemany_calls, [])
        self.assertEqual(connection.rollback_count, 0)

    def test_replace_partition_rolls_back_when_insert_fails(self) -> None:
        rows = _sample_rows("2026-06-23")
        cursor = _FakeCursor(fail_on_executemany=True)
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "insert failed"):
            replace_prod_core_wealth_market_turnover_partition(
                connection=connection,
                rows=rows,
                partition_key="2026-06-23",
            )

        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(cursor.close_count, 1)

    def test_replace_partition_rolls_back_when_readback_mismatches(self) -> None:
        rows = _sample_rows("2026-06-23")
        read_back_rows = _read_back_rows(rows)
        read_back_rows[0] = (*read_back_rows[0][:6], Decimal("999.00"), *read_back_rows[0][7:])
        cursor = _FakeCursor(read_back_rows=read_back_rows)
        connection = _FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "read-back audit failed"):
            replace_prod_core_wealth_market_turnover_partition(
                connection=connection,
                rows=rows,
                partition_key="2026-06-23",
            )

        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(cursor.close_count, 1)

    def test_sql_contract_uses_explicit_columns_and_no_system_columns(self) -> None:
        validate_prod_core_wealth_market_turnover_sql_contract()
        combined_sql = "\n".join(
            (
                PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL,
                PROD_CORE_WEALTH_MARKET_TURNOVER_INSERT_SQL,
                PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL,
            )
        ).lower()
        self.assertNotIn("select *", combined_sql)
        for forbidden_column in ("created_at", "updated_at"):
            self.assertNotIn(forbidden_column, combined_sql)


class _FakeConnection:
    def __init__(self, cursor: "_FakeCursor") -> None:
        self._cursor = cursor
        self.set_session_calls: list[tuple[bool, bool]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> "_FakeCursor":
        return self._cursor

    def set_session(self, *, readonly: bool, autocommit: bool) -> None:
        self.set_session_calls.append((readonly, autocommit))

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


class _FakeCursor:
    def __init__(
        self,
        *,
        read_back_rows: list[tuple[object, ...]] | None = None,
        fail_on_executemany: bool = False,
    ) -> None:
        self.read_back_rows = read_back_rows or []
        self.fail_on_executemany = fail_on_executemany
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []
        self.rowcount = -1
        self.close_count = 0

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.execute_calls.append((sql, params))
        if sql == PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL:
            self.rowcount = 5
        elif sql == PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL:
            self.rowcount = len(self.read_back_rows)
        else:
            self.rowcount = -1

    def executemany(self, sql: str, params: list[tuple[object, ...]]) -> None:
        if self.fail_on_executemany:
            raise RuntimeError("insert failed")
        self.executemany_calls.append((sql, params))
        self.rowcount = len(params)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.read_back_rows

    def close(self) -> None:
        self.close_count += 1


def _sample_rows(partition_key: str) -> list[dict[str, object]]:
    rows = []
    for freq in STK_MINS_FREQS:
        rows.append(
            {
                "type": "stock",
                "market": "CN_A",
                "trade_date": partition_key,
                "freq": freq,
                "build_status": "READY",
                "latest_trade_time": datetime(2026, 6, 23, 15, 0),
                "total_amount": Decimal(f"{freq * 1000}.00"),
                "total_vol": freq * 10000,
                "security_count": 2,
                "source_row_count": 4,
                "points_json": (
                    f'[{{"tradeTime":"09:30","tradeTimeTs":"{partition_key} 09:30:00",'
                    f'"amount":{freq}.00,"vol":{freq * 100},"securityCount":2}}]'
                ),
                "build_version": "v1",
                "built_at": datetime(2026, 6, 23, 20, 0),
                "build_note": None,
            }
        )
    return rows


def _read_back_rows(rows: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [
        (
            row["type"],
            row["market"],
            row["trade_date"],
            row["freq"],
            row["build_status"],
            row["latest_trade_time"],
            row["total_amount"],
            row["total_vol"],
            row["security_count"],
            row["source_row_count"],
            row["points_json"],
            row["build_version"],
            row["built_at"],
            row["build_note"],
        )
        for row in rows
    ]


if __name__ == "__main__":
    unittest.main()
