from __future__ import annotations

import ast
import inspect
from datetime import datetime
from pathlib import Path

from src.foundation.dao.factory import DAOFactory
from src.operations.specs.registry import DATASET_FRESHNESS_METADATA, JOB_SPEC_REGISTRY
from src.foundation.services.sync.registry import SYNC_SERVICE_REGISTRY


OUTPUT_PATH = Path("docs/dataset-catalog.md")


FIELD_GLOSSARY = [
    ("ts_code", "证券代码"),
    ("name", "证券或板块名称"),
    ("trade_date", "交易日期（YYYY-MM-DD）"),
    ("ann_date", "公告日期"),
    ("end_date", "报告期或统计截止日期"),
    ("open/high/low/close", "OHLC 价格"),
    ("pre_close", "前收盘价"),
    ("change_amount", "涨跌额"),
    ("pct_chg", "涨跌幅（百分比）"),
    ("vol", "成交量"),
    ("amount", "成交额"),
    ("rank", "榜单排名"),
    ("source", "数据来源标记（如 api / derived_daily）"),
    ("query_*", "请求上下文参数快照，用于重放与溯源"),
    ("created_at/updated_at", "系统写入与更新时间"),
]

FIELD_MEANING_MAP = {
    "id": "系统代理主键",
    "ts_code": "证券代码（含股票/指数/板块等代码）",
    "symbol": "交易代码短码",
    "name": "名称",
    "industry": "行业分类",
    "area": "地区",
    "market": "市场类型",
    "exchange": "交易所",
    "list_status": "上市状态",
    "list_date": "上市日期",
    "delist_date": "退市日期",
    "trade_date": "交易日",
    "ann_date": "公告日",
    "end_date": "报告期/统计截止日期",
    "start_date": "开始日期（请求参数语义）",
    "pay_date": "派息日",
    "record_date": "股权登记日",
    "ex_date": "除权除息日",
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "close": "收盘价",
    "pre_close": "昨收价",
    "change": "涨跌额（上游原始字段）",
    "change_amount": "涨跌额（系统标准字段）",
    "pct_change": "涨跌幅（上游原始字段）",
    "pct_chg": "涨跌幅（系统标准字段）",
    "vol": "成交量",
    "amount": "成交额",
    "turnover_rate": "换手率",
    "total_mv": "总市值",
    "float_mv": "流通市值",
    "adj_factor": "复权因子",
    "rank": "排名",
    "rank_time": "榜单时间戳",
    "hot": "热度值",
    "concept": "所属概念",
    "rank_reason": "上榜原因",
    "idx_type": "板块类型",
    "index_code": "指数代码",
    "con_code": "成分代码",
    "weight": "权重",
    "is_open": "是否开市",
    "cal_date": "日历日期",
    "source": "数据来源标识（如 api / derived_daily）",
    "query_market": "请求上下文：market",
    "query_hot_type": "请求上下文：hot_type",
    "query_is_new": "请求上下文：is_new",
    "row_key_hash": "记录级哈希键（去重与幂等）",
    "event_key_hash": "事件级哈希键（事件聚合）",
    "created_at": "创建时间（系统写入）",
    "updated_at": "更新时间（系统写入）",
    "raw_payload": "原始响应载荷",
    "fetched_at": "抓取时间",
}


def _infer_api_name_from_source(service_cls) -> str | None:  # type: ignore[no-untyped-def]
    try:
        source = inspect.getsource(service_cls)
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "call":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def _raw_dao_name(resource: str, service_cls) -> str | None:  # type: ignore[no-untyped-def]
    value = getattr(service_cls, "raw_dao_name", None)
    if value:
        return str(value)
    candidate = f"raw_{resource}"
    return candidate


def _core_dao_name(service_cls) -> str | None:  # type: ignore[no-untyped-def]
    value = getattr(service_cls, "core_dao_name", None)
    if value:
        return str(value)
    return None


def _dao_to_table(factory: DAOFactory, dao_name: str | None) -> str | None:
    if not dao_name or not hasattr(factory, dao_name):
        return None
    dao = getattr(factory, dao_name)
    model = getattr(dao, "model", None)
    if model is None:
        return None
    return model.__table__.fullname


def _table_columns(factory: DAOFactory, dao_name: str | None) -> list[str]:
    if not dao_name or not hasattr(factory, dao_name):
        return []
    dao = getattr(factory, dao_name)
    model = getattr(dao, "model", None)
    if model is None:
        return []
    return [column.name for column in model.__table__.columns]


def _job_keys_for_resource(resource: str) -> list[str]:
    keys = []
    for key in JOB_SPEC_REGISTRY:
        if key.endswith(f".{resource}"):
            keys.append(key)
    return sorted(keys)


def _resource_row(resource: str, service_cls, factory: DAOFactory) -> dict[str, str]:  # type: ignore[no-untyped-def]
    raw_dao_name = _raw_dao_name(resource, service_cls)
    core_dao_name = _core_dao_name(service_cls)
    api_name = getattr(service_cls, "api_name", None) or _infer_api_name_from_source(service_cls) or "-"
    target_table = getattr(service_cls, "target_table", "-")
    fields = list(getattr(service_cls, "fields", []) or [])
    jobs = _job_keys_for_resource(resource)
    freshness = DATASET_FRESHNESS_METADATA.get(resource)
    observed_date_column = freshness[4] if freshness else "-"

    raw_table = _dao_to_table(factory, raw_dao_name) or "-"
    core_table = _dao_to_table(factory, core_dao_name) or target_table
    if core_table is None:
        core_table = "-"

    return {
        "resource": resource,
        "api_name": str(api_name),
        "raw_dao_name": raw_dao_name or "-",
        "core_dao_name": core_dao_name or "-",
        "raw_table": raw_table,
        "core_table": str(core_table),
        "field_count": str(len(fields)),
        "fields": ", ".join(fields) if fields else "-",
        "observed_date_column": observed_date_column,
        "jobs": ", ".join(jobs) if jobs else "-",
        "raw_columns": ", ".join(_table_columns(factory, raw_dao_name)) or "-",
        "core_columns": ", ".join(_table_columns(factory, core_dao_name)) or "-",
    }


def _field_meaning(field_name: str) -> str:
    if field_name in FIELD_MEANING_MAP:
        return FIELD_MEANING_MAP[field_name]
    if field_name.startswith("query_"):
        return "请求上下文字段"
    if field_name.endswith("_date"):
        return "日期字段（具体语义以接口文档为准）"
    if field_name.endswith("_time"):
        return "时间字段（具体语义以接口文档为准）"
    if field_name.endswith("_code"):
        return "代码字段（具体语义以接口文档为准）"
    return "上游原始字段，语义请参照对应接口文档"


def _render_field_dict(columns_text: str) -> list[str]:
    if columns_text == "-" or not columns_text.strip():
        return ["- 无"]
    columns = [item.strip() for item in columns_text.split(",") if item.strip()]
    return [f"- `{name}`: {_field_meaning(name)}" for name in columns]


def generate_markdown() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resources = sorted(SYNC_SERVICE_REGISTRY.items(), key=lambda item: item[0])
    factory = DAOFactory(None)
    rows = [_resource_row(resource, service_cls, factory) for resource, service_cls in resources]

    lines: list[str] = []
    lines.append("# 数据集能力与字段说明（自动生成）")
    lines.append("")
    lines.append(f"- 生成时间: `{now}`")
    lines.append("- 数据来源: `SYNC_SERVICE_REGISTRY`、`DAOFactory`、`JOB_SPEC_REGISTRY`")
    lines.append("- 适用范围: 现有可同步数据集（raw/core 主链路）")
    lines.append("")
    lines.append("## 字段语义约定（通用）")
    lines.append("")
    for field_name, description in FIELD_GLOSSARY:
        lines.append(f"- `{field_name}`: {description}")
    lines.append("")
    lines.append("## 数据集总览")
    lines.append("")
    lines.append("| resource | api_name | raw_table | core_table | 显式fields数 | 观测日期字段 | 支持任务 |")
    lines.append("| --- | --- | --- | --- | ---: | --- | --- |")
    for row in rows:
        lines.append(
            f"| `{row['resource']}` | `{row['api_name']}` | `{row['raw_table']}` | "
            f"`{row['core_table']}` | {row['field_count']} | `{row['observed_date_column']}` | {row['jobs']} |"
        )
    lines.append("")
    lines.append("## 分数据集详细说明")
    lines.append("")
    for row in rows:
        lines.append(f"### `{row['resource']}`")
        lines.append("")
        lines.append(f"- API: `{row['api_name']}`")
        lines.append(f"- Raw 表: `{row['raw_table']}`（DAO: `{row['raw_dao_name']}`）")
        lines.append(f"- Core 表: `{row['core_table']}`（DAO: `{row['core_dao_name']}`）")
        lines.append(f"- 显式请求 fields（{row['field_count']}）: {row['fields']}")
        lines.append(f"- 支持任务: {row['jobs']}")
        lines.append("- Raw 字段释义:")
        lines.extend(_render_field_dict(row["raw_columns"]))
        lines.append("- Core 字段释义:")
        lines.extend(_render_field_dict(row["core_columns"]))
        lines.append("")
    lines.append("## 维护方式")
    lines.append("")
    lines.append("每次新增或改动数据集后，执行：")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/generate_dataset_catalog.py")
    lines.append("```")
    lines.append("")
    lines.append("然后提交更新后的 `docs/dataset-catalog.md`。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    markdown = generate_markdown()
    OUTPUT_PATH.write_text(markdown, encoding="utf-8")
    print(f"generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
