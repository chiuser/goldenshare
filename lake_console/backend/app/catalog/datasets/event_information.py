from __future__ import annotations

from lake_console.backend.app.catalog.models import LakeDatasetDefinition, LakeNodeDefinition


def _event_date_dataset(*, dataset_key: str, display_name: str, description: str) -> LakeDatasetDefinition:
    return LakeDatasetDefinition(
        dataset_key=dataset_key,
        display_name=display_name,
        source="prod-raw-db",
        api_name=dataset_key,
        source_doc_id=f"tushare.{dataset_key}",
        description=description,
        dataset_role="raw_dataset",
        storage_root=f"raw_tushare/{dataset_key}",
        group_key="news",
        primary_layout="by_event_date",
        available_layouts=("by_event_date",),
        write_policy="replace_partition",
        update_mode="manual_sync_center",
        nodes=(
            LakeNodeDefinition(
                layer="raw_tushare",
                node_key="raw_by_event_date",
                node_name="原始事件日期分区",
                description="从生产 raw_tushare 只读导出的事件日期分区事实。",
                scan_profile="event_date",
                path=f"raw_tushare/{dataset_key}",
                recommended_usage="用于按事件日期裁剪查询；不代表交易日或连续自然日完整性。",
                partition_dimensions=("event_date",),
            ),
        ),
    )


EVENT_INFORMATION_DATASETS: tuple[LakeDatasetDefinition, ...] = (
    _event_date_dataset(
        dataset_key="anns_d",
        display_name="上市公司公告",
        description="上市公司全量公告，Lake 按公告事件日期 event_date 分区。",
    ),
    _event_date_dataset(
        dataset_key="irm_qa_sh",
        display_name="上证E互动问答",
        description="上证E互动问答，Lake 按源表 trade_date 映射出的事件日期 event_date 分区。",
    ),
    _event_date_dataset(
        dataset_key="irm_qa_sz",
        display_name="深证互动易问答",
        description="深证互动易问答，Lake 按源表 trade_date 映射出的事件日期 event_date 分区。",
    ),
    _event_date_dataset(
        dataset_key="research_report",
        display_name="券商研究报告",
        description="券商研究报告，Lake 按源表 trade_date 映射出的事件日期 event_date 分区。",
    ),
)
