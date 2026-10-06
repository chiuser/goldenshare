"""Physical market file checks shared by candidates and future asset checks."""

from datetime import date
from pathlib import Path

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA,
    SILVER_MONEYFLOW_MKT_DC_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MoneyflowContractError,
    market_moneyflow_day,
)


def audit_market_moneyflow_file(
    connection, path: Path, trade_date: str, *, silver=False
) -> None:
    day = market_moneyflow_day(trade_date)
    schema = (
        SILVER_MONEYFLOW_MKT_DC_SCHEMA
        if silver
        else RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA
    )
    if not path.is_file():
        raise MoneyflowContractError("file_missing")
    try:
        actual = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [str(path)],
        ).fetchall()
        if [(r[0], r[1]) for r in actual] != [(c.name, c.type) for c in schema]:
            raise MoneyflowContractError("file_schema")
        total, invalid = connection.execute(
            "SELECT count(*), count(*) FILTER(WHERE trade_date IS NULL OR trade_date != ?) "
            "FROM read_parquet(?, hive_partitioning=false)",
            [date.fromisoformat(day) if silver else day.replace("-", ""), str(path)],
        ).fetchone()
        if total != 1 or invalid:
            raise MoneyflowContractError("file_count_or_date")
    except MoneyflowContractError:
        raise
    except Exception as error:
        raise MoneyflowContractError("file_unreadable") from error


def audit_market_moneyflow_standardization(
    connection, raw: Path, silver: Path, trade_date: str
) -> None:
    audit_market_moneyflow_file(connection, raw, trade_date)
    audit_market_moneyflow_file(connection, silver, trade_date, silver=True)
    difference = connection.execute(
        "SELECT count(*) FROM ("
        "(SELECT * FROM read_parquet(?,hive_partitioning=false) EXCEPT "
        "SELECT * REPLACE(strftime(trade_date,'%Y%m%d') AS trade_date) FROM read_parquet(?,hive_partitioning=false)) "
        "UNION ALL (SELECT * REPLACE(strftime(trade_date,'%Y%m%d') AS trade_date) FROM read_parquet(?,hive_partitioning=false) "
        "EXCEPT SELECT * FROM read_parquet(?,hive_partitioning=false)))",
        [str(raw), str(silver), str(silver), str(raw)],
    ).fetchone()[0]
    if difference:
        raise MoneyflowContractError("standardization_difference")
