from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date
import json
import os
from pathlib import Path
from threading import Lock, local
import time
from typing import Any

import pytest
from sqlalchemy import text

from src.db import SessionLocal
from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.config.settings import get_settings


_RUN_FLAG = "RUN_TUSHARE_IDX_MINS_ACTIVE_POOL_PROBE"
_API_NAME = "idx_mins"
_ACTIVE_RESOURCE = os.getenv("IDX_MINS_ACTIVE_RESOURCE", "index_daily").strip() or "index_daily"
_ACTIVE_CODES_FILE = os.getenv("IDX_MINS_ACTIVE_CODES_FILE", "").strip()
_TRADE_DATE = os.getenv("IDX_MINS_PROBE_TRADE_DATE", "20260430").strip()
_FREQ = os.getenv("IDX_MINS_PROBE_FREQ", "30min").strip() or "30min"
_MAX_CALLS_PER_MINUTE = int(os.getenv("IDX_MINS_PROBE_MAX_CALLS_PER_MINUTE", "100"))
_MAX_WORKERS = int(os.getenv("IDX_MINS_PROBE_WORKERS", "8"))
_PAGE_LIMIT = int(os.getenv("IDX_MINS_PROBE_PAGE_LIMIT", "8000"))
_MAX_PAGES_PER_CODE = int(os.getenv("IDX_MINS_PROBE_MAX_PAGES_PER_CODE", "20"))
_FIELDS = (
    "ts_code",
    "trade_time",
    "close",
    "open",
    "high",
    "low",
    "vol",
    "amount",
    "freq",
    "exchange",
    "vwap",
)


@dataclass(frozen=True)
class _CodeProbeResult:
    ts_code: str
    row_count: int
    page_count: int
    first_trade_time: str | None
    last_trade_time: str | None
    error: str | None = None
    mismatched_ts_code_count: int = 0
    mismatched_freq_count: int = 0


class _MinuteRateLimiter:
    def __init__(self, max_calls_per_minute: int) -> None:
        self.max_calls = max_calls_per_minute
        self.window_seconds = 60.0
        self.calls: list[float] = []
        self.lock = Lock()

    def acquire(self) -> None:
        if self.max_calls <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                self.calls = [item for item in self.calls if now - item < self.window_seconds]
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                sleep_seconds = self.window_seconds - (now - self.calls[0]) + 0.05
            time.sleep(max(sleep_seconds, 0.05))


def _parse_yyyymmdd(value: str) -> date:
    normalized = value.replace("-", "").strip()
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid trade date: {value}")
    return date.fromisoformat(f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:8]}")


def _request_window(trade_date: str) -> tuple[str, str]:
    parsed = _parse_yyyymmdd(trade_date)
    day_text = parsed.isoformat()
    return f"{day_text} 09:00:00", f"{day_text} 19:00:00"


def _load_active_index_codes() -> list[str]:
    if _ACTIVE_CODES_FILE:
        path = Path(_ACTIVE_CODES_FILE)
        return [
            item.strip().upper()
            for item in path.read_text(encoding="utf-8").splitlines()
            if item.strip()
        ]

    with SessionLocal() as session:
        rows = session.execute(
            text(
                """
                SELECT ts_code
                FROM ops.index_series_active
                WHERE resource = :resource
                ORDER BY ts_code
                """
            ),
            {"resource": _ACTIVE_RESOURCE},
        ).scalars()
        return [str(item).strip().upper() for item in rows if str(item).strip()]


def _fetch_code_rows(
    client: TushareHttpClient,
    limiter: _MinuteRateLimiter,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    offset = 0
    page_count = 0
    while True:
        if page_count >= _MAX_PAGES_PER_CODE:
            raise RuntimeError(f"idx_mins exceeded max pages per code: ts_code={ts_code} pages={page_count}")
        limiter.acquire()
        page = client.call(
            api_name=_API_NAME,
            params={
                "ts_code": ts_code,
                "freq": _FREQ,
                "start_date": start_date,
                "end_date": end_date,
                "limit": _PAGE_LIMIT,
                "offset": offset,
            },
            fields=_FIELDS,
        )
        page_count += 1
        rows.extend(page)
        if len(page) < _PAGE_LIMIT:
            return rows, page_count
        offset += _PAGE_LIMIT


def _probe_code(
    client: TushareHttpClient,
    limiter: _MinuteRateLimiter,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> _CodeProbeResult:
    try:
        rows, page_count = _fetch_code_rows(client, limiter, ts_code=ts_code, start_date=start_date, end_date=end_date)
    except Exception as exc:
        return _CodeProbeResult(
            ts_code=ts_code,
            row_count=0,
            page_count=0,
            first_trade_time=None,
            last_trade_time=None,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    trade_times = sorted(str(row.get("trade_time")) for row in rows if row.get("trade_time") is not None)
    return _CodeProbeResult(
        ts_code=ts_code,
        row_count=len(rows),
        page_count=page_count,
        first_trade_time=trade_times[0] if trade_times else None,
        last_trade_time=trade_times[-1] if trade_times else None,
        mismatched_ts_code_count=sum(1 for row in rows if str(row.get("ts_code") or "").upper() != ts_code),
        mismatched_freq_count=sum(1 for row in rows if str(row.get("freq") or "").strip() not in {"", _FREQ}),
    )


_THREAD_LOCAL = local()


def _thread_client(token: str) -> TushareHttpClient:
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        client = TushareHttpClient(token=token)
        _THREAD_LOCAL.client = client
    return client


def _probe_code_in_worker(
    token: str,
    limiter: _MinuteRateLimiter,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> _CodeProbeResult:
    return _probe_code(
        _thread_client(token),
        limiter,
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )


def _write_report(results: list[_CodeProbeResult], *, active_count: int, start_date: str, end_date: str) -> Path:
    trade_date = _parse_yyyymmdd(_TRADE_DATE).strftime("%Y%m%d")
    report_path = Path(
        os.getenv(
            "IDX_MINS_PROBE_REPORT_PATH",
            f"reports/tushare_idx_mins_active_pool_probe_{trade_date}_{_FREQ}.json",
        )
    )
    empty_codes = [item.ts_code for item in results if item.row_count == 0 and item.error is None]
    error_codes = [item.ts_code for item in results if item.error is not None]
    mismatched_codes = [
        item.ts_code
        for item in results
        if item.mismatched_ts_code_count > 0 or item.mismatched_freq_count > 0
    ]
    payload = {
        "api_name": _API_NAME,
        "resource": _ACTIVE_RESOURCE,
        "active_codes_file": _ACTIVE_CODES_FILE or None,
        "trade_date": _TRADE_DATE,
        "freq": _FREQ,
        "start_date": start_date,
        "end_date": end_date,
        "rate_limit_per_minute": _MAX_CALLS_PER_MINUTE,
        "workers": _MAX_WORKERS,
        "active_count": active_count,
        "codes_with_rows": sum(1 for item in results if item.row_count > 0 and item.error is None),
        "codes_without_rows": len(empty_codes),
        "codes_with_errors": len(error_codes),
        "codes_with_field_mismatch": len(mismatched_codes),
        "total_rows": sum(item.row_count for item in results),
        "empty_codes": empty_codes,
        "error_codes": error_codes,
        "mismatched_codes": mismatched_codes,
        "results": [asdict(item) for item in results],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key != "results"}, ensure_ascii=False, indent=2))
    print(f"idx_mins probe report: {report_path}")
    return report_path


@pytest.mark.skipif(
    os.getenv(_RUN_FLAG) != "1",
    reason=f"set {_RUN_FLAG}=1 to probe live Tushare idx_mins active index pool",
)
def test_tushare_idx_mins_30min_covers_active_index_pool_on_20260430() -> None:
    settings = get_settings()
    if not settings.tushare_token:
        pytest.skip("TUSHARE_TOKEN is not configured")

    active_codes = _load_active_index_codes()
    assert active_codes, f"no active index codes found for resource={_ACTIVE_RESOURCE}"

    start_date, end_date = _request_window(_TRADE_DATE)
    limiter = _MinuteRateLimiter(_MAX_CALLS_PER_MINUTE)
    results: list[_CodeProbeResult] = []
    with ThreadPoolExecutor(max_workers=max(1, _MAX_WORKERS)) as executor:
        futures = [
            executor.submit(
                _probe_code_in_worker,
                settings.tushare_token,
                limiter,
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            for ts_code in active_codes
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if index == 1 or index % 50 == 0 or index == len(active_codes):
                print(
                    "idx_mins probe progress: "
                    f"{index}/{len(active_codes)} latest={result.ts_code} rows={result.row_count} "
                    f"errors={sum(1 for item in results if item.error is not None)}",
                    flush=True,
                )
    results.sort(key=lambda item: item.ts_code)
    _write_report(results, active_count=len(active_codes), start_date=start_date, end_date=end_date)

    empty_codes = [item.ts_code for item in results if item.row_count == 0 and item.error is None]
    error_codes = [item for item in results if item.error is not None]
    mismatched_codes = [
        item
        for item in results
        if item.mismatched_ts_code_count > 0 or item.mismatched_freq_count > 0
    ]

    assert not error_codes, f"idx_mins API errors: {error_codes[:10]}"
    assert not mismatched_codes, f"idx_mins field mismatches: {mismatched_codes[:10]}"
    assert not empty_codes, f"idx_mins returned no {_FREQ} rows for active codes: {empty_codes[:50]}"
