"""Reuse daily checks with the actual same-day upstream publication."""

from collections import Counter

from dagster import AssetKey
from dagster._core.definitions.data_version import get_input_event_pointer_tag

from orchestrator.defs.checks.daily_audit_coverage import (
    BOARD_CLASSIFICATION_FILE_VERSION,
    version_string,
)
from orchestrator.defs.daily_data_audit.evidence import metadata
from orchestrator.defs.daily_data_audit.index_minute_audit import (
    INDEX_MINUTE_GOLD_INPUTS,
)
from orchestrator.defs.run_contracts.adj_factor import (
    ADJ_FACTOR_RETIRED_RETENTION_START_DATE,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
)

RAW_ADJ = "raw_tushare_adj_factor"
SILVER_ADJ = "silver_adj_factor"
LIFECYCLE = "silver_stock_lifecycle"
RAW_BOARD_INDEX = "raw_tushare_dc_index"
SILVER_BOARD_INDEX = "silver_dc_index"
RAW_BOARD_DAILY = "raw_tushare_dc_daily"
SILVER_BOARD_DAILY = "silver_dc_daily"
TREND = "gold_stock_daily_trend_channel"
TREND_STATE = "gold_stock_daily_trend_channel_state"
STOCK_DAILY = "silver_stock_daily"
STOCK_QFQ = "gold_stock_daily_qfq"
TREND_INPUTS = (STOCK_QFQ, "silver_stock_basic", LIFECYCLE, "silver_trade_calendar")
MAJOR_MINUTE_NINETURN = (5, 15, 30, 60, 90, 120)

# Direct input assets are ordered so a dependent row consumes the result built
# above it, including the two market breadth inputs and the board quote chain.
DEPENDENT_INPUTS = {
    RAW_ADJ: (LIFECYCLE,),
    SILVER_ADJ: (RAW_ADJ, LIFECYCLE),
    RAW_BOARD_DAILY: (RAW_BOARD_INDEX,),
    SILVER_BOARD_DAILY: (RAW_BOARD_DAILY, SILVER_BOARD_INDEX),
    "silver_stock_nineturn_daily": ("raw_tushare_stk_nineturn", "silver_stock_identity_map"),
    TREND: TREND_INPUTS,
    TREND_STATE: TREND_INPUTS,
    "gold_stock_daily_qfq_nineturn": (STOCK_QFQ,),
    "gold_dc_daily_technical": (SILVER_BOARD_DAILY,),
    **{
        f"gold_stk_mins_qfq_nineturn_{freq}m": (f"gold_stk_mins_qfq_{freq}m",)
        for freq in (30, 60, 90, 120)
    },
    "silver_index_daily": ("raw_index_daily",),
    **{key: (source,) for key, source in INDEX_MINUTE_GOLD_INPUTS.items()},
    "gold_major_index_daily_nineturn": ("gold_market_major_indices_daily",),
    **{
        f"gold_major_index_mins_nineturn_{freq}m": (f"gold_major_index_mins_{freq}m",)
        for freq in MAJOR_MINUTE_NINETURN
    },
    "gold_market_breadth_daily": (STOCK_DAILY,),
    "gold_stock_return_distribution": (STOCK_DAILY,),
    "gold_wealth_market_turnover": (
        STOCK_DAILY, *(f"silver_stk_mins_{freq}m" for freq in (1, 5, 15, 30, 60)),
    ),
    "ch_share_fact_market_breadth_daily": (
        "gold_market_breadth_daily", "gold_stock_return_distribution",
    ),
    "silver_index_factor_pro": ("raw_tushare_idx_factor_pro",),
    **{
        f"gold_major_index_mins_technical_{freq}m": (f"gold_major_index_mins_{freq}m",)
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    },
}


def expand_dependent_changes(changed, published):
    if SILVER_ADJ in changed:
        changed.update({RAW_ADJ} & published)
    if changed.intersection((TREND, TREND_STATE)):
        changed.update({TREND, TREND_STATE} & published)
    for key, inputs in DEPENDENT_INPUTS.items():
        if key in published and changed.intersection(inputs):
            changed.add(key)


def dependent_read_keys(changed):
    return {
        source for key in changed.intersection(DEPENDENT_INPUTS)
        for source in DEPENDENT_INPUTS[key]
    }


def _passing_check(bundle, name):
    return bool(bundle and name in bundle.checks and bundle.checks[name].evaluation.passed)


def _publication(row):
    return next(
        (item for item in row["completeness"]["evidence"] if item["type"] == "materialization"),
        None,
    )


def _matches_pointer(bundle, key, row):
    upstream = _publication(row)
    if not upstream or not bundle or not bundle.materialization:
        return False
    tags = bundle.materialization.asset_materialization.tags or {}
    return tags.get(get_input_event_pointer_tag(AssetKey(key))) == str(upstream["record_id"])


def _board_check_version(bundle, key):
    name = f"{key}_core_check"
    if not _passing_check(bundle, name):
        return None
    return metadata(bundle.checks[name].evaluation).get(BOARD_CLASSIFICATION_FILE_VERSION)


def _matches_source(key, source, row, evidence):
    if (key, source) in {
        (RAW_BOARD_DAILY, RAW_BOARD_INDEX), (SILVER_BOARD_DAILY, SILVER_BOARD_INDEX),
    }:
        index = evidence.get(source)
        index_version = _board_check_version(index, source)
        if not index_version:
            return False
        if source == RAW_BOARD_INDEX:
            identity = metadata(index.materialization.asset_materialization).get("tushare_source_fingerprint")
        else:
            identity = version_string(index_version)
        return (
            identity is not None
            and identity == row["version"]["target_version"]
            and _board_check_version(evidence.get(key), key) == index_version
        )
    bundle = evidence.get(SILVER_ADJ if key == RAW_ADJ else key)
    return _matches_pointer(bundle, source, row)


def _adj_factor_reconciliation(evidence, rows, day):
    silver = evidence.get(SILVER_ADJ)
    name = "silver_adj_factor_lifecycle_coverage_check"
    if day < ADJ_FACTOR_RETIRED_RETENTION_START_DATE or not _passing_check(silver, name):
        return None
    check = silver.checks[name]
    rules = metadata(check.evaluation).get("rule_passed", {})
    raw = rows.get(RAW_ADJ)
    if (
        raw and silver.materialization and check.run_id == silver.materialization.run_id
        and _matches_pointer(silver, RAW_ADJ, raw)
        and rules.get("silver_adj_factor_coverage_complete")
    ):
        return check
    return None


def apply_dependent_evidence(report, evidence, targets, changed):
    rows = {row["scope"]["asset_key"]: row for row in report["rows"]}
    check_names = {target.asset_key: target.check_names for target in targets}
    recalculated = changed or rows.keys()
    for key, inputs in DEPENDENT_INPUTS.items():
        if key not in rows or key not in recalculated:
            continue
        row = rows[key]
        if row["update"]["status"] != "updated" or row["completeness"]["status"] != "pending":
            continue
        bundle = evidence.get(key)
        names = check_names[key]
        if not names or not all(_passing_check(bundle, name) for name in names):
            row["completeness"]["reason"] = {
                "code": "not_verified", "message": "缺少本次发布通过的生产 Check",
            }
            continue
        required = (*inputs, TREND) if key == TREND_STATE else inputs
        if any(rows.get(source, {}).get("completeness", {}).get("status") != "complete"
               for source in required):
            row["completeness"]["reason"] = {
                "code": "upstream_pending", "message": "等待实际输入的齐备结果",
            }
            continue
        matched = all(_matches_source(key, source, rows[source], evidence) for source in inputs)
        if key == TREND_STATE:
            matched = matched and _publication(rows[TREND])["run_id"] == bundle.materialization.run_id
        adj_check = None
        if key == RAW_ADJ:
            adj_check = _adj_factor_reconciliation(evidence, rows, row["scope"]["business_date"])
            matched = matched and adj_check is not None
        if not matched:
            row["completeness"]["reason"] = {
                "code": "version_mismatch", "message": "已核验的上游与本次实际输入无法对应",
            }
            continue
        row["version"]["inputs"] = [
            {
                "asset_key": source,
                "scope": rows[source]["scope"],
                "target_version": rows[source]["version"]["target_version"],
            }
            for source in required if rows[source]["version"]["target_version"]
        ]
        for source in required:
            publication = _publication(rows[source])
            if publication:
                row["completeness"]["evidence"].append({**publication, "asset_key": source})
        row["completeness"].update(
            status="complete",
            reason={"code": "check_passed", "message": "本次生产 Check 通过，实际输入的齐备结果已核对"},
        )
        if adj_check:
            row["completeness"]["evidence"].append({
                "type": "check", "asset_key": SILVER_ADJ, "run_id": adj_check.run_id,
                "record_id": adj_check.id, "passed": True,
                "check_name": "silver_adj_factor_lifecycle_coverage_check",
                "message": "对应这次 Raw 的上市股票覆盖及双向对账通过",
            })
    report["summary"] = dict.fromkeys(report["summary"], 0) | dict(
        Counter(row["completeness"]["status"] for row in rows.values())
    )
    return report
