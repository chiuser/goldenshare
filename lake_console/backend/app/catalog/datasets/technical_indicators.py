from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeCommandExample, LakeDatasetDefinition, LakeLayerDefinition


CYQ_PERF_FIELDS: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "his_low",
    "his_high",
    "cost_5pct",
    "cost_15pct",
    "cost_50pct",
    "cost_85pct",
    "cost_95pct",
    "weight_avg",
    "winner_rate",
)


TECHNICAL_INDICATOR_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    LakeDatasetDefinition(
        dataset_key="cyq_perf",
        display_name="每日筹码及胜率",
        source="tushare",
        api_name="cyq_perf",
        source_doc_id="293",
        description="每日筹码及胜率，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/cyq_perf",
        group_key="technical_indicators",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="源站事实",
                purpose="Tushare 每日筹码及胜率原始落盘层。",
                layout="by_date",
                path="raw_tushare/cyq_perf",
                recommended_usage="筹码分布、平均成本与胜率日频研究。",
            ),
        ),
        command_examples=(
            LakeCommandExample(
                example_key="cyq_perf_prod_raw_plan_trade_date",
                title="预览筹码及胜率单日导出",
                scenario="plan",
                description="不请求 Tushare，只预览一个 trade_date 分区替换范围。",
                argv=("lake-console", "plan-sync", "cyq_perf", "--from", "prod-raw-db", "--trade-date", "2026-05-07"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。",),
            ),
            LakeCommandExample(
                example_key="cyq_perf_prod_raw_sync_trade_date",
                title="从生产 raw 导出单日筹码及胜率",
                scenario="sync_point",
                description="使用字段白名单从 raw_tushare.cyq_perf 只读导出，并替换本地 Lake 对应分区。",
                argv=("lake-console", "sync-dataset", "cyq_perf", "--from", "prod-raw-db", "--trade-date", "2026-05-07"),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT。", "已配置只读 prod_raw_db_url。"),
            ),
            LakeCommandExample(
                example_key="cyq_perf_prod_raw_sync_range",
                title="从生产 raw 导出区间筹码及胜率",
                scenario="sync_range",
                description="读取本地交易日历展开开市日，再按 trade_date 写本地分区。",
                argv=(
                    "lake-console",
                    "sync-dataset",
                    "cyq_perf",
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


__all__ = ["CYQ_PERF_FIELDS", "TECHNICAL_INDICATOR_DATASETS"]
