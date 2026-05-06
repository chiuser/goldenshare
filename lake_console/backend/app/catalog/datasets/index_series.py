from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeCommandExample, LakeDatasetDefinition, LakeLayerDefinition
from lake_console.backend.app.catalog.tushare_index_series import INDEX_DAILY_BASIC_FIELDS, INDEX_DAILY_FIELDS


INDEX_SERIES_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    LakeDatasetDefinition(
        dataset_key="index_daily",
        display_name="指数日线行情",
        source="tushare",
        api_name="index_daily",
        source_doc_id="95",
        description="指数日线，按交易日分区落盘，第一阶段只支持 prod-core-db 只读导出。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/index_daily",
        group_key="index_market_data",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="源站事实",
                purpose="指数日线原始事实层，字段口径保持 Tushare index_daily。",
                layout="by_date",
                path="raw_tushare/index_daily",
                recommended_usage="指数横截面与日频行情研究。",
            ),
        ),
        command_examples=(
            LakeCommandExample(
                example_key="index_daily_prod_core_plan_trade_date",
                title="预览指数日线单日导出",
                scenario="plan",
                description="不请求 Tushare，从生产 core 只读预览一个交易日分区替换范围。",
                argv=("lake-console", "plan-sync", "index_daily", "--from", "prod-core-db", "--trade-date", "2026-04-30"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。",),
            ),
            LakeCommandExample(
                example_key="index_daily_prod_core_sync_trade_date",
                title="从生产 core 导出单日指数日线",
                scenario="sync_point",
                description="使用字段映射从 core_serving.index_daily_serving 只读导出，并替换本地 Lake 对应分区。",
                argv=("lake-console", "sync-dataset", "index_daily", "--from", "prod-core-db", "--trade-date", "2026-04-30"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_core_db_url。"),
            ),
            LakeCommandExample(
                example_key="index_daily_prod_core_sync_range",
                title="从生产 core 导出区间指数日线",
                scenario="sync_range",
                description="读取本地交易日历展开开市日，再按 trade_date 写本地分区。",
                argv=(
                    "lake-console",
                    "sync-dataset",
                    "index_daily",
                    "--from",
                    "prod-core-db",
                    "--start-date",
                    "2026-04-01",
                    "--end-date",
                    "2026-04-30",
                ),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_core_db_url。"),
            ),
        ),
    ),
    LakeDatasetDefinition(
        dataset_key="index_daily_basic",
        display_name="指数每日指标",
        source="tushare",
        api_name="index_dailybasic",
        source_doc_id="128",
        description="指数每日指标，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/index_daily_basic",
        group_key="index_market_data",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="源站事实",
                purpose="指数每日指标原始落盘层。",
                layout="by_date",
                path="raw_tushare/index_daily_basic",
                recommended_usage="指数估值、换手和规模指标研究。",
            ),
        ),
        command_examples=(
            LakeCommandExample(
                example_key="index_daily_basic_prod_raw_plan_trade_date",
                title="预览指数每日指标单日导出",
                scenario="plan",
                description="不请求 Tushare，只预览一个 trade_date 分区替换范围。",
                argv=("lake-console", "plan-sync", "index_daily_basic", "--from", "prod-raw-db", "--trade-date", "2026-04-30"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。",),
            ),
            LakeCommandExample(
                example_key="index_daily_basic_prod_raw_sync_trade_date",
                title="从生产 raw 导出单日指数每日指标",
                scenario="sync_point",
                description="使用字段白名单从 raw_tushare.index_daily_basic 只读导出，并替换本地 Lake 对应分区。",
                argv=("lake-console", "sync-dataset", "index_daily_basic", "--from", "prod-raw-db", "--trade-date", "2026-04-30"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
            ),
            LakeCommandExample(
                example_key="index_daily_basic_prod_raw_sync_range",
                title="从生产 raw 导出区间指数每日指标",
                scenario="sync_range",
                description="读取本地交易日历展开开市日，再按 trade_date 写本地分区。",
                argv=(
                    "lake-console",
                    "sync-dataset",
                    "index_daily_basic",
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
    "INDEX_DAILY_FIELDS",
    "INDEX_DAILY_BASIC_FIELDS",
    "INDEX_SERIES_DATASETS",
]
