import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    describe_parquet_query,
    read_parquet,
    silver_trade_calendar_select,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    RAW,
    SILVER,
    lake_path_template,
    raw_trade_calendar_path,
    silver_trade_calendar_path,
    trade_calendar_staging_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_full_file_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger

TRADE_CALENDAR_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_TRADE_CALENDAR_SCHEMA
}
LOGGER = DgStdoutLogger("basic_facts.trade_calendar")


class TradeCalendarUpdateConfig(dg.Config):
    minimum_end_date: str | None = None


def _validate_source_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        value = row.get("is_open")
        if not (
            (type(value) is int and value in (0, 1))
            or (type(value) is str and value in ("0", "1"))
        ):
            raise ValueError(f"交易日历源开市标记非法，日期: {row.get('cal_date')}")


@dataclass(frozen=True)
class CalendarFileStats:
    path: Path
    first_date: date
    last_date: date
    row_count: int
    sha256: str


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _calendar_rows(path: Path, layer: str) -> str:
    if layer == RAW:
        return silver_trade_calendar_select(path)
    return (
        f"SELECT exchange, trade_date, is_open, pretrade_date FROM {read_parquet(path)}"
    )


def inspect_calendar_candidate(
    connection, path: Path, *, layer: str
) -> CalendarFileStats:
    contract = (
        RAW_TUSHARE_TRADE_CALENDAR_SCHEMA
        if layer == RAW
        else SILVER_TRADE_CALENDAR_SCHEMA
    )
    fields = connection.execute(describe_parquet_query(path)).fetchall()
    if [(name, kind) for name, kind, *_ in fields] != [
        (c.name, c.type) for c in contract
    ]:
        raise ValueError(f"交易日历候选字段或类型不匹配: {path}")
    if layer == RAW:
        malformed_dates = connection.execute(
            f"""
            SELECT count(*) FROM {read_parquet(path)}
            WHERE NOT regexp_full_match(cal_date, '[0-9]{{8}}')
               OR try_strptime(cal_date, '%Y%m%d') IS NULL
               OR (nullif(pretrade_date, '') IS NOT NULL
                   AND (NOT regexp_full_match(pretrade_date, '[0-9]{{8}}')
                        OR try_strptime(pretrade_date, '%Y%m%d') IS NULL))
            """
        ).fetchone()[0]
        if malformed_dates:
            raise ValueError(f"交易日历候选日期格式非法: {path}")

    row_count, distinct_dates, first, last, invalid = connection.execute(
        f"""
        SELECT count(*), count(DISTINCT trade_date), min(trade_date), max(trade_date),
               count(*) FILTER (
                 WHERE exchange IS DISTINCT FROM 'SSE'
                    OR trade_date IS NULL OR is_open IS NULL
                    OR pretrade_date >= trade_date
               )
        FROM ({_calendar_rows(path, layer)})
        """
    ).fetchone()
    if invalid or not row_count or row_count != distinct_dates:
        raise ValueError(f"交易日历候选为空或包含无效记录、重复日期: {path}")
    if row_count != (last - first).days + 1:
        raise ValueError(f"交易日历候选日期不连续: {path}")

    bad_pretrade = connection.execute(
        f"""
        WITH checked AS (
            SELECT pretrade_date, max(trade_date) FILTER (WHERE is_open) OVER (
                ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS expected
            FROM ({_calendar_rows(path, layer)})
        )
        SELECT count(*) FROM checked WHERE pretrade_date IS DISTINCT FROM expected
        """
    ).fetchone()[0]
    if bad_pretrade:
        raise ValueError(f"交易日历候选有 {bad_pretrade} 条上一交易日不一致: {path}")
    return CalendarFileStats(path, first, last, row_count, _file_sha256(path))


def _require_end_date(stats: CalendarFileStats, minimum_end_date: date | None) -> None:
    if minimum_end_date is not None and stats.last_date < minimum_end_date:
        raise ValueError(
            f"交易日历候选截止日 {stats.last_date} 早于本次要求的 {minimum_end_date}"
        )


def _compare_published_history(
    connection, candidate: CalendarFileStats, target: Path, *, layer: str
):
    if not target.exists():
        return {"historical_is_open_changes": 0, "historical_pretrade_date_changes": 0}

    missing, open_changes, prev_changes = connection.execute(
        f"""
        SELECT count(*) FILTER (WHERE updated.trade_date IS NULL),
               count(*) FILTER (WHERE updated.trade_date IS NOT NULL
                 AND old.is_open IS DISTINCT FROM updated.is_open),
               count(*) FILTER (WHERE updated.trade_date IS NOT NULL
                 AND old.pretrade_date IS DISTINCT FROM updated.pretrade_date)
        FROM ({_calendar_rows(target, layer)}) AS old
        LEFT JOIN ({_calendar_rows(candidate.path, layer)}) AS updated USING (exchange, trade_date)
        """
    ).fetchone()
    if missing:
        raise ValueError(f"交易日历候选缺失 {missing} 个已发布日期: {target}")
    return {
        "historical_is_open_changes": open_changes,
        "historical_pretrade_date_changes": prev_changes,
    }


def _prepare_publication(
    context: dg.AssetExecutionContext, root: Path, target: Path, *, layer: str
) -> Path:
    candidate = trade_calendar_staging_path(root, context.run_id, layer)
    staging_root = candidate.parents[3]
    if not staging_root.is_dir() or staging_root.stat().st_dev != root.stat().st_dev:
        raise RuntimeError("交易日历 staging 不存在或与正式 Lake 不在同一文件系统")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if candidate.parent.stat().st_dev != target.parent.stat().st_dev:
        raise RuntimeError("交易日历候选与正式目标不在同一文件系统")
    return candidate


def _publication_record(path: Path) -> Path:
    return path.with_name("publication.json")


def _write_publication_record(path: Path, record: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _record_calendar_publication(
    stats: CalendarFileStats,
    target: Path,
    *,
    run_id: str,
    state: str,
    source_evidence: dict | None = None,
) -> dict:
    record_path = _publication_record(stats.path)
    record = {
        "run_id": run_id,
        "target_path": str(target),
        "calendar_start_date": stats.first_date.isoformat(),
        "calendar_end_date": stats.last_date.isoformat(),
        "row_count": stats.row_count,
        "sha256": stats.sha256,
        "state": state,
        **(source_evidence or {}),
    }
    _write_publication_record(record_path, record)
    return {
        "calendar_start_date": record["calendar_start_date"],
        "calendar_end_date": record["calendar_end_date"],
        "sha256": stats.sha256,
        "publication_record": str(record_path),
    }


def _publish_calendar(
    stats: CalendarFileStats,
    target: Path,
    *,
    run_id: str,
    source_evidence: dict | None = None,
) -> dict:
    _record_calendar_publication(
        stats,
        target,
        run_id=run_id,
        state="validated",
        source_evidence=source_evidence,
    )
    os.replace(stats.path, target)
    return _record_calendar_publication(
        stats,
        target,
        run_id=run_id,
        state="published",
        source_evidence=source_evidence,
    )


def _find_raw_publication(context: dg.AssetExecutionContext, root: Path, *, run=None):
    run = context.run if run is None else run
    while run is not None:
        candidate = trade_calendar_staging_path(root, run.run_id, RAW)
        publish_path = _publication_record(candidate)
        if publish_path.is_file():
            record = json.loads(publish_path.read_text(encoding="utf-8"))
            if record["run_id"] != run.run_id:
                raise RuntimeError("Raw 交易日历发布记录的运行编号不一致")
            return candidate, record
        if run.parent_run_id is None:
            break
        run = context.instance.get_run_by_id(run.parent_run_id)
    return None


def _raw_publication_matches(
    candidate: Path, record: dict, raw_path: Path, digest: str
) -> bool:
    return (
        record["target_path"] == str(raw_path)
        and record["sha256"] == digest
        and (
            record["state"] == "published"
            or (record["state"] == "validated" and not candidate.exists())
        )
    )


def _verified_raw_sha256(
    context: dg.AssetExecutionContext, root: Path, raw_path: Path
) -> str:
    actual_sha256 = _file_sha256(raw_path)
    prior = _find_raw_publication(context, root)
    if prior is not None:
        candidate, record = prior
        if not _raw_publication_matches(candidate, record, raw_path, actual_sha256):
            raise RuntimeError("正式 Raw 交易日历与本次运行链的发布记录不一致")
    elif context.job_name == "calendar_update_job":
        raise RuntimeError("交易日历更新缺少本次运行链的 Raw 发布记录")
    return actual_sha256


def _recover_interrupted_raw(
    context: dg.AssetExecutionContext, root: Path, raw_path: Path
) -> dict | None:
    parent_id = context.run.parent_run_id
    if parent_id is None or not raw_path.is_file():
        return None
    parent_run = context.instance.get_run_by_id(parent_id)
    if parent_run is None:
        return None
    prior = _find_raw_publication(context, root, run=parent_run)
    if prior is None:
        return None
    candidate, record = prior
    if record["state"] == "validated" and _raw_publication_matches(
        candidate,
        record,
        raw_path,
        _file_sha256(raw_path),
    ):
        return record
    return None


def _verify_silver_matches_raw(connection, raw_path: Path, candidate: Path) -> None:
    expected = _calendar_rows(raw_path, RAW)
    actual = _calendar_rows(candidate, SILVER)
    different = connection.execute(
        f"""
        WITH expected AS ({expected}), actual AS ({actual})
        SELECT EXISTS (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
            OR EXISTS (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
        """
    ).fetchone()[0]
    if different:
        raise ValueError("Silver 交易日历与 Raw 标准化结果不一致")


@dg.asset(
    name="raw_tushare_trade_calendar",
    group_name="calendar",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="trade_cal",
        source_system=SourceSystem.TUSHARE,
        source_api="trade_cal",
        source_category_path="股票数据 / 基础数据",
        source_doc="docs/sources/tushare/股票数据/基础数据/0026_交易日历.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
        path_template=lake_path_template(
            raw_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "raw_contract": "cal_date/pretrade_date YYYYMMDD string, is_open 0/1 integer",
            "update_policy": "low_frequency_full_file_api_update",
        },
    ),
    description=(
        "Tushare 交易日历 raw 源镜像，保存上交所交易日历原始字段，"
        "供标准交易日历和全市场日频资产判断交易日使用。"
    ),
)
def raw_tushare_trade_calendar(
    context: dg.AssetExecutionContext,
    config: TradeCalendarUpdateConfig,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    started_at = monotonic()
    lake_root.ensure_available_for_run()
    root = lake_root.root()
    target_path = raw_trade_calendar_path(root)
    candidate = _prepare_publication(context, root, target_path, layer=RAW)
    LOGGER.stdout("trade_calendar_raw_started", exchange="SSE")

    minimum_end_date = (
        date.fromisoformat(config.minimum_end_date) if config.minimum_end_date else None
    )
    recovered = _recover_interrupted_raw(context, root, target_path)
    if recovered is None:
        source_metadata = fetch_tushare_full_file_to_raw(
            tushare=tushare,
            duckdb=duckdb,
            api_name="trade_cal",
            api_params={"exchange": "SSE"},
            fields=TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
            column_types=TRADE_CALENDAR_RAW_COLUMN_TYPES,
            target_path=candidate,
            allow_empty=False,
            validate_source_rows=_validate_source_rows,
        )
        with connect_configured_duckdb() as connection:
            stats = inspect_calendar_candidate(connection, candidate, layer=RAW)
            if source_metadata["dagster/row_count"] != stats.row_count:
                raise ValueError("交易日历候选与源请求返回的行数不一致")
            _require_end_date(stats, minimum_end_date)
            history = _compare_published_history(
                connection, stats, target_path, layer=RAW
            )
        publication = _publish_calendar(
            stats,
            target_path,
            run_id=context.run_id,
            source_evidence={"source_metadata": source_metadata, "history": history},
        )
    else:
        with connect_configured_duckdb() as connection:
            published = inspect_calendar_candidate(connection, target_path, layer=RAW)
        stats = CalendarFileStats(
            candidate,
            published.first_date,
            published.last_date,
            published.row_count,
            published.sha256,
        )
        _require_end_date(stats, minimum_end_date)
        source_metadata = recovered["source_metadata"]
        history = recovered["history"]
        publication = _record_calendar_publication(
            stats,
            target_path,
            run_id=context.run_id,
            state="published",
            source_evidence={"source_metadata": source_metadata, "history": history},
        )
    elapsed_ms = round((monotonic() - started_at) * 1000)
    LOGGER.stdout(
        "trade_calendar_raw_completed",
        row_count=stats.row_count,
        page_count=source_metadata["goldenshare/page_count"],
        first_date=publication["calendar_start_date"],
        last_date=publication["calendar_end_date"],
        elapsed_ms=elapsed_ms,
    )
    return dg.MaterializeResult(
        metadata={
            **source_metadata,
            **build_materialization_metadata(
                uri=target_path,
                extra_metadata={
                    "summary": "已校验并发布上交所 Raw 交易日历全量文件。",
                    "next_action": "等待 raw blocking check 通过后生成 silver_trade_calendar。",
                    "result_status": "written",
                    "input_summary": "从 Tushare trade_cal 读取上交所已发布的全部日历。",
                    "filter_summary": "保留源站显式字段。",
                    "diagnostic_ref": "字段检查见 raw_trade_calendar_contract_check。",
                    "elapsed_ms": elapsed_ms,
                    **history,
                    **publication,
                },
            ),
        }
    )


@dg.asset(
    name="silver_trade_calendar",
    deps=["raw_tushare_trade_calendar"],
    group_name="calendar",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="trade_cal",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_trade_calendar",
        column_schema=SILVER_TRADE_CALENDAR_SCHEMA,
        path_template=lake_path_template(
            silver_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
    ),
    description=(
        "A 股交易日历 silver 标准事实，按上交所交易日口径输出标准日期字段，"
        "供日频资产分区注册、freshness 和 readiness 判断使用。"
    ),
)
def silver_trade_calendar(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    started_at = monotonic()
    lake_root.ensure_available_for_run()
    root = lake_root.root()
    raw_path = raw_trade_calendar_path(root)
    target_path = silver_trade_calendar_path(root)
    candidate = _prepare_publication(context, root, target_path, layer=SILVER)
    LOGGER.stdout("trade_calendar_silver_started")
    raw_sha256 = _verified_raw_sha256(context, root, raw_path)
    with connect_configured_duckdb() as connection:
        if context.job_name != "calendar_update_job":
            inspect_calendar_candidate(connection, raw_path, layer=RAW)
        connection.execute(
            copy_query_to_parquet(silver_trade_calendar_select(raw_path), candidate)
        )
        stats = inspect_calendar_candidate(connection, candidate, layer=SILVER)
        _verify_silver_matches_raw(connection, raw_path, candidate)
        history = _compare_published_history(
            connection, stats, target_path, layer=SILVER
        )
    publication = _publish_calendar(stats, target_path, run_id=context.run_id)
    elapsed_ms = round((monotonic() - started_at) * 1000)
    LOGGER.stdout(
        "trade_calendar_silver_completed",
        row_count=stats.row_count,
        first_date=publication["calendar_start_date"],
        last_date=publication["calendar_end_date"],
        elapsed_ms=elapsed_ms,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=stats.row_count,
            observed_columns=[column.name for column in SILVER_TRADE_CALENDAR_SCHEMA],
            extra_metadata={
                "summary": "已校验并发布 A 股标准交易日历。",
                "next_action": "等待 silver_trade_calendar blocking checks 通过后供下游消费。",
                "result_status": "written",
                "input_summary": "输入为 raw_tushare_trade_calendar 正式文件。",
                "filter_summary": "标准化日期和开市标记。",
                "diagnostic_ref": "字段和主键检查见 Silver checks。",
                "raw_sha256": raw_sha256,
                "elapsed_ms": elapsed_ms,
                **history,
                **publication,
            },
        )
    )
