from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

import typer


def run_repair_stock_st_missing_dates(
    *,
    session_local,
    service_cls,
    dates: list[str],
    date_file: Path | None,
    output_dir: Path | None,
    apply: bool,
    fail_on_review_items: bool,
    echo_fn: Callable[[str], None],
) -> None:
    parsed_dates = _parse_trade_dates(dates=dates, date_file=date_file)
    with session_local() as session:
        result = service_cls().run(
            session,
            trade_dates=parsed_dates,
            output_dir=output_dir,
            apply=apply,
            fail_on_review_items=fail_on_review_items,
        )

    preview_total = sum(preview.reconstructed_count for preview in result.date_previews)
    review_total = sum(preview.manual_review_count for preview in result.date_previews)
    mode = "apply" if apply else "preview"
    echo_fn(
        f"repair-stock-st-missing-dates [{mode}] "
        f"dates={len(result.date_previews)} "
        f"preview_rows={preview_total} "
        f"manual_review_items={review_total}"
    )
    echo_fn(f" - summary: {result.artifacts.summary_path}")
    echo_fn(f" - preview_rows: {result.artifacts.preview_rows_path}")
    echo_fn(f" - manual_review: {result.artifacts.manual_review_path}")
    if result.skipped_review_dates:
        echo_fn(
            " - skipped_review_dates: "
            + ", ".join(item.isoformat() for item in result.skipped_review_dates)
        )
    if apply:
        echo_fn(
            f" - applied_dates={result.applied_date_count} "
            f"applied_rows={result.applied_row_count}"
        )


def _parse_trade_dates(*, dates: list[str], date_file: Path | None) -> list[date]:
    values: list[str] = []
    values.extend(item.strip() for item in dates if item.strip())
    if date_file is not None:
        if not date_file.exists():
            raise typer.BadParameter(f"date_file 不存在：{date_file}")
        for line in date_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            values.append(stripped)
    if not values:
        raise typer.BadParameter("至少传一个 --date 或 --date-file。")

    parsed: list[date] = []
    invalid: list[str] = []
    for value in values:
        try:
            parsed.append(date.fromisoformat(value))
        except ValueError:
            invalid.append(value)
    if invalid:
        raise typer.BadParameter("日期格式错误，只支持 YYYY-MM-DD：" + ", ".join(invalid))
    return sorted(set(parsed))

