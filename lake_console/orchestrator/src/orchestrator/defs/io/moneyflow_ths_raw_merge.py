"""THS source coverage, field-preserving Raw merge and final missing-code lists."""

from contextlib import contextmanager
from threading import Timer
from time import perf_counter

import duckdb

from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ROWS_PER_ROUND,
    MONEYFLOW_THS_READINESS_FILE_MAX_BYTES,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_THS_MONEYFLOW_AUTOMATION,
)
from orchestrator.defs.run_contracts.moneyflow_daily import (
    daily_fields,
    daily_key_fields,
)


@contextmanager
def moneyflow_ths_raw_connection(directory, deadline, check):
    check()
    with moneyflow_candidate_connection(directory) as connection:
        check()
        timer = Timer(max(0, deadline - perf_counter()), connection.interrupt)
        timer.start()
        try:
            yield connection
            check()
        except duckdb.Error:
            check()
            raise
        finally:
            timer.cancel()
            timer.join()


def assert_moneyflow_ths_file_budget(path):
    if path.stat().st_size > MONEYFLOW_THS_READINESS_FILE_MAX_BYTES:
        raise MoneyflowContractError("file_hash_budget")


def assert_moneyflow_ths_source_coverage(connection, raw, expected, suspended):
    missing, extra = connection.execute(
        "WITH actual AS MATERIALIZED (SELECT ts_code FROM read_parquet($raw,hive_partitioning=false)), "
        "expected AS (SELECT unnest($expected) AS ts_code) "
        "SELECT (SELECT count(*) FROM expected ANTI JOIN actual USING(ts_code)), "
        "(SELECT count(*) FROM actual WHERE ts_code NOT IN (SELECT unnest($allowed)))",
        {"raw": str(raw), "expected": sorted(expected), "allowed": sorted(expected | suspended)},
    ).fetchone()
    if extra:
        raise MoneyflowContractError("source_extra_codes")
    if missing >= STOCK_THS_MONEYFLOW_AUTOMATION.missing_record_limit:
        raise MoneyflowContractError("source_missing_codes", retryable=True)


def _moneyflow_ths_merge_query(raw, target):
    fields = daily_fields("moneyflow_ths")
    keys = daily_key_fields("moneyflow_ths")
    params = {"source": str(raw)}
    if not target.exists():
        return "SELECT * FROM read_parquet($source,hive_partitioning=false)", params
    params["old"] = str(target)
    projection = ",".join(f'coalesce(n."{f}",o."{f}") AS "{f}"' for f in fields)
    join = " AND ".join(f'n."{f}"=o."{f}"' for f in keys)
    return (
        (f"SELECT {projection} FROM read_parquet($source,hive_partitioning=false) n "
         f"FULL OUTER JOIN read_parquet($old,hive_partitioning=false) o ON {join}"),
        params,
    )


def merge_moneyflow_ths_raw_candidate(connection, raw, target, candidate):
    query, params = _moneyflow_ths_merge_query(raw, target)
    if candidate.exists():
        difference = connection.execute(
            f"WITH merged AS ({query}) SELECT count(*) FROM "
            "((SELECT * FROM merged EXCEPT SELECT * FROM read_parquet($candidate,hive_partitioning=false)) "
            "UNION ALL (SELECT * FROM read_parquet($candidate,hive_partitioning=false) EXCEPT SELECT * FROM merged))",
            {**params, "candidate": str(candidate)},
        ).fetchone()[0]
        if difference:
            raise MoneyflowContractError("update_candidate_changed")
    else:
        keys = ",".join(daily_key_fields("moneyflow_ths"))
        connection.execute(
            f"COPY (SELECT * FROM ({query}) ORDER BY {keys}) TO $candidate (FORMAT PARQUET)",
            {**params, "candidate": str(candidate)},
        )


def moneyflow_ths_raw_metadata(connection, final, expected):
    nullable = [f for f in daily_fields("moneyflow_ths") if f not in daily_key_fields("moneyflow_ths")]
    nulls = " OR ".join(f'"{f}" IS NULL' for f in nullable)
    count, missing, null_codes = connection.execute(
        "WITH final AS MATERIALIZED (SELECT * FROM read_parquet($final,hive_partitioning=false)), "
        "missing AS (SELECT unnest($expected) AS ts_code EXCEPT SELECT ts_code FROM final) "
        "SELECT (SELECT count(*) FROM final), "
        "(SELECT coalesce(list(ts_code ORDER BY ts_code),[]::VARCHAR[]) FROM missing), "
        f"(SELECT coalesce(list(DISTINCT ts_code ORDER BY ts_code) FILTER(WHERE {nulls}),[]::VARCHAR[]) FROM final)",
        {"final": str(final), "expected": sorted(expected)},
    ).fetchone()
    if not 0 < count <= MONEYFLOW_MAX_ROWS_PER_ROUND:
        raise MoneyflowContractError("file_count_date_or_key")
    return {
        "row_count": count,
        "scope_row_counts": {"all": count},
        "missing_record_codes": missing,
        "null_value_codes": null_codes,
    }
