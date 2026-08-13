from pathlib import Path

from orchestrator.defs.run_contracts.idx_factor_pro import (
    normalize_idx_factor_pro_trade_date,
)
from orchestrator.defs.run_contracts.index_mins import (
    normalize_index_mins_silver_freq,
    normalize_index_mins_source_freq,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    normalize_major_index_mins_silver_freq,
    normalize_major_index_mins_source_freq,
    normalize_major_index_mins_trade_date,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    normalize_major_index_mins_technical_freq,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    normalize_qfq_nineturn_minute_freq,
)
from orchestrator.defs.run_contracts.stk_mins import (
    normalize_stk_mins_freq,
    normalize_stk_mins_qfq_freq,
)

DEFAULT_LAKE_ROOT = "/Volumes/datasource/data_lake"
DEFAULT_LAKE_STAGING_ROOT = "/Volumes/datasource/data_lake_staging"
PATH_TEMPLATE_LAKE_ROOT = Path("data_lake")
PATH_TEMPLATE_PARTITION_KEY = "{partition_key}"
PATH_TEMPLATE_TS_CODE = "{ts_code}"
PATH_TEMPLATE_YEAR = "{year}"

RAW = "raw"
SILVER = "silver"
GOLD = "gold"
LAYERS = {RAW, SILVER, GOLD}

FORBIDDEN_NEW_LAKE_PARTS = {
    "raw_tushare",
    "manifest",
    "derived",
    "research",
    "lake_jobs",
    "duckdb_compute",
}


def lake_path(root: Path, layer: str, *parts: str) -> Path:
    if layer not in LAYERS:
        raise ValueError(f"Unsupported lake layer: {layer}")

    forbidden = FORBIDDEN_NEW_LAKE_PARTS.intersection(parts)
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise ValueError(f"New Dagster lake paths must not contain legacy path parts: {names}")

    return root / layer / Path(*parts)


def lake_path_template(path: Path) -> str:
    return path.as_posix()


def raw_trade_calendar_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "trade_calendar", "full", "part-000.parquet")


def silver_trade_calendar_path(root: Path) -> Path:
    return lake_path(root, SILVER, "calendar", "trade_calendar", "full", "part-000.parquet")


def raw_stock_basic_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "stock_basic", "full", "part-000.parquet")


def silver_stock_basic_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "stock_basic", "full", "part-000.parquet")


def silver_stock_lifecycle_path(root: Path) -> Path:
    return lake_path(
        root,
        SILVER,
        "basic",
        "stock_lifecycle",
        "full",
        "part-000.parquet",
    )


def raw_namechange_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "namechange", "full", "part-000.parquet")


def silver_namechange_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "namechange", "full", "part-000.parquet")


def silver_stock_identity_map_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "stock_identity_map", "part-000.parquet")


def raw_stock_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "stock_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_stk_nineturn_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "stk_nineturn",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_stock_nineturn_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "stock_nineturn_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_stk_mins_path(root: Path, freq: int | str, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "stk_mins",
        f"freq={normalize_stk_mins_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_stk_mins_path(root: Path, freq: int | str, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "stk_mins",
        f"freq={normalize_stk_mins_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def _gold_stk_mins_qfq_ts_code_part(ts_code: str) -> str:
    if not ts_code or "/" in ts_code:
        raise ValueError("gold stk_mins qfq ts_code must be non-empty and must not contain '/'")

    return f"ts_code={ts_code}"


def _gold_stk_mins_qfq_year_part(year: int | str) -> str:
    year_value = str(year)
    if year_value == PATH_TEMPLATE_YEAR:
        return f"year={year_value}"
    if len(year_value) != 4 or not year_value.isdigit():
        raise ValueError("gold stk_mins qfq year must be a four-digit year")

    return f"year={year_value}"


def gold_stk_mins_qfq_path(root: Path, freq: int | str, ts_code: str, year: int | str) -> Path:
    return lake_path(
        root,
        GOLD,
        "quote",
        "stk_mins_qfq",
        f"freq={normalize_stk_mins_qfq_freq(freq)}",
        _gold_stk_mins_qfq_ts_code_part(ts_code),
        _gold_stk_mins_qfq_year_part(year),
        "part-000.parquet",
    )


def gold_stk_mins_qfq_nineturn_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stk_mins_qfq_nineturn",
        f"freq={normalize_qfq_nineturn_minute_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_stk_mins_qfq_nineturn_staging_path(
    root: Path,
    run_id: str,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stk_mins_qfq_nineturn",
        "_staging",
        _qfq_nineturn_run_id_part(run_id),
        f"freq={normalize_qfq_nineturn_minute_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_stk_mins_qfq_macd_kdj_path(
    root: Path,
    freq: int | str,
    ts_code: str,
    year: int | str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stk_mins_qfq_macd_kdj",
        f"freq={normalize_stk_mins_qfq_freq(freq)}",
        _gold_stk_mins_qfq_ts_code_part(ts_code),
        _gold_stk_mins_qfq_year_part(year),
        "part-000.parquet",
    )


def gold_stk_mins_qfq_macd_kdj_state_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stk_mins_qfq_macd_kdj_state",
        f"freq={normalize_stk_mins_qfq_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_adj_factor_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "adj_factor",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_suspend_d_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "suspend_d",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_stock_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "stock_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_adj_factor_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "adj_factor",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_stock_daily_qfq_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "quote",
        "stock_daily_qfq",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_stock_daily_qfq_nineturn_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stock_daily_qfq_nineturn",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_stock_daily_qfq_nineturn_staging_path(
    root: Path,
    run_id: str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "stock_daily_qfq_nineturn",
        "_staging",
        _qfq_nineturn_run_id_part(run_id),
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def _qfq_nineturn_run_id_part(run_id: str) -> str:
    normalized = str(run_id).strip()
    if not normalized or "/" in normalized:
        raise ValueError(
            "QFQ nine-turn run_id must be non-empty and must not contain '/'."
        )
    return f"run_id={normalized}"


def gold_dc_daily_technical_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "board",
        "dc_daily_technical",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def silver_stock_suspend_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "stock_suspend_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_market_breadth_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "breadth",
        "market_breadth_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_stock_return_distribution_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "breadth",
        "stock_return_distribution",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_wealth_market_turnover_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "wealth",
        "market_turnover",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_index_basic_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "index_basic", "full", "part-000.parquet")


def silver_index_basic_path(root: Path) -> Path:
    return lake_path(root, SILVER, "index_basic", "full", "part-000.parquet")


def raw_index_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "index_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_index_daily_staging_path(
    root: Path,
    run_id: str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        RAW,
        "index_daily",
        "_staging",
        f"run_id={run_id}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def _safe_run_id_part(run_id: str, *, asset_family: str) -> str:
    normalized = str(run_id).strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError(f"{asset_family} run_id must be a safe non-empty path component")
    return f"run_id={normalized}"


def _idx_factor_pro_partition_component(partition_key: str) -> str:
    if partition_key == PATH_TEMPLATE_PARTITION_KEY:
        return partition_key
    return normalize_idx_factor_pro_trade_date(partition_key)


def raw_idx_factor_pro_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "idx_factor_pro",
        f"trade_date={_idx_factor_pro_partition_component(partition_key)}",
        "part-000.parquet",
    )


def raw_idx_factor_pro_staging_path(
    staging_root: Path,
    run_id: str,
    partition_key: str,
) -> Path:
    return lake_path(
        staging_root,
        RAW,
        "tushare",
        "idx_factor_pro",
        "_staging",
        _safe_run_id_part(run_id, asset_family="idx_factor_pro"),
        f"trade_date={_idx_factor_pro_partition_component(partition_key)}",
        "part-000.parquet",
    )


def silver_index_factor_pro_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "index",
        "index_factor_pro",
        f"trade_date={_idx_factor_pro_partition_component(partition_key)}",
        "part-000.parquet",
    )


def silver_index_factor_pro_staging_path(
    staging_root: Path,
    run_id: str,
    partition_key: str,
) -> Path:
    return lake_path(
        staging_root,
        SILVER,
        "index",
        "index_factor_pro",
        "_staging",
        _safe_run_id_part(run_id, asset_family="index_factor_pro"),
        f"trade_date={_idx_factor_pro_partition_component(partition_key)}",
        "part-000.parquet",
    )


def gold_major_index_mins_technical_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "major_index_mins_technical",
        f"freq={normalize_major_index_mins_technical_freq(freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def gold_major_index_mins_technical_staging_path(
    root: Path,
    run_id: str,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "major_index_mins_technical",
        "_staging",
        _safe_run_id_part(run_id, asset_family="major_index_mins_technical"),
        f"freq={normalize_major_index_mins_technical_freq(freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def gold_major_index_mins_technical_state_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "major_index_mins_technical_state",
        f"freq={normalize_major_index_mins_technical_freq(freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def gold_major_index_mins_technical_state_staging_path(
    root: Path,
    run_id: str,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "indicator",
        "major_index_mins_technical_state",
        "_staging",
        _safe_run_id_part(run_id, asset_family="major_index_mins_technical_state"),
        f"freq={normalize_major_index_mins_technical_freq(freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def raw_index_mins_path(root: Path, source_freq: str, partition_key: str) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "index_mins",
        f"freq={normalize_index_mins_source_freq(source_freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_major_index_mins_path(
    root: Path,
    source_freq: str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        RAW,
        "tushare",
        "major_index_mins",
        f"freq={normalize_major_index_mins_source_freq(source_freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def raw_major_index_mins_staging_path(
    root: Path,
    run_id: str,
    source_freq: str,
    partition_key: str,
) -> Path:
    safe_run_id = str(run_id).strip()
    if (
        not safe_run_id
        or safe_run_id in {".", ".."}
        or "/" in safe_run_id
        or "\\" in safe_run_id
    ):
        raise ValueError("major_index_mins run_id must be a safe non-empty path component")
    return lake_path(
        root,
        RAW,
        "tushare",
        "major_index_mins",
        "_staging",
        f"run_id={safe_run_id}",
        f"freq={normalize_major_index_mins_source_freq(source_freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def silver_major_index_mins_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "major_index_mins",
        f"freq={normalize_major_index_mins_silver_freq(freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def silver_major_index_mins_staging_path(
    root: Path,
    run_id: str,
    freq: int | str,
    partition_key: str,
) -> Path:
    safe_run_id = str(run_id).strip()
    if (
        not safe_run_id
        or safe_run_id in {".", ".."}
        or "/" in safe_run_id
        or "\\" in safe_run_id
    ):
        raise ValueError("major_index_mins run_id must be a safe non-empty path component")
    return lake_path(
        root,
        SILVER,
        "quote",
        "major_index_mins",
        "_staging",
        f"run_id={safe_run_id}",
        f"freq={normalize_major_index_mins_silver_freq(freq)}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def gold_major_index_mins_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        root,
        GOLD,
        "quote",
        "major_index_mins",
        f"freq={int(str(freq).lower().removesuffix('min').removesuffix('m'))}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def gold_major_index_mins_staging_path(
    staging_root: Path,
    run_id: str,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        staging_root,
        GOLD,
        "quote",
        "major_index_mins",
        "_staging",
        f"run_id={_safe_run_id_part(run_id, asset_family='gold_major_index_mins')}",
        f"freq={int(str(freq).lower().removesuffix('min').removesuffix('m'))}",
        f"trade_date={_major_index_mins_partition_component(partition_key)}",
        "part-000.parquet",
    )


def _major_index_mins_partition_component(partition_key: str) -> str:
    if partition_key == PATH_TEMPLATE_PARTITION_KEY:
        return partition_key
    return normalize_major_index_mins_trade_date(partition_key)


def silver_index_mins_path(root: Path, freq: int | str, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "quote",
        "index_mins",
        f"freq={normalize_index_mins_silver_freq(freq)}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_index_mins_path(root: Path, freq: int | str, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "quote",
        "index_mins",
        f"freq={int(str(freq).lower().removesuffix('min').removesuffix('m'))}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def gold_index_mins_staging_path(
    staging_root: Path,
    run_id: str,
    freq: int | str,
    partition_key: str,
) -> Path:
    return lake_path(
        staging_root,
        GOLD,
        "quote",
        "index_mins",
        "_staging",
        f"run_id={_safe_run_id_part(run_id, asset_family='gold_index_mins')}",
        f"freq={int(str(freq).lower().removesuffix('min').removesuffix('m'))}",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def _validate_staging_component(value: str, *, name: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"index_global {name} must be a safe non-empty path component")
    return value


def raw_index_global_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        RAW,
        "index_global",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def raw_index_global_staging_path(
    root: Path,
    run_id: str,
    trade_date: str,
    probe_phase: str,
) -> Path:
    safe_run_id = _validate_staging_component(run_id, name="run_id")
    safe_phase = _validate_staging_component(probe_phase, name="probe_phase")
    return lake_path(
        root,
        RAW,
        "index_global",
        "_staging",
        f"run_id={safe_run_id}",
        f"trade_date={trade_date}",
        f"probe_phase={safe_phase}",
        "part-000.parquet",
    )


def silver_index_global_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "index_global",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def silver_index_global_staging_path(
    root: Path,
    run_id: str,
    trade_date: str,
) -> Path:
    safe_run_id = _validate_staging_component(run_id, name="run_id")
    return lake_path(
        root,
        SILVER,
        "index_global",
        "_staging",
        f"run_id={safe_run_id}",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def silver_index_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "index_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )


def raw_dc_index_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        RAW,
        "board",
        "dc_index",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def raw_dc_member_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        RAW,
        "board",
        "dc_member",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def raw_dc_daily_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        RAW,
        "board",
        "dc_daily",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def silver_dc_index_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "board",
        "dc_index",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def silver_dc_industry_hierarchy_path(root: Path) -> Path:
    return lake_path(
        root,
        SILVER,
        "board",
        "dc_industry_hierarchy",
        "full",
        "part-000.parquet",
    )


def silver_dc_member_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "board",
        "dc_member",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def silver_dc_daily_path(root: Path, trade_date: str) -> Path:
    return lake_path(
        root,
        SILVER,
        "board",
        "dc_daily",
        f"trade_date={trade_date}",
        "part-000.parquet",
    )


def gold_market_major_indices_daily_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "market",
        "major_indices_daily",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )
