from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from lake_console.backend.app.catalog.datasets.market_equity import DAILY_FIELDS
from lake_console.backend.app.catalog.tushare_reference_master import (
    ETF_BASIC_FIELDS,
    ETF_INDEX_FIELDS,
    THS_INDEX_FIELDS,
    THS_MEMBER_FIELDS,
)


PROD_RAW_DB_SOURCE = "prod-raw-db"
PROD_RAW_DB_ALLOWED_TABLES = {
    "daily": "raw_tushare.daily",
    "etf_basic": "raw_tushare.etf_basic",
    "etf_index": "raw_tushare.etf_index",
    "ths_index": "raw_tushare.ths_index",
    "ths_member": "raw_tushare.ths_member",
}
PROD_RAW_DB_FIELDS = {
    "daily": DAILY_FIELDS,
    "etf_basic": ETF_BASIC_FIELDS,
    "etf_index": ETF_INDEX_FIELDS,
    "ths_index": THS_INDEX_FIELDS,
    "ths_member": THS_MEMBER_FIELDS,
}
PROD_RAW_DB_ORDER_BY = {
    "etf_basic": ("ts_code",),
    "etf_index": ("ts_code",),
    "ths_index": ("ts_code",),
    "ths_member": ("ts_code", "con_code"),
}
PROD_RAW_DB_SYSTEM_FIELDS = {"api_name", "fetched_at", "raw_payload"}


@dataclass(frozen=True)
class ProdRawQuery:
    sql: str
    params: tuple[Any, ...]
    table_name: str
    fields: tuple[str, ...]


class ProdRawDbConfigError(RuntimeError):
    pass


def build_daily_prod_raw_query(*, trade_date: date) -> ProdRawQuery:
    table_name = _require_allowed_table("daily")
    fields = _require_allowed_fields("daily")
    projection = ", ".join(fields)
    if "*" in projection:
        raise ValueError("prod-raw-db 查询禁止 select *。")
    return ProdRawQuery(
        sql=(
            f"select {projection} "
            f"from {table_name} "
            "where trade_date = %s "
            "order by ts_code"
        ),
        params=(trade_date,),
        table_name=table_name,
        fields=fields,
    )


def build_daily_prod_raw_range_query(*, start_date: date, end_date: date) -> ProdRawQuery:
    table_name = _require_allowed_table("daily")
    fields = _require_allowed_fields("daily")
    projection = ", ".join(fields)
    if "*" in projection:
        raise ValueError("prod-raw-db 查询禁止 select *。")
    return ProdRawQuery(
        sql=(
            f"select {projection} "
            f"from {table_name} "
            "where trade_date >= %s and trade_date <= %s "
            "order by trade_date, ts_code"
        ),
        params=(start_date, end_date),
        table_name=table_name,
        fields=fields,
    )


def build_prod_raw_current_query(*, dataset_key: str) -> ProdRawQuery:
    table_name = _require_allowed_table(dataset_key)
    fields = _require_allowed_fields(dataset_key)
    projection = ", ".join(fields)
    if "*" in projection:
        raise ValueError("prod-raw-db 查询禁止 select *。")
    order_fields = PROD_RAW_DB_ORDER_BY.get(dataset_key)
    if not order_fields:
        raise ValueError(f"prod-raw-db 缺少排序字段定义：{dataset_key}")
    order_by = ", ".join(order_fields)
    return ProdRawQuery(
        sql=(
            f"select {projection} "
            f"from {table_name} "
            f"order by {order_by}"
        ),
        params=(),
        table_name=table_name,
        fields=fields,
    )


def fetch_prod_raw_rows(*, database_url: str | None, query: ProdRawQuery) -> list[dict[str, Any]]:
    if not database_url:
        raise ProdRawDbConfigError(
            "缺少 GOLDENSHARE_PROD_RAW_DB_URL。请通过环境变量或 lake_console/config.local.toml 配置 prod_raw_db_url。"
        )
    _assert_query_is_safe(query)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise ProdRawDbConfigError("缺少 psycopg，请先安装 lake_console/backend/requirements.txt。") from exc

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("set transaction read only")
            with connection.cursor() as cursor:
                cursor.execute(query.sql, query.params)
                return [dict(row) for row in cursor.fetchall()]


def iter_prod_raw_rows(
    *,
    database_url: str | None,
    query: ProdRawQuery,
    batch_size: int = 20000,
    cursor_name: str = "lake_prod_raw_cursor",
) -> Iterator[list[dict[str, Any]]]:
    if not database_url:
        raise ProdRawDbConfigError(
            "缺少 GOLDENSHARE_PROD_RAW_DB_URL。请通过环境变量或 lake_console/config.local.toml 配置 prod_raw_db_url。"
        )
    if batch_size <= 0:
        raise ValueError("prod-raw-db batch_size 必须大于 0。")
    _assert_query_is_safe(query)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise ProdRawDbConfigError("缺少 psycopg，请先安装 lake_console/backend/requirements.txt。") from exc

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("set transaction read only")
            with connection.cursor(name=cursor_name) as cursor:
                cursor.itersize = batch_size
                cursor.execute(query.sql, query.params)
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    yield [dict(row) for row in rows]


def _require_allowed_table(dataset_key: str) -> str:
    table_name = PROD_RAW_DB_ALLOWED_TABLES.get(dataset_key)
    if table_name is None:
        allowed = ", ".join(sorted(PROD_RAW_DB_ALLOWED_TABLES))
        raise ValueError(f"prod-raw-db 只允许导出白名单数据集：{allowed}")
    schema_name, _, relation_name = table_name.partition(".")
    if schema_name != "raw_tushare" or not relation_name:
        raise ValueError(f"prod-raw-db 表白名单配置非法：{table_name}")
    return table_name


def _require_allowed_fields(dataset_key: str) -> tuple[str, ...]:
    fields = PROD_RAW_DB_FIELDS.get(dataset_key)
    if fields is None:
        raise ValueError(f"prod-raw-db 缺少字段白名单：{dataset_key}")
    blocked = sorted(set(fields) & PROD_RAW_DB_SYSTEM_FIELDS)
    if blocked:
        raise ValueError(f"prod-raw-db 字段白名单包含系统字段：{blocked}")
    if any(field.strip() == "*" for field in fields):
        raise ValueError("prod-raw-db 字段白名单禁止星号。")
    return fields


def _assert_query_is_safe(query: ProdRawQuery) -> None:
    normalized_sql = " ".join(query.sql.lower().split())
    if "select *" in normalized_sql:
        raise ValueError("prod-raw-db 查询禁止 select *。")
    if query.table_name not in PROD_RAW_DB_ALLOWED_TABLES.values():
        raise ValueError(f"prod-raw-db 查询表不在白名单：{query.table_name}")
    if not query.table_name.startswith("raw_tushare."):
        raise ValueError(f"prod-raw-db 查询只能访问 raw_tushare schema：{query.table_name}")
    if any(
        blocked in normalized_sql
        for blocked in (" ops.", " core.", " core_serving.", " core_serving_light.", " biz.", " app.", " platform.")
    ):
        raise ValueError("prod-raw-db 查询禁止访问非 raw_tushare schema。")
