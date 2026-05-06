from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeCommandExample, LakeDatasetDefinition, LakeLayerDefinition


FUND_DAILY_FIELDS: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)

FUND_ADJ_FIELDS: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "adj_factor",
)


MARKET_FUND_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    LakeDatasetDefinition(
        dataset_key="fund_daily",
        display_name="基金日线行情",
        source="tushare",
        api_name="fund_daily",
        source_doc_id="127",
        description="基金日线行情，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/fund_daily",
        group_key="etf_fund",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="源站事实",
                purpose="Tushare 基金日线原始落盘层。",
                layout="by_date",
                path="raw_tushare/fund_daily",
                recommended_usage="ETF / 基金日频行情研究。",
            ),
        ),
        command_examples=(
            LakeCommandExample(
                example_key="fund_daily_prod_raw_plan_trade_date",
                title="预览基金日线单日导出",
                scenario="plan",
                description="不请求 Tushare，只预览一个 trade_date 分区替换范围。",
                argv=("lake-console", "plan-sync", "fund_daily", "--from", "prod-raw-db", "--trade-date", "2026-04-30"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。",),
            ),
            LakeCommandExample(
                example_key="fund_daily_prod_raw_sync_trade_date",
                title="从生产 raw 导出单日基金日线",
                scenario="sync_point",
                description="使用字段白名单从 raw_tushare.fund_daily 只读导出，并替换本地 Lake 对应分区。",
                argv=("lake-console", "sync-dataset", "fund_daily", "--from", "prod-raw-db", "--trade-date", "2026-04-30"),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
            ),
            LakeCommandExample(
                example_key="fund_daily_prod_raw_sync_range",
                title="从生产 raw 导出区间基金日线",
                scenario="sync_range",
                description="读取本地交易日历展开开市日，再按 trade_date 写本地分区。",
                argv=(
                    "lake-console",
                    "sync-dataset",
                    "fund_daily",
                    "--from",
                    "prod-raw-db",
                    "--start-date",
                    "2026-04-01",
                    "--end-date",
                    "2026-04-30",
                ),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
            ),
        ),
    ),
    LakeDatasetDefinition(
        dataset_key="fund_adj",
        display_name="基金复权因子",
        source="tushare",
        api_name="fund_adj",
        source_doc_id="199",
        description="基金复权因子，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/fund_adj",
        group_key="etf_fund",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="源站事实",
                purpose="Tushare 基金复权因子原始落盘层。",
                layout="by_date",
                path="raw_tushare/fund_adj",
                recommended_usage="ETF / 基金复权价格恢复与研究。",
            ),
        ),
        command_examples=(
            LakeCommandExample(
                example_key="fund_adj_prod_raw_plan_trade_date",
                title="预览基金复权因子单日导出",
                scenario="plan",
                description="不请求 Tushare，只预览一个 trade_date 分区替换范围。",
                argv=("lake-console", "plan-sync", "fund_adj", "--from", "prod-raw-db", "--trade-date", "2026-04-30"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。",),
            ),
            LakeCommandExample(
                example_key="fund_adj_prod_raw_sync_trade_date",
                title="从生产 raw 导出单日基金复权因子",
                scenario="sync_point",
                description="使用字段白名单从 raw_tushare.fund_adj 只读导出，并替换本地 Lake 对应分区。",
                argv=("lake-console", "sync-dataset", "fund_adj", "--from", "prod-raw-db", "--trade-date", "2026-04-30"),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
            ),
            LakeCommandExample(
                example_key="fund_adj_prod_raw_sync_range",
                title="从生产 raw 导出区间基金复权因子",
                scenario="sync_range",
                description="读取本地交易日历展开开市日，再按 trade_date 写本地分区。",
                argv=(
                    "lake-console",
                    "sync-dataset",
                    "fund_adj",
                    "--from",
                    "prod-raw-db",
                    "--start-date",
                    "2026-04-01",
                    "--end-date",
                    "2026-04-30",
                ),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
            ),
        ),
    ),
)


__all__ = [
    "FUND_ADJ_FIELDS",
    "FUND_DAILY_FIELDS",
    "MARKET_FUND_DATASETS",
]
