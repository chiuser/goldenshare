from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.ops.action_catalog import get_maintenance_action


BizProducerType = Literal["maintenance_action", "dagster_asset"]
BizObservationQueryKey = Literal[
    "direct_trade_date",
    "static_snapshot",
    "maintenance_task_trace",
    "sector_analysis_published_batch",
    "wealth_turnover_ready_snapshot",
]
BizFreshnessPolicyKey = Literal[
    "latest_completed_trade_day",
    "published_batch_trade_day",
    "static_snapshot_ready",
    "maintenance_task_trace",
    "wealth_turnover_snapshot",
]


@dataclass(frozen=True, slots=True)
class BizDatasetDefinition:
    dataset_key: str
    display_name: str
    description: str
    table_name: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    observation_query_key: BizObservationQueryKey
    freshness_policy_key: BizFreshnessPolicyKey
    business_date_column: str | None
    observed_at_column: str | None
    ready_after_local_time: str | None
    producer_type: BizProducerType
    producer_key: str


@dataclass(frozen=True, slots=True)
class BizDatasetLintIssue:
    dataset_key: str
    code: str
    message: str


BIZ_TABLE_SOURCE_KEY = "biz_tableset"
BIZ_TABLE_SOURCE_DISPLAY_NAME = "Biz数据集"

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_]+$")
_TABLE_NAME_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_LOCAL_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_CONTROL_TABLE = "core_serving.wealth_sector_analysis_publish_batch"
_QUERY_KEYS = {
    "direct_trade_date",
    "static_snapshot",
    "maintenance_task_trace",
    "sector_analysis_published_batch",
    "wealth_turnover_ready_snapshot",
}
_FRESHNESS_POLICIES = {
    "latest_completed_trade_day",
    "published_batch_trade_day",
    "static_snapshot_ready",
    "maintenance_task_trace",
    "wealth_turnover_snapshot",
}
_PRODUCER_TYPES = {"maintenance_action", "dagster_asset"}


def _definition(
    *,
    dataset_key: str,
    display_name: str,
    table_name: str,
    group_key: str,
    group_label: str,
    group_order: int,
    item_order: int,
    observation_query_key: BizObservationQueryKey,
    freshness_policy_key: BizFreshnessPolicyKey,
    business_date_column: str | None,
    observed_at_column: str | None,
    ready_after_local_time: str | None,
    producer_type: BizProducerType,
    producer_key: str,
) -> BizDatasetDefinition:
    return BizDatasetDefinition(
        dataset_key=dataset_key,
        display_name=display_name,
        description=f"{display_name}的运营状态与维护入口。",
        table_name=table_name,
        group_key=group_key,
        group_label=group_label,
        group_order=group_order,
        item_order=item_order,
        observation_query_key=observation_query_key,
        freshness_policy_key=freshness_policy_key,
        business_date_column=business_date_column,
        observed_at_column=observed_at_column,
        ready_after_local_time=ready_after_local_time,
        producer_type=producer_type,
        producer_key=producer_key,
    )


_SECTOR_ANALYSIS_PRODUCER = "maintenance.materialize_wealth_sector_analysis_daily"

BIZ_DATASET_DEFINITIONS: tuple[BizDatasetDefinition, ...] = (
    _definition(
        dataset_key="wealth_market_turnover_snapshot",
        display_name="成交额分钟快照",
        table_name="core_serving.wealth_market_turnover_snapshot",
        group_key="data_mart",
        group_label="数据集市",
        group_order=10,
        item_order=10,
        observation_query_key="wealth_turnover_ready_snapshot",
        freshness_policy_key="wealth_turnover_snapshot",
        business_date_column="trade_date",
        observed_at_column="built_at",
        ready_after_local_time="20:00",
        producer_type="dagster_asset",
        producer_key="prod_core_wealth_market_turnover",
    ),
    _definition(
        dataset_key="equity_daily_snapshot",
        display_name="股票日线数据集市快照",
        table_name="dm.equity_daily_snapshot",
        group_key="data_mart",
        group_label="数据集市",
        group_order=10,
        item_order=20,
        observation_query_key="maintenance_task_trace",
        freshness_policy_key="maintenance_task_trace",
        business_date_column=None,
        observed_at_column=None,
        ready_after_local_time=None,
        producer_type="maintenance_action",
        producer_key="maintenance.rebuild_dm",
    ),
    _definition(
        dataset_key="wealth_sector_hierarchy",
        display_name="板块层级",
        table_name="core_serving.wealth_sector_hierarchy",
        group_key="sector_analysis",
        group_label="板块分析",
        group_order=20,
        item_order=10,
        observation_query_key="static_snapshot",
        freshness_policy_key="static_snapshot_ready",
        business_date_column="code_reference_trade_date",
        observed_at_column="published_at",
        ready_after_local_time=None,
        producer_type="dagster_asset",
        producer_key="prod_core_wealth_sector_hierarchy",
    ),
    _definition(
        dataset_key="wealth_sector_heat_daily",
        display_name="每日板块热度",
        table_name="core_serving.wealth_sector_heat_daily",
        group_key="sector_analysis",
        group_label="板块分析",
        group_order=20,
        item_order=20,
        observation_query_key="direct_trade_date",
        freshness_policy_key="latest_completed_trade_day",
        business_date_column="trade_date",
        observed_at_column="calculated_at",
        ready_after_local_time="21:15",
        producer_type="maintenance_action",
        producer_key="maintenance.materialize_wealth_sector_heat_daily",
    ),
    *(
        _definition(
            dataset_key=dataset_key,
            display_name=display_name,
            table_name=f"core_serving.{dataset_key}",
            group_key="sector_analysis",
            group_label="板块分析",
            group_order=20,
            item_order=item_order,
            observation_query_key="sector_analysis_published_batch",
            freshness_policy_key="published_batch_trade_day",
            business_date_column="trade_date",
            observed_at_column="published_at",
            ready_after_local_time="20:05",
            producer_type="maintenance_action",
            producer_key=_SECTOR_ANALYSIS_PRODUCER,
        )
        for dataset_key, display_name, item_order in (
            ("wealth_sector_momentum_daily", "板块动量", 30),
            ("wealth_sector_dual_momentum_daily", "板块双动量", 40),
            ("wealth_sector_relative_rotation_daily", "板块相对轮动", 50),
            ("wealth_sector_member_breadth_daily", "板块成员涨跌广度", 60),
            ("wealth_sector_member_ma_breadth_daily", "板块成员均线广度", 70),
            ("wealth_sector_price_volume_daily", "板块价量分析", 80),
            ("wealth_sector_daily_insight_summary", "板块每日洞察汇总", 90),
            ("wealth_sector_daily_insight_item", "板块每日洞察明细", 100),
        )
    ),
    _definition(
        dataset_key="news_stock_link",
        display_name="新闻个股关联",
        table_name="core_serving.news_stock_link",
        group_key="content_relation",
        group_label="内容关联",
        group_order=30,
        item_order=10,
        observation_query_key="maintenance_task_trace",
        freshness_policy_key="maintenance_task_trace",
        business_date_column=None,
        observed_at_column=None,
        ready_after_local_time=None,
        producer_type="maintenance_action",
        producer_key="maintenance.materialize_news_stock_links",
    ),
    _definition(
        dataset_key="equity_qfq_nineturn_daily",
        display_name="股票日线前复权神奇九转",
        table_name="core_serving.equity_qfq_nineturn_daily",
        group_key="technical_indicators",
        group_label="技术指标",
        group_order=40,
        item_order=10,
        observation_query_key="direct_trade_date",
        freshness_policy_key="latest_completed_trade_day",
        business_date_column="trade_date",
        observed_at_column="published_at",
        ready_after_local_time="20:00",
        producer_type="dagster_asset",
        producer_key="prod_core_stock_daily_qfq_nineturn",
    ),
    _definition(
        dataset_key="index_nineturn_daily",
        display_name="指数日线神奇九转",
        table_name="core_serving.index_nineturn_daily",
        group_key="technical_indicators",
        group_label="技术指标",
        group_order=40,
        item_order=20,
        observation_query_key="direct_trade_date",
        freshness_policy_key="latest_completed_trade_day",
        business_date_column="trade_date",
        observed_at_column="published_at",
        ready_after_local_time="20:00",
        producer_type="dagster_asset",
        producer_key="prod_core_index_daily_nineturn",
    ),
)


def list_biz_dataset_definitions() -> tuple[BizDatasetDefinition, ...]:
    return BIZ_DATASET_DEFINITIONS


def get_biz_dataset_definition(dataset_key: str) -> BizDatasetDefinition:
    for definition in BIZ_DATASET_DEFINITIONS:
        if definition.dataset_key == dataset_key:
            return definition
    raise KeyError(f"unknown Biz dataset: {dataset_key}")


def lint_biz_dataset_definitions(
    definitions: tuple[BizDatasetDefinition, ...] | None = None,
) -> tuple[BizDatasetLintIssue, ...]:
    selected = definitions if definitions is not None else BIZ_DATASET_DEFINITIONS
    issues: list[BizDatasetLintIssue] = []
    seen_keys: set[str] = set()
    seen_tables: set[str] = set()

    def add(definition: BizDatasetDefinition, code: str, message: str) -> None:
        issues.append(BizDatasetLintIssue(definition.dataset_key, code, message))

    for definition in selected:
        if definition.dataset_key in seen_keys:
            add(definition, "duplicate_dataset_key", "dataset_key 必须唯一")
        seen_keys.add(definition.dataset_key)
        if definition.table_name in seen_tables:
            add(definition, "duplicate_table_name", "table_name 必须唯一")
        seen_tables.add(definition.table_name)

        for field_name, value in (
            ("dataset_key", definition.dataset_key),
            ("group_key", definition.group_key),
        ):
            if not _IDENTIFIER_PATTERN.fullmatch(value):
                add(definition, "invalid_identifier", f"{field_name} 不是合法标识符")
        for field_name, value in (
            ("business_date_column", definition.business_date_column),
            ("observed_at_column", definition.observed_at_column),
        ):
            if value is not None and not _IDENTIFIER_PATTERN.fullmatch(value):
                add(definition, "invalid_identifier", f"{field_name} 不是合法标识符")
        if not _TABLE_NAME_PATTERN.fullmatch(definition.table_name):
            add(definition, "invalid_table_name", "table_name 必须是 schema.table")
        if definition.observation_query_key not in _QUERY_KEYS:
            add(definition, "invalid_observation_query", "observation_query_key 未登记")
        if definition.freshness_policy_key not in _FRESHNESS_POLICIES:
            add(definition, "invalid_freshness_policy", "freshness_policy_key 未登记")
        if definition.producer_type not in _PRODUCER_TYPES:
            add(definition, "invalid_producer_type", "producer_type 未登记")

        if definition.freshness_policy_key in {
            "latest_completed_trade_day",
            "published_batch_trade_day",
            "wealth_turnover_snapshot",
        }:
            if definition.business_date_column is None:
                add(definition, "missing_business_date_column", "按交易日判迟必须声明日期列")
            if definition.ready_after_local_time is None or not _LOCAL_TIME_PATTERN.fullmatch(
                definition.ready_after_local_time
            ):
                add(definition, "invalid_ready_after_local_time", "按交易日判迟必须声明 HH:MM 时间")
        elif definition.freshness_policy_key == "static_snapshot_ready":
            if definition.business_date_column is None or definition.observed_at_column is None:
                add(definition, "invalid_static_snapshot", "静态快照必须声明日期列和发布时间列")
            if definition.ready_after_local_time is not None:
                add(definition, "invalid_static_snapshot", "静态快照不得声明判迟时间")
        elif definition.freshness_policy_key == "maintenance_task_trace":
            if any(
                value is not None
                for value in (
                    definition.business_date_column,
                    definition.observed_at_column,
                    definition.ready_after_local_time,
                )
            ):
                add(definition, "invalid_task_trace_columns", "任务轨迹策略不得声明业务表时间列")

        if definition.producer_type == "maintenance_action":
            action = get_maintenance_action(definition.producer_key)
            if action is None:
                add(definition, "missing_maintenance_action", "维护动作不存在")
            elif definition.table_name not in action.target_tables:
                add(definition, "maintenance_target_mismatch", "维护动作未绑定本定义目标表")
        elif not definition.producer_key.strip():
            add(definition, "missing_dagster_asset_key", "Dagster asset key 不能为空")

        if definition.table_name == _CONTROL_TABLE:
            add(definition, "control_table_visible", "发布控制表不得注册为用户可见卡片")

    return tuple(issues)
