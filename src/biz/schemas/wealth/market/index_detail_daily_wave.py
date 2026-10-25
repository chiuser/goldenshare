"""Strict HTTP facts for the daily-wave trial (LLD 14.6.1 and 15.3).

Validation preserves source text and checks the published contract only.  It
does not read data, select extrema, change identifiers, or run the calculator.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC


def _date_text(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("日期必须为YYYY-MM-DD")
    return value


def _time_text(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if (parsed.utcoffset() != timedelta(hours=8)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+08:00", value) is None):
        raise ValueError("时间必须为上海+08:00完整ISO文本")
    return value


def _closed_text(value: str) -> str:
    _time_text(value)
    if value != value[:10] + "T15:00:00+08:00":
        raise ValueError("日线确认时间必须为上海15:00")
    return value


def _number_text(value: str) -> str:
    if value == "-0" or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?", value) is None:
        raise ValueError("数字必须为规范十进制文本")
    return value


def _positive_text(value: str) -> str:
    _number_text(value)
    if Decimal(value) <= 0:
        raise ValueError("收盘价或绝对长度必须大于零")
    return value


DateText = Annotated[str, AfterValidator(_date_text)]
TimeText = Annotated[str, AfterValidator(_time_text)]
ClosedText = Annotated[str, AfterValidator(_closed_text)]
NumberText = Annotated[str, AfterValidator(_number_text)]
PositiveText = Annotated[str, AfterValidator(_positive_text)]
Identifier = Annotated[str, Field(min_length=1)]
Count = Annotated[int, Field(ge=0)]
Validity = Literal["VALID", "INVALID", "UNKNOWN"]


def _unique(values, message: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(message)


def _dates(values: list[str], *, nonempty: bool = True) -> None:
    if (nonempty and not values) or values != sorted(set(values)):
        raise ValueError("日期必须非空、升序且唯一")


def _closed(day: str) -> str:
    return day + "T15:00:00+08:00"


class _DailyWaveDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DailyWavePointDto(_DailyWaveDto):
    date: DateText
    close: PositiveText
    dif: NumberText
    dea: NumberText
    macd: NumberText


class _TurnDto(_DailyWaveDto):
    id: Identifier
    metric: Literal["CLOSE", "DIF"]
    value: NumberText
    firstDate: DateText
    lastDate: DateText
    plateauDates: list[DateText]

    @model_validator(mode="after")
    def consistent_platform(self):
        _dates(self.plateauDates)
        if (self.firstDate != self.plateauDates[0] or self.lastDate != self.plateauDates[-1]
                or self.id != f"{DEFAULT_SPEC.ts_code}:day:{self.metric}:{self.firstDate}"):
            raise ValueError("峰谷平台或编号错误")
        return self


class DailyWaveConfirmedTurnDto(_TurnDto):
    kind: Literal["MAX", "MIN"]
    confirmedAt: ClosedText

    @model_validator(mode="after")
    def confirmed_after_platform(self):
        if self.confirmedAt <= _closed(self.lastDate):
            raise ValueError("峰谷确认时间必须晚于平台")
        return self


class DailyWavePendingTurnDto(_TurnDto):
    kind: None
    confirmedAt: None
    possibleKind: Literal["MAX", "MIN"] | None


class DailyWaveExtremeDto(_DailyWaveDto):
    value: NumberText
    dates: list[DateText]

    @model_validator(mode="after")
    def ordered_dates(self):
        _dates(self.dates)
        return self


class DailyWaveHistogramExtremeDto(DailyWaveExtremeDto):
    absoluteLength: PositiveText

    @model_validator(mode="after")
    def absolute_length(self):
        if Decimal(self.value).copy_abs() != Decimal(self.absoluteLength):
            raise ValueError("柱值与绝对长度不一致")
        return self


class DailyWavePriceExtremeDto(DailyWaveExtremeDto):
    value: PositiveText


class DailyWaveExtremaDto(_DailyWaveDto):
    maxClose: DailyWavePriceExtremeDto
    minClose: DailyWavePriceExtremeDto
    maxDif: DailyWaveExtremeDto
    minDif: DailyWaveExtremeDto
    longestRed: DailyWaveHistogramExtremeDto | None
    longestGreen: DailyWaveHistogramExtremeDto | None

    @model_validator(mode="after")
    def signs_and_order(self):
        if (Decimal(self.minClose.value) <= 0
                or Decimal(self.minClose.value) > Decimal(self.maxClose.value)
                or Decimal(self.minDif.value) > Decimal(self.maxDif.value)
                or self.longestRed is not None and Decimal(self.longestRed.value) <= 0
                or self.longestGreen is not None and Decimal(self.longestGreen.value) >= 0):
            raise ValueError("极值顺序或红绿柱符号错误")
        return self


class DailyWaveColorSegmentDto(_DailyWaveDto):
    id: Identifier
    color: Literal["RED", "GREEN"]
    startDate: DateText
    endDate: DateText
    lastColoredDate: DateText
    coloredCount: Annotated[int, Field(ge=1)]
    zeroDates: list[DateText]
    isLeftComplete: bool
    isEnded: bool
    endKnownAt: ClosedText | None
    turnIds: list[Identifier]
    extrema: DailyWaveExtremaDto

    @model_validator(mode="after")
    def consistent_color(self):
        _dates(self.zeroDates, nonempty=False)
        _unique(self.turnIds, "色段峰谷编号重复")
        if (not self.startDate <= self.lastColoredDate <= self.endDate
                or any(not self.startDate <= day <= self.endDate for day in self.zeroDates)
                or self.lastColoredDate in self.zeroDates
                or self.id != f"{DEFAULT_SPEC.ts_code}:day:{self.color}:{self.startDate}"
                or self.isEnded != (self.endKnownAt is not None)
                or self.endKnownAt is not None and self.endKnownAt <= _closed(self.endDate)):
            raise ValueError("色段日期、编号或结束确认错误")
        return self


class DailyWaveDateRangeDto(_DailyWaveDto):
    startDate: DateText
    endDate: DateText

    @model_validator(mode="after")
    def ordered_range(self):
        if self.startDate > self.endDate:
            raise ValueError("日期区间反向")
        return self


class DailyWavePriceEndpointDto(_DailyWaveDto):
    date: DateText
    closedAt: ClosedText
    close: PositiveText
    tiedDates: list[DateText]

    @model_validator(mode="after")
    def earliest_tied_date(self):
        _dates(self.tiedDates)
        if self.date != self.tiedDates[0] or self.closedAt != _closed(self.date):
            raise ValueError("价格日期、收盘时间或最早并列日错误")
        return self


class DailyWaveIssueDto(_DailyWaveDto):
    message: Annotated[str, Field(min_length=1)]
    dates: list[DateText]


class DailyWavePricePointDto(_DailyWaveDto):
    date: DateText
    close: PositiveText


class DailyWavePriceComparisonDto(_DailyWaveDto):
    fromDate: DateText
    toDate: DateText
    relation: Literal["HIGHER", "LOWER", "EQUAL"]


class DailyWaveInternalPriceRelationsDto(_DailyWaveDto):
    highs: list[DailyWavePricePointDto]
    lows: list[DailyWavePricePointDto]
    highComparisons: list[DailyWavePriceComparisonDto]
    lowComparisons: list[DailyWavePriceComparisonDto]
    status: Literal["INSUFFICIENT", "RISING", "FALLING", "MIXED", "EQUAL"]

    @model_validator(mode="after")
    def consistent_lists(self):
        for points, comparisons in ((self.highs, self.highComparisons), (self.lows, self.lowComparisons)):
            _dates([point.date for point in points], nonempty=False)
            if len(comparisons) != max(0, len(points) - 1):
                raise ValueError("内部高低点与相邻比较数量不一致")
            if any((comparison.fromDate, comparison.toDate) != (left.date, right.date)
                   for left, right, comparison in zip(points, points[1:], comparisons)):
                raise ValueError("内部相邻比较日期不一致")
        if (len(self.highs) < 2 or len(self.lows) < 2) != (self.status == "INSUFFICIENT"):
            raise ValueError("内部高低点不足状态错误")
        return self


class DailyWaveTailReviewDto(_DailyWaveDto):
    range: DailyWaveDateRangeDto | None
    turnIds: list[Identifier]
    extrema: DailyWaveExtremaDto | None
    strictlyBrokeStart: bool | None
    touchedStart: bool | None


class DailyWavePriceSegmentDto(_DailyWaveDto):
    id: Identifier
    sourceColorSegmentId: Identifier
    previousColorSegmentId: Identifier | None
    direction: Literal["UP", "DOWN"]
    generated: bool
    startSearchRange: DailyWaveDateRangeDto | None
    endSearchRange: DailyWaveDateRangeDto | None
    start: DailyWavePriceEndpointDto | None
    end: DailyWavePriceEndpointDto | None
    startKnownAt: ClosedText | None
    isEnded: bool
    endKnownAt: ClosedText | None
    startValidity: Validity
    endValidity: Validity
    endpointValidity: Validity
    issues: list[DailyWaveIssueDto]
    internalPriceRelations: DailyWaveInternalPriceRelationsDto | None
    tailReview: DailyWaveTailReviewDto
    extrema: DailyWaveExtremaDto | None
    difTurnIds: list[Identifier]

    @model_validator(mode="after")
    def generated_fields(self):
        if self.id != f"{self.sourceColorSegmentId}:PRICE:{self.direction}":
            raise ValueError("价格候选编号错误")
        if not self.generated:
            if (any(value is not None for value in (self.start, self.end, self.startKnownAt,
                    self.endKnownAt, self.extrema, self.internalPriceRelations,
                    self.tailReview.range, self.tailReview.extrema,
                    self.tailReview.strictlyBrokeStart, self.tailReview.touchedStart))
                    or self.isEnded or self.difTurnIds or self.tailReview.turnIds or not self.issues
                    or (self.startValidity, self.endValidity, self.endpointValidity) != ("UNKNOWN",) * 3):
                raise ValueError("未生成候选的字段或空值错误")
        elif (any(value is None for value in (self.start, self.end, self.startKnownAt,
                self.startSearchRange, self.endSearchRange, self.extrema, self.internalPriceRelations,
                self.tailReview.range, self.tailReview.extrema,
                self.tailReview.strictlyBrokeStart, self.tailReview.touchedStart))
                or self.isEnded != (self.endKnownAt is not None)):
            raise ValueError("已生成候选缺少事实或结束确认错误")
        return self


class DailyWaveEndpointOffsetDto(_DailyWaveDto):
    difTurnId: Identifier
    priceEndpoint: Literal["START", "END"]
    tradingDayOffset: int


class DailyWaveMappingDto(_DailyWaveDto):
    sourceColorSegmentId: Identifier
    priceSegmentId: Identifier
    colorRange: DailyWaveDateRangeDto
    priceRange: DailyWaveDateRangeDto | None
    observationIntersection: DailyWaveDateRangeDto | None
    priceObservationIntersection: DailyWaveDateRangeDto | None
    sourceTurnIds: list[Identifier]
    priceTurnIds: list[Identifier]
    endpointOffsets: list[DailyWaveEndpointOffsetDto]
    issues: list[DailyWaveIssueDto]


class DailyWaveBarStatsDto(_DailyWaveDto):
    coloredCount: Annotated[int, Field(ge=1)]
    longestBar: DailyWaveHistogramExtremeDto


class DailyWaveThreeBarStatsDto(_DailyWaveDto):
    previous: DailyWaveBarStatsDto
    opposite: DailyWaveBarStatsDto
    next: DailyWaveBarStatsDto


class DailyWaveThreePriceExtremaDto(_DailyWaveDto):
    previous: DailyWavePriceExtremeDto
    opposite: DailyWavePriceExtremeDto
    next: DailyWavePriceExtremeDto


class DailyWaveShortOppositeDto(_DailyWaveDto):
    previousColorSegmentId: Identifier
    oppositeColorSegmentId: Identifier
    nextColorSegmentId: Identifier
    barStats: DailyWaveThreeBarStatsDto
    priceHighs: DailyWaveThreePriceExtremaDto
    priceLows: DailyWaveThreePriceExtremaDto
    difTurnIds: list[Identifier]


class DailyWaveCoverageCountsDto(_DailyWaveDto):
    leftIncomplete: Count
    ungenerated: Count
    invalid: Count
    unknown: Count


class DailyWaveCoverageDto(_DailyWaveDto):
    mainPointCount: Count
    leftIncompleteColorSegmentIds: list[Identifier]
    ungeneratedPriceSegmentIds: list[Identifier]
    invalidPriceSegmentIds: list[Identifier]
    unknownPriceSegmentIds: list[Identifier]
    counts: DailyWaveCoverageCountsDto


class _DailyWaveHeaderDto(_DailyWaveDto):
    schemaVersion: int
    tsCode: Literal["000001.SH"]
    period: Literal["day"]
    ruleId: Identifier
    calculationId: Identifier
    calculatedAt: TimeText
    requestedStart: DateText
    requestedEnd: DateText

    @model_validator(mode="after")
    def current_identity(self):
        if (self.schemaVersion != DEFAULT_SPEC.schema_version or self.ruleId != DEFAULT_SPEC.rule_id
                or self.requestedStart != DEFAULT_SPEC.requested_start
                or self.requestedEnd != DEFAULT_SPEC.requested_end):
            raise ValueError("响应身份或请求范围不符合本次规则")
        return self


class DailyWaveEmptyDto(_DailyWaveHeaderDto):
    status: Literal["empty"]


class DailyWaveReadyDto(_DailyWaveHeaderDto):
    status: Literal["ready"]
    observationStart: DateText
    observationEnd: DateText
    contextStart: DateText
    contextEnd: DateText
    asOf: ClosedText
    sourcePoints: Annotated[list[DailyWavePointDto], Field(min_length=1, max_length=DEFAULT_SPEC.max_main_points)]
    turns: list[DailyWaveConfirmedTurnDto]
    pendingTurns: list[DailyWavePendingTurnDto]
    colorSegments: list[DailyWaveColorSegmentDto]
    segments: list[DailyWavePriceSegmentDto]
    mappings: list[DailyWaveMappingDto]
    shortOppositeSegments: list[DailyWaveShortOppositeDto]
    coverage: DailyWaveCoverageDto

    @model_validator(mode="after")
    def consistent_facts(self):
        days = [point.date for point in self.sourcePoints]
        _dates(days)
        if (self.observationStart != days[0] or self.observationEnd != days[-1]
                or self.contextEnd != self.observationEnd
                or not DEFAULT_SPEC.absolute_start <= self.contextStart <= self.observationStart
                or not self.requestedStart <= self.observationStart <= self.observationEnd <= self.requestedEnd
                or self.asOf != _closed(self.observationEnd) or self.calculatedAt < self.asOf
                or self.coverage.mainPointCount != len(days)):
            raise ValueError("响应实际范围、时点或数量错误")
        turns = {turn.id: turn for turn in [*self.turns, *self.pendingTurns]}
        colors = {segment.id: segment for segment in self.colorSegments}
        prices = {segment.id: segment for segment in self.segments}
        if (len(turns) != len(self.turns) + len(self.pendingTurns)
                or len(colors) != len(self.colorSegments) or len(prices) != len(self.segments)):
            raise ValueError("响应编号重复")
        for turn in turns.values():
            if (not self.contextStart <= turn.firstDate <= turn.lastDate <= self.contextEnd
                    or turn.confirmedAt is not None and turn.confirmedAt > self.asOf):
                raise ValueError("峰谷超出本次已知范围")
        for color in self.colorSegments:
            if (not self.contextStart <= color.startDate <= color.endDate <= self.contextEnd
                    or color.endKnownAt is not None and color.endKnownAt > self.asOf
                    or not set(color.turnIds) <= turns.keys()):
                raise ValueError("色段范围或峰谷引用错误")
        for segment in self.segments:
            _unique(segment.difTurnIds, "价格候选DIF编号重复")
            _unique(segment.tailReview.turnIds, "尾部峰谷编号重复")
            if (segment.sourceColorSegmentId not in colors
                    or segment.previousColorSegmentId is not None and segment.previousColorSegmentId not in colors
                    or not set([*segment.difTurnIds, *segment.tailReview.turnIds]) <= turns.keys()
                    or any(turns[identifier].metric != "DIF" for identifier in segment.difTurnIds if identifier in turns)):
                raise ValueError("价格候选引用不存在")
            color = colors[segment.sourceColorSegmentId]
            if segment.direction != ("UP" if color.color == "RED" else "DOWN"):
                raise ValueError("价格候选与源色段方向不一致")
            if segment.generated and (segment.startKnownAt != _closed(color.startDate)
                    or segment.isEnded != color.isEnded or segment.endKnownAt != color.endKnownAt):
                raise ValueError("价格候选的可知时点与源色段不一致")
            if segment.generated:
                for endpoint, search in ((segment.start, segment.startSearchRange), (segment.end, segment.endSearchRange)):
                    if (not self.contextStart <= search.startDate <= search.endDate <= color.endDate
                            or any(not search.startDate <= day <= search.endDate for day in endpoint.tiedDates)):
                        raise ValueError("价格极值及搜索范围日期不一致")
                if ((segment.endSearchRange.startDate, segment.endSearchRange.endDate) != (segment.start.date, color.endDate)
                        or (segment.tailReview.range.startDate, segment.tailReview.range.endDate) != (segment.end.date, color.endDate)):
                    raise ValueError("价格终点搜索或尾部范围不一致")
        self._check_mappings(turns, colors, prices)
        for triple in self.shortOppositeSegments:
            _unique(triple.difTurnIds, "三段对照DIF编号重复")
            if (not {triple.previousColorSegmentId, triple.oppositeColorSegmentId,
                    triple.nextColorSegmentId} <= colors.keys() or not set(triple.difTurnIds) <= turns.keys()
                    or any(turns[identifier].metric != "DIF" for identifier in triple.difTurnIds if identifier in turns)):
                raise ValueError("三段对照引用不存在")
        expected = (
            [segment.id for segment in self.colorSegments if not segment.isLeftComplete
             and segment.startDate <= self.observationEnd and segment.endDate >= self.observationStart],
            [segment.id for segment in self.segments if not segment.generated],
            [segment.id for segment in self.segments if segment.endpointValidity == "INVALID"],
            [segment.id for segment in self.segments if segment.endpointValidity == "UNKNOWN"],
        )
        actual = (self.coverage.leftIncompleteColorSegmentIds, self.coverage.ungeneratedPriceSegmentIds,
                  self.coverage.invalidPriceSegmentIds, self.coverage.unknownPriceSegmentIds)
        counts = self.coverage.counts
        if actual != expected or (counts.leftIncomplete, counts.ungenerated, counts.invalid, counts.unknown) != tuple(map(len, expected)):
            raise ValueError("响应分类数量或引用错误")
        return self

    def _check_mappings(self, turns, colors, prices) -> None:
        if (len(self.mappings) != len(prices)
                or {mapping.priceSegmentId for mapping in self.mappings} != prices.keys()):
            raise ValueError("候选与映射必须一一对应")
        for mapping in self.mappings:
            _unique(mapping.priceTurnIds, "价格映射峰谷编号重复")
            _unique([(offset.difTurnId, offset.priceEndpoint) for offset in mapping.endpointOffsets], "DIF偏移重复")
            if (mapping.sourceColorSegmentId not in colors
                    or not set([*mapping.sourceTurnIds, *mapping.priceTurnIds]) <= turns.keys()
                    or any(offset.difTurnId not in turns or turns[offset.difTurnId].metric != "DIF"
                           for offset in mapping.endpointOffsets)):
                raise ValueError("映射引用不存在或DIF类型错误")
            segment = prices[mapping.priceSegmentId]
            color = colors[mapping.sourceColorSegmentId]
            if (segment.sourceColorSegmentId != mapping.sourceColorSegmentId
                    or (mapping.colorRange.startDate, mapping.colorRange.endDate) != (color.startDate, color.endDate)
                    or mapping.sourceTurnIds != color.turnIds):
                raise ValueError("映射与源色段不一致")
            expected_color = self._intersection(color.startDate, color.endDate)
            expected_price = self._intersection(segment.start.date, segment.end.date) if segment.generated else None
            actual_color = ((mapping.observationIntersection.startDate, mapping.observationIntersection.endDate)
                            if mapping.observationIntersection is not None else None)
            actual_price = ((mapping.priceObservationIntersection.startDate, mapping.priceObservationIntersection.endDate)
                            if mapping.priceObservationIntersection is not None else None)
            if actual_color != expected_color or actual_price != expected_price:
                raise ValueError("映射与实际观察范围交集不一致")
            if segment.generated and (mapping.priceRange is None
                    or (mapping.priceRange.startDate, mapping.priceRange.endDate) != (segment.start.date, segment.end.date)):
                raise ValueError("映射与价格范围不一致")
            if not segment.generated and (mapping.priceRange is not None
                    or mapping.priceObservationIntersection is not None or mapping.priceTurnIds or mapping.endpointOffsets):
                raise ValueError("未生成候选不能具有价格映射")

    def _intersection(self, start: str, end: str) -> tuple[str, str] | None:
        start, end = max(start, self.observationStart), min(end, self.observationEnd)
        return (start, end) if start <= end else None
