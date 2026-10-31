from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, datetime
import hashlib
from pathlib import Path
import sys
from threading import BoundedSemaphore, RLock
import time
from typing import Any

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteHistoryBudgetError, IndexMinuteSourceContractError
from src.biz.schemas.wealth.market.index_detail_xxm import InternalXxmResponseDto
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastResponseDto
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.snapshot_validation import validate_structure_record
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar, XxmPeriod
from .source import (CN_ZONE, INDICATOR_VERSION, XxmSourceError, assert_continuous, calendar_dates,
                     expected_through, minute_reader, minute_request, read_daily, read_minutes)
from .shared_loads import SharedLoads


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


@dataclass(frozen=True)
class SeriesEntry:
    raw: tuple[XxmBar, ...]
    signature: tuple
    calculator: XxmCalculator
    processed: tuple[XxmBar, ...]
    points: list[dict]
    events: list[dict]
    structure_records: dict[str, dict]
    fingerprints: list[str]
    checkpoints: dict[int, dict]
    open_dates: tuple[date, ...] = ()
    validated_through: str | None = None

    def calculator_at(self, count: int, check) -> XxmCalculator:
        """Independent real prefix state; no hypothetical/future state is cached."""
        if type(count) is not int or not 0 <= count <= len(self.processed):
            raise ValueError("XXM prefix outside processed source")
        check()
        current = self.calculator
        child = XxmCalculator(period=current.period, source_identity=current.source_identity,
                              ts_code=current.ts_code, spec=current.spec)
        if count == 0:
            check()
            return child
        if count == len(self.processed):
            child.restore(current.snapshot())
            check()
            return child
        offset = count // BUDGET.source_batch_rows * BUDGET.source_batch_rows
        if offset:
            snapshot = self.checkpoints[offset]
            if snapshot["processed"] != offset or snapshot["previous"]["time"] != self.processed[offset - 1].time:
                raise ValueError("XXM checkpoint is not the requested real prefix")
            child.restore(snapshot)
        for index in range(offset, count):
            if index % BUDGET.source_batch_rows == 0:
                check()
            child.step(self.processed[index])
        check()
        return child


class XxmCache:
    def __init__(self, *, max_bytes: int = BUDGET.cache_max_bytes, max_series: int = BUDGET.cache_max_series) -> None:
        self.max_bytes, self.max_series = max_bytes, max_series
        self.entries: OrderedDict[tuple, tuple[SeriesEntry | ForecastResponseDto, int]] = OrderedDict()
        self.lock = RLock()
        self.loads = SharedLoads(max_entries=max_series)

    def get(self, key: tuple) -> SeriesEntry | ForecastResponseDto | None:
        with self.lock:
            if key not in self.entries:
                return None
            self.entries.move_to_end(key)
            return self.entries[key][0]

    def put(self, key: tuple, entry: SeriesEntry | ForecastResponseDto, *, check=None) -> None:
        size = _deep_size(entry)
        if check is not None:
            check()
        with self.lock:
            if check is not None:
                check()
            self.entries.pop(key, None)
            if size <= self.max_bytes:
                self.entries[key] = (entry, size)
            while self.entries and (len(self.entries) > self.max_series or sum(v[1] for v in self.entries.values()) > self.max_bytes):
                self.entries.popitem(last=False)

    def get_forecast(self, key: tuple) -> ForecastResponseDto | None:
        response = self.get(("forecast", *key))
        return response.model_copy(deep=True) if response is not None else None

    def put_forecast(self, key: tuple, response: ForecastResponseDto) -> None:
        self.put(("forecast", *key), response.model_copy(deep=True))


_CACHE = XxmCache()
_REQUEST_SLOTS = BoundedSemaphore(BUDGET.max_concurrent_requests)
_PERIODS = ("day", "m60", "m90", "m120")


class IndexDetailXxmQueryService:
    def __init__(self, *, lake_root: Path | None = None, cache: XxmCache | None = None) -> None:
        self.reader = minute_reader(lake_root) if lake_root is not None else None
        self.cache = cache or _CACHE
        self.lake_identity = str(lake_root.resolve()) if lake_root is not None else "daily"

    def build(self, session: Session, *, period: XxmPeriod, start_date: date | None, end_date: date | None,
              limit: int, now: datetime | None = None) -> InternalXxmResponseDto:
        if period not in _PERIODS or not 1 <= limit <= BUDGET.max_response_rows or (start_date and end_date and start_date > end_date):
            raise XxmQueryError("XXM_REQUEST_INVALID", "研究指标请求参数不合法。", 400)
        with self.load_entry(session, period=period, now=now) as (entry, context, open_dates, remaining):
            upper = min(end_date or context.trade_date, context.trade_date)
            expected = expected_through(period, open_dates, context.generated_at, upper)
            response = self._response(entry, period=period, expected=expected, start_date=start_date, limit=limit, check=remaining)
            if len(response.model_dump_json().encode()) > BUDGET.max_response_bytes:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标响应超过预算。", 503)
            remaining()
            return response

    @contextmanager
    def load_entry(self, session: Session, *, period: XxmPeriod, now: datetime | None = None):
        """Publish a validated real prefix; consumers never hold a source slot."""
        if period not in _PERIODS:
            raise XxmQueryError("XXM_REQUEST_INVALID", "研究指标周期不合法。", 400)
        if period != "day" and self.reader is None:
            raise XxmQueryError("XXM_QUERY_FAILED", "本地分钟来源未配置。", 503)
        started = time.perf_counter()

        def remaining() -> float:
            left = BUDGET.request_deadline_seconds - (time.perf_counter() - started)
            if left <= 0:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503)
            return left

        try:
            now = (now or datetime.now(CN_ZONE)).astimezone(CN_ZONE)
            context = MarketPageContextQuery().resolve_context(
                session, market="CN_A", requested_trade_date=None, now=now,
            )
            remaining()
            key = (id(session.get_bind()), self.lake_identity, period, MAIN_SPEC.spec_hash)
            # Before/after the cutover and different calendar coverages cannot
            # join the same flight, even when their latest physical bar matches.
            completed_hint = expected_through(period, (context.trade_date,), now, context.trade_date)
            flight_key = (*key, context.trade_date, now.date(), completed_hint)
            def load():
                if not _REQUEST_SLOTS.acquire(timeout=remaining()):
                    raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503)
                try:
                    return self._load_series(session, key=key, period=period, now=now,
                                             business_date=context.trade_date, remaining=remaining)
                finally:
                    _REQUEST_SLOTS.release()
            entry, open_dates = self.cache.loads.load(flight_key, load, remaining)
            remaining()
            yield entry, context, open_dates, remaining
            remaining()
        except XxmQueryError:
            raise
        except TimeoutError as exc:
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503) from exc
        except (IndexMinuteHistoryBudgetError, OverflowError) as exc:
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标来源超过读取预算。", 503) from exc
        except (XxmSourceError, IndexMinuteSourceContractError, ValueError, TypeError) as exc:
            raise XxmQueryError("XXM_SOURCE_CONTRACT_INVALID", "研究指标来源存在缺口或字段不一致。") from exc
        except Exception as exc:
            remaining()
            raise XxmQueryError("XXM_QUERY_FAILED", "研究指标查询失败，请重试。") from exc

    def _load_series(self, session, *, key, period, now, business_date, remaining):
        open_dates = calendar_dates(session, end=now.date())
        completed = expected_through(period, open_dates, now, business_date)
        previous_entry = self.cache.get(key)
        if period == "day":
            raw = read_daily(session, completed=completed, check=remaining)
            signature = ()
        else:
            assert self.reader is not None
            freq = int(period[1:])
            request = minute_request(freq, business_date)
            signature = tuple(self.reader.history_source_signature(request, dataset=dataset) for dataset in ("bars", "indicators"))
            remaining()
            raw = previous_entry.raw if previous_entry is not None and signature == previous_entry.signature else read_minutes(
                self.reader, freq=freq, end=business_date, deadline=remaining)
        remaining()
        if (previous_entry is not None and signature == previous_entry.signature and raw == previous_entry.raw
                and completed == previous_entry.validated_through and open_dates == previous_entry.open_dates):
            return previous_entry, open_dates
        processed = tuple(bar for bar in raw if completed is not None and bar.time <= completed)
        assert_continuous(processed, period=period, open_dates=open_dates)
        origin = f"{period}|{processed[0].time if processed else 'empty'}|{INDICATOR_VERSION if period != 'day' else 'bfq'}"
        revised = (previous_entry is None or processed[:len(previous_entry.processed)] != previous_entry.processed
                   or previous_entry.calculator.source_identity != origin)
        calculator = XxmCalculator(period=period, source_identity=origin)
        if revised:
            entry = SeriesEntry(raw=raw, signature=signature, calculator=calculator, processed=(), points=[], events=[],
                                structure_records={}, fingerprints=[], checkpoints={})
        else:
            calculator.restore(previous_entry.calculator.snapshot())
            # No published container or terminal record is ever mutated in place.
            entry = SeriesEntry(raw=raw, signature=signature, calculator=calculator, processed=previous_entry.processed,
                                points=deepcopy(previous_entry.points), events=deepcopy(previous_entry.events),
                                structure_records=deepcopy(previous_entry.structure_records),
                                fingerprints=list(previous_entry.fingerprints), checkpoints=deepcopy(previous_entry.checkpoints))
        for index in range(len(entry.processed), len(processed)):
            if index % BUDGET.source_batch_rows == 0:
                remaining()
            bar = processed[index]
            step = entry.calculator.step(bar)
            self._merge_structure_updates(entry, step.structures, through=bar.time)
            if (index + 1) % BUDGET.source_batch_rows == 0:
                entry.checkpoints[index + 1] = entry.calculator.snapshot()
            entry.points.append(deepcopy(step.point))
            entry.events.extend(deepcopy(step.events))
            previous_hash = entry.fingerprints[-1] if entry.fingerprints else origin
            numeric = "|".join(float(v).hex() for v in (bar.close, bar.dif, bar.dea, bar.hist))
            entry.fingerprints.append(hashlib.sha256(f"{previous_hash}|{bar.time}|{numeric}".encode()).hexdigest())
        entry = replace(entry, processed=processed, raw=raw, signature=signature,
                        open_dates=open_dates, validated_through=completed)
        # Validate the entire candidate, including all structure associations,
        # before publishing. A failed candidate is discarded with its calculator.
        self._validate_entry(entry, check=remaining)
        self._response(entry, period=period, expected=completed, start_date=None,
                       limit=len(processed), check=remaining)
        remaining()
        self.cache.put(key, entry, check=remaining)
        return entry, open_dates

    @staticmethod
    def _validate_entry(entry: SeriesEntry, *, check) -> None:
        """A visible-window filter must never sanitize an invalid candidate."""
        count = len(entry.processed)
        if (entry.calculator.processed != count or len(entry.points) != count
                or len(entry.fingerprints) != count):
            raise ValueError("XXM result/source cardinality mismatch")
        times = {bar.time for bar in entry.processed}
        for index, (bar, point) in enumerate(zip(entry.processed, entry.points)):
            if index % BUDGET.source_batch_rows == 0:
                check()
            if any(point[field] != getattr(bar, field) for field in ("time", "close", "dif", "dea", "hist")):
                raise ValueError("XXM point differs from the original source bar")
        if any(event["time"] not in times for event in entry.events):
            raise ValueError("XXM event outside its real prefix")
        for index, (identity, record) in enumerate(entry.structure_records.items()):
            if index % BUDGET.source_batch_rows == 0:
                check()
            if not entry.processed or identity != record["id"]:
                raise ValueError("XXM structure outside its real prefix")
            validate_structure_record(record, period=entry.calculator.period, upper=entry.processed[-1].time,
                                      id_factory=entry.calculator._id)

    @staticmethod
    def _merge_structure_updates(entry: SeriesEntry, updates, *, through: str) -> None:
        seen = set()
        for incoming in updates:
            record = validate_structure_record(incoming, period=entry.calculator.period, upper=through,
                                               id_factory=entry.calculator._id)
            identity = record["id"]
            if identity in seen:
                raise ValueError("Duplicate structure update in one bar")
            seen.add(identity)
            previous = entry.structure_records.get(identity)
            if previous is None:
                if record["status"] not in ("ASSESSING", "FOLLOWING") or record["formedAt"] != through:
                    raise ValueError("A new structure must be formed by this bar")
            else:
                allowed = {"ASSESSING": {"FOLLOWING", "DISAPPEARED"},
                           "FOLLOWING": {"FOLLOWING", "FINISHED", "DISAPPEARED"}}
                if record["status"] not in allowed.get(previous["status"], set()):
                    raise ValueError("A terminal structure cannot be overwritten or reopened")
                changes = {"status", "originWave", "firstOppositeAt", "nextSameColorStart",
                           "trackingEndedAt", "disappearedAt", "disappearanceReason"}
                if any(record[field] != value for field, value in previous.items() if field not in changes):
                    raise ValueError("Structure formation facts are immutable")
                for field in changes - {"status"}:
                    if previous[field] is not None and record[field] != previous[field]:
                        raise ValueError("Known structure facts cannot be rewritten")
                changed_times = [record[field] for field in ("firstOppositeAt", "nextSameColorStart", "trackingEndedAt")
                                 if record[field] != previous[field]]
                if not changed_times or any(stamp != through for stamp in changed_times):
                    raise ValueError("A structure update must occur on this bar")
            entry.structure_records[identity] = record

    @staticmethod
    def _project_structure(record: dict, *, through: str) -> dict | None:
        if record["formedAt"] > through:
            return None
        result = deepcopy(record)
        if result["trackingEndedAt"] is not None and result["trackingEndedAt"] > through:
            result.update(status="FOLLOWING" if result["firstOppositeAt"] is not None
                          and result["firstOppositeAt"] <= through else "ASSESSING",
                          trackingEndedAt=None, disappearedAt=None, disappearanceReason=None)
        if result["nextSameColorStart"] is not None and result["nextSameColorStart"] > through:
            result["nextSameColorStart"] = None
        if result["firstOppositeAt"] is not None and result["firstOppositeAt"] > through:
            result.update(status="ASSESSING", originWave=None, firstOppositeAt=None, nextSameColorStart=None)
        return result

    @staticmethod
    def _response(entry: SeriesEntry, *, period: XxmPeriod, expected: str | None,
                  start_date: date | None, limit: int, check) -> InternalXxmResponseDto:
        times = [bar.time for bar in entry.processed]
        end_index = bisect_right(times, expected) if expected is not None else 0
        indices = [index for index in range(end_index) if start_date is None or times[index][:10] >= start_date.isoformat()][-limit:] if limit else []
        points = deepcopy([entry.points[index] for index in indices])
        first, last = (points[0]["time"], points[-1]["time"]) if points else (None, None)
        through = times[end_index - 1] if end_index else None
        events = deepcopy([event for event in entry.events if first is not None and first <= event["time"] <= last])
        related = {point["activeStructureId"] for point in points if point["activeStructureId"] is not None}
        related.update(event["relatedStructureId"] for event in events if event["relatedStructureId"] is not None)
        structures = []
        assessing = []
        following = {"TOP": None, "BOTTOM": None}
        for index, record in enumerate(entry.structure_records.values()):
            if index % BUDGET.source_batch_rows == 0:
                check()
            projected = IndexDetailXxmQueryService._project_structure(record, through=through) if through else None
            if projected is None:
                continue
            if projected["status"] == "ASSESSING":
                assessing.append(projected)
            if projected["status"] == "FOLLOWING":
                direction = projected["direction"]
                if following[direction] is not None:
                    raise ValueError("Multiple followed structures for one direction")
                following[direction] = projected
            stamps = tuple(projected[key] for key in ("formedAt", "firstOppositeAt", "nextSameColorStart",
                                                       "trackingEndedAt", "disappearedAt"))
            if (projected["id"] in related or first is not None
                    and (any(stamp is not None and first <= stamp <= last for stamp in stamps)
                         or projected["formedAt"] <= last and (projected["trackingEndedAt"] is None
                                                                or projected["trackingEndedAt"] >= first))):
                structures.append(projected)
        current = entry.calculator_at(end_index, check)
        if assessing != ([current.active_structure] if current.active_structure is not None else []):
            raise ValueError("Projected structure differs from the actual prefix calculator")
        if following != current.followed_structures:
            raise ValueError("Projected following structures differ from the actual prefix calculator")
        status = "EMPTY" if through is None else "DELAYED" if expected and through < expected else "READY"
        message = "研究指标暂无数据" if status == "EMPTY" else f"研究指标数据截至 {through}" if status == "DELAYED" else None
        response = InternalXxmResponseDto(
            tsCode="000001.SH", period=period, algorithmVersion=MAIN_SPEC.algorithm_version, specHash=MAIN_SPEC.spec_hash,
            source={"kind": "daily_factor" if period == "day" else "minute_gold",
                    "inputId": entry.fingerprints[end_index - 1] if end_index else hashlib.sha256(b"empty").hexdigest(),
                    "startTime": times[0] if end_index else None, "computedThrough": through,
                    "initialHistoryIncomplete": True, "indicatorVersion": None if period == "day" else INDICATOR_VERSION},
            points=points, events=events, structures=sorted(structures, key=lambda item: (item["formedAt"], item["id"])),
            meta={"count": len(points), "responseStart": first, "responseEnd": last},
            dataStatus={"status": status, "message": message, "asOf": through})
        check()
        return response
