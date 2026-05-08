from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from lake_console.backend.app.catalog.datasets.board_hotspot import (
    DC_DAILY_FIELDS,
    DC_HOT_FIELDS,
    DC_INDEX_FIELDS,
    DC_MEMBER_FIELDS,
    KPL_CONCEPT_CONS_FIELDS,
    KPL_LIST_FIELDS,
    THS_DAILY_FIELDS,
    THS_HOT_FIELDS,
)
from lake_console.backend.app.catalog.datasets.leader_board import (
    LIMIT_CPT_LIST_FIELDS,
    LIMIT_LIST_D_FIELDS,
    LIMIT_LIST_THS_FIELDS,
    LIMIT_STEP_FIELDS,
    TOP_LIST_FIELDS,
)
from lake_console.backend.app.catalog.datasets.market_equity import (
    ADJ_FACTOR_FIELDS,
    DAILY_BASIC_FIELDS,
    DAILY_FIELDS,
    MARGIN_FIELDS,
    STK_LIMIT_FIELDS,
    STOCK_ST_FIELDS,
    SUSPEND_D_FIELDS,
)
from lake_console.backend.app.catalog.datasets.market_fund import FUND_ADJ_FIELDS, FUND_DAILY_FIELDS
from lake_console.backend.app.catalog.datasets.moneyflow import (
    MONEYFLOW_CNT_THS_FIELDS,
    MONEYFLOW_DC_FIELDS,
    MONEYFLOW_FIELDS,
    MONEYFLOW_IND_DC_FIELDS,
    MONEYFLOW_IND_THS_FIELDS,
    MONEYFLOW_MKT_DC_FIELDS,
    MONEYFLOW_THS_FIELDS,
)
from lake_console.backend.app.catalog.datasets.technical_indicators import CYQ_PERF_FIELDS
from lake_console.backend.app.catalog.tushare_index_series import INDEX_DAILY_BASIC_FIELDS
from lake_console.backend.app.catalog.tushare_reference_master import (
    ETF_BASIC_FIELDS,
    ETF_INDEX_FIELDS,
    THS_INDEX_FIELDS,
    THS_MEMBER_FIELDS,
)


PROD_RAW_DB_SOURCE = "prod-raw-db"
PROD_RAW_DB_ALLOWED_TABLES = {
    "adj_factor": "raw_tushare.adj_factor",
    "cyq_perf": "raw_tushare.cyq_perf",
    "daily_basic": "raw_tushare.daily_basic",
    "daily": "raw_tushare.daily",
    "dc_daily": "raw_tushare.dc_daily",
    "dc_hot": "raw_tushare.dc_hot",
    "dc_index": "raw_tushare.dc_index",
    "dc_member": "raw_tushare.dc_member",
    "etf_basic": "raw_tushare.etf_basic",
    "etf_index": "raw_tushare.etf_index",
    "fund_adj": "raw_tushare.fund_adj",
    "fund_daily": "raw_tushare.fund_daily",
    "index_daily_basic": "raw_tushare.index_daily_basic",
    "kpl_concept_cons": "raw_tushare.kpl_concept_cons",
    "kpl_list": "raw_tushare.kpl_list",
    "limit_cpt_list": "raw_tushare.limit_cpt_list",
    "limit_list_d": "raw_tushare.limit_list",
    "limit_list_ths": "raw_tushare.limit_list_ths",
    "limit_step": "raw_tushare.limit_step",
    "margin": "raw_tushare.margin",
    "moneyflow": "raw_tushare.moneyflow",
    "moneyflow_cnt_ths": "raw_tushare.moneyflow_cnt_ths",
    "moneyflow_dc": "raw_tushare.moneyflow_dc",
    "moneyflow_ind_dc": "raw_tushare.moneyflow_ind_dc",
    "moneyflow_ind_ths": "raw_tushare.moneyflow_ind_ths",
    "moneyflow_mkt_dc": "raw_tushare.moneyflow_mkt_dc",
    "moneyflow_ths": "raw_tushare.moneyflow_ths",
    "stk_limit": "raw_tushare.stk_limit",
    "stock_st": "raw_tushare.stock_st",
    "suspend_d": "raw_tushare.suspend_d",
    "ths_daily": "raw_tushare.ths_daily",
    "ths_index": "raw_tushare.ths_index",
    "ths_hot": "raw_tushare.ths_hot",
    "ths_member": "raw_tushare.ths_member",
    "top_list": "raw_tushare.top_list",
}
PROD_RAW_DB_FIELDS = {
    "adj_factor": ADJ_FACTOR_FIELDS,
    "cyq_perf": CYQ_PERF_FIELDS,
    "daily_basic": DAILY_BASIC_FIELDS,
    "daily": DAILY_FIELDS,
    "etf_basic": ETF_BASIC_FIELDS,
    "etf_index": ETF_INDEX_FIELDS,
    "fund_adj": FUND_ADJ_FIELDS,
    "fund_daily": FUND_DAILY_FIELDS,
    "index_daily_basic": INDEX_DAILY_BASIC_FIELDS,
    "dc_daily": DC_DAILY_FIELDS,
    "dc_hot": DC_HOT_FIELDS,
    "dc_index": DC_INDEX_FIELDS,
    "dc_member": DC_MEMBER_FIELDS,
    "kpl_concept_cons": KPL_CONCEPT_CONS_FIELDS,
    "kpl_list": KPL_LIST_FIELDS,
    "limit_cpt_list": LIMIT_CPT_LIST_FIELDS,
    "limit_list_d": LIMIT_LIST_D_FIELDS,
    "limit_list_ths": LIMIT_LIST_THS_FIELDS,
    "limit_step": LIMIT_STEP_FIELDS,
    "margin": MARGIN_FIELDS,
    "moneyflow": MONEYFLOW_FIELDS,
    "moneyflow_cnt_ths": MONEYFLOW_CNT_THS_FIELDS,
    "moneyflow_dc": MONEYFLOW_DC_FIELDS,
    "moneyflow_ind_dc": MONEYFLOW_IND_DC_FIELDS,
    "moneyflow_ind_ths": MONEYFLOW_IND_THS_FIELDS,
    "moneyflow_mkt_dc": MONEYFLOW_MKT_DC_FIELDS,
    "moneyflow_ths": MONEYFLOW_THS_FIELDS,
    "stk_limit": STK_LIMIT_FIELDS,
    "stock_st": STOCK_ST_FIELDS,
    "suspend_d": SUSPEND_D_FIELDS,
    "ths_daily": THS_DAILY_FIELDS,
    "ths_index": THS_INDEX_FIELDS,
    "ths_hot": THS_HOT_FIELDS,
    "ths_member": THS_MEMBER_FIELDS,
    "top_list": TOP_LIST_FIELDS,
}
PROD_RAW_DB_ORDER_BY = {
    "adj_factor": ("ts_code",),
    "cyq_perf": ("ts_code",),
    "daily": ("ts_code",),
    "daily_basic": ("ts_code",),
    "dc_daily": ("ts_code",),
    "dc_hot": ("ts_code", "rank_time", "query_market", "query_hot_type", "query_is_new"),
    "dc_index": ("ts_code",),
    "dc_member": ("ts_code", "con_code"),
    "etf_basic": ("ts_code",),
    "etf_index": ("ts_code",),
    "fund_adj": ("ts_code",),
    "fund_daily": ("ts_code",),
    "index_daily_basic": ("ts_code",),
    "kpl_concept_cons": ("ts_code", "con_code"),
    "kpl_list": ("ts_code",),
    "limit_cpt_list": ("ts_code", "rank"),
    "limit_list_d": ("ts_code", "limit"),
    "limit_list_ths": ("ts_code", "limit_type"),
    "limit_step": ("ts_code", "nums"),
    "margin": ("exchange_id",),
    "moneyflow": ("ts_code",),
    "moneyflow_cnt_ths": ("ts_code",),
    "moneyflow_dc": ("ts_code",),
    "moneyflow_ind_dc": ("content_type", "ts_code"),
    "moneyflow_ind_ths": ("ts_code",),
    "moneyflow_mkt_dc": ("trade_date",),
    "moneyflow_ths": ("ts_code",),
    "stk_limit": ("ts_code",),
    "stock_st": ("ts_code", "type"),
    "suspend_d": ("ts_code", "suspend_type", "suspend_timing"),
    "ths_daily": ("ts_code",),
    "ths_index": ("ts_code",),
    "ths_hot": ("ts_code", "rank_time", "query_market", "query_is_new"),
    "ths_member": ("ts_code", "con_code"),
    "top_list": ("ts_code", "reason"),
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
    return build_prod_raw_trade_date_query(dataset_key="daily", trade_date=trade_date)


def build_daily_prod_raw_range_query(*, start_date: date, end_date: date) -> ProdRawQuery:
    return build_prod_raw_trade_date_range_query(dataset_key="daily", start_date=start_date, end_date=end_date)


def build_prod_raw_trade_date_query(*, dataset_key: str, trade_date: date) -> ProdRawQuery:
    table_name = _require_allowed_table(dataset_key)
    fields = _require_allowed_fields(dataset_key)
    projection = ", ".join(_render_projection_fields(dataset_key, fields))
    if "*" in projection:
        raise ValueError("prod-raw-db 查询禁止 select *。")
    order_by = _build_order_by(dataset_key, include_trade_date=False)
    return ProdRawQuery(
        sql=(
            f"select {projection} "
            f"from {table_name} "
            "where trade_date = %s "
            f"order by {order_by}"
        ),
        params=(trade_date,),
        table_name=table_name,
        fields=fields,
    )


def build_prod_raw_trade_date_range_query(*, dataset_key: str, start_date: date, end_date: date) -> ProdRawQuery:
    table_name = _require_allowed_table(dataset_key)
    fields = _require_allowed_fields(dataset_key)
    projection = ", ".join(_render_projection_fields(dataset_key, fields))
    if "*" in projection:
        raise ValueError("prod-raw-db 查询禁止 select *。")
    order_by = _build_order_by(dataset_key, include_trade_date=True)
    return ProdRawQuery(
        sql=(
            f"select {projection} "
            f"from {table_name} "
            "where trade_date >= %s and trade_date <= %s "
            f"order by {order_by}"
        ),
        params=(start_date, end_date),
        table_name=table_name,
        fields=fields,
    )


def build_prod_raw_current_query(*, dataset_key: str) -> ProdRawQuery:
    table_name = _require_allowed_table(dataset_key)
    fields = _require_allowed_fields(dataset_key)
    projection = ", ".join(_render_projection_fields(dataset_key, fields))
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


def _build_order_by(dataset_key: str, *, include_trade_date: bool) -> str:
    order_fields = PROD_RAW_DB_ORDER_BY.get(dataset_key)
    if not order_fields:
        raise ValueError(f"prod-raw-db 缺少排序字段定义：{dataset_key}")
    fields = list(order_fields)
    if include_trade_date and "trade_date" not in fields:
        fields = ["trade_date", *fields]
    return ", ".join(_render_sql_identifier(field) for field in fields)


def _render_projection_fields(dataset_key: str, fields: tuple[str, ...]) -> tuple[str, ...]:
    if dataset_key == "dc_hot":
        return tuple(_render_dc_hot_projection(field) for field in fields)
    if dataset_key == "ths_hot":
        return tuple(_render_ths_hot_projection(field) for field in fields)
    return tuple(_render_sql_identifier(field) for field in fields)


def _render_sql_identifier(field: str) -> str:
    if field == "limit":
        return '"limit"'
    if field == "desc":
        return '"desc"'
    if field == "leading":
        return '"leading"'
    return field


def _render_dc_hot_projection(field: str) -> str:
    if field == "market":
        return "query_market as market"
    if field == "hot_type":
        return "query_hot_type as hot_type"
    if field == "is_new":
        return "query_is_new as is_new"
    return _render_sql_identifier(field)


def _render_ths_hot_projection(field: str) -> str:
    if field == "market":
        return "query_market as market"
    if field == "is_new":
        return "query_is_new as is_new"
    return _render_sql_identifier(field)


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
