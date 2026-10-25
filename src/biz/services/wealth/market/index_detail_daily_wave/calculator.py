"""Completed daily facts only, LLD 14.3.1/14.4; no trading signals or I/O."""
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, localcontext
import json
import sys

from .local_extrema import LocalExtremaScanner, number
from .budget import (
    DailyWaveBudget, DailyWaveBudgetExceeded, DailyWaveCancelled, DailyWaveInputError,
    DailyWaveSourceInputError,
)
from .spec import DEFAULT_SPEC, DailyWaveReviewSpec
from .types import (
    BasicRecords, ColorSegment, DailyPoint, Extreme, Extrema, HistogramExtreme,
    Turn, DateRange, CalendarDay, PriceEndpoint, Issue, PricePoint, PriceComparison,
    InternalPriceRelations, TailReview, PriceSegment, EndpointOffset, MappingRecord,
    BarStats, ThreeBarStats, ThreePriceExtrema, ShortOppositeRecord, CandidateRecords,
    AsOfChange, Coverage, CoverageCounts, ReviewResult,
)

_INPUT_FIELDS = frozenset(("tsCode", "date", "close", "dif", "dea", "macd", "completed"))


def _date(value: object) -> str:
    if not isinstance(value, str):
        raise DailyWaveInputError("日期必须为YYYY-MM-DD文本")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DailyWaveInputError("日期必须为YYYY-MM-DD文本") from exc
    if parsed.isoformat() != value:
        raise DailyWaveInputError("日期必须为YYYY-MM-DD文本")
    return value


def _closed_at(day: str) -> str:
    return f"{day}T15:00:00+08:00"


def _require_closed_at(value):
    if not isinstance(value, str) or value != _closed_at(_date(value[:10])):
        raise DailyWaveInputError("日线完成或确认时间必须为上海15:00")


def _value(value: object, max_bytes: int) -> Decimal:
    if isinstance(value, str) and len(value) > max_bytes:
        raise DailyWaveBudgetExceeded("输入数字超过字节上限")
    try:
        result = number(value)
    except ValueError as exc:
        raise DailyWaveInputError(str(exc)) from exc
    if result.is_zero():
        return Decimal(0)
    # Bound fixed-notation allocation before formatting a large exponent.
    extent = max(1, result.adjusted() + 1) + max(0, -result.as_tuple().exponent) + 2
    if extent > max_bytes:
        raise DailyWaveBudgetExceeded("规范数字超过输入字节上限")
    return result


def _points(rows: object, as_of: str, spec: DailyWaveReviewSpec,
            guard: DailyWaveBudget) -> tuple[DailyPoint, ...]:
    if not isinstance(rows, (list, tuple)):
        raise DailyWaveInputError("输入必须为日线列表或元组")
    if len(rows) > spec.max_total_points:
        raise DailyWaveBudgetExceeded("输入日线超过总根数上限")
    last = None
    main_count = context_count = 0
    encoded_size = 2  # The canonical JSON array's square brackets.
    result = []
    for row in rows:
        guard.check()
        if not isinstance(row, Mapping) or set(row) != _INPUT_FIELDS:
            raise DailyWaveInputError("日线字段必须与基础输入合同一致")
        if row["tsCode"] != spec.ts_code:
            raise DailyWaveInputError("本次基础计算只接受000001.SH")
        if row["completed"] is not True:
            raise DailyWaveInputError("基础输入必须为已完成日线")
        day = _date(row["date"])
        if not spec.absolute_start <= day <= as_of:
            raise DailyWaveInputError("输入日期超出本次允许范围")
        if last is not None and day <= last:
            raise DailyWaveInputError("日线日期必须升序且唯一")
        last = day
        main_count += day >= spec.requested_start
        context_count += day < spec.requested_start
        if main_count > spec.max_main_points or context_count > spec.max_context_points:
            raise DailyWaveBudgetExceeded("主范围或前段超过根数上限")
        values = {key: _value(row[key], spec.max_input_bytes)
                  for key in ("close", "dif", "dea", "macd")}
        if values["close"] <= 0:
            raise DailyWaveInputError("收盘价必须大于零")
        point = DailyPoint(date=day, **values)
        normalized = {"tsCode": spec.ts_code, **point.to_dict(), "completed": True}
        encoded_size += len(json.dumps(normalized, separators=(",", ":"),
                                       ensure_ascii=False).encode("utf-8")) + bool(result)
        if encoded_size > spec.max_input_bytes:
            raise DailyWaveBudgetExceeded("规范输入超过字节上限")
        # Local precision changes must not round long, valid source values.
        indicators = [values[key] for key in ("dif", "dea", "macd")]
        precision = max(28, max(v.adjusted() for v in indicators)
                        - min(v.as_tuple().exponent for v in indicators) + 5)
        try:
            with localcontext() as context:
                context.prec = precision
                error = (values["macd"] - 2 * (values["dif"] - values["dea"])).copy_abs()
        except DecimalException as exc:
            raise DailyWaveSourceInputError("源指标超出十进制运算范围") from exc
        if error > spec.source_equation_tolerance:
            raise DailyWaveSourceInputError("源MACD柱与DIF/DEA关系不符")
        result.append(point)
    guard.check()
    return tuple(result)


def _memory_size(value: object, guard: DailyWaveBudget, seen: set[int] | None = None) -> int:
    guard.check()
    if seen is None:
        seen = set()
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if is_dataclass(value) and not isinstance(value, type):
        size += sum(_memory_size(getattr(value, f.name), guard, seen) for f in fields(value))
    elif isinstance(value, tuple):
        size += sum(_memory_size(item, guard, seen) for item in value)
    return size


def build_basic_records(rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...], *,
                        as_of: str, spec: DailyWaveReviewSpec = DEFAULT_SPEC,
                        deadline: float | None = None,
                        check_cancelled: Callable[[], bool] | None = None) -> BasicRecords:
    """Return facts for this completed prefix, without observing any later row."""
    guard = DailyWaveBudget(spec, deadline, check_cancelled)
    guard.check()
    as_of = _date(as_of)
    if not spec.absolute_start <= as_of <= spec.requested_end:
        raise DailyWaveInputError("截止日期超出试验范围")
    points = _points(rows, as_of, spec, guard)
    state = _BasicRecordState(spec, guard)
    for point in points:
        state.step(point)
    result = state.freeze()
    if _memory_size(result, guard) > spec.max_memory_bytes:
        raise DailyWaveBudgetExceeded("基础结果超过内存上限")
    guard.check()
    return result


def build_color_segments(rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...], *,
                         as_of: str, spec: DailyWaveReviewSpec = DEFAULT_SPEC,
                         deadline: float | None = None,
                         check_cancelled: Callable[[], bool] | None = None) -> tuple[ColorSegment, ...]:
    """Use the same validated calculation; do not maintain another color algorithm."""
    return build_basic_records(rows, as_of=as_of, spec=spec, deadline=deadline,
                               check_cancelled=check_cancelled).colorSegments


def histogram_color(value: Decimal):
    return "RED" if value > 0 else "GREEN" if value < 0 else None


class _Statistics:
    """Running extrema. Copying a snapshot never aliases its date lists."""
    def __init__(self):
        self.values = {}
        self.close_dates: dict[Decimal, list[str]] = {}

    def add(self, point):
        self.close_dates.setdefault(point.close, []).append(point.date)
        for key, value, maximum in (
            ("maxClose", point.close, True), ("minClose", point.close, False),
            ("maxDif", point.dif, True), ("minDif", point.dif, False),
            ("longestRed", point.macd, True), ("longestGreen", point.macd, False),
        ):
            if key == "longestRed" and value <= 0 or key == "longestGreen" and value >= 0:
                continue
            old = self.values.get(key)
            if old is None or (value > old[0] if maximum else value < old[0]):
                self.values[key] = [value, [point.date]]
            elif value == old[0]:
                old[1].append(point.date)

    def copy(self):
        result = _Statistics()
        result.values = {key: [value, dates.copy()] for key, (value, dates) in self.values.items()}
        result.close_dates = {value: dates.copy() for value, dates in self.close_dates.items()}
        return result

    def freeze(self):
        def extreme(key):
            if key not in self.values:
                return None
            value, dates = self.values[key]
            if key.startswith("longest"):
                return HistogramExtreme(value, value.copy_abs(), tuple(dates))
            return Extreme(value, tuple(dates))
        return Extrema(*(extreme(key) for key in (
            "maxClose", "minClose", "maxDif", "minDif", "longestRed", "longestGreen")))


class _ColorState:
    def __init__(self, point, spec, left_complete):
        self.id = f"{spec.ts_code}:day:{histogram_color(point.macd)}:{point.date}"
        self.color = histogram_color(point.macd)
        self.startDate = point.date
        self.isLeftComplete = left_complete
        self.endKnownAt = None
        self.coloredCount = 0
        self.zeroDates = []
        self.turnIds = set()
        self.stats = _Statistics()
        self.cached = None
        self.add(point)

    def add(self, point):
        self.endDate = point.date
        if point.macd:
            self.lastColoredDate = point.date
            self.coloredCount += 1
        else:
            self.zeroDates.append(point.date)
        self.stats.add(point)
        self.cached = None

    def record(self, turns):
        if self.cached is None:
            def key(identifier):
                turn = turns[identifier]
                return (0, turn.firstDate, turn.metric) if turn.confirmedAt else (1, "", turn.metric)
            self.cached = ColorSegment(
                self.id, self.color, self.startDate, self.endDate, self.lastColoredDate,
                self.coloredCount, tuple(self.zeroDates), self.isLeftComplete,
                self.endKnownAt is not None, self.endKnownAt,
                tuple(sorted(self.turnIds, key=key)), self.stats.freeze())
        return self.cached


class _BasicRecordState:
    def __init__(self, spec, guard):
        self.spec, self.guard = spec, guard
        self.points = []
        self.scanners = {metric: LocalExtremaScanner() for metric in ("CLOSE", "DIF")}
        self.confirmed = {}
        self.pending = {}
        self.turns = {}
        self.colors = []
        self.changed_colors = set()
        self.changed_turns = {}
        self.new_confirmed = []

    def step(self, point):
        self.guard.check()
        self.points.append(point)
        self.changed_colors, self.changed_turns, self.new_confirmed = set(), {}, []
        color = histogram_color(point.macd)
        if color is not None and (not self.colors or color != self.colors[-1].color):
            if self.colors:
                previous = self.colors[-1]
                previous.endKnownAt = _closed_at(point.date)
                previous.cached = None
                self.changed_colors.add(previous.id)
            self.colors.append(_ColorState(point, self.spec, bool(self.colors)))
        elif self.colors:
            self.colors[-1].add(point)
        if self.colors:
            self.changed_colors.add(self.colors[-1].id)
        for metric, column in (("CLOSE", "close"), ("DIF", "dif")):
            old = self.pending.pop(metric, None)
            if old is not None:
                self.turns.pop(old.id)
                self.changed_turns[old.id] = old
            scanner = self.scanners[metric]
            found = scanner.step(point.date, getattr(point, column))
            if found is not None:
                record = Turn(
                    f"{self.spec.ts_code}:day:{metric}:{found.first_at}", metric, found.kind,
                    found.value, found.first_at, found.last_at,
                    tuple(p.date for p in self.points[found.first_index:found.last_index + 1]),
                    _closed_at(found.confirmed_at))
                self.confirmed[record.id] = self.turns[record.id] = record
                self.changed_turns[record.id] = record
                self.new_confirmed.append(record.id)
            tail = scanner.pending()
            record = Turn(
                f"{self.spec.ts_code}:day:{metric}:{tail['first_at']}", metric, None,
                number(tail["value"]), tail["first_at"], tail["last_at"],
                tuple(p.date for p in self.points[tail["first_index"]:tail["last_index"] + 1]),
                None, tail["possible_kind"])
            self.pending[metric] = self.turns[record.id] = record
            if old != record:
                self.changed_turns[record.id] = record
            elif old is not None:
                self.changed_turns.pop(old.id, None)
        for identifier in self.changed_turns:
            current = self.turns.get(identifier)
            for segment in self.colors:
                attached = identifier in segment.turnIds
                relevant = current is not None and current.firstDate <= segment.endDate and current.lastDate >= segment.startDate
                if attached != relevant or relevant:
                    segment.turnIds.discard(identifier)
                    if relevant:
                        segment.turnIds.add(identifier)
                    segment.cached = None
                    self.changed_colors.add(segment.id)
        self.guard.check()

    def color_records(self):
        return tuple(segment.record(self.turns) for segment in self.colors)

    def freeze(self):
        return BasicRecords(
            self.spec.ts_code, self.spec.period, self.spec.rule_id,
            _closed_at(self.points[-1].date) if self.points else None,
            self.points[0].date if self.points else None,
            self.points[-1].date if self.points else None, tuple(self.points),
            tuple(sorted(self.confirmed.values(), key=lambda t: (t.firstDate, t.metric))),
            tuple(self.pending.values()), self.color_records())


def intersect_ranges(a, b):
    if a is None or b is None:
        return None
    start, end = max(a.startDate, b.startDate), min(a.endDate, b.endDate)
    return DateRange(start, end) if start <= end else None


def _in_range(turn, window):
    return window is not None and turn.firstDate <= window.endDate and turn.lastDate >= window.startDate


def _turn_key(turn):
    return turn.firstDate, turn.metric, turn.id


def _internal_relations(turns, start, end, window):
    entries = []
    relevant = [t for t in turns if t.metric == "CLOSE" and t.confirmedAt and _in_range(t, window)]
    for turn in relevant:
        intersecting = [day for day in turn.plateauDates if window.startDate <= day <= window.endDate]
        if intersecting:
            entries.append((turn.kind, PricePoint(intersecting[0], turn.value), turn.id))
    for kind, endpoint in (start, end):
        same = next((t for t in relevant if t.kind == kind and endpoint.date in t.plateauDates), None)
        if same is None:
            entries.append((kind, PricePoint(endpoint.date, endpoint.close), f"endpoint:{kind}:{endpoint.date}"))
    highs = tuple(item[1] for item in sorted(entries, key=lambda x: x[1].date) if item[0] == "MAX")
    lows = tuple(item[1] for item in sorted(entries, key=lambda x: x[1].date) if item[0] == "MIN")

    def compare(points):
        return tuple(PriceComparison(a.date, b.date,
            "HIGHER" if b.close > a.close else "LOWER" if b.close < a.close else "EQUAL")
            for a, b in zip(points, points[1:]))
    high_comparisons, low_comparisons = compare(highs), compare(lows)
    relations = {p.relation for p in high_comparisons + low_comparisons}
    status = ("INSUFFICIENT" if len(highs) < 2 or len(lows) < 2 else
              "RISING" if relations == {"HIGHER"} else
              "FALLING" if relations == {"LOWER"} else
              "MIXED" if {"HIGHER", "LOWER"} <= relations else "EQUAL")
    return InternalPriceRelations(highs, lows, high_comparisons, low_comparisons, status)


class _Candidate:
    def __init__(self, source, previous, points):
        self.source_id = source.id
        self.previous_id = previous.id if previous else None
        self.direction = "UP" if source.color == "RED" else "DOWN"
        self.id = f"{source.id}:PRICE:{self.direction}"
        self.first_day = source.startDate
        self.start_range = DateRange(previous.startDate, source.startDate) if previous else None
        self.generated = bool(previous and previous.isLeftComplete and previous.isEnded)
        self.cached = self.mapping = None
        if not self.generated:
            return
        search = [p for p in points if previous.startDate <= p.date <= source.startDate]
        value = min(p.close for p in search) if self.direction == "UP" else max(p.close for p in search)
        ties = tuple(p.date for p in search if p.close == value)
        self.start = PriceEndpoint(ties[0], _closed_at(ties[0]), value, ties)
        self.a = _Statistics()
        for point in points:
            if self.start.date <= point.date <= source.startDate:
                self.a.add(point)
        extreme = self.a.values["maxClose" if self.direction == "UP" else "minClose"]
        self.end_date = extreme[1][0]
        self.b, self.tail = _Statistics(), _Statistics()
        for point in points:
            if self.start.date <= point.date <= self.end_date:
                self.b.add(point)
            if self.end_date <= point.date <= source.startDate:
                self.tail.add(point)
        self.last_day = source.startDate

    def advance(self, point):
        if not self.generated or point.date <= self.last_day:
            return
        key = "maxClose" if self.direction == "UP" else "minClose"
        old = self.a.values[key][0]
        self.a.add(point)
        if (point.close > old if self.direction == "UP" else point.close < old):
            self.end_date = point.date
            self.b = self.a.copy()
            self.tail = _Statistics()
        self.tail.add(point)
        self.last_day = point.date

    def refresh(self, source, turns, observation, calendar_indices):
        turns = tuple(sorted(turns, key=_turn_key))
        color_range = DateRange(source.startDate, source.endDate)
        issues = []
        if not self.generated:
            issues.append(Issue("缺少完整前绿段" if self.direction == "UP" else "缺少完整前红段", (source.startDate,)))
            record = PriceSegment(
                self.id, source.id, self.previous_id, self.direction, False,
                self.start_range, None, None, None, None, False, None,
                "UNKNOWN", "UNKNOWN", "UNKNOWN", tuple(issues), None,
                TailReview(None, (), None, None, None), None, ())
            window, price_turns, offsets = None, (), ()
        else:
            key = "maxClose" if self.direction == "UP" else "minClose"
            value, ties = self.a.values[key]
            end = PriceEndpoint(self.end_date, _closed_at(self.end_date), value, tuple(ties))
            window = DateRange(self.start.date, end.date)
            b = self.b.freeze()
            valid = True
            if end.date <= self.start.date:
                issues.append(Issue("终点不晚于起点", (self.start.date, end.date)))
                valid = False
            if not (end.close > self.start.close if self.direction == "UP" else end.close < self.start.close):
                issues.append(Issue("无价格上升" if self.direction == "UP" else "无价格下降", (self.start.date, end.date)))
                valid = False
            start_extreme = b.minClose if self.direction == "UP" else b.maxClose
            end_extreme = b.maxClose if self.direction == "UP" else b.minClose
            if start_extreme.value != self.start.close:
                issues.append(Issue("起点不是段内极值", start_extreme.dates))
                valid = False
            if end_extreme.value != end.close:
                issues.append(Issue("终点不是段内极值", end_extreme.dates))
                valid = False
            if end.date < source.startDate:
                issues.append(Issue("价格终点早于本色区间，指标对应待核", (end.date, source.startDate)))
            price_turns = tuple(t for t in turns if _in_range(t, window))
            dif = tuple(t.id for t in price_turns if t.metric == "DIF")
            if not any(t.metric == "DIF" and t.confirmedAt for t in price_turns):
                issues.append(Issue("DIF对应证据不足，尾峰可能尚未确认", (window.startDate, window.endDate)))
            tail_range = DateRange(end.date, source.endDate)
            tail_extrema = self.tail.freeze()
            tail_price = tail_extrema.minClose if self.direction == "UP" else tail_extrema.maxClose
            broke = tail_price.value < self.start.close if self.direction == "UP" else tail_price.value > self.start.close
            touch_dates = self.tail.close_dates.get(self.start.close, ())
            touched = bool(touch_dates)
            if broke:
                issues.append(Issue("终点后价格严格突破起始收盘", tail_price.dates))
            if touched:
                issues.append(Issue("终点后价格接触起始收盘", tuple(touch_dates)))
            relation = _internal_relations(
                turns, ("MIN" if self.direction == "UP" else "MAX", self.start),
                ("MAX" if self.direction == "UP" else "MIN", end), window)
            record = PriceSegment(
                self.id, source.id, self.previous_id, self.direction, True,
                self.start_range, DateRange(self.start.date, source.endDate), self.start, end,
                _closed_at(self.first_day), source.isEnded, source.endKnownAt,
                "VALID", "VALID", "VALID" if valid else "INVALID", tuple(issues), relation,
                TailReview(tail_range, tuple(t.id for t in turns if _in_range(t, tail_range)),
                           tail_extrema, broke, touched), b, dif)
            offsets = tuple(EndpointOffset(t.id, name, calendar_indices[endpoint.date] - calendar_indices[t.lastDate])
                for t in price_turns if t.metric == "DIF"
                for name, endpoint in (("START", self.start), ("END", end)))
        mapping = MappingRecord(
            source.id, self.id, color_range, window, intersect_ranges(color_range, observation),
            intersect_ranges(window, observation), source.turnIds,
            tuple(t.id for t in price_turns), offsets, tuple(issues))
        changed = record != self.cached or mapping != self.mapping
        self.cached, self.mapping = record, mapping
        return changed


class _PriceCandidateState:
    def __init__(self, observation, calendar, guard):
        self.observation, self.guard = observation, guard
        self.calendar_indices = {row.date: i for i, row in enumerate(row for row in calendar if row.isOpen)}
        self.candidates = {}
        self.turn_links = {}

    def step(self, basic):
        self.guard.check()
        colors = basic.color_records()
        if not colors:
            return ()
        current = colors[-1]
        if current.id not in self.candidates and intersect_ranges(
                DateRange(current.startDate, current.endDate), self.observation):
            index = len(colors) - 1
            self.candidates[current.id] = _Candidate(current, colors[index - 1] if index else None, basic.points)
        # A segment may start in context and enter the observation window later.
        candidate = self.candidates.get(current.id)
        if candidate is not None:
            if candidate.generated and candidate.last_day < basic.points[-1].date:
                for point in basic.points:
                    if candidate.last_day < point.date <= current.endDate:
                        candidate.advance(point)
        by_id = {color.id: color for color in colors}
        dirty = set(basic.changed_colors) & self.candidates.keys()
        evidence_dirty = set()
        for identifier, turn in basic.changed_turns.items():
            dirty.update(self.turn_links.get(identifier, ()))
            evidence_dirty.update(self.turn_links.get(identifier, ()))
            for cid, item in self.candidates.items():
                if item.generated and turn.firstDate <= by_id[cid].endDate and turn.lastDate >= item.start.date:
                    dirty.add(cid)
                    evidence_dirty.add(cid)
        updated = []
        turns = tuple(basic.turns.values())
        for cid in sorted(dirty):
            self.guard.check()
            candidate = self.candidates[cid]
            changed = candidate.refresh(by_id[cid], turns, self.observation, self.calendar_indices)
            if changed or cid in evidence_dirty:
                updated.append(candidate.id)
            for linked in self.turn_links.values():
                linked.discard(cid)
            referenced = set(candidate.mapping.priceTurnIds) | set(candidate.cached.tailReview.turnIds)
            for identifier in referenced:
                self.turn_links.setdefault(identifier, set()).add(cid)
        self.guard.check()
        return tuple(updated)

    def freeze(self, colors, turns):
        triples = []
        for a, b, c in zip(colors, colors[1:], colors[2:]):
            self.guard.check()
            if not intersect_ranges(DateRange(c.startDate, c.endDate), self.observation):
                continue
            def bar(segment):
                return BarStats(segment.coloredCount,
                    segment.extrema.longestRed if segment.color == "RED" else segment.extrema.longestGreen)
            ids = set(a.turnIds + b.turnIds + c.turnIds)
            triples.append(ShortOppositeRecord(
                a.id, b.id, c.id, ThreeBarStats(bar(a), bar(b), bar(c)),
                ThreePriceExtrema(*(s.extrema.maxClose for s in (a, b, c))),
                ThreePriceExtrema(*(s.extrema.minClose for s in (a, b, c))),
                tuple(t.id for t in sorted(turns, key=_turn_key) if t.id in ids and t.metric == "DIF")))
        items = tuple(self.candidates.values())
        return CandidateRecords(tuple(c.cached for c in items), tuple(c.mapping for c in items), tuple(triples))


def _calendar_indices_check(calendar, points, guard):
    if not isinstance(calendar, (tuple, list)):
        raise DailyWaveInputError("日历必须为CalendarDay序列")
    if len(calendar) > guard.spec.max_calendar_days:
        raise DailyWaveBudgetExceeded("日历超过自然日上限")
    previous = None
    for row in calendar:
        guard.check()
        if not isinstance(row, CalendarDay) or row.exchange != "SSE" or type(row.isOpen) is not bool:
            raise DailyWaveInputError("日历字段或类型错误")
        day = date.fromisoformat(_date(row.date))
        if previous is not None and day != previous + timedelta(days=1):
            raise DailyWaveInputError("日历必须逐自然日升序连续且唯一")
        previous = day
    if points:
        if not calendar or calendar[0].date != points[0].date or calendar[-1].date != points[-1].date:
            raise DailyWaveInputError("日历范围与本次完整输入不一致")
        if {p.date for p in points} != {row.date for row in calendar if row.isOpen}:
            raise DailyWaveInputError("行情日期与SSE开市日不一致")


def _observation(points, supplied, spec):
    main = tuple(p for p in points if p.date >= spec.requested_start)
    actual = DateRange(main[0].date, main[-1].date) if main else None
    if supplied != actual:
        raise DailyWaveInputError("实际观察范围必须与本次主范围首末一致")
    return main


def build_price_candidates(basic, *, observation_range, calendar, spec=DEFAULT_SPEC,
                           deadline=None, check_cancelled=None):
    guard = DailyWaveBudget(spec, deadline, check_cancelled)
    guard.check()
    if not isinstance(basic, BasicRecords) or basic.tsCode != spec.ts_code or basic.ruleId != spec.rule_id:
        raise DailyWaveInputError("基础结果对象或规则不一致")
    _calendar_indices_check(calendar, basic.sourcePoints, guard)
    _observation(basic.sourcePoints, observation_range, spec)
    state = _PriceCandidateState(observation_range, calendar, guard)
    turns = basic.turns + basic.pendingTurns
    for i, color in enumerate(basic.colorSegments):
        guard.check()
        if not intersect_ranges(DateRange(color.startDate, color.endDate), observation_range):
            continue
        candidate = _Candidate(color, basic.colorSegments[i - 1] if i else None, basic.sourcePoints)
        if candidate.generated:
            for point in basic.sourcePoints:
                if candidate.last_day < point.date <= color.endDate:
                    candidate.advance(point)
        candidate.refresh(color, turns, observation_range, state.calendar_indices)
        state.candidates[color.id] = candidate
    result = state.freeze(basic.colorSegments, turns)
    guard.check()
    return result


def build_review(rows, *, observation_range, calendar, as_of, calculation_id, calculated_at,
                 spec=DEFAULT_SPEC, deadline=None, check_cancelled=None):
    guard = DailyWaveBudget(spec, deadline, check_cancelled)
    guard.check()
    as_of = _date(as_of)
    if not spec.absolute_start <= as_of <= spec.requested_end:
        raise DailyWaveInputError("截止日期超出试验范围")
    points = _points(rows, as_of, spec, guard)
    main = _observation(points, observation_range, spec)
    _calendar_indices_check(calendar, points, guard)
    if not isinstance(calculated_at, datetime) or calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise DailyWaveInputError("计算时间必须有时区")
    when = calculated_at.astimezone(timezone(timedelta(hours=8)))
    if points and when < datetime.fromisoformat(_closed_at(points[-1].date)):
        raise DailyWaveInputError("计算时间早于末根日线完成")
    if not isinstance(calculation_id, str) or not calculation_id:
        raise DailyWaveInputError("缺少本次计算编号")
    base = _BasicRecordState(spec, guard)
    candidates = _PriceCandidateState(observation_range, calendar, guard)
    changes = []
    for point in points:
        base.step(point)
        updated = candidates.step(base)
        if observation_range and observation_range.startDate <= point.date <= observation_range.endDate:
            changes.append(AsOfChange(_closed_at(point.date), tuple(sorted(base.new_confirmed)),
                                     tuple(sorted(base.changed_colors)), tuple(sorted(updated))))
    basic = base.freeze()
    result = candidates.freeze(basic.colorSegments, basic.turns + basic.pendingTurns)
    left = tuple(c.id for c in basic.colorSegments if not c.isLeftComplete and
                 intersect_ranges(DateRange(c.startDate, c.endDate), observation_range))
    ungenerated = tuple(c.id for c in result.priceSegments if not c.generated)
    invalid = tuple(c.id for c in result.priceSegments if c.endpointValidity == "INVALID")
    unknown = tuple(c.id for c in result.priceSegments if c.endpointValidity == "UNKNOWN")
    review = ReviewResult(
        spec.schema_version, spec.ts_code, spec.period, "ready" if main else "empty", spec.rule_id,
        calculation_id, when.isoformat(), spec.requested_start, spec.requested_end,
        main[0].date if main else None, main[-1].date if main else None,
        basic.contextStart, basic.contextEnd, basic.asOf, main, basic.turns, basic.pendingTurns,
        basic.colorSegments, result.priceSegments, result.mappings, result.shortOppositeSegments,
        tuple(changes), Coverage(len(main), left, ungenerated, invalid, unknown,
                                CoverageCounts(len(left), len(ungenerated), len(invalid), len(unknown))))
    validate_review_result(review, spec=spec, guard=guard)
    return review


def review_prefix(rows, *, as_of, observation_range, calendar, calculation_id, calculated_at,
                  spec=DEFAULT_SPEC, deadline=None, check_cancelled=None):
    return build_review(rows, observation_range=observation_range, calendar=calendar, as_of=as_of,
        calculation_id=calculation_id, calculated_at=calculated_at, spec=spec, deadline=deadline,
        check_cancelled=check_cancelled)


def validate_review_result(result, *, spec=DEFAULT_SPEC, guard=None):
    guard = guard or DailyWaveBudget(spec)
    guard.check()
    if _memory_size(result, guard) > spec.max_memory_bytes:
        raise DailyWaveBudgetExceeded("完整结果超过内存上限")
    turns = result.turns + result.pendingTurns
    turn_ids = {t.id for t in turns}
    colors = {s.id for s in result.colorSegments}
    prices = {s.id for s in result.priceSegments}
    if len(turn_ids) != len(turns) or len(colors) != len(result.colorSegments) or len(prices) != len(result.priceSegments):
        raise DailyWaveInputError("结果编号重复")
    if (result.schemaVersion != spec.schema_version or result.tsCode != spec.ts_code
            or result.period != spec.period or result.ruleId != spec.rule_id
            or result.requestedStart != spec.requested_start or result.requestedEnd != spec.requested_end
            or result.status not in {"ready", "empty"}):
        raise DailyWaveInputError("结果头部与本次规则不一致")
    if (result.status == "ready") != bool(result.sourcePoints):
        raise DailyWaveInputError("结果状态与实际主范围行情不一致")
    if result.sourcePoints:
        if (result.observationStart != result.sourcePoints[0].date
                or result.observationEnd != result.sourcePoints[-1].date
                or result.contextEnd != result.observationEnd
                or result.asOf != _closed_at(result.observationEnd)
                or result.contextStart > result.observationStart):
            raise DailyWaveInputError("结果实际日期与本次行情不一致")
    confirmed_ids = {t.id for t in result.turns}
    for turn in turns:
        guard.check()
        if (turn.metric not in {"CLOSE", "DIF"} or not turn.value.is_finite()
                or not turn.plateauDates or tuple(sorted(set(turn.plateauDates))) != turn.plateauDates
                or turn.firstDate != turn.plateauDates[0] or turn.lastDate != turn.plateauDates[-1]
                or turn.id != f"{spec.ts_code}:day:{turn.metric}:{turn.firstDate}"):
            raise DailyWaveInputError("峰谷编号或平台日期错误")
        for day in turn.plateauDates:
            _date(day)
            if not result.contextStart <= day <= result.contextEnd:
                raise DailyWaveInputError("峰谷发生日期超出完整输入")
        if turn.id in confirmed_ids:
            _require_closed_at(turn.confirmedAt)
            if (turn.kind not in {"MAX", "MIN"} or turn.confirmedAt is None
                    or not _closed_at(turn.lastDate) < turn.confirmedAt <= result.asOf):
                raise DailyWaveInputError("峰谷确认时点错误")
        elif turn.kind is not None or turn.confirmedAt is not None or turn.possibleKind not in {None, "MIN", "MAX"}:
            raise DailyWaveInputError("未确认尾部不能伪装已确认峰谷")
    color_by_id = {s.id: s for s in result.colorSegments}
    for segment in result.colorSegments:
        guard.check()
        if not set(segment.turnIds) <= turn_ids:
            raise DailyWaveInputError("色段引用了不存在的峰谷")
        if (segment.id != f"{spec.ts_code}:day:{segment.color}:{segment.startDate}"
                or segment.color not in {"RED", "GREEN"} or segment.startDate > segment.endDate
                or segment.coloredCount < 1 or segment.lastColoredDate > segment.endDate
                or segment.isEnded != (segment.endKnownAt is not None)):
            raise DailyWaveInputError("色段日期、数量或结束状态错误")
        if segment.isEnded and not _closed_at(segment.endDate) < segment.endKnownAt <= result.asOf:
            raise DailyWaveInputError("色段结束确认时点错误")
        if segment.isEnded:
            _require_closed_at(segment.endKnownAt)
    for segment in result.priceSegments:
        guard.check()
        if segment.sourceColorSegmentId not in colors or segment.previousColorSegmentId not in colors | {None}:
            raise DailyWaveInputError("价格候选引用了不存在的色段")
        if not set(segment.difTurnIds + segment.tailReview.turnIds) <= turn_ids:
            raise DailyWaveInputError("价格候选引用了不存在的峰谷")
        source = color_by_id[segment.sourceColorSegmentId]
        if (segment.direction != ("UP" if source.color == "RED" else "DOWN")
                or segment.id != f"{source.id}:PRICE:{segment.direction}"
                or any(value not in {"VALID", "INVALID", "UNKNOWN"} for value in (
                    segment.startValidity, segment.endValidity, segment.endpointValidity))):
            raise DailyWaveInputError("价格候选方向、编号或有效性字段错误")
        if not segment.generated:
            if (segment.start is not None or segment.end is not None or segment.startKnownAt is not None
                    or segment.isEnded or segment.endKnownAt is not None or segment.extrema is not None
                    or segment.internalPriceRelations is not None or segment.endpointValidity != "UNKNOWN"
                    or segment.startValidity != "UNKNOWN" or segment.endValidity != "UNKNOWN"
                    or segment.difTurnIds or segment.tailReview != TailReview(None, (), None, None, None)
                    or not segment.issues):
                raise DailyWaveInputError("未生成候选的空值或状态错误")
        else:
            if (segment.start is None or segment.end is None or segment.startSearchRange is None
                    or segment.endSearchRange is None or segment.extrema is None
                    or segment.internalPriceRelations is None
                    or segment.startKnownAt != _closed_at(source.startDate)
                    or segment.isEnded != source.isEnded or segment.endKnownAt != source.endKnownAt):
                raise DailyWaveInputError("已生成候选缺少字段或结束确认错误")
            for endpoint in (segment.start, segment.end):
                if (endpoint.closedAt != _closed_at(_date(endpoint.date)) or endpoint.close <= 0
                        or not endpoint.close.is_finite() or not endpoint.tiedDates
                        or endpoint.date != endpoint.tiedDates[0]
                        or tuple(sorted(set(endpoint.tiedDates))) != endpoint.tiedDates):
                    raise DailyWaveInputError("价格极值日期、并列或收盘值错误")
            if segment.internalPriceRelations.status not in {"INSUFFICIENT", "RISING", "FALLING", "MIXED", "EQUAL"}:
                raise DailyWaveInputError("内部高低点关系状态错误")
    if len(result.mappings) != len(result.priceSegments) or {m.priceSegmentId for m in result.mappings} != prices:
        raise DailyWaveInputError("价格候选和对应关系不是一一对应")
    for mapping in result.mappings:
        if mapping.priceSegmentId not in prices or mapping.sourceColorSegmentId not in colors:
            raise DailyWaveInputError("对应关系引用不存在")
        if not set(mapping.sourceTurnIds + mapping.priceTurnIds) <= turn_ids:
            raise DailyWaveInputError("对应关系峰谷引用不存在")
        for offset in mapping.endpointOffsets:
            if (offset.difTurnId not in turn_ids or offset.priceEndpoint not in {"START", "END"}
                    or type(offset.tradingDayOffset) is not int):
                raise DailyWaveInputError("DIF交易日偏移字段错误")
    for triple in result.shortOppositeSegments:
        if not {triple.previousColorSegmentId, triple.oppositeColorSegmentId, triple.nextColorSegmentId} <= colors or not set(triple.difTurnIds) <= turn_ids:
            raise DailyWaveInputError("三段反色对照引用不存在")
    for change in result.asofChanges:
        if (not set(change.newConfirmedTurnIds) <= confirmed_ids
                or not set(change.updatedColorSegmentIds) <= colors
                or not set(change.updatedPriceSegmentIds) <= prices):
            raise DailyWaveInputError("逐日变化引用不存在")
        if not result.observationStart <= change.asOf[:10] <= result.observationEnd:
            raise DailyWaveInputError("逐日变化日期不在实际观察范围")
    if len(result.sourcePoints) != result.coverage.mainPointCount or len(result.sourcePoints) > spec.max_main_points:
        raise DailyWaveInputError("主范围数量或统计错误")
    observation = DateRange(result.observationStart, result.observationEnd) if result.observationStart else None
    expected_left = tuple(s.id for s in result.colorSegments if not s.isLeftComplete and
                          intersect_ranges(DateRange(s.startDate, s.endDate), observation))
    expected_ungenerated = tuple(s.id for s in result.priceSegments if not s.generated)
    expected_invalid = tuple(s.id for s in result.priceSegments if s.endpointValidity == "INVALID")
    expected_unknown = tuple(s.id for s in result.priceSegments if s.endpointValidity == "UNKNOWN")
    if (result.coverage.leftIncompleteColorSegmentIds != expected_left
            or result.coverage.ungeneratedPriceSegmentIds != expected_ungenerated
            or result.coverage.invalidPriceSegmentIds != expected_invalid
            or result.coverage.unknownPriceSegmentIds != expected_unknown
            or result.coverage.counts != CoverageCounts(len(expected_left), len(expected_ungenerated),
                                                       len(expected_invalid), len(expected_unknown))):
        raise DailyWaveInputError("主范围分类统计与实际记录不一致")
    encoded = json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > spec.max_response_bytes:
        raise DailyWaveBudgetExceeded("完整结果序列化超过字节上限")
    guard.check()
