from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from src.cli_parts.shared import (
    attach_cli_progress_reporter as _attach_cli_progress_reporter_impl,
    auto_reconcile_stale_executions as _auto_reconcile_stale_executions_impl,
    open_execution_counts as _open_execution_counts_impl,
    prepare_sync_kwargs_for_service as _prepare_sync_kwargs_for_service_impl,
    resolve_default_sync_date as _resolve_default_sync_date_impl,
)
from src.cli_parts.sync_handlers import (
    run_sync_daily as _run_sync_daily_impl,
    run_sync_history as _run_sync_history_impl,
)
from src.cli_parts.ops_handlers import (
    run_ops_daily_health_report as _run_ops_daily_health_report_impl,
    run_ops_rebuild_dataset_status as _run_ops_rebuild_dataset_status_impl,
    run_ops_reconcile_executions as _run_ops_reconcile_executions_impl,
    run_ops_reconcile_sync_job_state as _run_ops_reconcile_sync_job_state_impl,
    run_ops_scheduler_serve as _run_ops_scheduler_serve_impl,
    run_ops_scheduler_tick as _run_ops_scheduler_tick_impl,
    run_ops_seed_dataset_pipeline_mode as _run_ops_seed_dataset_pipeline_mode_impl,
    run_ops_seed_default_single_source as _run_ops_seed_default_single_source_impl,
    run_ops_seed_moneyflow_multi_source as _run_ops_seed_moneyflow_multi_source_impl,
    run_ops_validate_market_mood as _run_ops_validate_market_mood_impl,
    run_ops_worker_run as _run_ops_worker_run_impl,
    run_ops_worker_serve as _run_ops_worker_serve_impl,
    run_reconcile_moneyflow as _run_reconcile_moneyflow_impl,
    run_reconcile_stock_basic as _run_reconcile_stock_basic_impl,
)
from src.cli_parts.backfill_handlers import (
    run_backfill_by_date_range as _run_backfill_by_date_range_impl,
    run_backfill_by_trade_date as _run_backfill_by_trade_date_impl,
    run_backfill_equity_series as _run_backfill_equity_series_impl,
    run_backfill_fund_series as _run_backfill_fund_series_impl,
    run_backfill_index_series as _run_backfill_index_series_impl,
    run_backfill_low_frequency as _run_backfill_low_frequency_impl,
    run_backfill_trade_cal as _run_backfill_trade_cal_impl,
    run_reconcile_dataset as _run_reconcile_dataset_impl,
    run_refresh_serving_light as _run_refresh_serving_light_impl,
)
from src.foundation.dao.factory import DAOFactory
from src.foundation.config.logging import configure_logging
from src.foundation.config.settings import get_settings
from src.db import SessionLocal
from src.foundation.services.migration import RawTushareBootstrapService
from src.foundation.services.sync_v2.linter import lint_all_sync_v2_contracts
from src.foundation.serving import ServingPublishService, validate_serving_coverage
from src.ops.models.ops.job_execution import JobExecution
from src.ops.runtime import OperationsScheduler, OperationsWorker
from src.ops.services.operations_daily_health_report_service import DailyHealthReportService
from src.ops.services.operations_dataset_reconcile_service import DatasetReconcileService
from src.ops.services.operations_dataset_pipeline_mode_seed_service import DatasetPipelineModeSeedService
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.ops.services.operations_default_single_source_seed_service import DefaultSingleSourceSeedService
from src.ops.services.operations_execution_reconciliation_service import OperationsExecutionReconciliationService
from src.ops.services.operations_moneyflow_multi_source_seed_service import MoneyflowMultiSourceSeedService
from src.ops.services.operations_moneyflow_reconcile_service import MoneyflowReconcileService
from src.ops.services.operations_history_backfill_service import HistoryBackfillService
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshService
from src.ops.services.operations_stock_basic_reconcile_service import StockBasicReconcileService
from src.ops.services.operations_sync_job_state_reconciliation_service import SyncJobStateReconciliationService
from src.biz.services.market_mood_walkforward_validation_service import MarketMoodWalkForwardValidationService
from src.foundation.services.sync.registry import SYNC_SERVICE_REGISTRY, build_sync_service


app = typer.Typer(help="goldenshare market data foundation CLI")


def _alembic_config() -> Config:
    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def _resolve_default_sync_date(session) -> date:
    return _resolve_default_sync_date_impl(
        session,
        build_sync_service_fn=build_sync_service,
        default_exchange=get_settings().default_exchange,
    )


def _open_execution_counts(session) -> tuple[int, int]:
    return _open_execution_counts_impl(session, job_execution_model=JobExecution)


def _auto_reconcile_stale_executions(
    session,
    *,
    stale_for_minutes: int,
    limit: int,
) -> int:
    return _auto_reconcile_stale_executions_impl(
        session,
        stale_for_minutes=stale_for_minutes,
        limit=limit,
        reconciliation_service=OperationsExecutionReconciliationService(),
    )


def _prepare_sync_kwargs_for_service(service, kwargs: dict[str, object | None]) -> dict[str, object]:
    return _prepare_sync_kwargs_for_service_impl(service, kwargs)


def _attach_cli_progress_reporter(service, *, resource: str) -> None:
    _attach_cli_progress_reporter_impl(service, resource=resource)


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
    exchange_id: str | None = typer.Option(None, "--exchange-id", help="Optional exchange_id filter for margin resource."),
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
    _run_sync_history_impl(
        session_local=SessionLocal,
        build_sync_service_fn=build_sync_service,
        attach_progress_fn=_attach_cli_progress_reporter,
        prepare_kwargs_fn=_prepare_sync_kwargs_for_service,
        reconciliation_service_cls=SyncJobStateReconciliationService,
        snapshot_service_cls=DatasetStatusSnapshotService,
        resources=resources,
        ts_code=ts_code,
        list_status=list_status,
        classify=classify,
        index_code=index_code,
        con_code=con_code,
        exchange=exchange,
        exchange_id=exchange_id,
        ths_type=ths_type,
        idx_type=idx_type,
        market=market,
        hot_type=hot_type,
        is_new=is_new,
        tag=tag,
        limit_type=limit_type,
        start_date=start_date,
        end_date=end_date,
        echo_fn=typer.echo,
    )


@app.command("sync-daily")
def sync_daily(
    trade_date: str | None = typer.Option(None, help="YYYY-MM-DD"),
    ts_code: str | None = typer.Option(None),
    exchange: str | None = typer.Option(None, "--exchange"),
    exchange_id: str | None = typer.Option(None, "--exchange-id"),
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
            "margin",
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
    _run_sync_daily_impl(
        session_local=SessionLocal,
        resolve_default_sync_date_fn=_resolve_default_sync_date,
        build_sync_service_fn=build_sync_service,
        attach_progress_fn=_attach_cli_progress_reporter,
        prepare_kwargs_fn=_prepare_sync_kwargs_for_service,
        snapshot_service_cls=DatasetStatusSnapshotService,
        resources=resources,
        trade_date_text=trade_date,
        ts_code=ts_code,
        exchange=exchange,
        exchange_id=exchange_id,
        limit_type=limit_type,
        con_code=con_code,
        idx_type=idx_type,
        market=market,
        hot_type=hot_type,
        is_new=is_new,
        tag=tag,
        echo_fn=typer.echo,
    )


@app.command("rebuild-dm")
def rebuild_dm() -> None:
    with SessionLocal() as session:
        session.execute(text("REFRESH MATERIALIZED VIEW dm.equity_daily_snapshot"))
        session.commit()


@app.command("refresh-serving-light")
def refresh_serving_light(
    dataset: str = typer.Option("equity_daily_bar", "--dataset", "-d", help="当前仅支持 equity_daily_bar"),
    start_date: str | None = typer.Option(None, "--start-date", help="可选：起始日期 YYYY-MM-DD"),
    end_date: str | None = typer.Option(None, "--end-date", help="可选：结束日期 YYYY-MM-DD"),
    ts_code: str | None = typer.Option(None, "--ts-code", help="可选：仅刷新指定股票代码"),
) -> None:
    _run_refresh_serving_light_impl(
        session_local=SessionLocal,
        refresh_service_cls=ServingLightRefreshService,
        dataset=dataset,
        start_date=start_date,
        end_date=end_date,
        ts_code=ts_code,
        echo_fn=typer.echo,
    )


@app.command("list-resources")
def list_resources() -> None:
    for resource in SYNC_SERVICE_REGISTRY:
        typer.echo(resource)


@app.command("sync-v2-lint-contracts")
def sync_v2_lint_contracts() -> None:
    report = lint_all_sync_v2_contracts()
    if report.passed:
        typer.echo("sync-v2-lint-contracts: passed")
        return
    typer.echo(f"sync-v2-lint-contracts: failed issues={len(report.issues)}")
    for issue in report.issues:
        typer.echo(f" - dataset={issue.dataset_key} code={issue.code} message={issue.message}")
    raise typer.Exit(code=1)


@app.command("reconcile-dataset")
def reconcile_dataset(
    dataset: str = typer.Option(
        ...,
        "--dataset",
        "-d",
        help=(
            "当前支持 trade_cal/daily/daily_basic/fund_daily/adj_factor/stk_limit/"
            "suspend_d/margin/dc_index/index_daily/index_daily_basic/"
            "limit_list_d/limit_list_ths/"
            "moneyflow/moneyflow_ths/moneyflow_dc/moneyflow_cnt_ths/"
            "moneyflow_ind_ths/moneyflow_ind_dc/moneyflow_mkt_dc/"
            "top_list/block_trade/stock_st/stk_nineturn/dc_member/"
            "fund_adj/index_basic/etf_basic/etf_index/hk_basic/us_basic/"
            "ths_index/kpl_list/kpl_concept_cons/broker_recommend"
        ),
    ),
    start_date: str | None = typer.Option(None, "--start-date", help="可选：起始日期 YYYY-MM-DD"),
    end_date: str | None = typer.Option(None, "--end-date", help="可选：结束日期 YYYY-MM-DD"),
    sample_limit: int = typer.Option(20, "--sample-limit", min=0, max=200, help="输出每日差异样例上限"),
    abs_diff_threshold: int = typer.Option(
        -1,
        "--abs-diff-threshold",
        help="总行数绝对差阈值；-1 表示不校验。超过阈值时返回非 0。",
    ),
) -> None:
    _run_reconcile_dataset_impl(
        session_local=SessionLocal,
        reconcile_service_cls=DatasetReconcileService,
        dataset=dataset,
        start_date=start_date,
        end_date=end_date,
        sample_limit=sample_limit,
        abs_diff_threshold=abs_diff_threshold,
        echo_fn=typer.echo,
    )


@app.command("ops-rebuild-dataset-status")
def ops_rebuild_dataset_status() -> None:
    _run_ops_rebuild_dataset_status_impl(
        session_local=SessionLocal,
        dataset_status_snapshot_service_cls=DatasetStatusSnapshotService,
        echo_fn=typer.echo,
    )


@app.command("ops-daily-health-report")
def ops_daily_health_report(
    report_date: str | None = typer.Option(None, "--date", help="报告日期，格式 YYYY-MM-DD；默认今天"),
    output_format: str = typer.Option("md", "--format", help="输出格式：md 或 json"),
    output: Path | None = typer.Option(None, "--output", help="输出文件路径；不传则打印到终端"),
) -> None:
    _run_ops_daily_health_report_impl(
        session_local=SessionLocal,
        daily_health_report_service_cls=DailyHealthReportService,
        report_date_text=report_date,
        output_format=output_format,
        output=output,
        echo_fn=typer.echo,
    )


@app.command("ops-validate-market-mood")
def ops_validate_market_mood(
    start_date: str | None = typer.Option(None, "--start-date", help="可选：起始日期 YYYY-MM-DD"),
    end_date: str | None = typer.Option(None, "--end-date", help="可选：结束日期 YYYY-MM-DD"),
    exchange: str = typer.Option("SSE", "--exchange", help="交易所，默认 SSE"),
    train_days: int = typer.Option(140, min=1, help="训练窗口交易日数"),
    valid_days: int = typer.Option(40, min=1, help="验证窗口交易日数"),
    test_days: int = typer.Option(20, min=1, help="测试窗口交易日数"),
    roll_days: int = typer.Option(20, min=1, help="每折向前滚动交易日数"),
    min_state_samples: int = typer.Option(30, min=1, help="状态最小样本阈值"),
    max_signal_days: int | None = typer.Option(None, min=1, help="最多使用最近 N 个共同交易日"),
    delta_temp: float = typer.Option(5.0, "--delta-temp", help="MTI 连续标签容忍阈值"),
    delta_emotion: float = typer.Option(8.0, "--delta-emotion", help="MSI 连续标签容忍阈值"),
    include_points: bool = typer.Option(False, "--include-points", help="输出每个测试日的详细点位"),
    output: Path | None = typer.Option(None, "--output", help="输出文件路径；不传则打印到终端"),
) -> None:
    _run_ops_validate_market_mood_impl(
        session_local=SessionLocal,
        validation_service_cls=MarketMoodWalkForwardValidationService,
        start_date_text=start_date,
        end_date_text=end_date,
        exchange=exchange,
        train_days=train_days,
        valid_days=valid_days,
        test_days=test_days,
        roll_days=roll_days,
        min_state_samples=min_state_samples,
        max_signal_days=max_signal_days,
        delta_temp=delta_temp,
        delta_emotion=delta_emotion,
        include_points=include_points,
        output=output,
        echo_fn=typer.echo,
    )


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
    _run_reconcile_stock_basic_impl(
        session_local=SessionLocal,
        reconcile_service_cls=StockBasicReconcileService,
        sample_limit=sample_limit,
        threshold_only_tushare=threshold_only_tushare,
        threshold_only_biying=threshold_only_biying,
        threshold_comparable_diff=threshold_comparable_diff,
        echo_fn=typer.echo,
    )


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
    _run_reconcile_moneyflow_impl(
        session_local=SessionLocal,
        reconcile_service_cls=MoneyflowReconcileService,
        start_date_text=start_date,
        end_date_text=end_date,
        range_days=range_days,
        sample_limit=sample_limit,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
        threshold_only_tushare=threshold_only_tushare,
        threshold_only_biying=threshold_only_biying,
        threshold_comparable_diff=threshold_comparable_diff,
        echo_fn=typer.echo,
    )


@app.command("ops-seed-default-single-source")
def ops_seed_default_single_source(
    source_key: str = typer.Option("tushare", "--source-key", help="默认来源键（例如 tushare）。"),
    apply: bool = typer.Option(False, "--apply", help="执行写入。默认仅预览（dry-run）。"),
) -> None:
    _run_ops_seed_default_single_source_impl(
        session_local=SessionLocal,
        service_cls=DefaultSingleSourceSeedService,
        source_key=source_key,
        apply=apply,
        echo_fn=typer.echo,
    )


@app.command("ops-seed-moneyflow-multi-source")
def ops_seed_moneyflow_multi_source(
    apply: bool = typer.Option(False, "--apply", help="执行写入。默认仅预览（dry-run）。"),
) -> None:
    _run_ops_seed_moneyflow_multi_source_impl(
        session_local=SessionLocal,
        service_cls=MoneyflowMultiSourceSeedService,
        apply=apply,
        echo_fn=typer.echo,
    )


@app.command("ops-seed-dataset-pipeline-mode")
def ops_seed_dataset_pipeline_mode(
    apply: bool = typer.Option(False, "--apply", help="执行写入。默认仅预览（dry-run）。"),
) -> None:
    _run_ops_seed_dataset_pipeline_mode_impl(
        session_local=SessionLocal,
        service_cls=DatasetPipelineModeSeedService,
        apply=apply,
        echo_fn=typer.echo,
    )


@app.command("backfill-trade-cal")
def backfill_trade_cal(
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    exchange: str | None = typer.Option(None),
) -> None:
    _run_backfill_trade_cal_impl(
        session_local=SessionLocal,
        history_backfill_service_cls=HistoryBackfillService,
        snapshot_service_cls=DatasetStatusSnapshotService,
        start_date=start_date,
        end_date=end_date,
        exchange=exchange,
        echo_fn=typer.echo,
    )


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
    _run_backfill_equity_series_impl(
        session_local=SessionLocal,
        history_backfill_service_cls=HistoryBackfillService,
        snapshot_service_cls=DatasetStatusSnapshotService,
        resource=resource,
        start_date=start_date,
        end_date=end_date,
        offset=offset,
        limit=limit,
        echo_fn=typer.echo,
    )


@app.command("backfill-by-trade-date")
def backfill_by_trade_date(
    resource: str = typer.Option(
        ...,
        help="daily_basic, moneyflow, margin, top_list, block_trade, limit_list_d, dc_member, ths_hot, dc_hot, limit_list_ths, limit_step, limit_cpt_list, or kpl_concept_cons",
    ),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    exchange: str | None = typer.Option(None),
    exchange_id: str | None = typer.Option(None, "--exchange-id"),
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
    _run_backfill_by_trade_date_impl(
        session_local=SessionLocal,
        history_backfill_service_cls=HistoryBackfillService,
        snapshot_service_cls=DatasetStatusSnapshotService,
        resource=resource,
        start_date=start_date,
        end_date=end_date,
        exchange=exchange,
        exchange_id=exchange_id,
        limit_type=limit_type,
        ts_code=ts_code,
        con_code=con_code,
        idx_type=idx_type,
        market=market,
        hot_type=hot_type,
        is_new=is_new,
        offset=offset,
        limit=limit,
        echo_fn=typer.echo,
    )


@app.command("backfill-by-date-range")
def backfill_by_date_range(
    resource: str = typer.Option(..., help="ths_daily, dc_index, dc_daily, or kpl_list"),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    ts_code: str | None = typer.Option(None),
    idx_type: str | None = typer.Option(None, "--idx-type"),
    tag: str | None = typer.Option(None, "--tag"),
) -> None:
    _run_backfill_by_date_range_impl(
        session_local=SessionLocal,
        build_sync_service_fn=build_sync_service,
        reconciliation_service_cls=SyncJobStateReconciliationService,
        snapshot_service_cls=DatasetStatusSnapshotService,
        resource=resource,
        start_date=start_date,
        end_date=end_date,
        ts_code=ts_code,
        idx_type=idx_type,
        tag=tag,
        echo_fn=typer.echo,
    )


@app.command("backfill-low-frequency")
def backfill_low_frequency(
    resource: str = typer.Option(..., help="dividend or stk_holdernumber"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    _run_backfill_low_frequency_impl(
        session_local=SessionLocal,
        history_backfill_service_cls=HistoryBackfillService,
        snapshot_service_cls=DatasetStatusSnapshotService,
        resource=resource,
        offset=offset,
        limit=limit,
        echo_fn=typer.echo,
    )


@app.command("backfill-fund-series")
def backfill_fund_series(
    resource: str = typer.Option(..., help="fund_daily or fund_adj"),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    _run_backfill_fund_series_impl(
        session_local=SessionLocal,
        history_backfill_service_cls=HistoryBackfillService,
        resource=resource,
        start_date=start_date,
        end_date=end_date,
        offset=offset,
        limit=limit,
        echo_fn=typer.echo,
    )


@app.command("backfill-index-series")
def backfill_index_series(
    resource: str = typer.Option(..., help="index_daily, index_weekly, index_monthly, index_daily_basic, or index_weight"),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    offset: int = typer.Option(0),
    limit: int | None = typer.Option(None),
) -> None:
    _run_backfill_index_series_impl(
        session_local=SessionLocal,
        history_backfill_service_cls=HistoryBackfillService,
        resource=resource,
        start_date=start_date,
        end_date=end_date,
        offset=offset,
        limit=limit,
        echo_fn=typer.echo,
    )


@app.command("ops-scheduler-tick")
def ops_scheduler_tick(
    limit: int = typer.Option(100, min=1, max=1000, help="Maximum due schedules to enqueue in one tick."),
) -> None:
    _run_ops_scheduler_tick_impl(
        session_local=SessionLocal,
        scheduler_cls=OperationsScheduler,
        limit=limit,
        echo_fn=typer.echo,
    )


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
    _run_ops_worker_run_impl(
        session_local=SessionLocal,
        worker_cls=OperationsWorker,
        auto_reconcile_fn=_auto_reconcile_stale_executions,
        open_execution_counts_fn=_open_execution_counts,
        limit=limit,
        auto_reconcile_stale_for_minutes=auto_reconcile_stale_for_minutes,
        auto_reconcile_limit=auto_reconcile_limit,
        echo_fn=typer.echo,
    )


@app.command("ops-scheduler-serve")
def ops_scheduler_serve(
    limit: int = typer.Option(100, min=1, max=1000, help="Maximum due schedules to enqueue per cycle."),
    sleep_seconds: float = typer.Option(30.0, min=1.0, help="Seconds to sleep between scheduler cycles."),
    max_cycles: int | None = typer.Option(None, min=1, help="Optional max cycles for testing or one-off runs."),
) -> None:
    _run_ops_scheduler_serve_impl(
        session_local=SessionLocal,
        scheduler_cls=OperationsScheduler,
        limit=limit,
        sleep_seconds=sleep_seconds,
        max_cycles=max_cycles,
        echo_fn=typer.echo,
    )


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
    _run_ops_worker_serve_impl(
        session_local=SessionLocal,
        worker_cls=OperationsWorker,
        auto_reconcile_fn=_auto_reconcile_stale_executions,
        open_execution_counts_fn=_open_execution_counts,
        limit=limit,
        sleep_seconds=sleep_seconds,
        max_cycles=max_cycles,
        auto_reconcile_stale_for_minutes=auto_reconcile_stale_for_minutes,
        auto_reconcile_limit=auto_reconcile_limit,
        echo_fn=typer.echo,
    )


@app.command("ops-reconcile-executions")
def ops_reconcile_executions(
    stale_for_minutes: int = typer.Option(30, min=1, help="Treat queued/running executions without activity for this many minutes as stale."),
    limit: int = typer.Option(200, min=1, max=1000, help="Maximum open executions to inspect."),
    apply: bool = typer.Option(False, "--apply", help="Actually repair stale execution statuses. Without this flag, only preview."),
) -> None:
    _run_ops_reconcile_executions_impl(
        session_local=SessionLocal,
        service_cls=OperationsExecutionReconciliationService,
        stale_for_minutes=stale_for_minutes,
        limit=limit,
        apply=apply,
        echo_fn=typer.echo,
    )


@app.command("ops-reconcile-sync-job-state")
def ops_reconcile_sync_job_state(
    apply: bool = typer.Option(False, "--apply", help="Actually repair stale sync_job_state rows. Without this flag, only preview."),
) -> None:
    _run_ops_reconcile_sync_job_state_impl(
        session_local=SessionLocal,
        service_cls=SyncJobStateReconciliationService,
        apply=apply,
        echo_fn=typer.echo,
    )
