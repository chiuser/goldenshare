"""Market Raw candidates and source receipts; no formal promotion or events."""

import json
from pathlib import Path

from orchestrator.defs.checks.moneyflow import audit_market_moneyflow_file
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
    write_moneyflow_receipt,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.source_readiness.moneyflow import collect_market_moneyflow


def build_market_moneyflow_raw_candidate(
    *,
    tushare,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    **collection_options,
) -> Path:
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset="moneyflow_mkt_dc"
    )
    target = directory / "raw.parquet"
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise MoneyflowContractError("operation_conflict") from error
    write_moneyflow_receipt(
        directory, {"stage": "collecting", "trade_date": trade_date}
    )

    def persist_first(row):
        source = directory / "source.json"
        source.write_text(json.dumps([row]))
        projection = ", ".join(
            f'CAST("{c.name}" AS {c.type}) AS "{c.name}"'
            for c in RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA
        )
        with moneyflow_candidate_connection(directory) as connection:
            connection.execute(
                f"COPY (SELECT {projection} FROM read_json($source,format='array')) TO $target (FORMAT PARQUET)",
                {"source": str(source), "target": str(target)},
            )
            audit_market_moneyflow_file(connection, target, trade_date)

    stable = collect_market_moneyflow(
        tushare=tushare,
        trade_date=trade_date,
        on_first_round=persist_first,
        **collection_options,
    )
    write_moneyflow_receipt(
        directory,
        {
            "stage": "raw_candidate_ready",
            "trade_date": trade_date,
            "source": "tushare",
            "row_count": 1,
            "row_hash": stable.row_hash,
            "raw_sha256": candidate_file_hash(target),
            "request_count": stable.request_count,
            "retry_count": stable.retry_count,
            "elapsed_ms": stable.elapsed_ms,
            "stability_gap_seconds": stable.stability_gap_seconds,
        },
    )
    return target
