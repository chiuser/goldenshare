"""Stable stock-universe facts shared by minute-line gates and writers."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    current_cny_stock_basic_select,
    duckdb_string,
)
from orchestrator.defs.paths import silver_stock_basic_path
from orchestrator.defs.resources import DuckDBResource


def load_current_listed_stock_codes_for_stk_mins(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
) -> tuple[str, ...]:
    """Return the canonical current stock set used by raw minute extraction."""

    del duckdb
    stock_basic_path = silver_stock_basic_path(lake_root)
    if not stock_basic_path.exists():
        raise FileNotFoundError(f"Missing silver stock basic file: {stock_basic_path}")

    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT ts_code
            FROM ({current_cny_stock_basic_select(stock_basic_path)}) stock_basic
            WHERE list_date <= CAST({duckdb_string(partition_key)} AS DATE)
            ORDER BY ts_code
            """
        ).fetchall()

    return normalize_stk_mins_stock_codes(tuple(str(row[0]) for row in rows))


def normalize_stk_mins_stock_codes(stock_codes: Sequence[str]) -> tuple[str, ...]:
    """Normalize the code set before it becomes a source-coverage identity."""

    normalized = tuple(
        sorted({str(value).strip().upper() for value in stock_codes if str(value).strip()})
    )
    if not normalized:
        raise ValueError("Expected stk_mins stock code set is empty.")
    if len(normalized) != len(stock_codes):
        raise ValueError("Expected stk_mins stock code set contains blank or duplicate values.")
    return normalized


def stk_mins_stock_code_set_hash(stock_codes: Sequence[str]) -> str:
    """Return the established stable MD5 identity for the canonical stock set."""

    normalized = normalize_stk_mins_stock_codes(stock_codes)
    return hashlib.md5(
        ",".join(normalized).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
