from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


PROD_RAW_EVENT_DATE_SOURCE = "prod-raw-db"
PROD_RAW_EVENT_DATE_SYSTEM_FIELDS = {"id", "row_key_hash", "api_name", "fetched_at", "raw_payload"}


@dataclass(frozen=True)
class EventDateDatasetSpec:
    dataset_key: str
    display_name: str
    table_name: str
    source_date_field: str
    fields: tuple[str, ...]
    order_by: tuple[str, ...]
    block_on_any_null_source_date: bool = False


@dataclass(frozen=True)
class EventDatePartitionCount:
    event_date: date
    source_row_count: int


@dataclass(frozen=True)
class EventDateQuery:
    sql: str
    params: tuple[Any, ...]
    table_name: str
    fields: tuple[str, ...]


class ProdRawEventDateConfigError(RuntimeError):
    pass


PROD_RAW_EVENT_DATE_DATASET_SPECS: dict[str, EventDateDatasetSpec] = {
    "anns_d": EventDateDatasetSpec(
        dataset_key="anns_d",
        display_name="上市公司公告",
        table_name="raw_tushare.anns_d",
        source_date_field="ann_date",
        fields=("ann_date", "ts_code", "name", "title", "url", "rec_time"),
        order_by=("ann_date", "ts_code", "rec_time", "url"),
    ),
    "irm_qa_sh": EventDateDatasetSpec(
        dataset_key="irm_qa_sh",
        display_name="上证E互动问答",
        table_name="raw_tushare.irm_qa_sh",
        source_date_field="trade_date",
        fields=("ts_code", "name", "trade_date", "q", "a", "pub_time"),
        order_by=("trade_date", "ts_code", "pub_time", "q"),
    ),
    "irm_qa_sz": EventDateDatasetSpec(
        dataset_key="irm_qa_sz",
        display_name="深证互动易问答",
        table_name="raw_tushare.irm_qa_sz",
        source_date_field="trade_date",
        fields=("ts_code", "name", "trade_date", "q", "a", "pub_time", "industry"),
        order_by=("trade_date", "ts_code", "pub_time", "q"),
    ),
    "research_report": EventDateDatasetSpec(
        dataset_key="research_report",
        display_name="券商研究报告",
        table_name="raw_tushare.research_report",
        source_date_field="trade_date",
        fields=(
            "report_code",
            "trade_date",
            "abstr",
            "title",
            "report_type",
            "author",
            "name",
            "ts_code",
            "inst_csname",
            "ind_name",
            "url",
        ),
        order_by=("trade_date", "report_code", "ts_code", "url"),
        block_on_any_null_source_date=True,
    ),
}


def list_event_date_dataset_keys() -> tuple[str, ...]:
    return tuple(PROD_RAW_EVENT_DATE_DATASET_SPECS)


def get_event_date_dataset_spec(dataset_key: str) -> EventDateDatasetSpec:
    spec = PROD_RAW_EVENT_DATE_DATASET_SPECS.get(dataset_key)
    if spec is None:
        allowed = ", ".join(sorted(PROD_RAW_EVENT_DATE_DATASET_SPECS))
        raise ValueError(f"prod-db-event-date 只允许数据集：{allowed}")
    _assert_spec_is_safe(spec)
    return spec


def build_event_date_partition_counts_query(
    *,
    dataset_key: str,
    start_date: date,
    end_date: date,
) -> EventDateQuery:
    if end_date < start_date:
        raise ValueError("event-date end_date 不能早于 start_date。")
    spec = get_event_date_dataset_spec(dataset_key)
    date_field = _render_sql_identifier(spec.source_date_field)
    return EventDateQuery(
        sql=(
            f"select {date_field} as event_date, count(*) as source_row_count "
            f"from {spec.table_name} "
            f"where {date_field} >= %s and {date_field} <= %s "
            f"group by {date_field} "
            f"order by {date_field}"
        ),
        params=(start_date, end_date),
        table_name=spec.table_name,
        fields=("event_date", "source_row_count"),
    )


def build_event_date_null_count_query(*, dataset_key: str) -> EventDateQuery:
    spec = get_event_date_dataset_spec(dataset_key)
    date_field = _render_sql_identifier(spec.source_date_field)
    return EventDateQuery(
        sql=(
            f"select count(*) as null_date_count "
            f"from {spec.table_name} "
            f"where {date_field} is null"
        ),
        params=(),
        table_name=spec.table_name,
        fields=("null_date_count",),
    )


def build_event_date_detail_query(*, dataset_key: str, event_date: date) -> EventDateQuery:
    spec = get_event_date_dataset_spec(dataset_key)
    projection = ", ".join(_render_sql_identifier(field) for field in spec.fields)
    order_by = ", ".join(_render_sql_identifier(field) for field in spec.order_by)
    if "*" in projection:
        raise ValueError("prod-db-event-date 查询禁止 select *。")
    date_field = _render_sql_identifier(spec.source_date_field)
    return EventDateQuery(
        sql=(
            f"select {projection} "
            f"from {spec.table_name} "
            f"where {date_field} = %s "
            f"order by {order_by}"
        ),
        params=(event_date,),
        table_name=spec.table_name,
        fields=spec.fields,
    )


def fetch_event_date_partition_counts(
    *,
    database_url: str | None,
    dataset_key: str,
    start_date: date,
    end_date: date,
) -> list[EventDatePartitionCount]:
    query = build_event_date_partition_counts_query(dataset_key=dataset_key, start_date=start_date, end_date=end_date)
    rows = _fetch_rows(database_url=database_url, query=query)
    return [
        EventDatePartitionCount(
            event_date=_parse_event_date(row.get("event_date")),
            source_row_count=int(row.get("source_row_count") or 0),
        )
        for row in rows
    ]


def fetch_event_date_null_count(*, database_url: str | None, dataset_key: str) -> int:
    query = build_event_date_null_count_query(dataset_key=dataset_key)
    rows = _fetch_rows(database_url=database_url, query=query)
    if not rows:
        return 0
    return int(rows[0].get("null_date_count") or 0)


def fetch_event_date_rows(*, database_url: str | None, dataset_key: str, event_date: date) -> list[dict[str, Any]]:
    query = build_event_date_detail_query(dataset_key=dataset_key, event_date=event_date)
    return _fetch_rows(database_url=database_url, query=query)


def iter_event_date_rows(
    *,
    database_url: str | None,
    dataset_key: str,
    event_date: date,
    batch_size: int = 20000,
    cursor_name: str = "lake_prod_raw_event_date_cursor",
) -> Iterator[list[dict[str, Any]]]:
    if batch_size <= 0:
        raise ValueError("prod-db-event-date batch_size 必须大于 0。")
    query = build_event_date_detail_query(dataset_key=dataset_key, event_date=event_date)
    yield from _iter_rows(database_url=database_url, query=query, batch_size=batch_size, cursor_name=cursor_name)


def _fetch_rows(*, database_url: str | None, query: EventDateQuery) -> list[dict[str, Any]]:
    if not database_url:
        raise ProdRawEventDateConfigError(
            "缺少 GOLDENSHARE_PROD_RAW_DB_URL，不能生成 prod_db_event_date 只读预检计划。"
        )
    _assert_query_is_safe(query)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise ProdRawEventDateConfigError("缺少 psycopg，请先安装 lake_console/backend/requirements.txt。") from exc

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("set transaction read only")
            with connection.cursor() as cursor:
                cursor.execute(query.sql, query.params)
                return [dict(row) for row in cursor.fetchall()]


def _iter_rows(
    *,
    database_url: str | None,
    query: EventDateQuery,
    batch_size: int,
    cursor_name: str,
) -> Iterator[list[dict[str, Any]]]:
    if not database_url:
        raise ProdRawEventDateConfigError(
            "缺少 GOLDENSHARE_PROD_RAW_DB_URL，不能执行 prod_db_event_date 只读明细拉取。"
        )
    _assert_query_is_safe(query)
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise ProdRawEventDateConfigError("缺少 psycopg，请先安装 lake_console/backend/requirements.txt。") from exc

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


def _assert_spec_is_safe(spec: EventDateDatasetSpec) -> None:
    schema_name, _, relation_name = spec.table_name.partition(".")
    if schema_name != "raw_tushare" or not relation_name:
        raise ValueError(f"prod-db-event-date 表白名单配置非法：{spec.table_name}")
    blocked = sorted(set(spec.fields) & PROD_RAW_EVENT_DATE_SYSTEM_FIELDS)
    if blocked:
        raise ValueError(f"prod-db-event-date 字段白名单包含生产系统字段：{blocked}")
    if any(field.strip() == "*" for field in spec.fields):
        raise ValueError("prod-db-event-date 字段白名单禁止星号。")
    for field in (*spec.fields, *spec.order_by, spec.source_date_field):
        _render_sql_identifier(field)


def _assert_query_is_safe(query: EventDateQuery) -> None:
    normalized_sql = " ".join(query.sql.lower().split())
    allowed_tables = {spec.table_name for spec in PROD_RAW_EVENT_DATE_DATASET_SPECS.values()}
    if "select *" in normalized_sql:
        raise ValueError("prod-db-event-date 查询禁止 select *。")
    if query.table_name not in allowed_tables:
        raise ValueError(f"prod-db-event-date 查询表不在白名单：{query.table_name}")
    if not query.table_name.startswith("raw_tushare."):
        raise ValueError(f"prod-db-event-date 查询只能访问 raw_tushare schema：{query.table_name}")
    if any(
        blocked in normalized_sql
        for blocked in (" ops.", " core.", " core_serving.", " core_serving_light.", " biz.", " app.", " platform.")
    ):
        raise ValueError("prod-db-event-date 查询禁止访问非 raw_tushare schema。")


def _render_sql_identifier(field: str) -> str:
    if not field or not field.replace("_", "").isalnum() or field[0].isdigit():
        raise ValueError(f"非法 SQL 字段名：{field!r}")
    return field


def _parse_event_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if len(normalized) == 8 and normalized.isdigit():
            return date.fromisoformat(f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}")
        return date.fromisoformat(normalized)
    raise ValueError(f"event_date 不可解析：{value!r}")
