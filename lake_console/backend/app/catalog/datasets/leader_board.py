from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeCommandExample, LakeDatasetDefinition, LakeLayerDefinition


LIMIT_LIST_D_FIELDS: tuple[str, ...] = (
    "trade_date",
    "ts_code",
    "industry",
    "name",
    "close",
    "pct_chg",
    "amount",
    "limit_amount",
    "float_mv",
    "total_mv",
    "turnover_ratio",
    "fd_amount",
    "first_time",
    "last_time",
    "open_times",
    "up_stat",
    "limit_times",
    "limit",
)

LIMIT_LIST_THS_FIELDS: tuple[str, ...] = (
    "trade_date",
    "ts_code",
    "name",
    "price",
    "pct_chg",
    "open_num",
    "lu_desc",
    "limit_type",
    "tag",
    "status",
    "first_lu_time",
    "last_lu_time",
    "first_ld_time",
    "last_ld_time",
    "limit_order",
    "limit_amount",
    "turnover_rate",
    "free_float",
    "lu_limit_order",
    "limit_up_suc_rate",
    "turnover",
    "rise_rate",
    "sum_float",
    "market_type",
)

LIMIT_STEP_FIELDS: tuple[str, ...] = (
    "ts_code",
    "name",
    "trade_date",
    "nums",
)

LIMIT_CPT_LIST_FIELDS: tuple[str, ...] = (
    "ts_code",
    "name",
    "trade_date",
    "days",
    "up_stat",
    "cons_nums",
    "up_nums",
    "pct_chg",
    "rank",
)

TOP_LIST_FIELDS: tuple[str, ...] = (
    "trade_date",
    "ts_code",
    "name",
    "close",
    "pct_change",
    "turnover_rate",
    "amount",
    "l_sell",
    "l_buy",
    "l_amount",
    "net_amount",
    "net_rate",
    "amount_rate",
    "float_values",
    "reason",
)


def _by_date_layers(*, dataset_key: str, purpose: str, recommended_usage: str) -> tuple[LakeLayerDefinition, ...]:
    return (
        LakeLayerDefinition(
            layer="raw_tushare",
            layer_name="源站事实",
            purpose=purpose,
            layout="by_date",
            path=f"raw_tushare/{dataset_key}",
            recommended_usage=recommended_usage,
        ),
    )


def _prod_raw_trade_date_examples(
    *,
    dataset_key: str,
    display_name: str,
    sample_trade_date: str,
    sample_start_date: str = "2026-04-01",
    sample_end_date: str = "2026-04-30",
) -> tuple[LakeCommandExample, ...]:
    return (
        LakeCommandExample(
            example_key=f"{dataset_key}_prod_raw_plan_trade_date",
            title=f"预览{display_name}单日导出",
            scenario="plan",
            description="不请求 Tushare，只预览一个 trade_date 分区替换范围。",
            argv=("lake-console", "plan-sync", dataset_key, "--from", "prod-raw-db", "--trade-date", sample_trade_date),
            prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。",),
        ),
        LakeCommandExample(
            example_key=f"{dataset_key}_prod_raw_sync_trade_date",
            title=f"从生产 raw 导出单日{display_name}",
            scenario="sync_point",
            description=f"使用字段白名单从 raw_tushare.{dataset_key if dataset_key != 'limit_list_d' else 'limit_list'} 只读导出，并替换本地 Lake 对应分区。",
            argv=("lake-console", "sync-dataset", dataset_key, "--from", "prod-raw-db", "--trade-date", sample_trade_date),
            prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
        ),
        LakeCommandExample(
            example_key=f"{dataset_key}_prod_raw_sync_range",
            title=f"从生产 raw 导出区间{display_name}",
            scenario="sync_range",
            description="读取本地交易日历展开开市日，再按 trade_date 写本地分区。",
            argv=(
                "lake-console",
                "sync-dataset",
                dataset_key,
                "--from",
                "prod-raw-db",
                "--start-date",
                sample_start_date,
                "--end-date",
                sample_end_date,
            ),
            prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
        ),
    )


LEADER_BOARD_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    LakeDatasetDefinition(
        dataset_key="limit_list_d",
        display_name="每日涨跌停名单",
        source="tushare",
        api_name="limit_list_d",
        source_doc_id="298",
        description="每日涨跌停、炸板数据，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/limit_list_d",
        group_key="limit_board",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=_by_date_layers(
            dataset_key="limit_list_d",
            purpose="Tushare 每日涨跌停、炸板数据原始落盘层。",
            recommended_usage="涨停池、炸板池与跌停池日频研究。",
        ),
        command_examples=_prod_raw_trade_date_examples(
            dataset_key="limit_list_d",
            display_name="每日涨跌停名单",
            sample_trade_date="2026-05-07",
        ),
    ),
    LakeDatasetDefinition(
        dataset_key="limit_list_ths",
        display_name="同花顺涨停名单",
        source="tushare",
        api_name="limit_list_ths",
        source_doc_id="355",
        description="同花顺每日涨跌停榜单，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/limit_list_ths",
        group_key="limit_board",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=_by_date_layers(
            dataset_key="limit_list_ths",
            purpose="Tushare 同花顺涨跌停榜单原始落盘层。",
            recommended_usage="同花顺涨停池、连板池与炸板池研究。",
        ),
        command_examples=_prod_raw_trade_date_examples(
            dataset_key="limit_list_ths",
            display_name="同花顺涨停名单",
            sample_trade_date="2026-04-30",
        ),
    ),
    LakeDatasetDefinition(
        dataset_key="limit_step",
        display_name="连板梯队",
        source="tushare",
        api_name="limit_step",
        source_doc_id="356",
        description="连板梯队，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/limit_step",
        group_key="limit_board",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=_by_date_layers(
            dataset_key="limit_step",
            purpose="Tushare 连板天梯原始落盘层。",
            recommended_usage="连板进阶统计与强势热度研究。",
        ),
        command_examples=_prod_raw_trade_date_examples(
            dataset_key="limit_step",
            display_name="连板梯队",
            sample_trade_date="2026-04-30",
            sample_start_date="2026-01-05",
            sample_end_date="2026-04-30",
        ),
    ),
    LakeDatasetDefinition(
        dataset_key="limit_cpt_list",
        display_name="涨停概念列表",
        source="tushare",
        api_name="limit_cpt_list",
        source_doc_id="357",
        description="最强板块统计，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/limit_cpt_list",
        group_key="limit_board",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=_by_date_layers(
            dataset_key="limit_cpt_list",
            purpose="Tushare 最强板块统计原始落盘层。",
            recommended_usage="强势板块轮动与板块热度研究。",
        ),
        command_examples=_prod_raw_trade_date_examples(
            dataset_key="limit_cpt_list",
            display_name="涨停概念列表",
            sample_trade_date="2026-04-30",
            sample_start_date="2026-01-05",
            sample_end_date="2026-04-30",
        ),
    ),
    LakeDatasetDefinition(
        dataset_key="top_list",
        display_name="龙虎榜",
        source="tushare",
        api_name="top_list",
        source_doc_id="106",
        description="龙虎榜每日明细，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/top_list",
        group_key="leader_board",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=_by_date_layers(
            dataset_key="top_list",
            purpose="Tushare 龙虎榜每日明细原始落盘层。",
            recommended_usage="龙虎榜上榜统计与席位活跃度日频研究。",
        ),
        command_examples=_prod_raw_trade_date_examples(
            dataset_key="top_list",
            display_name="龙虎榜",
            sample_trade_date="2026-05-07",
            sample_start_date="2026-04-01",
            sample_end_date="2026-04-30",
        ),
    ),
)


__all__ = [
    "LEADER_BOARD_DATASETS",
    "LIMIT_CPT_LIST_FIELDS",
    "LIMIT_LIST_D_FIELDS",
    "LIMIT_LIST_THS_FIELDS",
    "LIMIT_STEP_FIELDS",
    "TOP_LIST_FIELDS",
]
