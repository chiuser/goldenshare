from __future__ import annotations

from datetime import date
from typing import Callable

import typer


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
    trade_date: str,
    freqs: list[int],
    echo_fn: Callable[[str], None],
) -> None:
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
