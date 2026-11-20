from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    INDEX_BASIC_RAW_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io.index_basic_publication import (
    INDEX_BASIC_COVERAGE_METADATA_KEY,
    index_basic_publication,
)
from orchestrator.defs.io.index_basic_snapshot import (
    raw_index_basic_changes,
    write_index_basic_raw,
    write_index_basic_silver,
)
from orchestrator.defs.io.stock_period_raw import atomic_json, file_digest, file_version
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    raw_index_basic_path,
    silver_index_basic_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.index_period import index_period_codes
from orchestrator.defs.run_contracts.metadata import (
    READY_FOR_TRADE_DATE_METADATA_KEY,
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import TUSHARE_API_SOURCE_METHOD
from orchestrator.seeds.market.major_indices import active_major_indices_seed_rows
from orchestrator.utils.dg_log_helper import DgStdoutLogger

CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")
LOGGER = DgStdoutLogger("basic_facts.index_basic")
_RAW_ASSET = dg.AssetKey("raw_tushare_index_basic")
_SILVER_ASSET = dg.AssetKey("silver_index_basic")


class IndexBasicUpdateConfig(dg.Config):
    verify_source_market_coverage: bool = False
    scheduled_trade_date: str | None = None


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def _market_distribution(connection, path: Path) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT market, count(*) AS row_count
        FROM {read_parquet(path, hive_partitioning=False)}
        GROUP BY market
        ORDER BY market
        """
    ).fetchall()
    return [{"market": row[0], "row_count": int(row[1])} for row in rows]


def _raw_terminated_index_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            f"""
            SELECT count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE exp_date IS NOT NULL AND trim(CAST(exp_date AS VARCHAR)) != ''
            """
        ).fetchone()[0]
    )


def _latest_registered_index_trade_date(
    registered_trade_days: Sequence[str],
    today: str,
) -> str | None:
    eligible_trade_days = tuple(
        trade_date
        for trade_date in sorted(set(registered_trade_days))
        if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _resolve_ready_for_trade_date(context: dg.AssetExecutionContext) -> str:
    today = datetime.now(CN_A_TIMEZONE).date().isoformat()
    registered_trade_days = tuple(
        context.instance.get_dynamic_partitions(cn_a_index_trade_days.name)
    )
    ready_for_trade_date = _latest_registered_index_trade_date(
        registered_trade_days,
        today,
    )
    if ready_for_trade_date:
        return ready_for_trade_date

    raise RuntimeError(
        "silver_index_basic cannot resolve ready_for_trade_date: "
        f"{cn_a_index_trade_days.name} has no registered trade date on or before "
        f"{today}. Run index_trade_day_sensor first or register index trade day "
        "partitions."
    )


def _paired_publication(context: dg.AssetExecutionContext) -> bool:
    selected = (
        context.run.asset_selection or context.job_def.asset_layer.selected_asset_keys
    )
    return {_RAW_ASSET, _SILVER_ASSET}.issubset(selected)


def _first_refresh_report(connection, publication, candidates, ready_date: str) -> Path:
    changes = raw_index_basic_changes(
        connection, publication.targets["raw"], candidates["raw"]
    )
    period_codes = set(index_period_codes())
    major_codes = {row.ts_code for row in active_major_indices_seed_rows(ready_date)}
    required = period_codes | major_codes
    required_sql = ", ".join(duckdb_string(code) for code in sorted(required))
    versions = {}
    for name, path in (
        ("before", publication.targets["silver"]),
        ("after", candidates["silver"]),
    ):
        versions[name] = {}
        if path.is_file():
            rows = connection.execute(
                f"SELECT ts_code, CAST(list_date AS VARCHAR), CAST(exp_date AS VARCHAR) "
                f"FROM {read_parquet(path, hive_partitioning=False)} "
                f"WHERE ts_code IN ({required_sql})"
            ).fetchall()
            versions[name] = {
                code: [listed, terminated] for code, listed, terminated in rows
            }
    impacts = {
        code: {
            "before": versions["before"].get(code),
            "after": versions["after"].get(code),
            "reason": "missing_from_candidate"
            if code not in versions["after"]
            else "date_range_changed",
            "consumers": [
                consumer
                for consumer, codes in (
                    ("指数周月线", period_codes),
                    ("主要指数 Gold", major_codes),
                )
                if code in codes
            ],
        }
        for code in sorted(required)
        if code not in versions["after"]
        or versions["before"].get(code) != versions["after"][code]
    }
    report = publication.directory / "first_refresh_changes.json"
    atomic_json(
        report,
        {
            "ready_for_trade_date": ready_date,
            "raw_changes": changes,
            "downstream": impacts,
        },
    )
    return report


def _prepare_raw_publication(context, config, publication, duckdb, tushare) -> None:
    paired = _paired_publication(context)
    ready_date = _resolve_ready_for_trade_date(context) if paired else None
    scheduled = config.scheduled_trade_date
    if scheduled is not None and (
        scheduled != ready_date
        or scheduled != datetime.now(CN_A_TIMEZONE).date().isoformat()
    ):
        raise ValueError(
            "Index basic scheduled date differs from today's registered index trade date"
        )
    stages = ("raw", "silver") if paired else ("raw",)
    previous = publication.target_versions(stages)
    attempt = publication.new_attempt()
    candidates = {layer: attempt / f"{layer}.parquet" for layer in stages}
    coverage = {
        "raw": write_index_basic_raw(
            tushare,
            duckdb,
            candidates["raw"],
            verify_markets=config.verify_source_market_coverage,
        )
    }
    if paired:
        with duckdb.connect() as connection:
            coverage["silver"] = write_index_basic_silver(
                connection, candidates["raw"], candidates["silver"], ready_date
            )
            coverage["silver"]["raw_sha256"] = file_digest(candidates["raw"])
            if config.verify_source_market_coverage:
                report = _first_refresh_report(
                    connection, publication, candidates, ready_date
                )
                coverage["raw"]["changes_report"] = str(report)
    publication.freeze(
        candidates=candidates,
        coverage=coverage,
        previous=previous,
        ready_date=ready_date,
    )


def _prepare_silver_publication(context, publication, duckdb) -> None:
    if _paired_publication(context):
        raise RuntimeError(
            "Index basic paired run has no validated Raw/Silver publication"
        )
    ready_date = _resolve_ready_for_trade_date(context)
    raw_path = publication.targets["raw"]
    version = file_version(raw_path)
    previous = publication.target_versions(("silver",))
    candidate = publication.new_attempt() / "silver.parquet"
    with duckdb.connect() as connection:
        coverage = write_index_basic_silver(connection, raw_path, candidate, ready_date)
    coverage["raw_sha256"] = file_digest(raw_path)
    if version != file_version(raw_path):
        raise RuntimeError("Index basic Raw changed while preparing Silver")
    publication.freeze(
        candidates={"silver": candidate},
        coverage={"silver": coverage},
        previous=previous,
        ready_date=ready_date,
        raw_input={"published_version": version, "sha256": coverage["raw_sha256"]},
    )


@dg.asset(
    name="raw_tushare_index_basic",
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_basic",
        source_system=SourceSystem.TUSHARE,
        source_api="index_basic",
        source_category_path="指数专题",
        source_doc="docs/sources/tushare/指数专题/0094_指数基本信息.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_INDEX_BASIC_SCHEMA,
        path_template=lake_path_template(raw_index_basic_path(PATH_TEMPLATE_LAKE_ROOT)),
        extra_metadata={
            "update_policy": "daily_full_snapshot_api_update",
        },
    ),
    description=(
        "Tushare 指数基础信息 raw 源镜像，保存指数身份、市场和生命周期原始字段，"
        "供有效指数池和指数行情链路使用。"
    ),
)
def raw_tushare_index_basic(
    context: dg.AssetExecutionContext,
    config: IndexBasicUpdateConfig,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    path = raw_index_basic_path(lake_root.root())
    LOGGER.stdout("index_basic_raw_started")
    with index_basic_publication(
        lake_root.root(), context.run.root_run_id or context.run_id
    ) as publication:
        if publication.state is None:
            _prepare_raw_publication(context, config, publication, duckdb, tushare)
        evidence = publication.promote("raw")
        delivery = publication.delivery_metadata("raw")
        with connect_configured_duckdb() as connection:
            market_distribution = _market_distribution(connection, path)
            terminated_index_count = _raw_terminated_index_count(connection, path)

    LOGGER.stdout(
        "index_basic_raw_completed",
        row_count=evidence["candidate_rows"],
        terminated_index_count=terminated_index_count,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=path,
            row_count=evidence["candidate_rows"],
            observed_columns=INDEX_BASIC_RAW_COLUMNS,
            extra_metadata={
                "summary": "已写入 Tushare 指数基础信息 raw 全量快照。",
                "next_action": "等待 raw_index_basic blocking checks 通过后生成 silver_index_basic。",
                "result_status": "written",
                "input_summary": "来源为 Tushare index_basic，全量刷新指数身份字段。",
                "filter_summary": "raw 层不排除已终止指数，终止指数数量仅作为观测。",
                "diagnostic_ref": "完整诊断看 raw_index_basic checks 和 run stdout。",
                "market_distribution": market_distribution,
                "terminated_index_count": terminated_index_count,
                "source_method": TUSHARE_API_SOURCE_METHOD,
                "params": {},
                "fields": list(INDEX_BASIC_RAW_COLUMNS),
                "page_count": len(evidence["pages"]),
                "limit": evidence["page_limit"],
                INDEX_BASIC_COVERAGE_METADATA_KEY: delivery,
            },
        )
    )


@dg.asset(
    name="silver_index_basic",
    deps=[raw_tushare_index_basic],
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_basic",
        source_system=SourceSystem.DERIVED,
        data_contract="effective_index_basic",
        column_schema=SILVER_INDEX_BASIC_SCHEMA,
        path_template=lake_path_template(
            silver_index_basic_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "filter_policy": (
                "silver_index_basic automatically uses the latest registered "
                "cn_a_index_trade_days date, and keeps indexes with exp_date "
                "null or exp_date > ready_for_trade_date."
            ),
        },
    ),
    config_schema={},
    description=(
        "有效指数基础信息 silver 标准事实，按最新已注册指数交易日排除已终止指数，"
        "供指数日线、周线和月线链路对齐指数池。"
    ),
)
def silver_index_basic(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    raw_path = raw_index_basic_path(lake_root.root())
    target_path = silver_index_basic_path(lake_root.root())
    with index_basic_publication(
        lake_root.root(), context.run.root_run_id or context.run_id
    ) as publication:
        if publication.state is None:
            _prepare_silver_publication(context, publication, duckdb)
        ready_for_trade_date = publication.state["ready_date"]
        LOGGER.stdout(
            "index_basic_silver_started", ready_for_trade_date=ready_for_trade_date
        )
        publication.promote("silver")
        delivery = publication.delivery_metadata("silver")
        with connect_configured_duckdb() as connection:
            source_row_count = _row_count(connection, raw_path)
            source_market_distribution = _market_distribution(connection, raw_path)
            source_terminated_index_count = _raw_terminated_index_count(
                connection, raw_path
            )
            columns = _column_names(connection, target_path)
            row_count = delivery["candidate_rows"]
            market_distribution = _market_distribution(connection, target_path)

    LOGGER.stdout(
        "index_basic_silver_completed",
        ready_for_trade_date=ready_for_trade_date,
        source_row_count=source_row_count,
        row_count=row_count,
        filtered_out_row_count=source_row_count - row_count,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "summary": "已生成有效指数基础信息 silver 快照。",
                "next_action": "等待 silver_index_basic blocking checks 通过后供指数行情链路消费。",
                "result_status": "written",
                "input_summary": "输入为 raw_tushare_index_basic 和最新已注册指数交易日。",
                "filter_summary": (
                    f"按 ready_for_trade_date={ready_for_trade_date} 保留 {row_count} 个有效指数，"
                    f"过滤 {source_row_count - row_count} 个已终止或不适用指数。"
                ),
                "diagnostic_ref": "完整诊断看 silver_index_basic checks 和 run stdout。",
                "source_row_count": source_row_count,
                "kept_row_count": row_count,
                "filtered_out_row_count": source_row_count - row_count,
                "source_terminated_index_count": source_terminated_index_count,
                READY_FOR_TRADE_DATE_METADATA_KEY: ready_for_trade_date,
                "source_market_distribution": source_market_distribution,
                "market_distribution": market_distribution,
                INDEX_BASIC_COVERAGE_METADATA_KEY: delivery,
            },
        )
    )
