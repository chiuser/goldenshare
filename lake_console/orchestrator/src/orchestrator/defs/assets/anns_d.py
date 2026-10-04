"""Natural-day announcement Raw asset; production logic lives in core helpers."""

import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    ANNOUNCEMENT_SOURCE_DOC,
    AnnouncementError,
)
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.anns_d_source import AnnouncementProcessCall
from orchestrator.defs.anns_d_window import (
    ANNOUNCEMENT_WINDOW_TAG,
    announcement_day_run_id,
    announcement_single_day_tags,
    execute_announcement_window_day,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_anns_d_path,
)
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.anns_d import (
    AnnouncementPolicy,
    AnnouncementRawConfig,
)
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_ANNS_D_SCHEMA
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


@dg.asset(
    partitions_def=anns_d_natural_days,
    group_name="basic",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.BASIC_DATA),
    description="自然日全量公告六字段；保留不同版本，仅删除完全重复；缺URL和发布时间合法。",
    metadata=build_asset_definition_metadata(
        dataset_id="anns_d",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_anns_d_six_field_mirror",
        column_schema=RAW_ANNS_D_SCHEMA,
        path_template=lake_path_template(
            raw_anns_d_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        source_api="anns_d",
        source_doc=ANNOUNCEMENT_SOURCE_DOC,
        source_category_path="股票数据/参考数据",
    ),
)
def raw_tushare_anns_d(
    context: dg.AssetExecutionContext,
    config: AnnouncementRawConfig,
    lake_root: LakeRootResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    if lake_root.root() != Path(DEFAULT_LAKE_ROOT):
        raise AnnouncementError("announcement_formal_root_contract")
    lake_root.ensure_available_for_run()
    policy = AnnouncementPolicy(interval_seconds=config.interval_seconds)
    day = context.partition_key
    tags = context.run.tags
    if ANNOUNCEMENT_WINDOW_TAG not in tags:
        intent_id = tags.get("dagster/root_run_id", context.run.run_id)
        tags = announcement_single_day_tags(intent_id, day)
    window_id = tags[ANNOUNCEMENT_WINDOW_TAG]

    def cancelled():
        run = context.instance.get_run_by_id(context.run.run_id)
        return run is not None and run.status in (
            dg.DagsterRunStatus.CANCELING,
            dg.DagsterRunStatus.CANCELED,
        )

    control = AnnouncementControl(
        cancelled=cancelled,
        emit=lambda event: context.log.info(json.dumps(event, ensure_ascii=False)),
    )
    store = AnnouncementStore(
        lake_root.root(),
        Path(DEFAULT_LAKE_STAGING_ROOT),
        announcement_day_run_id(window_id, day),
        policy,
        control,
    )
    call = AnnouncementProcessCall(tushare.token, store.directory, policy)
    checkpoint, delivery = execute_announcement_window_day(
        day, call, store, control, tags
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=store.target(day),
            row_count=delivery["written_rows"],
            observed_columns=ANNOUNCEMENT_FIELDS,
            extra_metadata={
                **{
                    key: value
                    for key, value in delivery.items()
                    if key not in ("source_pages", "candidate", "baseline")
                },
                "rejected_rows": 0,
                "non_exact_duplicate_filter_rows": 0,
                "announcement_checkpoint": str(checkpoint.path),
                "announcement_identity": checkpoint.identity,
                "summary": "上市公司公告已交付。",
                "next_action": "等待文件合同与交付对账检查。",
            },
        )
    )
