from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeDatasetDefinition, LakeLayerDefinition

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
    ),
)
