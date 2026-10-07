"""Independent daily moneyflow source columns and exact SQL numeric validation."""

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_CNT_THS_SCHEMA,
    RAW_TUSHARE_MONEYFLOW_DC_SCHEMA,
    RAW_TUSHARE_MONEYFLOW_IND_DC_SCHEMA,
    RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA,
    RAW_TUSHARE_MONEYFLOW_SCHEMA,
    SILVER_MONEYFLOW_CNT_THS_SCHEMA,
    SILVER_MONEYFLOW_DC_SCHEMA,
    SILVER_MONEYFLOW_IND_DC_SCHEMA,
    SILVER_MONEYFLOW_IND_THS_SCHEMA,
    SILVER_MONEYFLOW_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError


def daily_schema(dataset: str, *, silver=False):
    """Select a fixed source contract; never infer identity from page contents."""
    if dataset == "moneyflow":
        return SILVER_MONEYFLOW_SCHEMA if silver else RAW_TUSHARE_MONEYFLOW_SCHEMA
    if dataset == "moneyflow_dc":
        return SILVER_MONEYFLOW_DC_SCHEMA if silver else RAW_TUSHARE_MONEYFLOW_DC_SCHEMA
    if dataset == "moneyflow_ind_ths":
        return (
            SILVER_MONEYFLOW_IND_THS_SCHEMA
            if silver
            else RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA
        )
    if dataset == "moneyflow_cnt_ths":
        return (
            SILVER_MONEYFLOW_CNT_THS_SCHEMA
            if silver
            else RAW_TUSHARE_MONEYFLOW_CNT_THS_SCHEMA
        )
    if dataset == "moneyflow_ind_dc":
        return (
            SILVER_MONEYFLOW_IND_DC_SCHEMA
            if silver
            else RAW_TUSHARE_MONEYFLOW_IND_DC_SCHEMA
        )
    raise MoneyflowContractError("daily_dataset")


def daily_fields(dataset: str):
    return tuple(c.name for c in daily_schema(dataset))


def daily_key_fields(dataset: str):
    daily_schema(dataset)
    return (
        ("trade_date", "content_type", "name")
        if dataset == "moneyflow_ind_dc"
        else ("trade_date", "ts_code")
    )


def daily_request_scopes(dataset: str):
    daily_schema(dataset)
    return ("行业", "概念", "地域") if dataset == "moneyflow_ind_dc" else (None,)


def daily_numeric_rejection_sql(name: str, target_type: str) -> str:
    """Validate lexical scale before CAST, which otherwise silently rounds."""
    value = f'"{name}"'
    kind = f'"{name}_json_type"'
    scale = (
        0
        if target_type in ("INTEGER", "BIGINT")
        else int(target_type.split(",")[1][:-1])
    )
    # Integer trailing zeros also cancel a negative scientific exponent.
    mantissa = f"regexp_extract({value}, '^[-+]?([0-9]+(?:\\.[0-9]+)?)', 1)"
    digits = f"replace({mantissa}, '.', '')"
    fraction = f"length(regexp_extract({value}, '\\.([0-9]+)', 1)) - (length({digits}) - length(rtrim({digits}, '0')))"
    exponent_text = f"nullif(regexp_extract({value}, '[eE]([-+]?[0-9]+)', 1), '')"
    exponent = f"coalesce(try_cast({exponent_text} AS INTEGER), 0)"
    zero = f"regexp_full_match({value}, '[-+]?0+(\\.0+)?([eE][-+]?[0-9]+)?')"
    return (
        f"({kind} != 'NULL' AND ("
        f"{kind} NOT IN ('VARCHAR','BIGINT','UBIGINT','DOUBLE') OR "
        f"NOT regexp_full_match({value}, '[-+]?[0-9]+(\\.[0-9]+)?([eE][-+]?[0-9]+)?') OR "
        f"try_cast({value} AS {target_type}) IS NULL OR "
        f"({exponent_text} IS NOT NULL AND try_cast({exponent_text} AS INTEGER) IS NULL) OR "
        f"(NOT {zero} AND {fraction} - {exponent} > {scale}) OR "
        f"({kind} = 'DOUBLE' AND abs(try_cast({value} AS DOUBLE)) >= 9007199254740992)))"
    )
