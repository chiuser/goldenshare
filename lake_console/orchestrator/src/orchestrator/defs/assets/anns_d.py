"""Natural-day announcement Raw asset; production logic lives in core helpers."""

import json
from collections.abc import Mapping
from pathlib import Path

import dagster as dg
from dagster._core.storage.tags import (
    ASSET_PARTITION_RANGE_END_TAG,
    ASSET_PARTITION_RANGE_START_TAG,
    PARTITION_NAME_TAG,
)

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementControl,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_FIELDS,
    ANNOUNCEMENT_SOURCE_DOC,
    AnnouncementError,
    announcement_date_range,
)
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.anns_d_run_intent import announcement_root_file_intent
from orchestrator.defs.anns_d_source import AnnouncementProcessCall
from orchestrator.defs.anns_d_window import (
    ANNOUNCEMENT_WINDOW_TAG,
    announcement_day_run_id,
    announcement_manual_window_tags,
    announcement_window_identity,
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


def _root_partition_days(tags):
    single = tags.get(PARTITION_NAME_TAG)
    first, last = (
        tags.get(ASSET_PARTITION_RANGE_START_TAG),
        tags.get(ASSET_PARTITION_RANGE_END_TAG),
    )
    if single is not None:
        if first is not None or last is not None:
            raise AnnouncementError("announcement_root_partition_conflict")
        return announcement_date_range(single, single)
    if first is None or last is None:
        raise AnnouncementError("announcement_root_partition_missing")
    return announcement_date_range(first, last)


def _root_policy(root):
    config = root.run_config
    for key in ("ops", ANNOUNCEMENT_ASSET, "config"):
        if not isinstance(config, Mapping):
            raise AnnouncementError("announcement_root_run_config")
        config = config.get(key, {})
    if not isinstance(config, Mapping):
        raise AnnouncementError("announcement_root_run_config")
    original = AnnouncementRawConfig(
        interval_seconds=config.get(
            "interval_seconds", AnnouncementRawConfig().interval_seconds
        )
    )
    return AnnouncementPolicy(interval_seconds=original.interval_seconds)


def _reject_legacy_root_window(root_id, days, staging):
    # P2 used root.run_id as window_id; only its fixed paths are inspected.
    daily_ids = tuple(announcement_day_run_id(root_id, day) for day in days)
    paths = [
        staging / "anns_d" / "windows" / root_id / name
        for name in ("admission.json", "budget.json", "execution.json")
    ]
    paths.extend(
        staging / "anns_d" / f"run_id={run_id}" / "delivery.json"
        for run_id in daily_ids
    )
    if any(assert_safe_announcement_path(path).exists() for path in paths):
        raise AnnouncementError("announcement_legacy_execution")


def _announcement_asset_window_tags(context, days, policy, staging):
    """Keep the original run's intent before any store or execution can write."""
    run, root = context.run, context.run
    root_id = run.root_run_id
    if root_id and root_id != run.run_id:
        root = context.instance.get_run_by_id(root_id)
        if root is None:
            raise AnnouncementError("announcement_root_run_missing")
        if _root_partition_days(root.tags) != days:
            raise AnnouncementError("announcement_root_partition_conflict")
        if _root_policy(root) != policy:
            raise AnnouncementError("announcement_window_contract_changed")
        if (
            ANNOUNCEMENT_WINDOW_TAG not in root.tags
            and not announcement_root_file_intent(
                root,
                instance=context.instance,
                asset_step_key=raw_tushare_anns_d.op.name,
            )
        ):
            raise AnnouncementError("announcement_root_asset_not_selected")
    root_tags = dict(root.tags)
    if ANNOUNCEMENT_WINDOW_TAG in root_tags:
        announcement_window_identity(days, root_tags, policy)
        tags = root_tags
    else:
        if len(days) != 1:
            raise AnnouncementError("announcement_manual_range_unsupported")
        _reject_legacy_root_window(root.run_id, days, staging)
        tags = announcement_manual_window_tags(
            root.run_id, days[0], days[-1], staging=staging, policy=policy
        )
    identity_keys = (
        "anns_d/window_id",
        "anns_d/execution_version",
        "anns_d/start_date",
        "anns_d/end_date",
        "anns_d/started_at",
        "anns_d/automatic",
    )
    for supplied in (root_tags, run.tags):
        if any(
            supplied[key] != tags.get(key) for key in identity_keys if key in supplied
        ):
            raise AnnouncementError("announcement_window_intent")
    return tags


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
    tags = _announcement_asset_window_tags(
        context, days, policy, Path(DEFAULT_LAKE_STAGING_ROOT)
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
    control.check()
    for day in days:
        control.check()
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
    control.check()
    return dg.MaterializeResult()
