"""主要指数周月线的受控初始化；不重新下载或审计已有源历史。"""

from dataclasses import dataclass

import dagster as dg
import pandas as pd
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.io.index_period_writer import (
    index_period_projection,
    index_period_silver_from_source_sql,
    load_index_period_calendar,
    load_index_period_listings,
    prepare_index_period_file,
    promote_index_period_file,
    synthesize_index_period,
)
from orchestrator.defs.prod_db.index_period import open_prod_index_period_rows
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_WEEKLY_SCHEMA,
    SILVER_INDEX_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_PERIOD_BOOTSTRAP_JOB_NAME,
    INDEX_WEEKLY,
    index_period_bounds,
    index_period_codes,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.run_keys import build_batch_id


def load_prod_index_period_relation(connection, resource, period, layer):
    schema = RAW_INDEX_WEEKLY_SCHEMA if layer == "raw" else SILVER_INDEX_WEEKLY_SCHEMA
    relation = f"index_period_source_{period.frequency}_{layer}"
    empty = ",".join(f'CAST(NULL AS {c.type}) AS "{c.name}"' for c in schema)
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {relation} AS SELECT {empty} WHERE false"
    )
    count = 0
    with open_prod_index_period_rows(resource, period=period, layer=layer) as cursor:
        while rows := cursor.fetchmany(cursor.itersize):
            # 有界来源批次的列式传输；业务转换与历史处理在DuckDB完成。
            batch = pd.DataFrame.from_records(rows, columns=[c.name for c in schema])
            connection.register("index_period_prod_batch", batch)
            connection.execute(
                f"INSERT INTO {relation} SELECT {index_period_projection(schema)} FROM index_period_prod_batch"
            )
            connection.unregister("index_period_prod_batch")
            count += len(rows)
            del batch, rows
    if connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0] != count:
        raise ValueError("Prod指数周期行传输数量不符")
    return relation, count


def build_index_period_silver_history(
    connection, *, root, period, raw, serving, source_count
):
    latest = connection.execute(
        f"SELECT ts_code,max(trade_date) FROM {serving} GROUP BY ts_code"
    ).fetchall()
    expected = set(index_period_codes()) - {"000680.SH"}
    if {r[0] for r in latest} != expected or len({r[1] for r in latest}) != 1:
        raise ValueError("Prod Serving当前代码或实际截至日不一致")
    as_of = latest[0][1]
    start, end = connection.execute(
        f"SELECT period_start_date,period_end FROM index_period_cycles_{period.frequency} WHERE cycle_date=date_trunc('{period.frequency}',DATE {duckdb_string(as_of)})::DATE"
    ).fetchone()
    listed = connection.execute(
        "SELECT list_date FROM index_period_listings WHERE ts_code='000680.SH'"
    ).fetchone()[0]
    first_cycle = index_period_bounds(
        period,
        listed.isoformat() if period == INDEX_WEEKLY else listed.strftime("%Y-%m"),
    )[0]
    partial = as_of < end
    raw_limit = start if partial else end
    op = "<" if partial else "<="
    code_raw = f"index_period_680_{period.frequency}"
    latest_raw = connection.execute(
        f"SELECT max(strptime(trade_date,'%Y%m%d')::DATE) FROM {raw} WHERE ts_code='000680.SH'"
    ).fetchone()[0]
    if latest_raw is not None and latest_raw > as_of:
        raise ValueError("科创综指Raw领先Serving快照，请人工择时重试")
    connection.execute(f"""CREATE OR REPLACE TEMP TABLE {code_raw} AS SELECT * FROM {raw}
        WHERE ts_code='000680.SH' AND strptime(trade_date,'%Y%m%d')::DATE >= DATE {duckdb_string(first_cycle)}
        AND strptime(trade_date,'%Y%m%d')::DATE {op} DATE {duckdb_string(raw_limit)}""")
    count_680 = connection.execute(f"SELECT count(*) FROM {code_raw}").fetchone()[0]
    selection = (
        index_period_silver_from_source_sql(serving, raw=False, period=period)
        + " UNION ALL "
        + index_period_silver_from_source_sql(code_raw, raw=True, period=period)
    )
    if partial and listed <= as_of:
        synthesize_index_period(
            connection,
            root=root,
            period=period,
            period_start=start,
            as_of=as_of,
            codes=("000680.SH",),
            output_relation="index_period_680_current",
        )
        selection += " UNION ALL SELECT * FROM index_period_680_current"
    relation = f"index_period_silver_history_{period.frequency}"
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {relation} AS SELECT {index_period_projection(SILVER_INDEX_WEEKLY_SCHEMA)} FROM ({selection})"
    )
    count = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
    expected_count = source_count + count_680 + int(partial and listed <= as_of)
    current_codes = connection.execute(
        f"SELECT count(DISTINCT ts_code) FROM {relation} WHERE period_start_date=DATE {duckdb_string(start)}"
    ).fetchone()[0]
    if count != expected_count or current_codes != len(index_period_codes()):
        raise ValueError("初始化转换行数或当前周期代码不完整")
    return relation


@dataclass(frozen=True)
class IndexPeriodHistoryFile:
    period: object
    layer: str
    prepared: object
    partitions: tuple


def index_period_partition_stats(connection, relation, period, layer):
    if layer == "raw":
        day = "strptime(s.trade_date,'%Y%m%d')::DATE"
        key = (
            f"strftime({day},'%Y-%m-%d')"
            if period == INDEX_WEEKLY
            else f"strftime({day},'%Y-%m')"
        )
        source = f"{relation} s"
    else:
        day = "s.trade_date"
        key = (
            "strftime(c.period_end,'%Y-%m-%d')"
            if period == INDEX_WEEKLY
            else "strftime(s.period_start_date,'%Y-%m')"
        )
        source = f"{relation} s JOIN index_period_cycles_{period.frequency} c ON date_trunc('{period.frequency}',s.period_start_date)::DATE=c.cycle_date"
    return tuple(
        connection.execute(
            f"SELECT {key},count(*),max({day}) FROM {source} GROUP BY 1 ORDER BY 1"
        ).fetchall()
    )


def build_index_period_history_files(
    connection, *, prod_postgres, lake_root, staging_root, operation_id, log=None
):
    load_index_period_listings(connection, lake_root)
    sources = {}
    for period in (INDEX_WEEKLY, INDEX_MONTHLY):
        for layer in ("raw", "serving"):
            if log:
                log(f"读取{period.dataset_id} {layer}固定字段和代码范围")
            sources[period.frequency, layer] = load_prod_index_period_relation(
                connection, prod_postgres, period, layer
            )
    dates = []
    for (_, layer), (relation, _) in sources.items():
        day = "strptime(trade_date,'%Y%m%d')::DATE" if layer == "raw" else "trade_date"
        dates.append(f"SELECT {day} AS day FROM {relation}")
    dates = " UNION ALL ".join(dates)
    minimum, maximum = connection.execute(
        f"SELECT min(day),max(day) FROM ({dates})"
    ).fetchone()
    start = min(
        index_period_bounds(
            p, minimum.isoformat() if p == INDEX_WEEKLY else minimum.strftime("%Y-%m")
        )[0]
        for p in (INDEX_WEEKLY, INDEX_MONTHLY)
    )
    end = max(
        index_period_bounds(
            p, maximum.isoformat() if p == INDEX_WEEKLY else maximum.strftime("%Y-%m")
        )[1]
        for p in (INDEX_WEEKLY, INDEX_MONTHLY)
    )
    load_index_period_calendar(connection, lake_root, start, end)
    files = []
    for period in (INDEX_WEEKLY, INDEX_MONTHLY):
        raw, _ = sources[period.frequency, "raw"]
        serving, count = sources[period.frequency, "serving"]
        silver = build_index_period_silver_history(
            connection,
            root=lake_root,
            period=period,
            raw=raw,
            serving=serving,
            source_count=count,
        )
        for layer, relation in (("raw", raw), ("silver", silver)):
            if log:
                log(f"生成并校验{period.dataset_id} {layer}完整候选")
            prepared = prepare_index_period_file(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                run_id=operation_id,
                period=period,
                layer=layer,
                source_relation=relation,
            )
            partitions = index_period_partition_stats(
                connection, relation, period, layer
            )
            if sum(row[1] for row in partitions) != prepared.check.file_row_count:
                raise ValueError("初始化分区分配数量不符")
            files.append(IndexPeriodHistoryFile(period, layer, prepared, partitions))
    return tuple(files)


def report_index_period_history(context, files, operation_id):
    instance = context.instance
    for period in (INDEX_WEEKLY, INDEX_MONTHLY):
        keys = sorted(
            {
                key
                for item in files
                if item.period == period
                for key, _, _ in item.partitions
            }
        )
        if keys:
            instance.add_dynamic_partitions(period.partition_set, keys)
    event_count = 0
    for item in files:
        period, layer = item.period, item.layer
        asset = period.raw_asset if layer == "raw" else period.silver_asset
        name = period.raw_check if layer == "raw" else period.silver_check
        batch = build_batch_id(
            producer=asset,
            scope="bootstrap",
            payload={"producer_run_id": context.run_id, "operation_id": operation_id},
        )
        for key, count, day in item.partitions:
            context.log_event(
                dg.AssetMaterialization(
                    asset_key=asset,
                    partition=key,
                    metadata=build_materialization_metadata(
                        uri=item.prepared.path,
                        row_count=count,
                        extra_metadata={
                            "file_row_count": item.prepared.check.file_row_count,
                            "trade_date": day.isoformat(),
                            "upstream_batch_id": batch,
                            "source_method": "index_period_bootstrap",
                            "units": "股／元／比例"
                            if layer == "raw"
                            else "手／千元／百分数",
                        },
                    ),
                )
            )
            event_count += 1
        records = (
            instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=dg.AssetKey(asset)),
                limit=len(item.partitions),
            ).records
            if item.partitions
            else ()
        )
        by_partition = {
            r.partition_key: r
            for r in records
            if r.asset_materialization.metadata["goldenshare/upstream_batch_id"].value
            == batch
        }
        for key, count, _ in item.partitions:
            record = by_partition[key]
            context.log_event(
                dg.AssetCheckEvaluation(
                    asset_key=dg.AssetKey(asset),
                    check_name=name,
                    passed=True,
                    blocking=True,
                    partition=key,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=record.storage_id,
                        run_id=record.run_id,
                        timestamp=record.timestamp,
                    ),
                    metadata=build_check_metadata(
                        check_scope=CheckScope.SCHEMA,
                        file_path=item.prepared.path,
                        checked_row_count=count,
                        failed_row_count=0,
                        extra_metadata={
                            "file_row_count": item.prepared.check.file_row_count
                        },
                    ),
                )
            )
            event_count += 1
    return event_count


def bootstrap_index_period_history(
    *, duckdb, prod_postgres, lake_root, staging_root, operation_id, instance, log=None
):
    summary = {}

    @dg.op(name="bootstrap_index_period_history", out={})
    def perform(context: dg.OpExecutionContext):
        report = log or context.log.info
        with duckdb.connect() as connection:
            files = build_index_period_history_files(
                connection,
                prod_postgres=prod_postgres,
                lake_root=lake_root,
                staging_root=staging_root,
                operation_id=context.run_id,
                log=report,
            )
            for item in files:
                report(f"提升{item.period.dataset_id} {item.layer}完整文件")
                promote_index_period_file(item.prepared)
        count = report_index_period_history(context, files, operation_id)
        summary.update(
            files=len(files),
            partitions=sum(len(item.partitions) for item in files),
            events=count,
            file_rows={
                f"{item.layer}_{item.period.dataset_id}": item.prepared.check.file_row_count
                for item in files
            },
        )

    @dg.job(name=INDEX_PERIOD_BOOTSTRAP_JOB_NAME)
    def bootstrap_job():
        perform()

    result = bootstrap_job.execute_in_process(instance=instance)
    return {**summary, "run_id": result.run_id}
