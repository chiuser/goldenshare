from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeDatasetDefinition, LakeLayerDefinition


MARKET_EQUITY_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    LakeDatasetDefinition(
        dataset_key="daily",
        display_name="股票日线",
        source="tushare",
        api_name="daily",
        source_doc_id="27",
        description="A股日线行情，按交易日分区落盘。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/daily",
        group_key="equity_market",
        primary_layout="by_date",
        available_layouts=("by_date",),
        write_policy="replace_partition",
        update_mode="manual_cli",
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="源站事实",
                purpose="Tushare 日线行情原始落盘层。",
                layout="by_date",
                path="raw_tushare/daily",
                recommended_usage="单日全市场横截面、行情研究基础数据。",
            ),
        ),
    ),
    LakeDatasetDefinition(
        dataset_key="stk_mins",
        display_name="股票历史分钟行情",
        source="tushare",
        api_name="stk_mins",
        source_doc_id="370",
        description="A股分钟线，包含原始层、派生层和研究重排层。",
        dataset_role="raw_dataset",
        storage_root="raw_tushare/stk_mins_by_date",
        group_key="equity_market",
        primary_layout="by_date",
        available_layouts=("by_date", "by_symbol_month"),
        write_policy="replace_partition",
        update_mode="manual_cli",
        supported_freqs=(1, 5, 15, 30, 60, 90, 120),
        raw_freqs=(1, 5, 15, 30, 60),
        derived_freqs=(90, 120),
        layers=(
            LakeLayerDefinition(
                layer="raw_tushare",
                layer_name="原始分钟线",
                purpose="Tushare 原始分钟线。",
                layout="by_date",
                path="raw_tushare/stk_mins_by_date",
                recommended_usage="单日全市场排名、横截面统计、派生计算来源。",
            ),
            LakeLayerDefinition(
                layer="derived",
                layer_name="派生分钟线",
                purpose="本地计算得到的 90/120 分钟线。",
                layout="by_date",
                path="derived/stk_mins_by_date",
                recommended_usage="本地派生周期分析。",
            ),
            LakeLayerDefinition(
                layer="research",
                layer_name="研究重排",
                purpose="按股票和月份重排后的查询优化层。",
                layout="by_symbol_month",
                path="research/stk_mins_by_symbol_month",
                recommended_usage="单股长周期回测、少数股票多月相似性分析。",
            ),
        ),
    ),
)
