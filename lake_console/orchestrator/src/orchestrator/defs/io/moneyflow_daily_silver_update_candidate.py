"""Build and reconcile one daily moneyflow Silver candidate from its Raw file."""

from functools import partial

from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
)
from orchestrator.defs.run_contracts.moneyflow_daily import daily_key_fields


def build_daily_moneyflow_silver_update_candidate(
    connection, *, raw, candidate, trade_date, dataset, checkpoint
):
    audit_file = partial(audit_daily_moneyflow_file, dataset=dataset)
    audit_standardization = partial(
        audit_daily_moneyflow_standardization, dataset=dataset
    )
    count = audit_file(connection, raw, trade_date)
    if not checkpoint.exists():
        if candidate.exists():
            audit_standardization(connection, raw, candidate, trade_date)
        else:
            connection.execute(
                "COPY (SELECT * REPLACE(strptime(trade_date,'%Y%m%d')::DATE AS trade_date) "
                f"FROM read_parquet($source,hive_partitioning=false) ORDER BY {','.join(daily_key_fields(dataset))}) TO $target (FORMAT PARQUET)",
                {"source": str(raw), "target": str(candidate)},
            )
        audit_standardization(connection, raw, candidate, trade_date)
    return count
