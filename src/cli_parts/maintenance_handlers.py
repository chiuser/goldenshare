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
