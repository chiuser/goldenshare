import dagster as dg

from orchestrator.defs.duckdb_sql import cn_a_trade_day_partition_keys_select
from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path


@dg.op(
    name="sync_cn_a_trade_day_partitions_op",
    required_resource_keys={"lake_root", "duckdb"},
    out=dg.Out(list[str]),
    description="Register 2026-04 SSE open trading days from silver_trade_calendar.",
)
def sync_cn_a_trade_day_partitions_op(context: dg.OpExecutionContext) -> dg.Output[list[str]]:
    lake_root = context.resources.lake_root
    duckdb = context.resources.duckdb

    lake_root.ensure_available_for_run()
    silver_path = silver_trade_calendar_path(lake_root.root())
    if not silver_path.exists():
        raise FileNotFoundError(f"Missing silver trade calendar file: {silver_path}")

    with duckdb.connect() as connection:
        rows = connection.execute(cn_a_trade_day_partition_keys_select(silver_path)).fetchall()

    partition_keys = [row[0] for row in rows]
    if not partition_keys:
        raise ValueError("No 2026-04 SSE open trading days found in silver_trade_calendar.")

    existing_keys_before = set(context.instance.get_dynamic_partitions(cn_a_trade_days.name))
    context.instance.add_dynamic_partitions(cn_a_trade_days.name, partition_keys)
    existing_keys_after = set(context.instance.get_dynamic_partitions(cn_a_trade_days.name))

    added_keys = sorted(existing_keys_after - existing_keys_before)
    context.log.info(
        "Registered %s cn_a_trade_days partition keys; newly added %s.",
        len(partition_keys),
        len(added_keys),
    )

    return dg.Output(
        partition_keys,
        metadata={
            "partition_definition": cn_a_trade_days.name,
            "source_path": str(silver_path),
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
            "exchange": "SSE",
            "partition_key_count": len(partition_keys),
            "newly_added_count": len(added_keys),
            "partition_key_sample": partition_keys[:10],
            "newly_added_sample": added_keys[:10],
        },
    )


@dg.job(
    name="sync_cn_a_trade_day_partitions",
    description="Register Dagster dynamic partition keys for 2026-04 CN A-share trading days.",
)
def sync_cn_a_trade_day_partitions() -> None:
    sync_cn_a_trade_day_partitions_op()
