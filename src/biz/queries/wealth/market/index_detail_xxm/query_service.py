from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
import hashlib
from pathlib import Path
import sys
from threading import BoundedSemaphore, Lock, RLock
import time
from typing import Any

from sqlalchemy.orm import Session

from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteHistoryBudgetError, IndexMinuteSourceContractError
from src.biz.schemas.wealth.market.index_detail_xxm import XxmResponseDto, XxmTopHistoryDto
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar, XxmPeriod
from .source import (CN_ZONE, INDICATOR_VERSION, XxmSourceError, assert_continuous, calendar_dates,
                     expected_through, minute_reader, minute_request, read_daily, read_minutes)


class XxmQueryError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _deep_size(value: Any, seen: set[int] | None = None) -> int:
    seen = set() if seen is None else seen
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(_deep_size(key, seen) + _deep_size(item, seen) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return size + sum(_deep_size(item, seen) for item in value)
    if is_dataclass(value):
        return size + sum(_deep_size(getattr(value, field.name), seen) for field in fields(value))
    if hasattr(value, "__dict__"):
        return size + _deep_size(vars(value), seen)
    return size


@dataclass
class SeriesEntry:
    raw: tuple[XxmBar, ...]
    signature: tuple
    calculator: XxmCalculator
    processed: tuple[XxmBar, ...]
    points: list[dict]
    events: list[dict]
    histories: dict[str, dict]
    fingerprints: list[str]


class XxmCache:
    def __init__(self, *, max_bytes: int = BUDGET.cache_max_bytes, max_series: int = BUDGET.cache_max_series) -> None:
        self.max_bytes, self.max_series = max_bytes, max_series
        self.entries: OrderedDict[tuple, tuple[SeriesEntry, int]] = OrderedDict()
        self.lock = RLock()

    def get(self, key: tuple) -> SeriesEntry | None:
        with self.lock:
            if key not in self.entries:
                return None
            self.entries.move_to_end(key)
            return self.entries[key][0]

    def put(self, key: tuple, entry: SeriesEntry) -> None:
        size = _deep_size(entry)
        with self.lock:
            self.entries.pop(key, None)
            if size <= self.max_bytes:
                self.entries[key] = (entry, size)
            while self.entries and (len(self.entries) > self.max_series or sum(v[1] for v in self.entries.values()) > self.max_bytes):
                self.entries.popitem(last=False)


_CACHE = XxmCache()
_REQUEST_SLOTS = BoundedSemaphore(BUDGET.max_concurrent_requests)
_SERIES_LOCKS = {period: Lock() for period in ("day", "m60", "m90", "m120")}


class IndexDetailXxmQueryService:
    def __init__(self, *, lake_root: Path | None = None, cache: XxmCache | None = None) -> None:
        self.reader = minute_reader(lake_root) if lake_root is not None else None
        self.cache = cache or _CACHE
        self.lake_identity = str(lake_root.resolve()) if lake_root is not None else "daily"

    def build(self, session: Session, *, period: XxmPeriod, start_date: date | None, end_date: date | None,
              limit: int, now: datetime | None = None) -> XxmResponseDto:
        if period not in _SERIES_LOCKS or not 1 <= limit <= BUDGET.max_response_rows or (start_date and end_date and start_date > end_date):
            raise XxmQueryError("XXM_REQUEST_INVALID", "研究指标请求参数不合法。", 400)
        if period != "day" and self.reader is None:
            raise XxmQueryError("XXM_QUERY_FAILED", "本地分钟来源未配置。", 503)
        started = time.perf_counter()

        def remaining() -> float:
            left = BUDGET.request_deadline_seconds - (time.perf_counter() - started)
            if left <= 0:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503)
            return left

        if not _REQUEST_SLOTS.acquire(blocking=False):
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询繁忙，请稍后重试。", 503)
        acquired = False
        try:
            acquired = _SERIES_LOCKS[period].acquire(timeout=remaining())
            if not acquired:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503)
            now = (now or datetime.now(CN_ZONE)).astimezone(CN_ZONE)
            open_dates = calendar_dates(session, end=now.date())
            completed = expected_through(period, open_dates, now, None)
            expected = expected_through(period, open_dates, now, end_date)
            key = (id(session.get_bind()), self.lake_identity, period, MAIN_SPEC.spec_hash)
            entry = self.cache.get(key)
            if period == "day":
                raw = read_daily(session, completed=completed, check=remaining)
                signature = ()
            else:
                assert self.reader is not None
                freq = int(period[1:])
                request = minute_request(freq, now.date())
                signature = tuple(self.reader.history_source_signature(request, dataset=dataset) for dataset in ("bars", "indicators"))
                remaining()
                raw = entry.raw if entry is not None and signature == entry.signature else read_minutes(
                    self.reader, freq=freq, end=now.date(), deadline=remaining)
            remaining()
            processed = tuple(bar for bar in raw if completed is not None and bar.time <= completed)
            assert_continuous(processed, period=period, open_dates=open_dates)
            origin = f"{period}|{processed[0].time if processed else 'empty'}|{INDICATOR_VERSION if period != 'day' else 'bfq'}"
            if entry is None or processed[:len(entry.processed)] != entry.processed or entry.calculator.source_identity != origin:
                entry = SeriesEntry(raw, signature, XxmCalculator(period=period, source_identity=origin), (), [], [], {}, [])
            offset = len(entry.processed)
            if offset != len(processed):
                calculator = XxmCalculator(period=period, source_identity=origin)
                calculator.restore(entry.calculator.snapshot())
                entry = SeriesEntry(raw, signature, calculator, entry.processed, list(entry.points),
                                    list(entry.events), dict(entry.histories), list(entry.fingerprints))
            for index in range(offset, len(processed)):
                if index % BUDGET.source_batch_rows == 0:
                    remaining()
                bar = processed[index]
                step = entry.calculator.step(bar)
                entry.points.append(step.point)
                entry.events.extend(step.events)
                entry.histories.update({history["id"]: history for history in step.histories})
                previous_hash = entry.fingerprints[-1] if entry.fingerprints else origin
                numeric = "|".join(float(v).hex() for v in (bar.close, bar.dif, bar.dea, bar.hist))
                entry.fingerprints.append(hashlib.sha256(f"{previous_hash}|{bar.time}|{numeric}".encode()).hexdigest())
            entry.processed, entry.raw, entry.signature = processed, raw, signature
            remaining()
            self.cache.put(key, entry)
            response = self._response(entry, period=period, expected=expected, start_date=start_date, limit=limit)
            if len(response.model_dump_json().encode()) > BUDGET.max_response_bytes:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标响应超过预算。", 503)
            remaining()
            return response
        except XxmQueryError:
            raise
        except (IndexMinuteHistoryBudgetError, OverflowError) as exc:
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标来源超过读取预算。", 503) from exc
        except (XxmSourceError, IndexMinuteSourceContractError, ValueError, TypeError) as exc:
            raise XxmQueryError("XXM_SOURCE_CONTRACT_INVALID", "研究指标来源存在缺口或字段不一致。") from exc
        except Exception as exc:
            remaining()
            raise XxmQueryError("XXM_QUERY_FAILED", "研究指标查询失败，请重试。") from exc
        finally:
            if acquired:
                _SERIES_LOCKS[period].release()
            _REQUEST_SLOTS.release()

    @staticmethod
    def _response(entry: SeriesEntry, *, period: XxmPeriod, expected: str | None,
                  start_date: date | None, limit: int) -> XxmResponseDto:
        times = [bar.time for bar in entry.processed]
        end_index = bisect_right(times, expected) if expected is not None else 0
        indices = [index for index in range(end_index) if start_date is None or times[index][:10] >= start_date.isoformat()][-limit:]
        points = [entry.points[index] for index in indices]
        first, last = (points[0]["time"], points[-1]["time"]) if points else (None, None)
        through = times[end_index - 1] if end_index else None
        events = [event for event in entry.events if first is not None and first <= event["time"] <= last]
        related = {event["relatedTopHistoryId"] for event in events if event["relatedTopHistoryId"]}
        histories = []
        for record in entry.histories.values():
            if through is None or record["confirmedAt"] > through:
                continue
            history = deepcopy(record)
            if history["endedAt"] is not None and history["endedAt"] > through:
                history.update(status="PENDING", endedAt=None, endReason=None)
            history["observedThrough"] = history["endedAt"] or through
            history["ageBars"] = bisect_right(times, history["observedThrough"]) - bisect_right(times, history["confirmedAt"])
            if first is not None and (history["id"] in related or history["status"] == "PENDING" or history["endedAt"] >= first):
                histories.append({field: history[field] for field in XxmTopHistoryDto.model_fields})
        status = "EMPTY" if through is None else "DELAYED" if expected and through < expected else "READY"
        message = "研究指标暂无数据" if status == "EMPTY" else f"研究指标数据截至 {through}" if status == "DELAYED" else None
        return XxmResponseDto(tsCode="000001.SH", period=period, algorithmVersion=MAIN_SPEC.algorithm_version,
                              specHash=MAIN_SPEC.spec_hash,
                              source={"kind": "daily_factor" if period == "day" else "minute_gold",
                                      "inputId": entry.fingerprints[end_index - 1] if end_index else hashlib.sha256(b"empty").hexdigest(),
                                      "startTime": times[0] if end_index else None, "computedThrough": through,
                                      "initialHistoryIncomplete": True, "indicatorVersion": None if period == "day" else INDICATOR_VERSION},
                              points=points, events=events, topHistories=histories,
                              meta={"count": len(points), "responseStart": first, "responseEnd": last},
                              dataStatus={"status": status, "message": message, "asOf": through})
