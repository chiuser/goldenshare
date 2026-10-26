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
    announcement_manual_window_tags,
    execute_announcement_window,
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
    policy = AnnouncementPolicy(interval_seconds=config.interval_seconds)
    days = tuple(context.partition_keys)
    tags = dict(context.run.tags)
    if ANNOUNCEMENT_WINDOW_TAG not in tags:
        if len(days) != 1:
            raise AnnouncementError("announcement_manual_range_unsupported")
        intent_id = context.run.root_run_id or context.run.run_id
        tags = announcement_manual_window_tags(
            intent_id,
            days[0],
            days[-1],
            staging=Path(DEFAULT_LAKE_STAGING_ROOT),
            policy=policy,
        )
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
    control.progress(active_run_id=context.run.run_id)

    def store_factory(day):
        lake_root.ensure_available_for_run()
        return AnnouncementStore(
            lake_root.root(),
            Path(DEFAULT_LAKE_STAGING_ROOT),
            announcement_day_run_id(window_id, day),
            policy,
            control,
        )

    deliveries = execute_announcement_window(
        days,
        tags=tags,
        policy=policy,
        control=control,
        store_factory=store_factory,
        call_factory=lambda day, store: AnnouncementProcessCall(
            tushare.token, store.directory, policy
        ),
    )
    for day in days:
        result = deliveries[day]
        delivery = result.delivery
        context.add_asset_metadata(
            build_materialization_metadata(
                uri=raw_anns_d_path(lake_root.root(), day),
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
                    "announcement_checkpoint": str(result.checkpoint_path),
                    "announcement_identity": dict(result.identity),
                    "summary": "上市公司公告已交付。",
                    "next_action": "等待文件合同与交付对账检查。",
                },
            ),
            partition_key=day,
        )
    return dg.MaterializeResult()
