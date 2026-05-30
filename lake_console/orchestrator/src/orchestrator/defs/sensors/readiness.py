from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg


CN_A_SENSOR_TIMEZONE = ZoneInfo("Asia/Shanghai")
CHECK_HISTORY_LIMIT = 5000

RAW_STOCK_BASIC_CHECKS = (
    "raw_stock_basic_file_exists",
    "raw_stock_basic_required_columns",
    "raw_stock_basic_row_count_positive",
    "raw_stock_basic_ts_code_present",
)
SILVER_STOCK_BASIC_CHECKS = (
    "silver_stock_basic_current_listed_only",
    "silver_stock_basic_has_listed_records",
    "silver_stock_basic_lifecycle_dates_valid",
    "silver_stock_basic_required_columns_non_null",
    "silver_stock_basic_unique_ts_code",
)
RAW_SUSPEND_D_CHECKS = (
    "raw_suspend_d_file_exists",
    "raw_suspend_d_partition_date_matches",
    "raw_suspend_d_required_columns",
    "raw_suspend_d_schema_matches_tushare_contract",
    "raw_suspend_d_stock_partition_key_allowed",
)
SILVER_SUSPEND_D_CHECKS = (
    "silver_suspend_d_known_type_values",
    "silver_suspend_d_stock_partition_key_allowed",
    "silver_suspend_d_unique_business_key",
)
RAW_STOCK_DAILY_CHECKS = (
    "raw_stock_daily_file_exists",
    "raw_stock_daily_partition_date_matches",
    "raw_stock_daily_required_columns",
    "raw_stock_daily_row_count_positive",
    "raw_stock_daily_stock_partition_key_allowed",
)
SILVER_STOCK_DAILY_BLOCKING_CHECKS = (
    "silver_stock_daily_after_list_date_only",
    "silver_stock_daily_bj_after_market_open_only",
    "silver_stock_daily_conflicting_duplicate_absent",
    "silver_stock_daily_current_listed_only",
    "silver_stock_daily_partition_date_matches",
    "silver_stock_daily_price_sanity",
    "silver_stock_daily_required_columns_non_null",
    "silver_stock_daily_row_count_positive",
    "silver_stock_daily_stock_partition_key_allowed",
    "silver_stock_daily_unique_ts_code_trade_date",
)
RAW_ADJ_FACTOR_CHECKS = (
    "raw_adj_factor_file_exists",
    "raw_adj_factor_partition_date_matches",
    "raw_adj_factor_positive_factor",
    "raw_adj_factor_required_columns",
    "raw_adj_factor_row_count_positive",
    "raw_adj_factor_schema_matches_tushare_contract",
    "raw_adj_factor_stock_current_partition_key_allowed",
    "raw_adj_factor_unique_ts_code_trade_date",
)
RAW_STK_MINS_CHECKS = (
    "raw_stk_mins_file_exists_and_row_count_positive",
    "raw_stk_mins_schema_matches_contract",
    "raw_stk_mins_freq_matches_asset",
    "raw_stk_mins_partition_date_matches",
    "raw_stk_mins_unique_ts_code_trade_time",
    "raw_stk_mins_price_volume_sanity",
    "raw_stk_mins_stock_mins_partition_key_registered",
)
SILVER_ADJ_FACTOR_BLOCKING_CHECKS = (
    "silver_adj_factor_coverage_complete",
    "silver_adj_factor_file_exists",
    "silver_adj_factor_listed_stock_only",
    "silver_adj_factor_partition_date_matches",
    "silver_adj_factor_positive_factor",
    "silver_adj_factor_required_columns",
    "silver_adj_factor_row_count_positive",
    "silver_adj_factor_schema_matches_contract",
    "silver_adj_factor_stock_current_partition_key_allowed",
    "silver_adj_factor_unique_ts_code_trade_date",
)
RAW_INDEX_DAILY_BY_CODE_CHECKS = (
    "raw_index_daily_by_code_file_exists",
    "raw_index_daily_by_code_partition_code_matches",
    "raw_index_daily_by_code_required_columns_and_types",
    "raw_index_daily_by_code_row_count_positive",
    "raw_index_daily_by_code_unique_ts_code_trade_date",
)
SILVER_INDEX_DAILY_BLOCKING_CHECKS = (
    "silver_index_daily_conflicting_duplicate_absent",
    "silver_index_daily_partition_date_matches",
    "silver_index_daily_price_sanity",
    "silver_index_daily_required_columns_and_types",
    "silver_index_daily_row_count_positive",
    "silver_index_daily_unique_ts_code_trade_date",
)
SILVER_INDEX_BASIC_BLOCKING_CHECKS = (
    "silver_index_basic_file_exists",
    "silver_index_basic_required_columns_and_types",
    "silver_index_basic_row_count_positive",
    "silver_index_basic_unique_ts_code",
    "silver_index_basic_required_fields_non_null",
    "silver_index_basic_no_terminated_indexes",
)
GOLD_MARKET_MAJOR_INDICES_DAILY_BLOCKING_CHECKS = (
    "gold_market_major_indices_daily_file_exists",
    "gold_market_major_indices_daily_required_columns_and_types",
    "gold_market_major_indices_daily_partition_date_matches",
    "gold_market_major_indices_daily_row_count_matches_seed",
    "gold_market_major_indices_daily_seed_codes_present",
    "gold_market_major_indices_daily_unique_ts_code",
    "gold_market_major_indices_daily_rank_matches_active_seed_order",
    "gold_market_major_indices_daily_price_sanity",
    "gold_market_major_indices_seed_codes_exist_in_index_basic",
    "gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes",
)

RAW_STOCK_BASIC_ASSET_KEY = dg.AssetKey("raw_tushare_stock_basic")
SILVER_STOCK_BASIC_ASSET_KEY = dg.AssetKey("silver_stock_basic")
RAW_SUSPEND_D_ASSET_KEY = dg.AssetKey("raw_tushare_suspend_d")
SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY = dg.AssetKey("silver_stock_suspend_daily")
RAW_STOCK_DAILY_ASSET_KEY = dg.AssetKey("raw_tushare_stock_daily")
SILVER_STOCK_DAILY_ASSET_KEY = dg.AssetKey("silver_stock_daily")
RAW_ADJ_FACTOR_ASSET_KEY = dg.AssetKey("raw_tushare_adj_factor")
SILVER_ADJ_FACTOR_ASSET_KEY = dg.AssetKey("silver_adj_factor")
RAW_STK_MINS_ASSET_KEYS = (
    dg.AssetKey("raw_stk_mins_1m"),
    dg.AssetKey("raw_stk_mins_5m"),
    dg.AssetKey("raw_stk_mins_15m"),
    dg.AssetKey("raw_stk_mins_30m"),
    dg.AssetKey("raw_stk_mins_60m"),
)
RAW_INDEX_DAILY_BY_CODE_ASSET_KEY = dg.AssetKey("raw_tushare_index_daily_by_code")
SILVER_INDEX_DAILY_ASSET_KEY = dg.AssetKey("silver_index_daily")
SILVER_INDEX_BASIC_ASSET_KEY = dg.AssetKey("silver_index_basic")
GOLD_MARKET_MAJOR_INDICES_DAILY_ASSET_KEY = dg.AssetKey(
    "gold_market_major_indices_daily"
)


@dataclass(frozen=True)
class AssetReadinessSpec:
    asset_key: dg.AssetKey
    blocking_check_names: tuple[str, ...]


@dataclass(frozen=True)
class AssetReadinessStatus:
    asset_key: str
    partition_key: str | None
    ready: bool
    materialized: bool
    checks_passed: bool
    freshness_passed: bool
    materialization_storage_id: int | None
    materialization_date: str | None
    missing_check_names: tuple[str, ...]
    failed_check_names: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class DatasetReadinessStatus:
    ready: bool
    statuses: tuple[AssetReadinessStatus, ...]

    @property
    def reason(self) -> str:
        if self.ready:
            return "ready"
        reasons = [status.reason for status in self.statuses if not status.ready]
        return "; ".join(reasons) if reasons else "not ready"


STOCK_BASIC_READINESS_SPECS = (
    AssetReadinessSpec(RAW_STOCK_BASIC_ASSET_KEY, RAW_STOCK_BASIC_CHECKS),
    AssetReadinessSpec(SILVER_STOCK_BASIC_ASSET_KEY, SILVER_STOCK_BASIC_CHECKS),
)
SUSPEND_D_READINESS_SPECS = (
    AssetReadinessSpec(RAW_SUSPEND_D_ASSET_KEY, RAW_SUSPEND_D_CHECKS),
    AssetReadinessSpec(SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY, SILVER_SUSPEND_D_CHECKS),
)
STOCK_DAILY_READINESS_SPECS = (
    AssetReadinessSpec(RAW_STOCK_DAILY_ASSET_KEY, RAW_STOCK_DAILY_CHECKS),
    AssetReadinessSpec(SILVER_STOCK_DAILY_ASSET_KEY, SILVER_STOCK_DAILY_BLOCKING_CHECKS),
)
ADJ_FACTOR_READINESS_SPECS = (
    AssetReadinessSpec(RAW_ADJ_FACTOR_ASSET_KEY, RAW_ADJ_FACTOR_CHECKS),
    AssetReadinessSpec(SILVER_ADJ_FACTOR_ASSET_KEY, SILVER_ADJ_FACTOR_BLOCKING_CHECKS),
)
RAW_STK_MINS_READINESS_SPECS = tuple(
    AssetReadinessSpec(asset_key, RAW_STK_MINS_CHECKS)
    for asset_key in RAW_STK_MINS_ASSET_KEYS
)
RAW_INDEX_DAILY_BY_CODE_READINESS_SPEC = AssetReadinessSpec(
    RAW_INDEX_DAILY_BY_CODE_ASSET_KEY,
    RAW_INDEX_DAILY_BY_CODE_CHECKS,
)
SILVER_INDEX_DAILY_READINESS_SPEC = AssetReadinessSpec(
    SILVER_INDEX_DAILY_ASSET_KEY,
    SILVER_INDEX_DAILY_BLOCKING_CHECKS,
)
SILVER_INDEX_BASIC_READINESS_SPEC = AssetReadinessSpec(
    SILVER_INDEX_BASIC_ASSET_KEY,
    SILVER_INDEX_BASIC_BLOCKING_CHECKS,
)
GOLD_MARKET_MAJOR_INDICES_DAILY_READINESS_SPEC = AssetReadinessSpec(
    GOLD_MARKET_MAJOR_INDICES_DAILY_ASSET_KEY,
    GOLD_MARKET_MAJOR_INDICES_DAILY_BLOCKING_CHECKS,
)


def _asset_key_label(asset_key: dg.AssetKey) -> str:
    return asset_key.to_user_string()


def materialized_partition_keys(
    instance: dg.DagsterInstance,
    asset_keys: tuple[dg.AssetKey, ...],
) -> set[str]:
    materialized_sets = [instance.get_materialized_partitions(asset_key) for asset_key in asset_keys]
    if not materialized_sets:
        return set()
    return set.intersection(*materialized_sets)


def _latest_materialization_record(
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_key: str | None,
):
    if partition_key is None:
        result = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset_key),
            limit=1,
        )
    else:
        result = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset_key, asset_partitions=[partition_key]),
            limit=1,
        )
    return result.records[0] if result.records else None


def _local_materialization_date(record) -> str:
    return datetime.fromtimestamp(record.timestamp, CN_A_SENSOR_TIMEZONE).date().isoformat()


def _check_passed_for_materialization(
    instance: dg.DagsterInstance,
    check_key: dg.AssetCheckKey,
    materialization_storage_id: int,
) -> bool | None:
    records = instance.event_log_storage.get_asset_check_execution_history(
        check_key,
        limit=CHECK_HISTORY_LIMIT,
    )
    for record in records:
        if record.status.value not in {"SUCCEEDED", "FAILED"}:
            continue
        event = record.event
        dagster_event = event.dagster_event if event else None
        evaluation = dagster_event.event_specific_data if dagster_event else None
        target = getattr(evaluation, "target_materialization_data", None)
        if not target or target.storage_id != materialization_storage_id:
            continue
        if not evaluation.blocking:
            return False
        return record.status.value == "SUCCEEDED" and bool(evaluation.passed)
    return None


def asset_readiness_status(
    instance: dg.DagsterInstance,
    spec: AssetReadinessSpec,
    *,
    partition_key: str | None = None,
    min_materialization_date: str | None = None,
) -> AssetReadinessStatus:
    materialization = _latest_materialization_record(instance, spec.asset_key, partition_key)
    asset_label = _asset_key_label(spec.asset_key)
    if materialization is None:
        return AssetReadinessStatus(
            asset_key=asset_label,
            partition_key=partition_key,
            ready=False,
            materialized=False,
            checks_passed=False,
            freshness_passed=False,
            materialization_storage_id=None,
            materialization_date=None,
            missing_check_names=spec.blocking_check_names,
            failed_check_names=(),
            reason=f"{asset_label} has no materialization",
        )

    materialization_date = _local_materialization_date(materialization)
    materialization_storage_id = materialization.storage_id
    missing_check_names = []
    failed_check_names = []
    for check_name in spec.blocking_check_names:
        check_key = dg.AssetCheckKey(spec.asset_key, check_name)
        check_passed = _check_passed_for_materialization(
            instance,
            check_key,
            materialization_storage_id,
        )
        if check_passed is None:
            missing_check_names.append(check_name)
        elif not check_passed:
            failed_check_names.append(check_name)

    checks_passed = not missing_check_names and not failed_check_names
    freshness_passed = (
        min_materialization_date is None or materialization_date >= min_materialization_date
    )
    ready = checks_passed and freshness_passed
    if ready:
        reason = "ready"
    elif not freshness_passed:
        reason = (
            f"{asset_label} materialized at {materialization_date}, "
            f"before required date {min_materialization_date}"
        )
    elif missing_check_names:
        reason = f"{asset_label} missing blocking checks: {missing_check_names}"
    else:
        reason = f"{asset_label} failed blocking checks: {failed_check_names}"

    return AssetReadinessStatus(
        asset_key=asset_label,
        partition_key=partition_key,
        ready=ready,
        materialized=True,
        checks_passed=checks_passed,
        freshness_passed=freshness_passed,
        materialization_storage_id=materialization_storage_id,
        materialization_date=materialization_date,
        missing_check_names=tuple(missing_check_names),
        failed_check_names=tuple(failed_check_names),
        reason=reason,
    )


def dataset_readiness_status(
    instance: dg.DagsterInstance,
    specs: tuple[AssetReadinessSpec, ...],
    *,
    partition_key: str | None = None,
    min_materialization_date: str | None = None,
) -> DatasetReadinessStatus:
    statuses = tuple(
        asset_readiness_status(
            instance,
            spec,
            partition_key=partition_key,
            min_materialization_date=min_materialization_date,
        )
        for spec in specs
    )
    return DatasetReadinessStatus(
        ready=all(status.ready for status in statuses),
        statuses=statuses,
    )


def stock_basic_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> DatasetReadinessStatus:
    return dataset_readiness_status(
        instance,
        STOCK_BASIC_READINESS_SPECS,
        min_materialization_date=trade_date,
    )


def stock_basic_ready_without_freshness(
    instance: dg.DagsterInstance,
) -> DatasetReadinessStatus:
    return dataset_readiness_status(instance, STOCK_BASIC_READINESS_SPECS)


def suspend_d_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> DatasetReadinessStatus:
    return dataset_readiness_status(
        instance,
        SUSPEND_D_READINESS_SPECS,
        partition_key=trade_date,
    )


def stock_daily_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> DatasetReadinessStatus:
    return dataset_readiness_status(
        instance,
        STOCK_DAILY_READINESS_SPECS,
        partition_key=trade_date,
    )


def adj_factor_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> DatasetReadinessStatus:
    return dataset_readiness_status(
        instance,
        ADJ_FACTOR_READINESS_SPECS,
        partition_key=trade_date,
    )


def raw_stk_mins_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> DatasetReadinessStatus:
    return dataset_readiness_status(
        instance,
        RAW_STK_MINS_READINESS_SPECS,
        partition_key=trade_date,
    )


def raw_index_daily_by_code_ready_for_code(
    instance: dg.DagsterInstance,
    index_code: str,
) -> AssetReadinessStatus:
    return asset_readiness_status(
        instance,
        RAW_INDEX_DAILY_BY_CODE_READINESS_SPEC,
        partition_key=index_code,
    )


def silver_index_daily_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> AssetReadinessStatus:
    return asset_readiness_status(
        instance,
        SILVER_INDEX_DAILY_READINESS_SPEC,
        partition_key=trade_date,
    )


def silver_index_basic_ready(instance: dg.DagsterInstance) -> AssetReadinessStatus:
    return asset_readiness_status(
        instance,
        SILVER_INDEX_BASIC_READINESS_SPEC,
    )


def gold_market_major_indices_daily_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> AssetReadinessStatus:
    return asset_readiness_status(
        instance,
        GOLD_MARKET_MAJOR_INDICES_DAILY_READINESS_SPEC,
        partition_key=trade_date,
    )


def status_payload(status: DatasetReadinessStatus) -> list[dict[str, object]]:
    return [
        {
            "asset_key": asset_status.asset_key,
            "partition_key": asset_status.partition_key,
            "ready": asset_status.ready,
            "materialized": asset_status.materialized,
            "checks_passed": asset_status.checks_passed,
            "freshness_passed": asset_status.freshness_passed,
            "materialization_storage_id": asset_status.materialization_storage_id,
            "materialization_date": asset_status.materialization_date,
            "missing_check_names": list(asset_status.missing_check_names),
            "failed_check_names": list(asset_status.failed_check_names),
            "reason": asset_status.reason,
        }
        for asset_status in status.statuses
    ]
