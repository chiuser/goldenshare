from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeCommandExample, LakeDatasetDefinition, LakeLayerDefinition

MONEYFLOW_FIELDS: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "buy_sm_vol",
    "buy_sm_amount",
    "sell_sm_vol",
    "sell_sm_amount",
    "buy_md_vol",
    "buy_md_amount",
    "sell_md_vol",
    "sell_md_amount",
    "buy_lg_vol",
    "buy_lg_amount",
    "sell_lg_vol",
    "sell_lg_amount",
    "buy_elg_vol",
    "buy_elg_amount",
    "sell_elg_vol",
    "sell_elg_amount",
    "net_mf_vol",
    "net_mf_amount",
)

MONEYFLOW_VOLUME_FIELDS: tuple[str, ...] = (
    "buy_sm_vol",
    "sell_sm_vol",
    "buy_md_vol",
    "sell_md_vol",
    "buy_lg_vol",
    "sell_lg_vol",
    "buy_elg_vol",
    "sell_elg_vol",
    "net_mf_vol",
)


MONEYFLOW_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    LakeDatasetDefinition(
        dataset_key="moneyflow",
        display_name="个股资金流向",
        source="tushare",
        api_name="moneyflow",
        source_doc_id="170",
        description="Tushare 个股资金流向，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/moneyflow",
        group_key="moneyflow",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="源站事实",
                purpose="Tushare 个股资金流向原始落盘层。",
                layout="by_date",
                path="raw_tushare/moneyflow",
                recommended_usage="资金流向研究、单日全市场资金分布分析。",
            ),
        ),
        command_examples=(
            LakeCommandExample(
                example_key="moneyflow_plan_trade_date",
                title="预览单日同步",
                scenario="plan",
                description="不请求 Tushare，只看一个 trade_date 分区替换范围。",
                argv=("lake-console", "plan-sync", "moneyflow", "--trade-date", "2026-04-24"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT。",),
            ),
            LakeCommandExample(
                example_key="moneyflow_sync_trade_date",
                title="同步单日全市场资金流",
                scenario="sync_point",
                description="写入一个 trade_date 分区。",
                argv=("lake-console", "sync-dataset", "moneyflow", "--trade-date", "2026-04-24"),
                prerequisites=("已配置 GOLDENSHARE_LAKE_ROOT 和 TUSHARE_TOKEN。",),
            ),
            LakeCommandExample(
                example_key="moneyflow_sync_range",
                title="同步区间全市场资金流",
                scenario="sync_range",
                description="读取本地交易日历，只请求开市交易日。",
                argv=("lake-console", "sync-dataset", "moneyflow", "--start-date", "2026-04-01", "--end-date", "2026-04-30"),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT 和 TUSHARE_TOKEN。"),
            ),
            LakeCommandExample(
                example_key="moneyflow_sync_ts_code_range",
                title="同步单股区间资金流",
                scenario="sync_range",
                description="适合调试或单股研究。",
                argv=(
                    "lake-console",
                    "sync-dataset",
                    "moneyflow",
                    "--ts-code",
                    "600000.SH",
                    "--start-date",
                    "2026-04-01",
                    "--end-date",
                    "2026-04-30",
                ),
                prerequisites=("已同步本地交易日历。", "已配置 GOLDENSHARE_LAKE_ROOT 和 TUSHARE_TOKEN。"),
            ),
        ),
    ),
)
