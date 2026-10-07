"""Physical independent board contracts for candidates and future blocking checks."""

from datetime import date
from pathlib import Path

from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ROWS_PER_ROUND,
    MoneyflowContractError,
    market_moneyflow_day,
)
from orchestrator.defs.run_contracts.moneyflow_board import (
    board_key_fields,
    board_request_scopes,
    board_schema,
)


def board_file_scope_counts(connection, path: Path, *, dataset: str):
    scopes = board_request_scopes(dataset)
    if scopes == (None,):
        return {
            "all": connection.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                [str(path)],
            ).fetchone()[0]
        }
    counts = dict(
        connection.execute(
            "SELECT content_type,count(*) FROM read_parquet(?,hive_partitioning=false) GROUP BY content_type",
            [str(path)],
        ).fetchall()
    )
    if set(counts) != set(scopes):
        raise MoneyflowContractError("file_scope_coverage")
    return counts


def audit_board_moneyflow_file(
    connection, path: Path, trade_date: str, *, dataset: str, silver=False
) -> int:
    day = market_moneyflow_day(trade_date)
    schema = board_schema(dataset, silver=silver)
    if not path.is_file():
        raise MoneyflowContractError("file_missing")
    try:
        actual = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchall()
        if [(r[0], r[1]) for r in actual] != [(c.name, c.type) for c in schema]:
            raise MoneyflowContractError("file_schema")
        key_fields = board_key_fields(dataset)
        key_sql = ",".join(key_fields)
        invalid_key = " OR ".join(
            f"{f} IS NULL OR trim({f})=''" for f in key_fields if f != "trade_date"
        )
        count, invalid, keys = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE trade_date IS NULL OR trade_date != ? "
            f"OR {invalid_key}),count(DISTINCT ({key_sql})) "
            "FROM read_parquet(?,hive_partitioning=false)",
            [date.fromisoformat(day) if silver else day.replace("-", ""), str(path)],
        ).fetchone()
        if not 0 < count <= MONEYFLOW_MAX_ROWS_PER_ROUND or invalid or keys != count:
            raise MoneyflowContractError("file_count_date_or_key")
        board_file_scope_counts(connection, path, dataset=dataset)
        return count
    except MoneyflowContractError:
        raise
    except Exception as error:
        raise MoneyflowContractError("file_unreadable") from error


def audit_board_moneyflow_equality(
    connection, first: Path, second: Path, *, dataset: str, second_silver=False
) -> None:
    for path, silver in ((first, False), (second, second_silver)):
        schema = board_schema(dataset, silver=silver)
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


def audit_board_moneyflow_standardization(
    connection, raw: Path, silver: Path, trade_date: str, *, dataset: str
) -> int:
    count = audit_board_moneyflow_file(connection, raw, trade_date, dataset=dataset)
    if (
        audit_board_moneyflow_file(
            connection, silver, trade_date, silver=True, dataset=dataset
        )
        != count
    ):
        raise MoneyflowContractError("standardization_count")
    audit_board_moneyflow_equality(
        connection, raw, silver, second_silver=True, dataset=dataset
    )
    return count
