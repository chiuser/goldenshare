from __future__ import annotations

from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
from bisect import bisect_right
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import date, datetime
import hashlib
from pathlib import Path
import sys
from threading import RLock
import time
from typing import Any

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError, IndexDetailQueryError, IndexDetailRequestError, IndexDetailUniverseService,
)
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader
from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteHistoryBudgetError, IndexMinuteSourceContractError
from src.biz.schemas.wealth.market.index_detail_xxm import InternalXxmResponseDto
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import InternalForecastResponseDto
from goldenshare_technical_indicators.xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET, REQUEST_SLOTS as _REQUEST_SLOTS
from goldenshare_technical_indicators.xxm.spec import MAIN_SPEC
from goldenshare_technical_indicators.xxm.snapshot_validation import validate_structure_record
from goldenshare_technical_indicators.xxm.types import XxmBar, XxmPeriod, XxmStep
from .source import (CN_ZONE, DAILY_START, INDICATOR_VERSION, XxmLakeCalendar, XxmSourceError, assert_continuous, calendar_dates,
                     expected_through, minute_reader, minute_request, normalize_minute_end,
                     plan_minute_window, read_daily, read_lake_daily, read_minutes)
from .shared_loads import SharedLoads


class XxmQueryError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def require_xxm_code(ts_code: str) -> str:
    if not isinstance(ts_code, str):
        raise XxmQueryError("XXM_REQUEST_INVALID", "tsCode 必须是六位代码及市场后缀。", 400)
    universe = IndexDetailUniverseService()
    try:
        code = universe.normalize_ts_code(ts_code)
        universe.require_supported(code)
    except IndexDetailRequestError as exc:
        raise XxmQueryError("XXM_REQUEST_INVALID", str(exc), 400) from exc
    except IndexDetailNotFoundError as exc:
        raise XxmQueryError("XXM_NOT_SUPPORTED", "该指数暂不支持顶底识别。", 404) from exc
    except IndexDetailQueryError as exc:
        raise XxmQueryError("XXM_QUERY_FAILED", "顶底识别指数名单配置不可用。", 500) from exc
    if code == "899050.BJ":
        raise XxmQueryError("XXM_NOT_SUPPORTED", "该指数暂不支持顶底识别。", 404)
    return code


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
        self.entries: OrderedDict[tuple, tuple[SeriesEntry | InternalForecastResponseDto, int]] = OrderedDict()
        self.lock = RLock()
        self.loads = SharedLoads(max_entries=max_series)

    def get(self, key: tuple) -> SeriesEntry | InternalForecastResponseDto | None:
        with self.lock:
            if key not in self.entries:
                return None
            self.entries.move_to_end(key)
            return self.entries[key][0]

    def put(self, key: tuple, entry: SeriesEntry | InternalForecastResponseDto, *, check=None) -> None:
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

    def get_forecast(self, key: tuple, *, check) -> InternalForecastResponseDto | None:
        if not self.lock.acquire(timeout=check()):
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "预测缓存读取超时。", 503)
        try:
            check()
            stored = self.entries.get(("forecast", *key))
            if stored is None:
                return None
            self.entries.move_to_end(("forecast", *key))
            response = stored[0].model_copy(deep=True)
            check()
            return response
        finally:
            self.lock.release()

    def put_forecast(self, key: tuple, prepared: InternalForecastResponseDto, size: int, *, check) -> None:
        if type(size) is not int or size <= 0 or size > self.max_bytes:
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "预测缓存超过预算。", 503)
        if not self.lock.acquire(timeout=check()):
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "预测缓存写入超时。", 503)
        try:
            candidate = self.entries.copy()
            candidate.pop(("forecast", *key), None)
            candidate[("forecast", *key)] = (prepared, size)
            while len(candidate) > self.max_series or sum(item[1] for item in candidate.values()) > self.max_bytes:
                candidate.popitem(last=False)
            check()
            self.entries = candidate
        finally:
            self.lock.release()


_CACHE = XxmCache()
_PERIODS = ("day", "m30", "m60", "m90", "m120")


class IndexDetailXxmQueryService:
    def __init__(self, *, lake_root: Path | None = None, daily_lake: IndexDailyLakeReader | None = None,
                 cache: XxmCache | None = None, entry_scope: str = "normal") -> None:
        self.reader = minute_reader(lake_root) if lake_root is not None else None
        self.daily_lake = daily_lake
        self.cache = cache or _CACHE
        self.entry_scope = entry_scope
        if daily_lake is not None:
            self.lake_identity = f"dg:{daily_lake.root}"
        else:
            self.lake_identity = str(lake_root.resolve()) if lake_root is not None else "daily"

    def cache_bind_id(self, session: Session | None) -> int | str | tuple[str, int | str]:
        bind = "dg" if self.daily_lake is not None else id(session.get_bind())
        return bind if self.entry_scope == "normal" else (self.entry_scope, bind)

    @staticmethod
    def _check_entry_identity(entry: SeriesEntry, *, ts_code: str, period: XxmPeriod) -> None:
        if (entry.calculator.ts_code != ts_code or entry.calculator.period != period
                or entry.calculator.spec.spec_hash != MAIN_SPEC.spec_hash):
            raise XxmQueryError("XXM_SOURCE_CONTRACT_INVALID", "顶底识别缓存或结果与请求标的不一致。")

    def build(self, session: Session | None, *, ts_code: str, period: XxmPeriod, start_date: date | None, end_date: date | None,
              limit: int, project=None, now: datetime | None = None) -> bytes:
        if period not in _PERIODS or not 1 <= limit <= BUDGET.max_response_rows or (start_date and end_date and start_date > end_date):
            raise XxmQueryError("XXM_REQUEST_INVALID", "研究指标请求参数不合法。", 400)
        window = {} if period == "day" else dict(window_rows=limit, requested_end=end_date)
        with self.load_entry(session, ts_code=ts_code, period=period, now=now, **window) as (entry, context, open_dates, remaining):
            code = entry.calculator.ts_code
            upper = min(end_date or context.trade_date, context.trade_date)
            expected = expected_through(period, open_dates, context.generated_at, upper)
            response = self._response(entry, ts_code=code, period=period, expected=expected, start_date=start_date, limit=limit, check=remaining)
            if project is None:
                from src.biz.services.wealth.market.index_detail_xxm.response_projection import project_xxm_response

                project = project_xxm_response
            response = project(response)
            remaining()
            body = response.model_dump_json().encode("utf-8")
            if len(body) > BUDGET.max_response_bytes:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标响应超过预算。", 503)
            remaining()
            return body

    @contextmanager
    def load_entry(self, session: Session | None, *, ts_code: str, period: XxmPeriod, now: datetime | None = None,
                   window_rows: int | None = None, requested_end: date | datetime | None = None,
                   lake_calendar: XxmLakeCalendar | None = None):
        """Publish a validated real prefix; consumers never hold a source slot."""
        started = time.perf_counter()

        def remaining() -> float:
            left = BUDGET.request_deadline_seconds - (time.perf_counter() - started)
            if left <= 0:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503)
            return left

        try:
            remaining()
            if period not in _PERIODS:
                raise XxmQueryError("XXM_REQUEST_INVALID", "研究指标周期不合法。", 400)
            code = require_xxm_code(ts_code)
            remaining()
            if period != "day" and self.reader is None:
                raise XxmQueryError("XXM_QUERY_FAILED", "本地分钟来源未配置。", 503)
            now = (now or datetime.now(CN_ZONE)).astimezone(CN_ZONE)
            context_query = MarketPageContextQuery()
            window = {}
            if self.daily_lake is not None:
                lake_calendar = lake_calendar or XxmLakeCalendar(self.daily_lake)
                rows = lake_calendar.recent(end=now.date(), open_days=2)
                context = context_query.resolve_local_context(
                    self.daily_lake, market="CN_A", requested_trade_date=None, now=now, calendar_rows=rows,
                )
                window["lake_calendar"] = lake_calendar
            else:
                context = context_query.resolve_context(session, market="CN_A", requested_trade_date=None, now=now)
            remaining()
            key = (self.cache_bind_id(session), self.lake_identity, period, MAIN_SPEC.spec_hash, code)
            # Before/after the cutover and different calendar coverages cannot
            # join the same flight, even when their latest physical bar matches.
            completed_hint = expected_through(period, (context.trade_date,), now, context.trade_date)
            flight_key = (*key, context.trade_date, now.date(), completed_hint)
            if period != "day":
                output_rows = BUDGET.response_default_minute if window_rows is None else window_rows
                if type(output_rows) is not int or not 1 <= output_rows <= BUDGET.max_response_rows:
                    raise XxmQueryError("XXM_REQUEST_INVALID", "分钟返回根数不合法。", 400)
                # Only forecasts pass a datetime; signals pass a date or None.
                if requested_end is not None and type(requested_end) is not date:
                    if (requested_end.tzinfo is None or completed_hint is None
                            or requested_end > datetime.fromisoformat(completed_hint)):
                        raise XxmQueryError("XXM_REQUEST_INVALID", "asOf 必须是已完成的开市端点。", 400)
                normalized_end = normalize_minute_end(period=period, requested_end=requested_end,
                                                       context=context, now=now)
                flight_key = (*key, output_rows, normalized_end, context.trade_date, now.date(), completed_hint)
                window.update(window_rows=output_rows, requested_end=normalized_end, context=context)
            def load():
                if not _REQUEST_SLOTS.acquire(timeout=remaining()):
                    raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503)
                try:
                    return self._load_series(session, ts_code=code, key=key, period=period, now=now,
                                             business_date=context.trade_date, remaining=remaining, **window)
                finally:
                    _REQUEST_SLOTS.release()
            entry, open_dates = self.cache.loads.load(flight_key, load, remaining)
            remaining()
            self._check_entry_identity(entry, ts_code=code, period=period)
            yield entry, context, open_dates, remaining
            remaining()
        except (AsyncCancelledError, FutureCancelledError):
            raise
        except XxmQueryError:
            raise
        except TimeoutError as exc:
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503) from exc
        except (IndexMinuteHistoryBudgetError, OverflowError) as exc:
            raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标来源超过读取预算。", 503) from exc
        except (XxmSourceError, IndexMinuteSourceContractError, ValueError, TypeError) as exc:
            raise XxmQueryError("XXM_SOURCE_CONTRACT_INVALID", "研究指标来源存在缺口或字段不一致。") from exc
        except Exception as exc:
            raise XxmQueryError("XXM_QUERY_FAILED", "研究指标查询失败，请重试。") from exc

    def _load_series(self, session, *, ts_code, key, period, now, business_date, remaining,
                      window_rows: int | None = None, requested_end: datetime | None = None, context=None,
                      lake_calendar: XxmLakeCalendar | None = None):
        remaining()
        if period == "day":
            if lake_calendar is not None:
                rows = lake_calendar.range(start=DAILY_START, end=now.date())
                if now.date() >= DAILY_START and (not rows or rows[-1][0] != now.date()):
                    raise XxmSourceError("SSE 交易日历未覆盖计算日期。")
                open_dates = tuple(day for day, opened, _ in rows if opened)
            else:
                open_dates = calendar_dates(session, start=date(1990, 1, 1), end=now.date())
            remaining()
            completed = expected_through(period, open_dates, now, business_date)
            previous_entry = self.cache.get(key)
            if previous_entry is not None:
                self._check_entry_identity(previous_entry, ts_code=ts_code, period=period)
            if self.daily_lake is not None:
                raw = read_lake_daily(self.daily_lake, ts_code=ts_code, completed=completed, check=remaining)
            else:
                raw = read_daily(session, ts_code=ts_code, completed=completed, check=remaining)
            signature = ()
        else:
            assert self.reader is not None
            calendar_options = {"lake_calendar": lake_calendar} if lake_calendar is not None else {}
            window = plan_minute_window(session, period=period,
                output_rows=BUDGET.response_default_minute if window_rows is None else window_rows,
                requested_end=requested_end, context=context, now=now, check=remaining, **calendar_options)
            remaining()
            open_dates = window.open_dates
            completed = window.end_time.isoformat() if window.end_time is not None else None
            key = (*key, window.output_rows, window.read_rows, window.start_time, window.end_time)
            previous_entry = self.cache.get(key)
            if previous_entry is not None:
                self._check_entry_identity(previous_entry, ts_code=ts_code, period=period)
            freq = int(period[1:])
            signatures = []
            if window.start_time is not None:
                request = minute_request(freq, window, ts_code=ts_code)
                for dataset in ("bars", "indicators"):
                    remaining()
                    signatures.append(self.reader.history_source_signature(request, dataset=dataset))
                    remaining()
            signature = tuple(signatures)
            if window.start_time is None:
                raw = ()
            elif previous_entry is not None and signature == previous_entry.signature:
                raw = previous_entry.raw
            else:
                raw = read_minutes(self.reader, ts_code=ts_code, freq=freq, window=window, deadline=remaining)
            remaining()
        remaining()
        if (previous_entry is not None and signature == previous_entry.signature and raw == previous_entry.raw
                and completed == previous_entry.validated_through and open_dates == previous_entry.open_dates):
            return previous_entry, open_dates
        processed = tuple(bar for bar in raw if completed is not None and bar.time <= completed)
        assert_continuous(processed, period=period, open_dates=open_dates)
        origin = f"{period}|{processed[0].time if processed else 'empty'}|{INDICATOR_VERSION if period != 'day' else 'bfq'}"
        revised = (previous_entry is None or processed[:len(previous_entry.processed)] != previous_entry.processed
                   or previous_entry.calculator.source_identity != origin)
        calculator = XxmCalculator(ts_code=ts_code, period=period, source_identity=origin)
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
            self._merge_structure_updates(entry, step, bar=bar)
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
        self._response(entry, ts_code=ts_code, period=period, expected=completed, start_date=None,
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
    def _merge_structure_updates(entry: SeriesEntry, step: XxmStep, *, bar: XxmBar) -> None:
        seen = set()
        for incoming in step.structures:
            record = validate_structure_record(incoming, period=entry.calculator.period, upper=bar.time,
                                               id_factory=entry.calculator._id)
            identity = record["id"]
            if identity in seen:
                raise ValueError("Duplicate structure update in one bar")
            seen.add(identity)
            previous = entry.structure_records.get(identity)
            if previous is not None and previous["status"] in ("FINISHED", "DISAPPEARED"):
                raise ValueError("A terminal structure cannot be overwritten or reopened")
            price_events = [event for event in step.events if event["route"] == "structure_price_break"
                            and event["relatedStructureId"] == identity]
            is_price_end = record["disappearanceReason"] == "structure_price_break"
            if len(price_events) != int(is_price_end):
                raise ValueError("Structure price ending and full events disagree")
            if price_events:
                event = price_events[0]
                if (event["time"] != bar.time or event["direction"] != record["direction"]
                        or event["eventReference"] != record["originalReference"]
                        or event["id"] != entry.calculator._id(bar.time, "CANCEL", "structure_price_break", identity)):
                    raise ValueError("Invalid structure price event association")
            if previous is None:
                formations = [event for event in step.events if event["id"] == record["structureEventId"]
                              and event["type"] == "STRUCTURE" and event["relatedStructureId"] == identity]
                if (record["formedAt"] != bar.time or len(formations) != 1
                        or record["status"] == "FINISHED"
                        or record["status"] == "DISAPPEARED" and not is_price_end):
                    raise ValueError("A new structure must be formed by this bar")
            else:
                allowed = {"ASSESSING": {"FOLLOWING", "DISAPPEARED"},
                           "FOLLOWING": {"FOLLOWING", "FINISHED", "DISAPPEARED"}}
                if record["status"] not in allowed.get(previous["status"], set()):
                    raise ValueError("A terminal structure cannot be overwritten or reopened")
                mutable = {"status", "originWave", "firstOppositeAt", "nextSameColorStart", "nextSameColorCount",
                           "trackingPriceExtreme", "trackingPriceExtremeAt", "trackingEndedAt", "disappearedAt", "disappearanceReason"}
                if any(record[field] != value for field, value in previous.items() if field not in mutable):
                    raise ValueError("Structure formation facts are immutable")
                for field in ("originWave", "firstOppositeAt"):
                    if previous[field] is not None and record[field] != previous[field]:
                        raise ValueError("Known origin facts cannot be rewritten")
                if record == previous:
                    raise ValueError("Redundant structure update")
            if record["firstOppositeAt"] == bar.time:
                sign = 1 if record["direction"] == "TOP" else -1
                history = entry.calculator.history[sign]
                if not history or record["originWave"] != asdict(history[-1]):
                    raise ValueError("New closed origin differs from the actual completed Wave")
                if (record["nextSameColorStart"] is not None or record["nextSameColorCount"] != 0
                        or record["trackingPriceExtreme"] != bar.close
                        or record["trackingPriceExtremeAt"] != bar.time):
                    raise ValueError("First-opposite tracking must start on this bar")
            elif previous is not None and previous["status"] == "FOLLOWING":
                sign = 1 if record["direction"] == "TOP" else -1
                raw_sign = (bar.hist > 0) - (bar.hist < 0)
                count, start = previous["nextSameColorCount"], previous["nextSameColorStart"]
                expected = deepcopy(previous)
                if count >= MAIN_SPEC.structure_follow_min_bars and raw_sign == -sign:
                    expected.update(status="FINISHED", trackingEndedAt=bar.time)
                else:
                    if raw_sign == sign:
                        expected.update(nextSameColorStart=start or bar.time, nextSameColorCount=count + 1)
                    elif raw_sign == -sign and count == 1:
                        expected.update(nextSameColorStart=None, nextSameColorCount=0)
                    if sign * (bar.close - previous["trackingPriceExtreme"]) > 0:
                        expected.update(trackingPriceExtreme=bar.close, trackingPriceExtremeAt=bar.time)
                    if sign * (bar.close - previous["originWave"]["price"]) > 0:
                        expected.update(status="DISAPPEARED", trackingEndedAt=bar.time,
                                        disappearedAt=bar.time, disappearanceReason="structure_price_break")
                if record != expected:
                    raise ValueError("Structure update differs from actual count/price advancement")
            elif previous is not None and record["trackingEndedAt"] != bar.time:
                raise ValueError("Assessment finalization must occur on this bar")
            entry.structure_records[identity] = record

    @staticmethod
    def _project_structure(record: dict, *, through: str, prefix_records: dict[str, dict]) -> dict | None:
        if record["formedAt"] > through:
            return None
        if record["trackingEndedAt"] is None or record["trackingEndedAt"] > through:
            current = prefix_records.get(record["id"])
            if current is None:
                raise ValueError("A live projected structure is missing from the actual prefix")
            return deepcopy(current)
        return deepcopy(record)

    @staticmethod
    def _response(entry: SeriesEntry, *, ts_code: str, period: XxmPeriod, expected: str | None,
                  start_date: date | None, limit: int, check) -> InternalXxmResponseDto:
        IndexDetailXxmQueryService._check_entry_identity(entry, ts_code=ts_code, period=period)
        times = [bar.time for bar in entry.processed]
        end_index = bisect_right(times, expected) if expected is not None else 0
        indices = [index for index in range(end_index) if start_date is None or times[index][:10] >= start_date.isoformat()][-limit:] if limit else []
        points = deepcopy([entry.points[index] for index in indices])
        first, last = (points[0]["time"], points[-1]["time"]) if points else (None, None)
        through = times[end_index - 1] if end_index else None
        events = deepcopy([event for event in entry.events if first is not None and first <= event["time"] <= last])
        related = {point["activeStructureId"] for point in points if point["activeStructureId"] is not None}
        related.update(event["relatedStructureId"] for event in events if event["relatedStructureId"] is not None)
        current = entry.calculator_at(end_index, check)
        prefix_records = {record["id"]: record for record in (
            current.active_structure, *current.followed_structures.values()) if record is not None}
        latest_records = {record["id"]: record for record in (
            entry.calculator.active_structure, *entry.calculator.followed_structures.values()) if record is not None}
        seen_latest = set()
        structures = []
        assessing = []
        following = {"TOP": None, "BOTTOM": None}
        for index, (identity, record) in enumerate(entry.structure_records.items()):
            if index % BUDGET.source_batch_rows == 0:
                check()
            if not entry.processed or identity != record["id"]:
                raise ValueError("XXM structure outside its real prefix")
            validate_structure_record(record, period=period, upper=entry.processed[-1].time,
                                      id_factory=entry.calculator._id)
            if record["status"] in ("ASSESSING", "FOLLOWING"):
                if record != latest_records.get(record["id"]):
                    raise ValueError("Latest structure differs from the actual calculator progress")
                seen_latest.add(record["id"])
            projected = IndexDetailXxmQueryService._project_structure(record, through=through, prefix_records=prefix_records) if through else None
            if projected is None:
                continue
            validate_structure_record(projected, period=period, upper=through, id_factory=current._id)
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
        if seen_latest != set(latest_records):
            raise ValueError("Latest structure aggregation omitted live calculator records")
        if assessing != ([current.active_structure] if current.active_structure is not None else []):
            raise ValueError("Projected structure differs from the actual prefix calculator")
        if following != current.followed_structures:
            raise ValueError("Projected following structures differ from the actual prefix calculator")
        status = "EMPTY" if through is None else "DELAYED" if expected and through < expected else "READY"
        message = "研究指标暂无数据" if status == "EMPTY" else f"研究指标数据截至 {through}" if status == "DELAYED" else None
        response = InternalXxmResponseDto(
            tsCode=ts_code, period=period, algorithmVersion=MAIN_SPEC.algorithm_version, specHash=MAIN_SPEC.spec_hash,
            source={"kind": "daily_factor" if period == "day" else "minute_gold",
                    "inputId": entry.fingerprints[end_index - 1] if end_index else hashlib.sha256(b"empty").hexdigest(),
                    "startTime": times[0] if end_index else None, "computedThrough": through,
                    "initialHistoryIncomplete": True, "indicatorVersion": None if period == "day" else INDICATOR_VERSION},
            points=points, events=events, structures=sorted(structures, key=lambda item: (item["formedAt"], item["id"])),
            meta={"count": len(points), "responseStart": first, "responseEnd": last},
            dataStatus={"status": status, "message": message, "asOf": through})
        check()
        return response
