"""Read-only full source probe for the index_global Bootstrap gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter, sleep
from typing import Callable

from orchestrator.defs.assets.index_global_raw import fetch_index_global_phase
from orchestrator.defs.bootstrap.index_global_bootstrap_plan import (
    IndexGlobalDatePlan,
    build_date_plan,
)
from orchestrator.defs.resources import TushareResource
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_NORMAL_PHASES,
    build_index_global_request_policy,
)


_SAMPLE_LIMIT = 20


@dataclass(frozen=True, slots=True)
class IndexGlobalSourceProbeReport:
    generated_at: str
    date_plan: IndexGlobalDatePlan
    source_method: str
    attempted_phase_count: int
    successful_phase_count: int
    empty_phase_count: int
    failed_phase_count: int
    source_row_count: int
    request_count: int
    page_count: int
    retry_count: int
    throttle_wait_ms: float
    elapsed_ms: float
    average_phase_elapsed_ms: float
    failure_samples: tuple[str, ...]
    empty_phase_samples: tuple[str, ...]
    should_stop: bool
    stop_reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "date_plan": self.date_plan.to_dict(),
            "failure_samples": list(self.failure_samples),
            "empty_phase_samples": list(self.empty_phase_samples),
            "throttle_wait_ms": round(self.throttle_wait_ms, 3),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "average_phase_elapsed_ms": round(self.average_phase_elapsed_ms, 3),
        }


def probe_index_global_source(
    *,
    tushare: TushareResource,
    date_plan: IndexGlobalDatePlan,
    stop_on_first_failure: bool = True,
    sleep_fn: Callable[[float], None] = sleep,
) -> IndexGlobalSourceProbeReport:
    """Probe every date/phase without promoting any result to the lake."""

    started = perf_counter()
    attempted = successful = empty = failed = 0
    source_rows = request_count = page_count = retry_count = 0
    phase_elapsed_ms = 0.0
    throttle_wait_ms = 0.0
    last_phase_finished_at: float | None = None
    failure_samples: list[str] = []
    empty_samples: list[str] = []
    minimum_interval_seconds = build_index_global_request_policy().minimum_interval_seconds

    for trade_date in date_plan.expected_natural_dates:
        for phase in INDEX_GLOBAL_NORMAL_PHASES:
            attempted += 1
            if last_phase_finished_at is not None:
                wait_started_at = perf_counter()
                wait_seconds = max(
                    minimum_interval_seconds - (wait_started_at - last_phase_finished_at),
                    0.0,
                )
                if wait_seconds:
                    sleep_fn(wait_seconds)
                    throttle_wait_ms += wait_seconds * 1000
            try:
                result = fetch_index_global_phase(
                    tushare=tushare,
                    trade_date=trade_date,
                    probe_phase=phase,
                    request_policy=build_index_global_request_policy(),
                )
            except Exception as exc:
                last_phase_finished_at = perf_counter()
                failed += 1
                if len(failure_samples) < _SAMPLE_LIMIT:
                    failure_samples.append(f"{trade_date}:{phase}:{exc}")
                if stop_on_first_failure:
                    break
                continue
            last_phase_finished_at = perf_counter()

            successful += 1
            source_rows += len(result.rows)
            request_count += result.request_count
            page_count += result.page_count
            retry_count += result.retry_count
            phase_elapsed_ms += result.elapsed_ms
            if result.empty:
                empty += 1
                if len(empty_samples) < _SAMPLE_LIMIT:
                    empty_samples.append(f"{trade_date}:{phase}")
        if failed and stop_on_first_failure:
            break

    elapsed_ms = (perf_counter() - started) * 1000
    return IndexGlobalSourceProbeReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        date_plan=date_plan,
        source_method="tushare_index_global_readonly_probe",
        attempted_phase_count=attempted,
        successful_phase_count=successful,
        empty_phase_count=empty,
        failed_phase_count=failed,
        source_row_count=source_rows,
        request_count=request_count,
        page_count=page_count,
        retry_count=retry_count,
        throttle_wait_ms=throttle_wait_ms,
        elapsed_ms=elapsed_ms,
        average_phase_elapsed_ms=(phase_elapsed_ms / successful if successful else 0.0),
        failure_samples=tuple(failure_samples),
        empty_phase_samples=tuple(empty_samples),
        should_stop=bool(failed),
        stop_reason_codes=("source_probe_failed",) if failed else (),
    )


def run_source_probe(
    *,
    tushare: TushareResource,
    start_date: str | None = None,
    end_date: str | None = None,
) -> IndexGlobalSourceProbeReport:
    return probe_index_global_source(
        tushare=tushare,
        date_plan=build_date_plan(start_date=start_date, end_date=end_date),
    )


def write_report(report: IndexGlobalSourceProbeReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


__all__ = [
    "IndexGlobalSourceProbeReport",
    "probe_index_global_source",
    "run_source_probe",
    "write_report",
]
