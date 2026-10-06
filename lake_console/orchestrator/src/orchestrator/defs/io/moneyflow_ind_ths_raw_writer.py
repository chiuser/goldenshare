"""Persist source pages and produce verified THS industry Raw candidates."""

import json
from decimal import Decimal
from pathlib import Path

from orchestrator.defs.checks.moneyflow_ind_ths import (
    audit_industry_moneyflow_equality,
    audit_industry_moneyflow_file,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
    write_moneyflow_receipt,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.run_contracts.moneyflow_ind_ths import (
    MONEYFLOW_IND_THS_FIELDS,
    industry_numeric_rejection_sql,
)
from orchestrator.defs.source_readiness.moneyflow_ind_ths import (
    collect_industry_moneyflow,
)


def _decimal_json(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported_source_scalar:{type(value).__name__}")


def insert_industry_moneyflow_page(
    connection, source: Path, round_number: int, trade_date: str
) -> None:
    if round_number not in (1, 2):
        raise MoneyflowContractError("source_round")
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE source_json AS SELECT json FROM read_json_objects(?,format='array')",
        [str(source)],
    )
    expected_keys = "[" + ",".join(f"'{f}'" for f in MONEYFLOW_IND_THS_FIELDS) + "]"
    invalid_schema = connection.execute(
        f"SELECT count(*) FROM source_json WHERE list_sort(json_keys(json)) != list_sort({expected_keys})"
    ).fetchone()[0]
    if invalid_schema:
        sample = connection.execute(
            f"SELECT json_keys(json) FROM source_json WHERE list_sort(json_keys(json)) != list_sort({expected_keys}) LIMIT 3"
        ).fetchall()
        raise MoneyflowContractError(f"source_row_schema:{sample}")
    extraction = ",".join(
        f"json_extract_string(json,'$.{f}') AS \"{f}\",json_type(json,'$.{f}') AS \"{f}_json_type\""
        for f in MONEYFLOW_IND_THS_FIELDS
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE source_page AS SELECT {extraction} FROM source_json"
    )
    invalid_identity = connection.execute(
        "SELECT count(*) FROM source_page WHERE trade_date_json_type != 'VARCHAR' "
        "OR trade_date IS NULL OR trade_date != ? OR ts_code_json_type != 'VARCHAR' "
        "OR ts_code IS NULL OR trim(ts_code)=''",
        [trade_date.replace("-", "")],
    ).fetchone()[0]
    if invalid_identity:
        sample = connection.execute(
            "SELECT substring(trade_date,1,32),substring(ts_code,1,80) FROM source_page "
            "WHERE trade_date_json_type != 'VARCHAR' OR trade_date IS NULL OR trade_date != ? "
            "OR ts_code_json_type != 'VARCHAR' OR ts_code IS NULL OR trim(ts_code)='' LIMIT 3",
            [trade_date.replace("-", "")],
        ).fetchall()
        raise MoneyflowContractError(f"source_partition_or_key:{sample}")
    invalid_text = connection.execute(
        "SELECT count(*) FROM source_page WHERE industry_json_type NOT IN ('NULL','VARCHAR') "
        "OR lead_stock_json_type NOT IN ('NULL','VARCHAR')"
    ).fetchone()[0]
    if invalid_text:
        sample = connection.execute(
            "SELECT substring(ts_code,1,80),industry_json_type,lead_stock_json_type FROM source_page "
            "WHERE industry_json_type NOT IN ('NULL','VARCHAR') OR lead_stock_json_type NOT IN ('NULL','VARCHAR') LIMIT 3"
        ).fetchall()
        raise MoneyflowContractError(f"source_text_type:{sample}")
    numeric_invalid = " OR ".join(
        industry_numeric_rejection_sql(c.name, c.type)
        for c in RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA
        if c.type != "VARCHAR"
    )
    if connection.execute(
        f"SELECT count(*) FROM source_page WHERE {numeric_invalid}"
    ).fetchone()[0]:
        failures = " UNION ALL ".join(
            f"SELECT substring(ts_code,1,80) AS ts_code,'{c.name}' AS field,substring(\"{c.name}\",1,80) AS value "
            f"FROM source_page WHERE {industry_numeric_rejection_sql(c.name, c.type)}"
            for c in RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA
            if c.type != "VARCHAR"
        )
        sample = connection.execute(f"SELECT * FROM ({failures}) LIMIT 3").fetchall()
        raise MoneyflowContractError(f"source_numeric_contract:{sample}")
    table = f"industry_round_{round_number}"
    declaration = ",".join(
        f'"{c.name}" {c.type}' for c in RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA
    )
    projection = ",".join(
        f'CAST("{c.name}" AS {c.type}) AS "{c.name}"'
        for c in RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA
    )
    connection.execute(f"CREATE TEMP TABLE IF NOT EXISTS {table} ({declaration})")
    connection.execute(f"INSERT INTO {table} SELECT {projection} FROM source_page")
    count, keys = connection.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,ts_code)) FROM {table}"
    ).fetchone()
    if count != keys:
        sample = connection.execute(
            f"SELECT trade_date,substring(ts_code,1,80),count(*) FROM {table} GROUP BY trade_date,ts_code HAVING count(*) > 1 LIMIT 3"
        ).fetchall()
        raise MoneyflowContractError(f"source_duplicate_key:{sample}")


def build_industry_moneyflow_raw_candidate(
    *,
    tushare,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    **collection_options,
) -> Path:
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset="moneyflow_ind_ths"
    )
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise MoneyflowContractError("operation_conflict") from error
    raw = directory / "raw.parquet"
    verification = directory / "verification.parquet"
    write_moneyflow_receipt(
        directory,
        {
            "stage": "collecting",
            "trade_date": trade_date,
            "dataset": "moneyflow_ind_ths",
        },
    )
    with moneyflow_candidate_connection(directory) as connection:

        def consume_page(round_number, offset, rows):
            pages = directory / f"round-{round_number}"
            pages.mkdir(exist_ok=True)
            page = pages / f"page-{offset}.json"
            with page.open("x") as stream:
                json.dump(rows, stream, default=_decimal_json)
            insert_industry_moneyflow_page(connection, page, round_number, trade_date)

        def complete_round(round_number, count):
            target = raw if round_number == 1 else verification
            connection.execute(
                f"COPY (SELECT * FROM industry_round_{round_number} ORDER BY trade_date,ts_code) TO $target (FORMAT PARQUET)",
                {"target": str(target)},
            )
            if audit_industry_moneyflow_file(connection, target, trade_date) != count:
                raise MoneyflowContractError("source_count")
            if round_number == 1:
                connection.execute("DROP TABLE industry_round_1")
            else:
                audit_industry_moneyflow_equality(connection, raw, verification)

        collected = collect_industry_moneyflow(
            tushare=tushare,
            trade_date=trade_date,
            consume_page=consume_page,
            complete_round=complete_round,
            **collection_options,
        )
    write_moneyflow_receipt(
        directory,
        {
            "stage": "raw_candidate_ready",
            "dataset": "moneyflow_ind_ths",
            "source": "tushare",
            "trade_date": trade_date,
            "row_count": collected.row_count,
            "raw_sha256": candidate_file_hash(raw),
            "verification_sha256": candidate_file_hash(verification),
            "request_count": collected.request_count,
            "retry_count": collected.retry_count,
            "elapsed_ms": collected.elapsed_ms,
            "peak_rss_bytes": collected.peak_rss_bytes,
            "stability_gap_seconds": collected.stability_gap_seconds,
        },
    )
    return raw
