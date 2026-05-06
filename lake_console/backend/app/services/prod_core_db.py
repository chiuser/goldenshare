from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from lake_console.backend.app.catalog.tushare_index_series import INDEX_DAILY_CORE_SELECT_FIELDS, INDEX_DAILY_FIELDS


PROD_CORE_DB_SOURCE = "prod-core-db"
PROD_CORE_DB_ALLOWED_TABLES = {
    "index_daily": "core_serving.index_daily_serving",
}
PROD_CORE_DB_FIELDS = {
    "index_daily": INDEX_DAILY_FIELDS,
}
PROD_CORE_DB_SELECT_FIELDS = {
    "index_daily": INDEX_DAILY_CORE_SELECT_FIELDS,
}
PROD_CORE_DB_SYSTEM_FIELDS = {"source", "created_at", "updated_at"}


@dataclass(frozen=True)
class ProdCoreQuery:
    sql: str
    params: tuple[Any, ...]
    table_name: str
    fields: tuple[str, ...]


class ProdCoreDbConfigError(RuntimeError):
    pass


def build_prod_core_trade_date_query(*, dataset_key: str, trade_date: date) -> ProdCoreQuery:
    table_name = _require_allowed_table(dataset_key)
    fields = _require_allowed_fields(dataset_key)
    projection = _build_projection(dataset_key)
    return ProdCoreQuery(
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


def build_prod_core_trade_date_range_query(*, dataset_key: str, start_date: date, end_date: date) -> ProdCoreQuery:
    table_name = _require_allowed_table(dataset_key)
    fields = _require_allowed_fields(dataset_key)
    projection = _build_projection(dataset_key)
    return ProdCoreQuery(
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


def fetch_prod_core_rows(*, database_url: str | None, query: ProdCoreQuery) -> list[dict[str, Any]]:
    if not database_url:
        raise ProdCoreDbConfigError(
            "缺少 GOLDENSHARE_PROD_CORE_DB_URL。请通过环境变量或 lake_console/config.local.toml 配置 prod_core_db_url。"
        )
    _assert_query_is_safe(query)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise ProdCoreDbConfigError("缺少 psycopg，请先安装 lake_console/backend/requirements.txt。") from exc

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("set transaction read only")
            with connection.cursor() as cursor:
                cursor.execute(query.sql, query.params)
                return [dict(row) for row in cursor.fetchall()]


def iter_prod_core_rows(
    *,
    database_url: str | None,
    query: ProdCoreQuery,
    batch_size: int = 20000,
    cursor_name: str = "lake_prod_core_cursor",
) -> Iterator[list[dict[str, Any]]]:
    if not database_url:
        raise ProdCoreDbConfigError(
            "缺少 GOLDENSHARE_PROD_CORE_DB_URL。请通过环境变量或 lake_console/config.local.toml 配置 prod_core_db_url。"
        )
    if batch_size <= 0:
        raise ValueError("prod-core-db batch_size 必须大于 0。")
    _assert_query_is_safe(query)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise ProdCoreDbConfigError("缺少 psycopg，请先安装 lake_console/backend/requirements.txt。") from exc

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


def _build_projection(dataset_key: str) -> str:
    select_fields = PROD_CORE_DB_SELECT_FIELDS.get(dataset_key)
    if select_fields is None:
        raise ValueError(f"prod-core-db 缺少 SQL 投影定义：{dataset_key}")
    projection = ", ".join(select_fields)
    if "*" in projection:
        raise ValueError("prod-core-db 查询禁止 select *。")
    return projection


def _require_allowed_table(dataset_key: str) -> str:
    table_name = PROD_CORE_DB_ALLOWED_TABLES.get(dataset_key)
    if table_name is None:
        allowed = ", ".join(sorted(PROD_CORE_DB_ALLOWED_TABLES))
        raise ValueError(f"prod-core-db 只允许导出白名单数据集：{allowed}")
    schema_name, _, relation_name = table_name.partition(".")
    if schema_name != "core_serving" or not relation_name:
        raise ValueError(f"prod-core-db 表白名单配置非法：{table_name}")
    return table_name


def _require_allowed_fields(dataset_key: str) -> tuple[str, ...]:
    fields = PROD_CORE_DB_FIELDS.get(dataset_key)
    if fields is None:
        raise ValueError(f"prod-core-db 缺少字段白名单：{dataset_key}")
    blocked = sorted(set(fields) & PROD_CORE_DB_SYSTEM_FIELDS)
    if blocked:
        raise ValueError(f"prod-core-db 字段白名单包含系统字段：{blocked}")
    if any(field.strip() == "*" for field in fields):
        raise ValueError("prod-core-db 字段白名单禁止星号。")
    return fields


def _assert_query_is_safe(query: ProdCoreQuery) -> None:
    normalized_sql = " ".join(query.sql.lower().split())
    if "select *" in normalized_sql:
        raise ValueError("prod-core-db 查询禁止 select *。")
    if query.table_name not in PROD_CORE_DB_ALLOWED_TABLES.values():
        raise ValueError(f"prod-core-db 查询表不在白名单：{query.table_name}")
    if query.table_name != "core_serving.index_daily_serving":
        raise ValueError(f"prod-core-db 当前只允许访问 core_serving.index_daily_serving：{query.table_name}")
    if any(
        blocked in normalized_sql
        for blocked in (" ops.", " raw_tushare.", " core.", " core_serving_light.", " biz.", " app.", " platform.")
    ):
        raise ValueError("prod-core-db 查询禁止访问 index_daily 例外之外的其他 schema。")
