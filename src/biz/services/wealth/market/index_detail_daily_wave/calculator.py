"""Completed daily facts only, LLD 14.3.1/14.4; no trading signals or I/O."""
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal, DecimalException, localcontext
import json
import math
import sys
import time

from .local_extrema import LocalExtremaScanner, number
from .spec import DEFAULT_SPEC, DailyWaveReviewSpec
from .types import (
    BasicRecords, ColorSegment, DailyPoint, Extreme, Extrema, HistogramExtreme,
    Turn,
)

_INPUT_FIELDS = frozenset(("tsCode", "date", "close", "dif", "dea", "macd", "completed"))


class DailyWaveInputError(ValueError):
    """Invalid caller input; never a partial successful computation."""


class DailyWaveBudgetExceeded(RuntimeError):
    """Stop this computation; another invocation starts from its own input."""


class DailyWaveCancelled(RuntimeError):
    """The caller has observed cancellation."""


class _Guard:
    def __init__(self, spec: DailyWaveReviewSpec, deadline: float | None,
                 check_cancelled: Callable[[], bool] | None):
        if deadline is not None and (isinstance(deadline, bool)
                                     or not math.isfinite(deadline)):
            raise DailyWaveInputError("deadline必须为有限单调时刻")
        self.deadline = min(time.monotonic() + spec.calculation_seconds,
                            deadline if deadline is not None else math.inf)
        self.check_cancelled = check_cancelled

    def check(self) -> None:
        if self.check_cancelled is not None and self.check_cancelled():
            raise DailyWaveCancelled("本次基础计算已取消")
        if time.monotonic() >= self.deadline:
            raise DailyWaveBudgetExceeded("本次基础计算超过时间上限")


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
            guard: _Guard) -> tuple[DailyPoint, ...]:
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
            raise DailyWaveInputError("源指标超出十进制运算范围") from exc
        if error > spec.source_equation_tolerance:
            raise DailyWaveInputError("源MACD柱与DIF/DEA关系不符")
        result.append(point)
    guard.check()
    return tuple(result)


def _turns(points: tuple[DailyPoint, ...], spec: DailyWaveReviewSpec,
           guard: _Guard) -> tuple[tuple[Turn, ...], tuple[Turn, ...]]:
    turns, pending = [], []
    for metric, column in (("CLOSE", "close"), ("DIF", "dif")):
        scanner = LocalExtremaScanner()
        for point in points:
            guard.check()
            found = scanner.step(point.date, getattr(point, column))
            if found is not None:
                turns.append(Turn(
                    id=f"{spec.ts_code}:day:{metric}:{found.first_at}",
                    metric=metric, kind=found.kind, value=found.value,
                    firstDate=found.first_at, lastDate=found.last_at,
                    plateauDates=tuple(p.date for p in points[found.first_index:found.last_index + 1]),
                    confirmedAt=_closed_at(found.confirmed_at),
                ))
        tail = scanner.pending()
        if tail is not None:
            pending.append(Turn(
                id=f"{spec.ts_code}:day:{metric}:{tail['first_at']}",
                metric=metric, kind=None, value=number(tail["value"]),
                firstDate=tail["first_at"], lastDate=tail["last_at"],
                plateauDates=tuple(p.date for p in points[tail["first_index"]:tail["last_index"] + 1]),
                confirmedAt=None, possibleKind=tail["possible_kind"],
            ))
    return (tuple(sorted(turns, key=lambda t: (t.firstDate, t.metric))), tuple(pending))


def _extreme(points: tuple[DailyPoint, ...], column: str, maximum: bool,
             guard: _Guard) -> Extreme:
    value = getattr(points[0], column)
    dates = []
    for point in points:
        guard.check()
        candidate = getattr(point, column)
        if (candidate > value if maximum else candidate < value):
            value, dates = candidate, []
        if candidate == value:
            dates.append(point.date)
    return Extreme(value, tuple(dates))


def _extrema(points: tuple[DailyPoint, ...], guard: _Guard) -> Extrema:
    red = tuple(p for p in points if p.macd > 0)
    green = tuple(p for p in points if p.macd < 0)

    def histogram(rows: tuple[DailyPoint, ...], maximum: bool) -> HistogramExtreme | None:
        if not rows:
            return None
        extreme = _extreme(rows, "macd", maximum, guard)
        return HistogramExtreme(extreme.value, extreme.value.copy_abs(), extreme.dates)

    return Extrema(_extreme(points, "close", True, guard),
                   _extreme(points, "close", False, guard),
                   _extreme(points, "dif", True, guard),
                   _extreme(points, "dif", False, guard),
                   histogram(red, True), histogram(green, False))


def _color_segments(points: tuple[DailyPoint, ...], turns: tuple[Turn, ...],
                    spec: DailyWaveReviewSpec, guard: _Guard) -> tuple[ColorSegment, ...]:
    result = []
    start = None
    color = None

    def finish(end: int, known_at: str | None) -> None:
        guard.check()
        part = points[start:end + 1]
        colored = tuple(p for p in part if p.macd != 0)
        result.append(ColorSegment(
            id=f"{spec.ts_code}:day:{color}:{part[0].date}", color=color,
            startDate=part[0].date, endDate=part[-1].date,
            lastColoredDate=colored[-1].date, coloredCount=len(colored),
            zeroDates=tuple(p.date for p in part if p.macd == 0),
            isLeftComplete=bool(result), isEnded=known_at is not None,
            endKnownAt=known_at,
            turnIds=tuple(t.id for t in turns
                          if t.firstDate <= part[-1].date and t.lastDate >= part[0].date),
            extrema=_extrema(part, guard),
        ))

    for index, point in enumerate(points):
        guard.check()
        actual = "RED" if point.macd > 0 else "GREEN" if point.macd < 0 else None
        if actual is None:
            continue
        if start is None:
            start, color = index, actual
        elif actual != color:
            finish(index - 1, _closed_at(point.date))
            start, color = index, actual
    if start is not None:
        finish(len(points) - 1, None)
    return tuple(result)


def _memory_size(value: object, guard: _Guard, seen: set[int] | None = None) -> int:
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
    guard = _Guard(spec, deadline, check_cancelled)
    guard.check()
    as_of = _date(as_of)
    if not spec.absolute_start <= as_of <= spec.requested_end:
        raise DailyWaveInputError("截止日期超出试验范围")
    points = _points(rows, as_of, spec, guard)
    turns, pending = _turns(points, spec, guard)
    colors = _color_segments(points, turns + pending, spec, guard)
    result = BasicRecords(
        tsCode=spec.ts_code, period=spec.period, ruleId=spec.rule_id,
        asOf=_closed_at(points[-1].date) if points else None,
        contextStart=points[0].date if points else None,
        contextEnd=points[-1].date if points else None,
        sourcePoints=points, turns=turns, pendingTurns=pending, colorSegments=colors,
    )
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
