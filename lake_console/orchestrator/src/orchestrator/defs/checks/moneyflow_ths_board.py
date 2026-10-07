"""Physical independent THS board contracts for candidates and future blocking checks."""

from datetime import date
from pathlib import Path

from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ROWS_PER_ROUND,
    MoneyflowContractError,
    market_moneyflow_day,
)
from orchestrator.defs.run_contracts.moneyflow_ths_board import ths_board_schema


def audit_ths_board_moneyflow_file(
    connection, path: Path, trade_date: str, *, dataset: str, silver=False
) -> int:
    day = market_moneyflow_day(trade_date)
    schema = ths_board_schema(dataset, silver=silver)
    if not path.is_file():
        raise MoneyflowContractError("file_missing")
    try:
        actual = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchall()
        if [(r[0], r[1]) for r in actual] != [(c.name, c.type) for c in schema]:
            raise MoneyflowContractError("file_schema")
        count, invalid, keys = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE trade_date IS NULL OR trade_date != ? "
            "OR ts_code IS NULL OR trim(ts_code)=''),count(DISTINCT (trade_date,ts_code)) "
            "FROM read_parquet(?,hive_partitioning=false)",
            [date.fromisoformat(day) if silver else day.replace("-", ""), str(path)],
        ).fetchone()
        if not 0 < count <= MONEYFLOW_MAX_ROWS_PER_ROUND or invalid or keys != count:
            raise MoneyflowContractError("file_count_date_or_key")
        return count
    except MoneyflowContractError:
        raise
    except Exception as error:
        raise MoneyflowContractError("file_unreadable") from error


def audit_ths_board_moneyflow_equality(
    connection, first: Path, second: Path, *, dataset: str, second_silver=False
) -> None:
    for path, silver in ((first, False), (second, second_silver)):
        schema = ths_board_schema(dataset, silver=silver)
        actual = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchall()
        if [(r[0], r[1]) for r in actual] != [(c.name, c.type) for c in schema]:
            raise MoneyflowContractError("file_schema")
    second_projection = (
        "* REPLACE(strftime(trade_date,'%Y%m%d') AS trade_date)"
        if second_silver
        else "*"
    )
    difference = connection.execute(
        "SELECT count(*) FROM ((SELECT * FROM read_parquet($first,hive_partitioning=false) EXCEPT "
        f"SELECT {second_projection} FROM read_parquet($second,hive_partitioning=false)) UNION ALL "
        f"(SELECT {second_projection} FROM read_parquet($second,hive_partitioning=false) EXCEPT "
        "SELECT * FROM read_parquet($first,hive_partitioning=false)))",
        {"first": str(first), "second": str(second)},
    ).fetchone()[0]
    if difference:
        raise MoneyflowContractError(
            "source_unstable" if not second_silver else "standardization_difference"
        )


def audit_ths_board_moneyflow_standardization(
    connection, raw: Path, silver: Path, trade_date: str, *, dataset: str
) -> int:
    count = audit_ths_board_moneyflow_file(connection, raw, trade_date, dataset=dataset)
    if (
        audit_ths_board_moneyflow_file(
            connection, silver, trade_date, silver=True, dataset=dataset
        )
        != count
    ):
        raise MoneyflowContractError("standardization_count")
    audit_ths_board_moneyflow_equality(
        connection, raw, silver, second_silver=True, dataset=dataset
    )
    return count
