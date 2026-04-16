from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from src.foundation.dao.factory import DAOFactory
from src.foundation.config.logging import configure_logging
from src.foundation.config.settings import get_settings
from src.db import SessionLocal
from src.foundation.services.migration import RawTushareBootstrapService
from src.foundation.serving import ServingPublishService, validate_serving_coverage
from src.ops.models.ops.job_execution import JobExecution
from src.operations.runtime import OperationsScheduler, OperationsWorker
from src.operations.services import (
    DailyHealthReportService,
    DatasetPipelineModeSeedService,
    DefaultSingleSourceSeedService,
    DatasetStatusSnapshotService,
    MoneyflowMultiSourceSeedService,
    MoneyflowReconcileService,
    OperationsExecutionReconciliationService,
    StockBasicReconcileService,
    SyncJobStateReconciliationService,
)
from src.operations.services.history_backfill_service import HistoryBackfillService
from src.foundation.services.sync.registry import SYNC_SERVICE_REGISTRY, build_sync_service


app = typer.Typer(help="goldenshare market data foundation CLI")


def _alembic_config() -> Config:
    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def _resolve_default_sync_date(session) -> date:
    trade_cal = build_sync_service("trade_cal", session)
    trade_cal.run_incremental()
    exchange = get_settings().default_exchange
    today = date.today()
    latest = trade_cal.dao.trade_calendar.get_latest_open_date(exchange, today)
    if latest is None:
        raise typer.BadParameter("No open trade date found in trade calendar.")
    today_row = trade_cal.dao.trade_calendar.fetch_by_pk(exchange, today)
    if today_row is None:
        raise typer.BadParameter("Today's trade calendar row is missing.")
    if today_row.is_open:
        if today_row.pretrade_date is None:
            raise typer.BadParameter("Today's trade calendar row has no pretrade_date.")
        return today_row.pretrade_date
    return latest


def _open_execution_counts(session) -> tuple[int, int]:
    queued = session.scalar(select(func.count()).select_from(JobExecution).where(JobExecution.status == "queued")) or 0
    running = session.scalar(select(func.count()).select_from(JobExecution).where(JobExecution.status == "running")) or 0
    return int(queued), int(running)


def _auto_reconcile_stale_executions(
    session,
    *,
    stale_for_minutes: int,
    limit: int,
) -> int:
    if stale_for_minutes <= 0:
        return 0
    service = OperationsExecutionReconciliationService()
    reconciled = service.reconcile_stale_executions(
        session,
        stale_for_minutes=stale_for_minutes,
        limit=limit,
    )
    return len(reconciled)


@app.callback()
def main() -> None:
    configure_logging()


@app.command("init-db")
def init_db() -> None:
    command.upgrade(_alembic_config(), "head")


@app.command("bootstrap-raw-tushare")
def bootstrap_raw_tushare(
    table: list[str] = typer.Option([], "--table", "-t", help="指定 raw 表名；不传则处理 raw 全部表。"),
    create_only: bool = typer.Option(False, help="仅建表，不迁移数据。"),
    drop_if_exists: bool = typer.Option(False, help="若目标表已存在，先 DROP 再重建。"),
) -> None:
    with SessionLocal() as session:
        result = RawTushareBootstrapService().run(
            session,
            table_names=table or None,
            migrate_data=not create_only,
            drop_if_exists=drop_if_exists,
            progress_callback=typer.echo,
        )

    typer.echo(
        "bootstrap-raw-tushare: "
        f"tables={len(result.tables)} "
        f"created={result.created_count} "
        f"migrated={result.migrated_count} "
        f"inserted_rows={result.inserted_rows_total}"
    )
    for item in result.tables:
        typer.echo(
            f" - {item.table_name}: "
            f"created={item.created} migrated={item.migrated} inserted={item.inserted_rows}"
        )


@app.command("validate-serving-coverage")
def validate_serving_coverage_cmd() -> None:
    with SessionLocal() as session:
        dao = DAOFactory(session)
        publish_service = ServingPublishService(dao)
        issues = validate_serving_coverage(dao=dao, builder_registry=publish_service.builder_registry)

    if not issues:
        typer.echo("validate-serving-coverage: OK")
        return

    typer.echo(f"validate-serving-coverage: FAILED issues={len(issues)}")
    for issue in issues:
        typer.echo(f" - dataset={issue.dataset_key} type={issue.issue_type} detail={issue.detail}")
    raise typer.Exit(code=1)


@app.command("sync-history")
def sync_history(
    resources: list[str] = typer.Option(..., "--resources", "-r"),
    ts_code: str | None = typer.Option(None),
    list_status: str | None = typer.Option(None, "--list-status", help="Optional list status filter for hk_basic."),
    classify: str | None = typer.Option(None, "--classify", help="Optional classify filter for us_basic."),
    index_code: str | None = typer.Option(None, "--index-code", help="For index_weight, maps to Tushare index_code."),
    con_code: str | None = typer.Option(None, "--con-code", help="For board/member resources, maps to concept code."),
    exchange: str | None = typer.Option(None, help="Optional exchange filter for reference resources."),
    ths_type: str | None = typer.Option(None, "--type", help="Optional type filter for 同花顺板块主数据."),
    idx_type: str | None = typer.Option(None, "--idx-type", help="Optional 东财板块类型筛选."),
    market: str | None = typer.Option(None, "--market", help="Optional market filter for hot list resources."),
    hot_type: str | None = typer.Option(None, "--hot-type", help="Optional hot list type filter for dc_hot."),
    is_new: str | None = typer.Option(None, "--is-new", help="Optional latest-snapshot tag for hot list resources."),
    tag: str | None = typer.Option(None, "--tag", help="Optional tag filter for kpl_list."),
    limit_type: str | None = typer.Option(None, "--limit-type", help="Optional limit list type filter."),
    start_date: str | None = typer.Option(None),
    end_date: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        reconciliation_service = SyncJobStateReconciliationService()
        snapshot_service = DatasetStatusSnapshotService()
        for resource in resources:
            service = build_sync_service(resource, session)
            kwargs = {
                "ts_code": ts_code,
                "list_status": list_status,
                "classify": classify,
                "index_code": index_code,
                "con_code": con_code,
                "exchange": exchange,
                "type": ths_type,
                "idx_type": idx_type,
                "market": market,
                "hot_type": hot_type,
                "is_new": is_new,
                "tag": tag,
                "limit_type": limit_type,
                "start_date": start_date,
                "end_date": end_date,
            }
            result = service.run_full(**{k: v for k, v in kwargs.items() if v is not None})
            if result.trade_date is None:
                reconciliation_service.refresh_resource_state_from_observed(session, resource)
            snapshot_service.refresh_resources(session, [resource])


@app.command("sync-daily")
def sync_daily(
    trade_date: str | None = typer.Option(None, help="YYYY-MM-DD"),
    ts_code: str | None = typer.Option(None),
    exchange: str | None = typer.Option(None, "--exchange"),
    limit_type: str | None = typer.Option(None, "--limit-type"),
    con_code: str | None = typer.Option(None, "--con-code"),
    idx_type: str | None = typer.Option(None, "--idx-type"),
    market: str | None = typer.Option(None, "--market"),
    hot_type: str | None = typer.Option(None, "--hot-type"),
    is_new: str | None = typer.Option(None, "--is-new"),
    tag: str | None = typer.Option(None, "--tag"),
    resources: list[str] = typer.Option(
        [
            "daily",
            "adj_factor",
            "daily_basic",
            "moneyflow",
            "limit_list_d",
            "top_list",
            "block_trade",
            "fund_daily",
            "index_daily",
            "ths_daily",
            "dc_index",
            "dc_member",
            "dc_daily",
            "ths_hot",
            "dc_hot",
            "kpl_list",
            "limit_list_ths",
            "limit_step",
            "limit_cpt_list",
            "kpl_concept_cons",
        ],
        "--resources",
        "-r",
    ),
) -> None:
    target_date = date.fromisoformat(trade_date) if trade_date else None
    with SessionLocal() as session:
        snapshot_service = DatasetStatusSnapshotService()
        if target_date is None:
            target_date = _resolve_default_sync_date(session)
        for resource in resources:
            service = build_sync_service(resource, session)
            service.run_incremental(
                trade_date=target_date,
                ts_code=ts_code,
                exchange=exchange,
                limit_type=limit_type,
                con_code=con_code,
                idx_type=idx_type,
                market=market,
                hot_type=hot_type,
                is_new=is_new,
                tag=tag,
            )
            snapshot_service.refresh_resources(session, [resource])


@app.command("rebuild-dm")
def rebuild_dm() -> None:
    with SessionLocal() as session:
        session.execute(text("REFRESH MATERIALIZED VIEW dm.equity_daily_snapshot"))
        session.commit()


@app.command("list-resources")
def list_resources() -> None:
    for resource in SYNC_SERVICE_REGISTRY:
        typer.echo(resource)


@app.command("ops-rebuild-dataset-status")
def ops_rebuild_dataset_status() -> None:
    with SessionLocal() as session:
        count = DatasetStatusSnapshotService().rebuild_all(session, strict=True)
        typer.echo(f"ops-rebuild-dataset-status: rebuilt={count}")


@app.command("ops-daily-health-report")
def ops_daily_health_report(
    report_date: str | None = typer.Option(None, "--date", help="报告日期，格式 YYYY-MM-DD；默认今天"),
    output_format: str = typer.Option("md", "--format", help="输出格式：md 或 json"),
    output: Path | None = typer.Option(None, "--output", help="输出文件路径；不传则打印到终端"),
) -> None:
    target_date = date.fromisoformat(report_date) if report_date else date.today()
    format_key = output_format.strip().lower()
    if format_key not in {"md", "json"}:
        raise typer.BadParameter("--format 仅支持 md 或 json")

    with SessionLocal() as session:
        service = DailyHealthReportService()
        report = service.build_report(session, report_date=target_date)
        rendered = service.render_markdown(report) if format_key == "md" else report.to_json()

    if output is None:
        typer.echo(rendered)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(f"ops-daily-health-report: written={output}")


@app.command("reconcile-stock-basic")
def reconcile_stock_basic(
    sample_limit: int = typer.Option(20, min=0, max=200, help="每类差异最多输出多少条样例。"),
    threshold_only_tushare: int = typer.Option(
        -1,
        help="only_tushare 阈值；-1 表示不校验。超过阈值时命令返回非 0。",
    ),
    threshold_only_biying: int = typer.Option(
        -1,
        help="only_biying 阈值；-1 表示不校验。超过阈值时命令返回非 0。",
    ),
    threshold_comparable_diff: int = typer.Option(
        -1,
        help="comparable_diff 阈值；-1 表示不校验。超过阈值时命令返回非 0。",
    ),
) -> None:
    with SessionLocal() as session:
        report = StockBasicReconcileService().run(session, sample_limit=sample_limit)

    typer.echo("reconcile-stock-basic summary")
    typer.echo(f"total_union={report.total_union}")
    typer.echo(f"comparable={report.comparable}")
    typer.echo(f"only_tushare={report.only_tushare}")
    typer.echo(f"only_biying={report.only_biying}")
    typer.echo(f"comparable_diff={report.comparable_diff}")

    if sample_limit > 0:
        for diff_type in ("only_tushare", "only_biying", "comparable_diff"):
            items = report.samples[diff_type]
            if not items:
                continue
            typer.echo(f"\n[{diff_type}] samples={len(items)}")
            for item in items:
                typer.echo(
                    " - "
                    f"{item.ts_code} "
                    f"t_name={item.tushare_name!r} b_name={item.biying_name!r} "
                    f"t_exchange={item.tushare_exchange!r} b_exchange={item.biying_exchange!r} "
                    f"t_name_norm={item.tushare_name_norm!r} b_name_norm={item.biying_name_norm!r} "
                    f"t_exchange_norm={item.tushare_exchange_norm!r} b_exchange_norm={item.biying_exchange_norm!r}"
                )

    failed_checks: list[str] = []
    if threshold_only_tushare >= 0 and report.only_tushare > threshold_only_tushare:
        failed_checks.append(f"only_tushare={report.only_tushare} > threshold={threshold_only_tushare}")
    if threshold_only_biying >= 0 and report.only_biying > threshold_only_biying:
        failed_checks.append(f"only_biying={report.only_biying} > threshold={threshold_only_biying}")
    if threshold_comparable_diff >= 0 and report.comparable_diff > threshold_comparable_diff:
        failed_checks.append(f"comparable_diff={report.comparable_diff} > threshold={threshold_comparable_diff}")

    if failed_checks:
        typer.echo("\nreconcile-stock-basic gate failed:")
        for check in failed_checks:
            typer.echo(f" - {check}")
        raise typer.Exit(code=1)


@app.command("reconcile-moneyflow")
def reconcile_moneyflow(
    start_date: str | None = typer.Option(None, "--start-date", help="对账开始日期（YYYY-MM-DD），默认自动推导。"),
    end_date: str | None = typer.Option(None, "--end-date", help="对账结束日期（YYYY-MM-DD），默认自动推导。"),
    range_days: int = typer.Option(5, min=1, max=120, help="当未传 start_date 时，默认回看最近 N 天。"),
    sample_limit: int = typer.Option(20, min=0, max=200, help="每类差异最多输出多少条样例。"),
    abs_tol: float = typer.Option(1.0, "--abs-tol", help="绝对误差阈值。"),
    rel_tol: float = typer.Option(0.03, "--rel-tol", help="相对误差阈值。"),
    threshold_only_tushare: int = typer.Option(-1, help="only_tushare 阈值；-1 表示不校验。"),
    threshold_only_biying: int = typer.Option(-1, help="only_biying 阈值；-1 表示不校验。"),
    threshold_comparable_diff: int = typer.Option(-1, help="comparable_diff 阈值；-1 表示不校验。"),
) -> None:
    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    with SessionLocal() as session:
        report = MoneyflowReconcileService().run(
            session,
            start_date=parsed_start,
            end_date=parsed_end,
            range_days=range_days,
            sample_limit=sample_limit,
            abs_tol=Decimal(str(abs_tol)),
            rel_tol=Decimal(str(rel_tol)),
        )

    typer.echo("reconcile-moneyflow summary")
    typer.echo(f"date_range={report.start_date.isoformat()}~{report.end_date.isoformat()}")
    typer.echo(f"total_union={report.total_union}")
    typer.echo(f"comparable={report.comparable}")
    typer.echo(f"only_tushare={report.only_tushare}")
    typer.echo(f"only_biying={report.only_biying}")
    typer.echo(f"comparable_diff={report.comparable_diff}")
    typer.echo(f"direction_mismatch={report.direction_mismatch}")

    if sample_limit > 0:
        for diff_type in ("only_tushare", "only_biying", "comparable_diff"):
            items = report.samples[diff_type]
            if not items:
                continue
            typer.echo(f"\n[{diff_type}] samples={len(items)}")
            for item in items:
                typer.echo(
                    " - "
                    f"{item.ts_code} {item.trade_date.isoformat()} "
                    f"field={item.field or '-'} "
                    f"t={item.tushare_value} b={item.biying_value} "
                    f"abs_diff={item.abs_diff} rel_diff={item.rel_diff} "
                    f"note={item.note or '-'}"
                )

    failed_checks: list[str] = []
    if threshold_only_tushare >= 0 and report.only_tushare > threshold_only_tushare:
        failed_checks.append(f"only_tushare={report.only_tushare} > threshold={threshold_only_tushare}")
    if threshold_only_biying >= 0 and report.only_biying > threshold_only_biying:
        failed_checks.append(f"only_biying={report.only_biying} > threshold={threshold_only_biying}")
    if threshold_comparable_diff >= 0 and report.comparable_diff > threshold_comparable_diff:
        failed_checks.append(f"comparable_diff={report.comparable_diff} > threshold={threshold_comparable_diff}")

    if failed_checks:
        typer.echo("\nreconcile-moneyflow gate failed:")
        for check in failed_checks:
            typer.echo(f" - {check}")
        raise typer.Exit(code=1)


@app.command("ops-seed-default-single-source")
def ops_seed_default_single_source(
    source_key: str = typer.Option("tushare", "--source-key", help="默认来源键（例如 tushare）。"),
    apply: bool = typer.Option(False, "--apply", help="执行写入。默认仅预览（dry-run）。"),
) -> None:
    with SessionLocal() as session:
        report = DefaultSingleSourceSeedService().run(
            session,
            source_key=source_key,
            dry_run=not apply,
        )

    mode = "apply" if apply else "dry-run"
    typer.echo(f"ops-seed-default-single-source [{mode}] source={report.source_key}")
    typer.echo(f"dataset_total={report.dataset_total}")
    typer.echo(f"created_mapping_rules={report.created_mapping_rules}")
    typer.echo(f"created_cleansing_rules={report.created_cleansing_rules}")
    typer.echo(f"created_resolution_policies={report.created_resolution_policies}")
    typer.echo(f"created_source_statuses={report.created_source_statuses}")


@app.command("ops-seed-moneyflow-multi-source")
def ops_seed_moneyflow_multi_source(
    apply: bool = typer.Option(False, "--apply", help="执行写入。默认仅预览（dry-run）。"),
) -> None:
    with SessionLocal() as session:
        report = MoneyflowMultiSourceSeedService().run(session, dry_run=not apply)

    mode = "apply" if apply else "dry-run"
    typer.echo(f"ops-seed-moneyflow-multi-source [{mode}] dataset={report.dataset_key}")
    typer.echo(f"created_pipeline_mode={report.created_pipeline_mode}")
    typer.echo(f"updated_pipeline_mode={report.updated_pipeline_mode}")
    typer.echo(f"created_mapping_rules={report.created_mapping_rules}")
    typer.echo(f"created_cleansing_rules={report.created_cleansing_rules}")
    typer.echo(f"created_source_statuses={report.created_source_statuses}")
    typer.echo(f"created_resolution_policy={report.created_resolution_policy}")
    typer.echo(f"updated_resolution_policy={report.updated_resolution_policy}")


@app.command("ops-seed-dataset-pipeline-mode")
def ops_seed_dataset_pipeline_mode(
    apply: bool = typer.Option(False, "--apply", help="执行写入。默认仅预览（dry-run）。"),
) -> None:
    with SessionLocal() as session:
        report = DatasetPipelineModeSeedService().run(session, dry_run=not apply)
    mode = "apply" if apply else "dry-run"
    typer.echo(f"ops-seed-dataset-pipeline-mode [{mode}]")
    typer.echo(f"dataset_total={report.dataset_total}")
    typer.echo(f"created={report.created}")
    typer.echo(f"updated={report.updated}")


@app.command("backfill-trade-cal")
def backfill_trade_cal(
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    exchange: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        service = HistoryBackfillService(session)
        summary = service.backfill_trade_calendar(date.fromisoformat(start_date), date.fromisoformat(end_date), exchange=exchange)
        DatasetStatusSnapshotService().refresh_resources(session, ["trade_cal"])
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("backfill-equity-series")
def backfill_equity_series(
    resource: str = typer.Option(
        ...,
        help="daily, adj_factor, stk_period_bar_week, stk_period_bar_month, "
        "stk_period_bar_adj_week, or stk_period_bar_adj_month",
    ),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        service = HistoryBackfillService(session)
        summary = service.backfill_equity_series(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            offset=offset,
            limit=limit,
            progress=typer.echo,
        )
        DatasetStatusSnapshotService().refresh_resources(session, [resource])
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("backfill-by-trade-date")
def backfill_by_trade_date(
    resource: str = typer.Option(
        ...,
        help="daily_basic, moneyflow, top_list, block_trade, limit_list_d, dc_member, ths_hot, dc_hot, limit_list_ths, limit_step, limit_cpt_list, or kpl_concept_cons",
    ),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    exchange: str | None = typer.Option(None),
    limit_type: str | None = typer.Option(None, "--limit-type"),
    ts_code: str | None = typer.Option(None),
    con_code: str | None = typer.Option(None, "--con-code"),
    idx_type: str | None = typer.Option(None, "--idx-type"),
    market: str | None = typer.Option(None, "--market"),
    hot_type: str | None = typer.Option(None, "--hot-type"),
    is_new: str | None = typer.Option(None, "--is-new"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        service = HistoryBackfillService(session)
        summary = service.backfill_by_trade_dates(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            exchange=exchange,
            limit_type=limit_type,
            ts_code=ts_code,
            con_code=con_code,
            idx_type=idx_type,
            market=market,
            hot_type=hot_type,
            is_new=is_new,
            offset=offset,
            limit=limit,
            progress=typer.echo,
        )
        DatasetStatusSnapshotService().refresh_resources(session, [resource])
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("backfill-by-date-range")
def backfill_by_date_range(
    resource: str = typer.Option(..., help="ths_daily, dc_index, dc_daily, or kpl_list"),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    ts_code: str | None = typer.Option(None),
    idx_type: str | None = typer.Option(None, "--idx-type"),
    tag: str | None = typer.Option(None, "--tag"),
) -> None:
    if resource not in {"ths_daily", "dc_index", "dc_daily", "kpl_list"}:
        raise typer.BadParameter("resource must be one of: ths_daily, dc_index, dc_daily, kpl_list")
    with SessionLocal() as session:
        reconciliation_service = SyncJobStateReconciliationService()
        snapshot_service = DatasetStatusSnapshotService()
        service = build_sync_service(resource, session)
        run_kwargs = {
            "ts_code": ts_code,
            "idx_type": idx_type,
            "start_date": start_date,
            "end_date": end_date,
        }
        if resource == "kpl_list":
            run_kwargs["tag"] = tag
        result = service.run_full(**run_kwargs)
        reconciliation_service.refresh_resource_state_from_observed(session, resource)
        snapshot_service.refresh_resources(session, [resource])
        typer.echo(f"{resource}: units=1 fetched={result.rows_fetched} written={result.rows_written}")


@app.command("backfill-low-frequency")
def backfill_low_frequency(
    resource: str = typer.Option(..., help="dividend or stk_holdernumber"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        service = HistoryBackfillService(session)
        summary = service.backfill_low_frequency_by_security(
            resource=resource,
            offset=offset,
            limit=limit,
            progress=typer.echo,
        )
        DatasetStatusSnapshotService().refresh_resources(session, [resource])
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("backfill-fund-series")
def backfill_fund_series(
    resource: str = typer.Option(..., help="fund_daily or fund_adj"),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        service = HistoryBackfillService(session)
        summary = service.backfill_fund_series(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            offset=offset,
            limit=limit,
            progress=typer.echo,
        )
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("backfill-index-series")
def backfill_index_series(
    resource: str = typer.Option(..., help="index_daily, index_weekly, index_monthly, index_daily_basic, or index_weight"),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        service = HistoryBackfillService(session)
        summary = service.backfill_index_series(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            offset=offset,
            limit=limit,
            progress=typer.echo,
        )
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("ops-scheduler-tick")
def ops_scheduler_tick(
    limit: int = typer.Option(100, min=1, max=1000, help="Maximum due schedules to enqueue in one tick."),
) -> None:
    with SessionLocal() as session:
        executions = OperationsScheduler().run_once(session, limit=limit)
        for execution in executions:
            typer.echo(
                "scheduled "
                f"execution#{execution.id} "
                f"schedule_id={execution.schedule_id} "
                f"spec={execution.spec_type}:{execution.spec_key} "
                f"status={execution.status}"
            )
        typer.echo(f"ops-scheduler-tick: scheduled={len(executions)}")


@app.command("ops-worker-run")
def ops_worker_run(
    limit: int = typer.Option(1, min=1, max=1000, help="Maximum queued executions to consume in one run."),
    auto_reconcile_stale_for_minutes: int = typer.Option(
        5,
        min=0,
        help="Automatically reconcile stale queued/running/canceling executions before consuming queue. Set 0 to disable.",
    ),
    auto_reconcile_limit: int = typer.Option(200, min=1, max=1000, help="Maximum open executions to inspect per auto-reconcile."),
) -> None:
    with SessionLocal() as session:
        reconciled = _auto_reconcile_stale_executions(
            session,
            stale_for_minutes=auto_reconcile_stale_for_minutes,
            limit=auto_reconcile_limit,
        )
        worker = OperationsWorker()
        processed = 0
        for _ in range(limit):
            execution = worker.run_next(session)
            if execution is None:
                break
            processed += 1
            typer.echo(
                "processed "
                f"execution#{execution.id} "
                f"status={execution.status} "
                f"rows_fetched={execution.rows_fetched} "
                f"rows_written={execution.rows_written}"
            )
        queued, running = _open_execution_counts(session)
        typer.echo(
            "ops-worker-run: "
            f"本轮新接任务={processed} "
            f"等待中={queued} "
            f"执行中={running} "
            f"自动收敛={reconciled}"
        )


@app.command("ops-scheduler-serve")
def ops_scheduler_serve(
    limit: int = typer.Option(100, min=1, max=1000, help="Maximum due schedules to enqueue per cycle."),
    sleep_seconds: float = typer.Option(30.0, min=1.0, help="Seconds to sleep between scheduler cycles."),
    max_cycles: int | None = typer.Option(None, min=1, help="Optional max cycles for testing or one-off runs."),
) -> None:
    cycles = 0
    while True:
        with SessionLocal() as session:
            executions = OperationsScheduler().run_once(session, limit=limit)
            typer.echo(f"ops-scheduler-serve: scheduled={len(executions)}")
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        time.sleep(sleep_seconds)


@app.command("ops-worker-serve")
def ops_worker_serve(
    limit: int = typer.Option(10, min=1, max=1000, help="Maximum queued executions to consume per cycle."),
    sleep_seconds: float = typer.Option(5.0, min=1.0, help="Seconds to sleep between worker cycles."),
    max_cycles: int | None = typer.Option(None, min=1, help="Optional max cycles for testing or one-off runs."),
    auto_reconcile_stale_for_minutes: int = typer.Option(
        5,
        min=0,
        help="Automatically reconcile stale queued/running/canceling executions before each cycle. Set 0 to disable.",
    ),
    auto_reconcile_limit: int = typer.Option(200, min=1, max=1000, help="Maximum open executions to inspect per auto-reconcile."),
) -> None:
    cycles = 0
    while True:
        with SessionLocal() as session:
            reconciled = _auto_reconcile_stale_executions(
                session,
                stale_for_minutes=auto_reconcile_stale_for_minutes,
                limit=auto_reconcile_limit,
            )
            worker = OperationsWorker()
            processed = 0
            for _ in range(limit):
                execution = worker.run_next(session)
                if execution is None:
                    break
                processed += 1
            queued, running = _open_execution_counts(session)
            typer.echo(
                "ops-worker-serve: "
                f"本轮新接任务={processed} "
                f"等待中={queued} "
                f"执行中={running} "
                f"自动收敛={reconciled}"
            )
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        time.sleep(sleep_seconds)


@app.command("ops-reconcile-executions")
def ops_reconcile_executions(
    stale_for_minutes: int = typer.Option(30, min=1, help="Treat queued/running executions without activity for this many minutes as stale."),
    limit: int = typer.Option(200, min=1, max=1000, help="Maximum open executions to inspect."),
    apply: bool = typer.Option(False, "--apply", help="Actually repair stale execution statuses. Without this flag, only preview."),
) -> None:
    with SessionLocal() as session:
        service = OperationsExecutionReconciliationService()
        if apply:
            reconciled = service.reconcile_stale_executions(session, stale_for_minutes=stale_for_minutes, limit=limit)
            for item in reconciled:
                typer.echo(
                    f"reconciled execution#{item.id} {item.previous_status}->{item.new_status} reason={item.reason}"
                )
            typer.echo(f"ops-reconcile-executions: reconciled={len(reconciled)}")
            return

        previews = service.preview_stale_executions(session, stale_for_minutes=stale_for_minutes, limit=limit)
        for item in previews:
            typer.echo(
                f"stale execution#{item.id} {item.previous_status}->{item.new_status} reason={item.reason}"
            )
        typer.echo(f"ops-reconcile-executions: stale={len(previews)}")


@app.command("ops-reconcile-sync-job-state")
def ops_reconcile_sync_job_state(
    apply: bool = typer.Option(False, "--apply", help="Actually repair stale sync_job_state rows. Without this flag, only preview."),
) -> None:
    with SessionLocal() as session:
        service = SyncJobStateReconciliationService()
        if apply:
            reconciled = service.reconcile_stale_sync_job_states(session)
            for item in reconciled:
                typer.echo(
                    "reconciled "
                    f"{item.job_name} "
                    f"{item.previous_last_success_date or 'none'}->{item.observed_last_success_date} "
                    f"target_table={item.target_table}"
                )
            typer.echo(f"ops-reconcile-sync-job-state: reconciled={len(reconciled)}")
            return

        previews = service.preview_stale_sync_job_states(session)
        for item in previews:
            typer.echo(
                "stale "
                f"{item.job_name} "
                f"{item.previous_last_success_date or 'none'}->{item.observed_last_success_date} "
                f"target_table={item.target_table}"
            )
        typer.echo(f"ops-reconcile-sync-job-state: stale={len(previews)}")
