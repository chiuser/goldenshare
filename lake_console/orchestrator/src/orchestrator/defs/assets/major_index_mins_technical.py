"""Gold technical and recursive-state assets for major-index minute bars."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    load_stock_mins_expected_trade_dates,
)
from orchestrator.defs.assets.major_index_mins_silver import (
    SILVER_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.catalog import get_lake_asset_catalog_entry
from orchestrator.defs.io.major_index_mins_technical_writer import (
    MajorIndexMinsTechnicalWriteResult,
    write_major_index_mins_technical_partition,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_tags import build_asset_tags
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMNS,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMNS,
    INDICATOR_VERSION,
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    PARAMS_KEY,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_state_asset_key,
)
from orchestrator.defs.run_contracts.metadata import (
    build_asset_definition_metadata,
    build_materialization_metadata,
)


def _load_expected_trade_dates(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    with duckdb_resource.connect() as connection:
        return load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=MAJOR_INDEX_MINS_HISTORY_START_DATE,
            evaluated_at=datetime.now(UTC),
            same_day_register_start=None,
        )


def _asset_spec(
    *,
    asset_key: str,
    dependency: dg.AssetsDefinition,
    freq: int,
    paired_asset_key: str,
) -> dg.AssetSpec:
    entry = get_lake_asset_catalog_entry(asset_key)
    return dg.AssetSpec(
        asset_key,
        deps=[dependency],
        partitions_def=cn_major_index_mins_trade_days,
        group_name=entry.group_name,
        tags=build_asset_tags(layer=entry.layer, data_domain=entry.data_domain),
        metadata=build_asset_definition_metadata(
            dataset_id=entry.dataset_id,
            source_system=entry.source_system,
            data_contract=entry.data_contract,
            column_schema=entry.column_schema,
            path_template=entry.path_template,
            extra_metadata={
                "freq": freq,
                "params_key": PARAMS_KEY,
                "indicator_version": INDICATOR_VERSION,
                "paired_asset_key": paired_asset_key,
                "partition_set": cn_major_index_mins_trade_days.name,
                "write_boundary": "m5_daily_multi_asset",
            },
        ),
        description=(
            f"主要指数 {freq} 分钟技术指标。"
            if entry.dataset_id == "major_index_mins_technical"
            else f"主要指数 {freq} 分钟技术指标日终递推状态。"
        ),
    )


def _technical_materialization_metadata(
    result: MajorIndexMinsTechnicalWriteResult,
) -> dict[str, object]:
    return build_materialization_metadata(
        uri=result.technical_path,
        row_count=result.technical_row_count,
        observed_columns=GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMNS,
        extra_metadata={
            **result.to_details(),
            "paired_asset_status": "technical_and_state_promoted",
        },
    )


def _state_materialization_metadata(
    result: MajorIndexMinsTechnicalWriteResult,
) -> dict[str, object]:
    return build_materialization_metadata(
        uri=result.state_path,
        row_count=result.state_row_count,
        observed_columns=GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMNS,
        extra_metadata={
            **result.to_details(),
            "paired_asset_status": "technical_and_state_promoted",
        },
    )


def _build_major_index_mins_technical_assets(
    *,
    freq: int,
    dependency: dg.AssetsDefinition,
) -> dg.AssetsDefinition:
    technical_key = major_index_mins_technical_asset_key(freq)
    state_key = major_index_mins_technical_state_asset_key(freq)

    @dg.multi_asset(
        name=f"{technical_key}_assets",
        specs=(
            _asset_spec(
                asset_key=technical_key,
                dependency=dependency,
                freq=freq,
                paired_asset_key=state_key,
            ),
            _asset_spec(
                asset_key=state_key,
                dependency=dependency,
                freq=freq,
                paired_asset_key=technical_key,
            ),
        ),
        can_subset=False,
    )
    def assets(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> Iterator[dg.MaterializeResult]:
        lake_root.ensure_available_for_run()
        expected_trade_dates = _load_expected_trade_dates(
            lake_root=lake_root.root(),
            duckdb_resource=duckdb,
        )
        result = write_major_index_mins_technical_partition(
            lake_root_path=lake_root.root(),
            staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
            duckdb_resource=duckdb,
            freq=freq,
            partition_key=context.partition_key,
            run_id=context.run_id,
            expected_trade_dates=expected_trade_dates,
        )
        yield dg.MaterializeResult(
            asset_key=technical_key,
            metadata=_technical_materialization_metadata(result),
        )
        yield dg.MaterializeResult(
            asset_key=state_key,
            metadata=_state_materialization_metadata(result),
        )

    return assets


GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS = tuple(
    _build_major_index_mins_technical_assets(freq=freq, dependency=dependency)
    for freq, dependency in zip(
        MAJOR_INDEX_MINS_TECHNICAL_FREQS,
        SILVER_MAJOR_INDEX_MINS_ASSETS,
        strict=True,
    )
)

(
    gold_major_index_mins_technical_1m_assets,
    gold_major_index_mins_technical_5m_assets,
    gold_major_index_mins_technical_15m_assets,
    gold_major_index_mins_technical_30m_assets,
    gold_major_index_mins_technical_60m_assets,
    gold_major_index_mins_technical_90m_assets,
    gold_major_index_mins_technical_120m_assets,
) = GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS


__all__ = [
    "GOLD_MAJOR_INDEX_MINS_TECHNICAL_ASSETS",
    "gold_major_index_mins_technical_1m_assets",
    "gold_major_index_mins_technical_5m_assets",
    "gold_major_index_mins_technical_15m_assets",
    "gold_major_index_mins_technical_30m_assets",
    "gold_major_index_mins_technical_60m_assets",
    "gold_major_index_mins_technical_90m_assets",
    "gold_major_index_mins_technical_120m_assets",
]
