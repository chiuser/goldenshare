from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.dao.factory import DAOFactory
from src.operations.specs.registry import DATASET_FRESHNESS_METADATA, JOB_SPEC_REGISTRY
from src.services.sync.registry import SYNC_SERVICE_REGISTRY


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
    api_name = getattr(service_cls, "api_name", "-")
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
        lines.append(f"- Raw 字段: {row['raw_columns']}")
        lines.append(f"- Core 字段: {row['core_columns']}")
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
