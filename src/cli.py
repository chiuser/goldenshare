from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from src.config.logging import configure_logging
from src.config.settings import get_settings
from src.db import SessionLocal
from src.operations.runtime import OperationsScheduler, OperationsWorker
from src.services.history_backfill_service import HistoryBackfillService
from src.services.sync.registry import SYNC_SERVICE_REGISTRY, build_sync_service


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


@app.callback()
def main() -> None:
    configure_logging()


@app.command("init-db")
def init_db() -> None:
    command.upgrade(_alembic_config(), "head")


@app.command("sync-history")
def sync_history(
    resources: list[str] = typer.Option(..., "--resources", "-r"),
    ts_code: str | None = typer.Option(None),
    index_code: str | None = typer.Option(None, "--index-code", help="For index_weight, maps to Tushare index_code."),
    start_date: str | None = typer.Option(None),
    end_date: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        for resource in resources:
            service = build_sync_service(resource, session)
            kwargs = {"ts_code": ts_code, "index_code": index_code, "start_date": start_date, "end_date": end_date}
            service.run_full(**{k: v for k, v in kwargs.items() if v is not None})


@app.command("sync-daily")
def sync_daily(
    trade_date: str | None = typer.Option(None, help="YYYY-MM-DD"),
    resources: list[str] = typer.Option(
        ["daily", "adj_factor", "daily_basic", "moneyflow", "limit_list_d", "top_list", "block_trade", "fund_daily", "index_daily"],
        "--resources",
        "-r",
    ),
) -> None:
    target_date = date.fromisoformat(trade_date) if trade_date else None
    with SessionLocal() as session:
        if target_date is None:
            target_date = _resolve_default_sync_date(session)
        for resource in resources:
            service = build_sync_service(resource, session)
            service.run_incremental(trade_date=target_date)


@app.command("rebuild-dm")
def rebuild_dm() -> None:
    with SessionLocal() as session:
        session.execute(text("REFRESH MATERIALIZED VIEW dm.equity_daily_snapshot"))
        session.commit()


@app.command("list-resources")
def list_resources() -> None:
    for resource in SYNC_SERVICE_REGISTRY:
        typer.echo(resource)


@app.command("backfill-trade-cal")
def backfill_trade_cal(
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    exchange: str | None = typer.Option(None),
) -> None:
    with SessionLocal() as session:
        service = HistoryBackfillService(session)
        summary = service.backfill_trade_calendar(date.fromisoformat(start_date), date.fromisoformat(end_date), exchange=exchange)
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
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("backfill-by-trade-date")
def backfill_by_trade_date(
    resource: str = typer.Option(
        ...,
        help="daily_basic, moneyflow, or limit_list_d",
    ),
    start_date: str = typer.Option(..., help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., help="YYYY-MM-DD"),
    exchange: str | None = typer.Option(None),
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
            offset=offset,
            limit=limit,
            progress=typer.echo,
        )
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


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
        typer.echo(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


@app.command("backfill-fund-series")
def backfill_fund_series(
    resource: str = typer.Option(..., help="fund_daily"),
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
    resource: str = typer.Option(..., help="index_weekly, index_monthly, index_daily_basic, or index_weight"),
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
) -> None:
    with SessionLocal() as session:
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
        typer.echo(f"ops-worker-run: processed={processed}")
