from __future__ import annotations

from datetime import date
from typing import Callable

import typer
from sqlalchemy import select

from src.foundation.models.core.trade_calendar import TradeCalendar


def run_refresh_serving_light(
    *,
    session_local,
    refresh_service_cls,
    dataset: str,
    start_date: str | None,
    end_date: str | None,
    ts_code: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    dataset_key = dataset.strip().lower()
    if dataset_key != "equity_daily_bar":
        raise typer.BadParameter("当前仅支持 --dataset equity_daily_bar")

    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
        raise typer.BadParameter("start_date 不能晚于 end_date")

    normalized_ts_code = ts_code.strip().upper() if ts_code else None
    with session_local() as session:
        result = refresh_service_cls().refresh_equity_daily_bar(
            session,
            start_date=parsed_start,
            end_date=parsed_end,
            ts_code=normalized_ts_code,
        )
    echo_fn(
        "refresh-serving-light done "
        f"dataset={dataset_key} "
        f"ts_code={normalized_ts_code or '*'} "
        f"start_date={parsed_start} "
        f"end_date={parsed_end} "
        f"touched_rows={result.touched_rows}"
    )


def run_wealth_build_turnover_snapshot(
    *,
    session_local,
    service_cls,
    trade_date: str | None,
    start_date: str | None,
    end_date: str | None,
    freqs: list[int],
    default_exchange: str,
    echo_fn: Callable[[str], None],
) -> None:
    if trade_date and (start_date or end_date):
        raise typer.BadParameter("--trade-date 不能与 --start-date/--end-date 同时使用")
    if (start_date and not end_date) or (end_date and not start_date):
        raise typer.BadParameter("--start-date 与 --end-date 必须同时提供")
    if not trade_date and not start_date and not end_date:
        raise typer.BadParameter("必须提供 --trade-date，或同时提供 --start-date 与 --end-date")

    if start_date and end_date:
        _run_wealth_build_turnover_snapshot_range(
            session_local=session_local,
            service_cls=service_cls,
            start_date=start_date,
            end_date=end_date,
            freqs=freqs,
            default_exchange=default_exchange,
            echo_fn=echo_fn,
        )
        return

    assert trade_date is not None
    try:
        parsed_trade_date = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise typer.BadParameter("trade_date 必须为 YYYY-MM-DD 格式") from exc
    with session_local() as session:
        service = service_cls()
        try:
            results = service.materialize_trade_date(
                session,
                trade_date=parsed_trade_date,
                freqs=freqs or None,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        session.commit()

    ready = sum(1 for item in results if item.build_status == "READY")
    failed = len(results) - ready
    for item in results:
        latest = item.latest_trade_time.strftime("%Y-%m-%d %H:%M:%S") if item.latest_trade_time else "-"
        note = item.build_note or "-"
        echo_fn(
            "turnover-snapshot "
            f"trade_date={item.trade_date.isoformat()} "
            f"freq={item.freq} "
            f"status={item.build_status} "
            f"latest_trade_time={latest} "
            f"security_count={item.security_count} "
            f"source_row_count={item.source_row_count} "
            f"points={item.points_count} "
            f"total_amount={item.total_amount} "
            f"total_vol={item.total_vol} "
            f"note={note}"
        )

    echo_fn(
        "wealth-build-turnover-snapshot done "
        f"trade_date={parsed_trade_date.isoformat()} "
        f"freq_count={len(results)} "
        f"ready={ready} failed={failed}"
    )


def _run_wealth_build_turnover_snapshot_range(
    *,
    session_local,
    service_cls,
    start_date: str,
    end_date: str,
    freqs: list[int],
    default_exchange: str,
    echo_fn: Callable[[str], None],
) -> None:
    try:
        parsed_start_date = date.fromisoformat(start_date)
        parsed_end_date = date.fromisoformat(end_date)
    except ValueError as exc:
        raise typer.BadParameter("start_date/end_date 必须为 YYYY-MM-DD 格式") from exc
    if parsed_start_date > parsed_end_date:
        raise typer.BadParameter("start_date 不能晚于 end_date")

    with session_local() as session:
        trade_dates = list(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(
                    TradeCalendar.exchange == default_exchange,
                    TradeCalendar.trade_date >= parsed_start_date,
                    TradeCalendar.trade_date <= parsed_end_date,
                    TradeCalendar.is_open.is_(True),
                )
                .order_by(TradeCalendar.trade_date)
            )
        )

    if not trade_dates:
        raise typer.BadParameter(
            f"区间 {parsed_start_date.isoformat()}~{parsed_end_date.isoformat()} 内没有开市交易日"
        )

    requested_freqs = freqs or [1, 5, 15, 30, 60]
    echo_fn(
        "wealth-build-turnover-snapshot plan "
        f"range={parsed_start_date.isoformat()}~{parsed_end_date.isoformat()} "
        f"trade_days={len(trade_dates)} "
        f"freqs={','.join(str(freq) for freq in requested_freqs)}"
    )

    total_ready = 0
    total_failed = 0
    total_freq_jobs = 0
    exception_dates: list[str] = []
    for index, current_trade_date in enumerate(trade_dates, start=1):
        with session_local() as session:
            service = service_cls()
            try:
                results = service.materialize_trade_date(
                    session,
                    trade_date=current_trade_date,
                    freqs=freqs or None,
                )
            except ValueError as exc:
                session.rollback()
                raise typer.BadParameter(str(exc)) from exc
            except Exception as exc:
                session.rollback()
                total_failed += len(requested_freqs)
                total_freq_jobs += len(requested_freqs)
                exception_dates.append(current_trade_date.isoformat())
                echo_fn(
                    f"[{index}/{len(trade_dates)}] "
                    f"trade_date={current_trade_date.isoformat()} "
                    f"ready=0 failed={len(requested_freqs)} "
                    f"error={type(exc).__name__}: {exc}"
                )
                continue
            session.commit()

        ready = sum(1 for item in results if item.build_status == "READY")
        failed = len(results) - ready
        total_ready += ready
        total_failed += failed
        total_freq_jobs += len(results)
        for item in results:
            latest = item.latest_trade_time.strftime("%Y-%m-%d %H:%M:%S") if item.latest_trade_time else "-"
            note = item.build_note or "-"
            echo_fn(
                "turnover-snapshot "
                f"trade_date={item.trade_date.isoformat()} "
                f"freq={item.freq} "
                f"status={item.build_status} "
                f"latest_trade_time={latest} "
                f"security_count={item.security_count} "
                f"source_row_count={item.source_row_count} "
                f"points={item.points_count} "
                f"total_amount={item.total_amount} "
                f"total_vol={item.total_vol} "
                f"note={note}"
            )
        echo_fn(
            f"[{index}/{len(trade_dates)}] "
            f"trade_date={current_trade_date.isoformat()} "
            f"ready={ready} failed={failed}"
        )

    summary = (
        "wealth-build-turnover-snapshot done "
        f"dates={len(trade_dates)} "
        f"freq_jobs={total_freq_jobs} "
        f"ready={total_ready} failed={total_failed}"
    )
    if exception_dates:
        summary += f" exception_dates={','.join(exception_dates)}"
    echo_fn(summary)
    if exception_dates:
        raise typer.Exit(code=1)
