"""Physical independent daily moneyflow contracts for candidates and future blocking checks."""

from datetime import date
from hashlib import sha256
from pathlib import Path

from orchestrator.defs.checks.daily_audit_coverage import (
    is_requested_version,
    key_coverage,
    select_codes,
    stat_version,
    version_string,
)
from orchestrator.defs.daily_data_audit.evidence import verified_stock_daily
from orchestrator.defs.paths import silver_stock_lifecycle_path
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ROWS_PER_ROUND,
    MoneyflowContractError,
    market_moneyflow_day,
)
from orchestrator.defs.run_contracts.moneyflow_daily import (
    daily_key_fields,
    daily_request_scopes,
    daily_schema,
)


def daily_file_scope_counts(connection, path: Path, *, dataset: str):
    scopes = daily_request_scopes(dataset)
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


def audit_daily_moneyflow_file(
    connection, path: Path, trade_date: str, *, dataset: str, silver=False, observed_codes=None,
    observed_board_keys: set[tuple[str, str]] | None = None,
) -> int:
    day = market_moneyflow_day(trade_date)
    schema = daily_schema(dataset, silver=silver)
    if not path.is_file():
        raise MoneyflowContractError("file_missing")
    try:
        actual = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchall()
        if [(r[0], r[1]) for r in actual] != [(c.name, c.type) for c in schema]:
            raise MoneyflowContractError("file_schema")
        key_fields = daily_key_fields(dataset)
        key_sql = ",".join(key_fields)
        invalid_key = " OR ".join(
            f"{f} IS NULL OR trim({f})=''" for f in key_fields if f != "trade_date"
        )
        code_projection = ", list(DISTINCT ts_code)" if observed_codes is not None else ""
        if observed_board_keys is not None:
            code_projection += ", list(DISTINCT (content_type, ts_code))"
        count, invalid, keys, *collections = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE trade_date IS NULL OR trade_date != ? "
            f"OR {invalid_key}),count(DISTINCT ({key_sql})){code_projection} "
            "FROM read_parquet(?,hive_partitioning=false)",
            [date.fromisoformat(day) if silver else day.replace("-", ""), str(path)],
        ).fetchone()
        if not 0 < count <= MONEYFLOW_MAX_ROWS_PER_ROUND or invalid or keys != count:
            raise MoneyflowContractError("file_count_date_or_key")
        daily_file_scope_counts(connection, path, dataset=dataset)
        if observed_codes is not None:
            observed_codes.update(collections[0])
        if observed_board_keys is not None:
            observed_board_keys.update(collections[-1])
        return count
    except MoneyflowContractError:
        raise
    except Exception as error:
        raise MoneyflowContractError("file_unreadable") from error


def audit_moneyflow_coverage(connection, instance, root, day, dataset, actual):
    inputs = {}
    if dataset in {"moneyflow_cnt_ths", "moneyflow_ind_ths"}:
        if day < "2026-11-19":
            return None
        seed = Path(__file__).parents[2] / "seeds" / "market" / f"{dataset}.txt"
        if not seed.is_file():
            return None
        source = seed.read_bytes()
        expected = set(source.decode().splitlines())
        inputs[f"{dataset} 生效名单"] = sha256(source).hexdigest()
    elif dataset == "moneyflow_dc":
        daily = verified_stock_daily(instance, root, day)
        if daily is None:
            return None
        path, version = daily
        expected = select_codes(
            connection,
            "SELECT ts_code FROM read_parquet(?, hive_partitioning=false) "
            "WHERE trade_date = ?::DATE AND vol > 0",
            [str(path), day],
        )
        if stat_version(path) != version:
            return None
        inputs["silver_stock_daily"] = version_string(version)
    else:
        path = silver_stock_lifecycle_path(root)
        version = stat_version(path)
        if version is None:
            return None
        expected = select_codes(
            connection,
            "SELECT ts_code FROM read_parquet(?, hive_partitioning=false) "
            "WHERE is_cny_stock AND list_date <= ?::DATE "
            "AND (delist_date IS NULL OR ?::DATE < delist_date)",
            [str(path), day, day],
        )
        if stat_version(path) != version:
            return None
        inputs["silver_stock_lifecycle"] = version_string(version)
    if not expected:
        return None
    return {
        **key_coverage(
            expected, actual,
            record_extras=dataset == "moneyflow_cnt_ths",
            confirm_changes=dataset == "moneyflow_cnt_ths",
        ),
        "inputs": inputs,
        "rule_version": "moneyflow_expected_codes_v1",
    }


def audit_covered_raw_moneyflow_file(connection, context, root, path, day, *, dataset):
    version = stat_version(path)
    collect_codes = version is not None and (
        dataset != "moneyflow_dc" or is_requested_version(context, version)
    )
    actual = set() if collect_codes else None
    count = audit_daily_moneyflow_file(
        connection, path, day, dataset=dataset, observed_codes=actual
    )
    if actual is None:
        return count, None
    coverage = audit_moneyflow_coverage(connection, context.instance, root, day, dataset, actual)
    if not coverage or stat_version(path) != version:
        return count, None
    return count, {**coverage, "file_version": version}


def audit_daily_moneyflow_equality(
    connection, first: Path, second: Path, *, dataset: str, second_silver=False,
    ts_codes=None,
) -> None:
    for path, silver in ((first, False), (second, second_silver)):
        schema = daily_schema(dataset, silver=silver)
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
    params = {"first": str(first), "second": str(second)}
    predicate = ""
    if ts_codes is not None:
        predicate = " WHERE ts_code IN (SELECT unnest($codes))"
        params["codes"] = sorted(ts_codes)
    first_query = f"SELECT * FROM read_parquet($first,hive_partitioning=false){predicate}"
    second_query = f"SELECT {second_projection} FROM read_parquet($second,hive_partitioning=false){predicate}"
    difference = connection.execute(
        f"SELECT count(*) FROM (({first_query} EXCEPT {second_query}) "
        f"UNION ALL ({second_query} EXCEPT {first_query}))", params,
    ).fetchone()[0]
    if difference:
        raise MoneyflowContractError(
            "source_unstable" if not second_silver else "standardization_difference"
        )


def audit_daily_moneyflow_standardization(
    connection, raw: Path, silver: Path, trade_date: str, *, dataset: str
) -> int:
    count = audit_daily_moneyflow_file(connection, raw, trade_date, dataset=dataset)
    if (
        audit_daily_moneyflow_file(
            connection, silver, trade_date, silver=True, dataset=dataset
        )
        != count
    ):
        raise MoneyflowContractError("standardization_count")
    audit_daily_moneyflow_equality(
        connection, raw, silver, second_silver=True, dataset=dataset
    )
    return count
