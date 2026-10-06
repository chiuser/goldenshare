"""THS industry source columns and exact SQL numeric validation."""

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA,
)

MONEYFLOW_IND_THS_FIELDS = tuple(c.name for c in RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA)


def industry_numeric_rejection_sql(name: str, target_type: str) -> str:
    """Validate lexical scale before CAST, which otherwise silently rounds."""
    value = f'"{name}"'
    kind = f'"{name}_json_type"'
    scale = 0 if target_type == "INTEGER" else int(target_type.split(",")[1][:-1])
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
