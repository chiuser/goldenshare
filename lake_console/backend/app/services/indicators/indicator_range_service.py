from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.indicators.indicator_compute_service import StkMinsIndicatorComputeService
from lake_console.backend.app.services.indicators.indicator_research_service import StkMinsIndicatorResearchService
from lake_console.backend.app.services.indicators.macd_spec import DEFAULT_MACD_PARAMS


class StkMinsIndicatorRangeService:
    def __init__(self, *, lake_root: Path, bucket_count: int, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.bucket_count = bucket_count
        self.progress = progress or print

    def compute_macd_range(
        self,
        *,
        mode: str,
        freqs: list[int],
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        if mode not in {"full", "incremental"}:
            raise ValueError("mode 仅支持 full 或 incremental。")
        if end_date < start_date:
            raise ValueError("end_date 不能早于 start_date。")
        freq_values = _normalize_freqs(freqs)
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        start_month = _month_key(start_date)
        end_month = _month_key(end_date)
        compute_service = StkMinsIndicatorComputeService(lake_root=self.lake_root, progress=self.progress)
        research_service = StkMinsIndicatorResearchService(
            lake_root=self.lake_root,
            bucket_count=self.bucket_count,
            progress=self.progress,
        )

        unit_summaries: list[dict[str, Any]] = []
        total_source_rows = 0
        total_indicator_rows = 0
        total_indicator_written_rows = 0
        total_research_written_rows = 0
        self.progress(
            f"[indicator_macd_range] start mode={mode} freqs={','.join(str(item) for item in freq_values)} "
            f"start_date={start_date.isoformat()} end_date={end_date.isoformat()}"
        )
        for index, freq in enumerate(freq_values, start=1):
            self.progress(f"[indicator_macd_range] compute unit={index}/{len(freq_values)} freq={freq}")
            compute_summary = compute_service.compute_macd(
                mode=mode,
                all_market=True,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
            )
            total_source_rows += int(compute_summary.get("source_rows") or 0)
            total_indicator_rows += int(compute_summary.get("indicator_rows") or 0)
            total_indicator_written_rows += int(compute_summary.get("written_rows") or 0)

            self.progress(
                f"[indicator_macd_range] research unit={index}/{len(freq_values)} freq={freq} "
                f"months={start_month}~{end_month}"
            )
            research_summary = research_service.rebuild_range(
                indicator="macd",
                params_key=DEFAULT_MACD_PARAMS.params_key,
                freq=freq,
                start_month=start_month,
                end_month=end_month,
            )
            total_research_written_rows += int(research_summary.get("written_rows") or 0)
            unit_summaries.append(
                {
                    "freq": freq,
                    "compute": compute_summary,
                    "research": research_summary,
                }
            )

        elapsed = time.monotonic() - started
        return {
            "operation": "compute_stk_mins_indicator_range",
            "indicator": "macd",
            "params_key": DEFAULT_MACD_PARAMS.params_key,
            "mode": mode,
            "scope": "all_market",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "freqs": freq_values,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "start_month": start_month,
            "end_month": end_month,
            "source_rows": total_source_rows,
            "indicator_rows": total_indicator_rows,
            "indicator_written_rows": total_indicator_written_rows,
            "research_written_rows": total_research_written_rows,
            "unit_summaries": unit_summaries,
            "elapsed_seconds": round(elapsed, 3),
        }


def _normalize_freqs(freqs: list[int]) -> list[int]:
    allowed = {1, 5, 15, 30, 60, 90, 120}
    if not freqs:
        raise ValueError("freqs 不能为空。")
    invalid = sorted(set(freqs) - allowed)
    if invalid:
        raise ValueError(f"不支持的 freqs={invalid}，允许值：1,5,15,30,60,90,120")
    return list(dict.fromkeys(int(item) for item in freqs))


def _month_key(value: date) -> str:
    return value.strftime("%Y-%m")
