import re
from dataclasses import dataclass
from datetime import date, timedelta

from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.catalog.lake_assets import (
    LakeAssetCatalogEntry,
    PartitionModelFamily,
    get_partition_model_definition,
    list_lake_asset_catalog_entries,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    index_period_bounds,
)
from orchestrator.defs.run_contracts.stock_period import period_for as stock_period_for

OUTSIDE_LOCAL = {
    "prod_core_wealth_market_turnover",
    "prod_core_stock_daily_qfq_nineturn",
    "prod_core_index_daily_nineturn",
    "prod_core_wealth_sector_hierarchy",
    "prod_ch_share_fact_market_breadth_daily",
    "prod_ch_dc_daily_technical",
    "lake_root_health",
}
INTERNATIONAL_INDEX = {"raw_index_global", "silver_index_global"}
SILVER_INDEX_PERIOD = {INDEX_WEEKLY.silver_asset, INDEX_MONTHLY.silver_asset}
UPDATE_ONLY = {
    "raw_tushare_namechange",
    "raw_tushare_suspend_d",
    "silver_stock_suspend_daily",
}
FIXED_SNAPSHOTS = {
    "raw_tushare_trade_calendar",
    "silver_trade_calendar",
    "silver_dc_industry_hierarchy",
    "silver_stock_suspend_confirmed",
}
DAILY_SNAPSHOTS = {
    "raw_tushare_stock_basic",
    "silver_stock_basic",
    "silver_stock_lifecycle",
    "raw_tushare_namechange",
    "silver_namechange",
    "silver_stock_identity_map",
    "raw_tushare_index_basic",
    "silver_index_basic",
    "raw_tushare_etf_basic",
    "silver_etf_basic",
}
ETF_COVERAGE_CHECK = {
    "silver_etf_daily": "silver_etf_daily_basic_coverage_check",
    "silver_etf_adj_factor": "silver_etf_adj_factor_basic_coverage_check",
}
LATE_STOCK_DAILY_COVERAGE_CHECKS = {
    "raw_tushare_moneyflow_dc": "raw_tushare_moneyflow_dc_file_contract_check",
    "raw_tushare_stk_nineturn": "raw_tushare_stk_nineturn_content_integrity_check",
}
DELIVERY_DATE_FIELDS = (
    "trade_date",
    "as_of_trade_date",
    "ready_for_trade_date",
    "target_trade_date",
    "source_trade_date",
    "last_trade_date",
    "partition_trade_date",
    "period_end",
    "business_date",
    "silver_asof",
    "announcement_end_date",
)


@dataclass(frozen=True)
class AuditTarget:
    entry: LakeAssetCatalogEntry
    partition: str | None
    expected_date: date | None
    requires_update: bool | None
    check_names: tuple[str, ...]
    exact_as_of: bool
    frequency: str | None
    excluded_reason: str | None = None

    @property
    def asset_key(self) -> str:
        return self.entry.asset_key


def read_calendar(root, day: date) -> dict[date, bool]:
    month_start, month_end = index_period_bounds(INDEX_MONTHLY, day.strftime("%Y-%m"))
    previous_start = (month_start - timedelta(days=1)).replace(day=1)
    _, week_end = index_period_bounds(INDEX_WEEKLY, day.isoformat())
    with connect_configured_duckdb() as connection:
        return dict(
            connection.execute(
                "SELECT trade_date, is_open FROM read_parquet(?) WHERE exchange = 'SSE' "
                "AND trade_date BETWEEN ?::DATE AND ?::DATE",
                [
                    str(silver_trade_calendar_path(root)),
                    previous_start,
                    max(month_end, week_end),
                ],
            ).fetchall()
        )


def _open_days(calendar: dict[date, bool], start: date, end: date) -> list[date] | None:
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    return (
        [day for day in days if calendar[day]]
        if all(day in calendar for day in days)
        else None
    )


def _period(entry, model, day, calendar):
    weekly = model.family == PartitionModelFamily.NATURAL_WEEK_PARTITION
    period = INDEX_WEEKLY if weekly else INDEX_MONTHLY
    start, end = index_period_bounds(
        period, day.isoformat() if weekly else day.strftime("%Y-%m")
    )
    open_days = _open_days(calendar, start, end)
    partition = (
        (open_days[-1].isoformat() if open_days else None)
        if weekly
        else day.strftime("%Y-%m")
    )
    if "stock" in entry.asset_key or "stk_period" in entry.asset_key:
        partition = stock_period_for(day, "week" if weekly else "month")
    expected = day
    due = calendar.get(day) if open_days is not None else None
    if entry.asset_key == "raw_index_weekly" and open_days:
        due = day == open_days[-1]
    if entry.asset_key == "raw_index_monthly" and open_days:
        due = day == open_days[0]
        previous_end = start - timedelta(days=1)
        previous = _open_days(calendar, previous_end.replace(day=1), previous_end)
        partition = previous_end.strftime("%Y-%m")
        expected = previous[-1] if previous else None
        if due and expected is None:
            due = None
    return partition, expected, due


def targets_for_day(day: date, calendar: dict[date, bool]) -> tuple[AuditTarget, ...]:
    targets = []
    for entry in list_lake_asset_catalog_entries():
        key = entry.asset_key
        model = get_partition_model_definition(entry.partition_model)
        family = model.family
        minute = re.search(r"_(\d+)m$", key)
        frequency = f"{minute[1]}分钟" if minute else None
        expected, due, partition, exact = day, calendar.get(day), day.isoformat(), False
        excluded = None
        if key in OUTSIDE_LOCAL:
            excluded, due, expected, partition = (
                "超出本地业务数据审计范围",
                False,
                None,
                None,
            )
        elif key in INTERNATIONAL_INDEX:
            excluded, due = "国际指数日线审计纳入二期", None
        elif family == PartitionModelFamily.NATURAL_DATE_PARTITION:
            due, frequency = day >= anns_d_natural_days.start.date(), "日更"
        elif family in {
            PartitionModelFamily.NATURAL_WEEK_PARTITION,
            PartitionModelFamily.NATURAL_MONTH_PARTITION,
        }:
            partition, expected, due = _period(entry, model, day, calendar)
            frequency = (
                "周线"
                if family == PartitionModelFamily.NATURAL_WEEK_PARTITION
                else "月线"
            )
            exact = True
        elif family == PartitionModelFamily.FULL_FILE:
            partition, exact = None, key in DAILY_SNAPSHOTS
            if key in FIXED_SNAPSHOTS:
                expected, due, frequency = None, False, "快照"
            elif not exact:
                due = None
        elif family == PartitionModelFamily.NON_PARTITIONED:
            partition, exact = None, True
        if key in UPDATE_ONLY:
            excluded = "仅考核更新"
        if due is False and key not in FIXED_SNAPSHOTS:
            excluded = excluded or "所选日无需交付"
        names = entry.blocking_check_names
        extra_check = ETF_COVERAGE_CHECK.get(key)
        if extra_check and extra_check not in names:
            names = (*names, extra_check)
        targets.append(
            AuditTarget(
                entry,
                partition,
                expected,
                due,
                names,
                exact,
                frequency or "日更",
                excluded,
            )
        )
    return tuple(targets)
