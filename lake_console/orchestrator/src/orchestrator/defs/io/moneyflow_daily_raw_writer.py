"""Persist source pages and produce verified independent daily moneyflow Raw candidates."""

import json
from decimal import Decimal
from pathlib import Path

from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_equality,
    audit_daily_moneyflow_file,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
    write_moneyflow_receipt,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.run_contracts.moneyflow_daily import (
    daily_fields,
    daily_key_fields,
    daily_numeric_rejection_sql,
    daily_request_scopes,
    daily_schema,
)
from orchestrator.defs.source_readiness.moneyflow_daily import (
    collect_daily_moneyflow,
)


def _decimal_json(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported_source_scalar:{type(value).__name__}")


def insert_daily_moneyflow_page(
    connection,
    source: Path,
    round_number: int,
    trade_date: str,
    *,
    dataset: str,
    content_type: str | None,
) -> None:
    schema = daily_schema(dataset)
    fields = daily_fields(dataset)
    key_fields = daily_key_fields(dataset)
    key_sample_sql = ",".join(f"substring({f},1,80) AS {f}" for f in key_fields)
    if content_type not in daily_request_scopes(dataset):
        raise MoneyflowContractError("source_scope")
    if round_number not in (1, 2):
        raise MoneyflowContractError("source_round")
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE source_json AS SELECT json FROM read_json_objects(?,format='array')",
        [str(source)],
    )
    expected_keys = "[" + ",".join(f"'{f}'" for f in fields) + "]"
    invalid_schema = connection.execute(
        f"SELECT count(*) FROM source_json WHERE list_sort(json_keys(json)) != list_sort({expected_keys})"
    ).fetchone()[0]
    if invalid_schema:
        sample = connection.execute(
            f"SELECT json_keys(json) FROM source_json WHERE list_sort(json_keys(json)) != list_sort({expected_keys}) LIMIT 3"
        ).fetchall()
        raise MoneyflowContractError(f"source_row_schema:{sample}")
    paths = "[" + ",".join(f"'$.{f}'" for f in fields) + "]"
    extraction = ",".join(
        f'values_list[{i}] AS "{f}",types_list[{i}] AS "{f}_json_type"'
        for i, f in enumerate(fields, start=1)
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE source_page AS WITH extracted AS MATERIALIZED "
        f"(SELECT json_extract_string(json,{paths}) AS values_list,"
        f"json_type(json,{paths}) AS types_list FROM source_json) SELECT {extraction} FROM extracted"
    )
    connection.execute("DROP TABLE source_json")
    invalid_identity_sql = (
        " OR ".join(
            f"{f}_json_type != 'VARCHAR' OR {f} IS NULL OR trim({f})=''"
            for f in key_fields
        )
        + " OR trade_date != ?"
    )
    identity_params = [trade_date.replace("-", "")]
    if content_type is not None:
        invalid_identity_sql += " OR content_type != ?"
        identity_params.append(content_type)
    if connection.execute(
        f"SELECT count(*) FROM source_page WHERE {invalid_identity_sql}",
        identity_params,
    ).fetchone()[0]:
        projection = ",".join(f"substring({f},1,80)" for f in key_fields)
        sample = connection.execute(
            f"SELECT {projection} FROM source_page WHERE {invalid_identity_sql} LIMIT 3",
            identity_params,
        ).fetchall()
        raise MoneyflowContractError(f"source_partition_or_key:{sample}")
    text_columns = [
        c.name for c in schema if c.type == "VARCHAR" and c.name not in key_fields
    ]
    text_invalid = " OR ".join(
        f"{name}_json_type NOT IN ('NULL','VARCHAR')" for name in text_columns
    )
    if (
        text_columns
        and connection.execute(
            f"SELECT count(*) FROM source_page WHERE {text_invalid}"
        ).fetchone()[0]
    ):
        projection = ",".join(f"{name}_json_type" for name in text_columns)
        sample = connection.execute(
            f"SELECT {key_sample_sql},{projection} FROM source_page WHERE {text_invalid} LIMIT 3"
        ).fetchall()
        raise MoneyflowContractError(f"source_text_type:{sample}")
    numeric_invalid = " OR ".join(
        daily_numeric_rejection_sql(c.name, c.type)
        for c in schema
        if c.type != "VARCHAR"
    )
    if connection.execute(
        f"SELECT count(*) FROM source_page WHERE {numeric_invalid}"
    ).fetchone()[0]:
        failures = " UNION ALL ".join(
            f"SELECT {key_sample_sql},'{c.name}' AS field,substring(\"{c.name}\",1,80) AS value "
            f"FROM source_page WHERE {daily_numeric_rejection_sql(c.name, c.type)}"
            for c in schema
            if c.type != "VARCHAR"
        )
        sample = connection.execute(f"SELECT * FROM ({failures}) LIMIT 3").fetchall()
        raise MoneyflowContractError(f"source_numeric_contract:{sample}")
    table = f"daily_round_{round_number}"
    declaration = ",".join(f'"{c.name}" {c.type}' for c in schema)
    projection = ",".join(f'CAST("{c.name}" AS {c.type}) AS "{c.name}"' for c in schema)
    connection.execute(f"CREATE TEMP TABLE IF NOT EXISTS {table} ({declaration})")
    connection.execute(f"INSERT INTO {table} SELECT {projection} FROM source_page")
    connection.execute("DROP TABLE source_page")
    key_sql = ",".join(key_fields)
    count, keys = connection.execute(
        f"SELECT count(*),count(DISTINCT ({key_sql})) FROM {table}"
    ).fetchone()
    if count != keys:
        sample = connection.execute(
            f"SELECT {key_sample_sql},count(*) FROM {table} GROUP BY {key_sql} HAVING count(*) > 1 LIMIT 3"
        ).fetchall()
        raise MoneyflowContractError(f"source_duplicate_key:{sample}")


def build_daily_moneyflow_raw_candidate(
    *,
    tushare,
    dataset: str,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    **collection_options,
) -> Path:
    daily_schema(dataset)
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset=dataset
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
            "dataset": dataset,
        },
    )
    with moneyflow_candidate_connection(directory) as connection:

        def consume_page(round_number, content_type, offset, rows):
            scope_number = daily_request_scopes(dataset).index(content_type) + 1
            pages = directory / f"round-{round_number}" / f"scope-{scope_number}"
            pages.mkdir(parents=True, exist_ok=True)
            page = pages / f"page-{offset}.json"
            with page.open("x") as stream:
                json.dump(rows, stream, default=_decimal_json)
            insert_daily_moneyflow_page(
                connection,
                page,
                round_number,
                trade_date,
                dataset=dataset,
                content_type=content_type,
            )

        def complete_round(round_number, count):
            key_sql = ",".join(daily_key_fields(dataset))
            target = raw if round_number == 1 else verification
            connection.execute(
                f"COPY (SELECT * FROM daily_round_{round_number} ORDER BY {key_sql}) TO $target (FORMAT PARQUET)",
                {"target": str(target)},
            )
            if (
                audit_daily_moneyflow_file(
                    connection, target, trade_date, dataset=dataset
                )
                != count
            ):
                raise MoneyflowContractError("source_count")
            if round_number == 1:
                connection.execute("DROP TABLE daily_round_1")
            else:
                audit_daily_moneyflow_equality(
                    connection, raw, verification, dataset=dataset
                )

        collected = collect_daily_moneyflow(
            tushare=tushare,
            trade_date=trade_date,
            consume_page=consume_page,
            complete_round=complete_round,
            **collection_options,
            dataset=dataset,
        )
    write_moneyflow_receipt(
        directory,
        {
            "stage": "raw_candidate_ready",
            "dataset": dataset,
            "source": "tushare",
            "trade_date": trade_date,
            "row_count": collected.row_count,
            "scope_row_counts": dict(
                zip(
                    (s or "all" for s in daily_request_scopes(dataset)),
                    collected.scope_row_counts,
                    strict=True,
                )
            ),
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
