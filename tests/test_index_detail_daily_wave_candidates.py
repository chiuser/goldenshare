"""Independent literal examples from LLD 14.5/14.7; no market or software oracle."""
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import builtins
import socket
import time

import pytest

from src.biz.services.wealth.market.index_detail_daily_wave import calculator as c
from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC
from src.biz.services.wealth.market.index_detail_daily_wave.types import CalendarDay, DateRange

WHEN = datetime(2026, 10, 25, tzinfo=timezone(timedelta(hours=8)))
IDENTITY = "00000000-0000-0000-0000-000000000001"


def row(day, close, dif, dea, h):
    return dict(tsCode="000001.SH", date=day, close=str(close), dif=str(dif),
                dea=str(dea), macd=str(h), completed=True)


def calendar(rows):
    """Artificial calendar: only the literal input dates are declared open."""
    if not rows: return ()
    start, end = date.fromisoformat(rows[0]["date"]), date.fromisoformat(rows[-1]["date"])
    open_days = {p["date"] for p in rows}
    return tuple(CalendarDay("SSE", (start + timedelta(days=i)).isoformat(),
        (start + timedelta(days=i)).isoformat() in open_days) for i in range((end-start).days+1))


def review(rows, **kwargs):
    main = [r for r in rows if r["date"] >= DEFAULT_SPEC.requested_start]
    observation = DateRange(main[0]["date"], main[-1]["date"]) if main else None
    return c.build_review(rows, observation_range=observation, calendar=calendar(rows),
        as_of=rows[-1]["date"] if rows else "2026-10-21", calculation_id=IDENTITY,
        calculated_at=WHEN, **kwargs)


def rising():
    return [row("2023-10-20",108,5,4,2), row("2023-10-23",100,4,5,-2),
        row("2023-10-24",110,5,4,2), row("2023-10-25",105,4,3.5,1),
        row("2023-10-26",120,7,6,2), row("2023-10-27",112,6,5.5,1),
        row("2023-10-30",130,9,8,2), row("2023-10-31",125,8,8.5,-1)]


def up(result):
    return next(s for s in result.priceSegments if s.direction == "UP")


def test_literal_rising_prices_dif_turns_internal_relations_and_confirmation():
    result = review(rising())
    segment = up(result)
    assert (segment.start.date, segment.start.close, segment.end.date, segment.end.close) == (
        "2023-10-23", Decimal(100), "2023-10-30", Decimal(130))
    assert (segment.startKnownAt, segment.endKnownAt, segment.endpointValidity) == (
        "2023-10-24T15:00:00+08:00", "2023-10-31T15:00:00+08:00", "VALID")
    assert [p.close for p in segment.internalPriceRelations.highs] == [110,120,130]
    assert [p.close for p in segment.internalPriceRelations.lows] == [100,105,112]
    assert segment.internalPriceRelations.status == "RISING"
    assert [t.value for t in result.turns if t.metric == "DIF" and t.kind == "MAX"] == [5,7,9]
    assert len(result.asofChanges) == 6
    assert result.sourcePoints[0].date == "2023-10-24"
    assert not up(review(rising()[:-1])).isEnded
    assert result.to_dict()["priceSegments"][0]["start"]["close"] == "100"


def test_mirrored_downward_candidate_uses_same_rules():
    rows = [dict(r, close=str(Decimal(300)-Decimal(r["close"])),
        dif=str(-Decimal(r["dif"])), dea=str(-Decimal(r["dea"])), macd=str(-Decimal(r["macd"]))) for r in rising()]
    segment = next(s for s in review(rows).priceSegments if s.direction == "DOWN")
    assert (segment.start.close, segment.end.close, segment.endpointValidity) == (200,170,"VALID")
    assert segment.internalPriceRelations.status == "FALLING"


@pytest.mark.parametrize("prices, expected_end, valid, broke", [
    ([110,105,120,90],120,"VALID",True),
    ([110,95,120,115],120,"INVALID",False),
    ([110,120,90,130],130,"INVALID",False),
    ([110,120,110,120],120,"VALID",False),
])
def test_conflicts_tail_strict_new_high_and_equal_high_are_independent(prices,expected_end,valid,broke):
    rows = rising()[:2] + [row(day, price,5,4,2) for day, price in zip(
        ("2023-10-24","2023-10-25","2023-10-26","2023-10-27"),prices)]
    segment = up(review(rows))
    assert segment.start.close == 100 and segment.end.close == expected_end
    assert segment.endpointValidity == valid and segment.tailReview.strictlyBrokeStart is broke
    if prices == [110,120,110,120]:
        assert segment.end.date == "2023-10-25"
        assert segment.end.tiedDates == ("2023-10-25","2023-10-27")
        assert segment.tailReview.range.startDate == "2023-10-25"


def test_old_high_before_start_is_not_selected_and_initial_end_may_be_in_previous_color():
    rows = [row("2023-10-18",130,5,4,2), row("2023-10-19",120,4,5,-2),
        row("2023-10-20",100,3,4,-2), row("2023-10-23",104,3,4,-2),
        row("2023-10-24",110,5,4,2), row("2023-10-25",108,4,3,2),row("2023-10-26",118,6,5,2)]
    assert up(review(rows)).end.close == 118
    rows = [row("2023-10-18",110,5,4,2), row("2023-10-19",100,4,5,-2),
        row("2023-10-20",120,4,5,-2), row("2023-10-23",110,4,5,-2),row("2023-10-24",115,5,4,2)]
    segment = up(review(rows))
    assert segment.end.date == "2023-10-20" and segment.extrema.maxClose.value == 120
    assert segment.tailReview.extrema.minClose.value == 110
    assert segment.tailReview.range == DateRange("2023-10-20","2023-10-24")
    assert any("早于本色" in issue.message for issue in segment.issues)


def test_short_reverse_is_three_records_and_no_threshold_merges_it():
    rows = rising()[:5] + [row("2023-10-27",115,5,5.0001,"-0.0002"),row("2023-10-30",125,7,6,2)]
    result = review(rows)
    assert [s.color for s in result.colorSegments][-3:] == ["RED","GREEN","RED"]
    triple = result.shortOppositeSegments[-1]
    assert triple.barStats.opposite.coloredCount == 1
    assert triple.barStats.opposite.longestBar.value == Decimal("-0.0002")
    assert len([s for s in result.priceSegments if s.direction == "UP"]) == 2


def test_cross_boundary_platform_uses_intersection_and_original_id_for_offsets():
    rows = [row("2023-10-19",130,7,6,2),row("2023-10-20",100,4,5,-2),
        row("2023-10-23",100,4,5,-2),row("2023-10-24",100,4,3,2),
        row("2023-10-25",110,5,4,2),row("2023-10-26",105,4.5,3.5,2)]
    result = review(rows)
    segment = up(result)
    turn = next(t for t in result.turns if t.metric == "DIF" and t.kind == "MIN")
    assert (turn.firstDate,turn.lastDate) == ("2023-10-20","2023-10-24")
    mapping = next(m for m in result.mappings if m.priceSegmentId == segment.id)
    assert next(o for o in mapping.endpointOffsets if o.difTurnId == turn.id and o.priceEndpoint == "START").tradingDayOffset == -2
    assert [p.close for p in segment.internalPriceRelations.lows].count(Decimal(100)) == 1
    assert turn.id.endswith("2023-10-20")


def test_step_count_prefix_independent_expectations_and_final_helper_no_rescan(monkeypatch):
    rows = rising()
    original = c.LocalExtremaScanner.step
    calls=[]
    def step(self,*args,**kwargs):
        calls.append(args[0])
        return original(self,*args,**kwargs)
    monkeypatch.setattr(c.LocalExtremaScanner,"step",step)
    result=review(rows)
    assert len(calls)==2*len(rows)
    basic=c.build_basic_records(rows,as_of=rows[-1]["date"])
    calls.clear()
    final=c.build_price_candidates(basic,observation_range=DateRange("2023-10-24","2023-10-31"),calendar=calendar(rows))
    assert calls==[] and final.priceSegments==result.priceSegments and final.mappings==result.mappings
    for i in range(3,len(rows)+1):
        prefix=rows[:i]
        earlier=review(prefix)
        current=up(earlier)
        assert current.end.close==[110,110,120,120,130,130][i-3]
        assert current.isEnded is (i==len(rows))
        assert earlier.asofChanges==result.asofChanges[:i-2]
        assert earlier.colorSegments[1].id==result.colorSegments[1].id
    old=result.to_dict()
    old["priceSegments"][0]["issues"].append({"message":"changed"})
    assert all(issue.message!="changed" for issue in result.priceSegments[0].issues)
    with pytest.raises(FrozenInstanceError): result.status="modified"


def test_unknown_left_empty_invalid_input_limits_and_no_io(monkeypatch):
    result=review(rising()[2:])
    assert result.priceSegments[0].generated is False
    assert result.priceSegments[0].endpointValidity=="UNKNOWN"
    assert result.priceSegments[0].tailReview.range is None
    assert set(review([]).to_dict())=={"schemaVersion","tsCode","period","status","ruleId","calculationId","calculatedAt","requestedStart","requestedEnd"}
    with pytest.raises(c.DailyWaveInputError):
        c.build_review(rising(),observation_range=DateRange("2023-10-25","2023-10-31"),calendar=calendar(rising()),
            as_of="2023-10-31",calculation_id=IDENTITY,calculated_at=WHEN)
    with pytest.raises(c.DailyWaveBudgetExceeded): review(rising(),spec=replace(DEFAULT_SPEC,max_response_bytes=10))
    with pytest.raises(c.DailyWaveBudgetExceeded): review(rising(),spec=replace(DEFAULT_SPEC,max_memory_bytes=1))
    def forbidden(*args,**kwargs): raise AssertionError("pure review performed I/O")
    monkeypatch.setattr(builtins,"open",forbidden)
    monkeypatch.setattr(socket,"socket",forbidden)
    assert up(review(rising())).end.close==130


@pytest.mark.parametrize("fault",["version","status","duplicate","confirmation","confirmation_clock","platform","missing_reference","direction","open_end","unknown_fields","mapping"])
def test_result_contract_rejects_corrupted_records(fault):
    result=review(rising())
    if fault=="version": result=replace(result,schemaVersion=99)
    elif fault=="status":result=replace(result,status="empty")
    elif fault=="duplicate":result=replace(result,turns=result.turns+(result.turns[0],))
    elif fault=="confirmation":result=replace(result,turns=(replace(result.turns[0],confirmedAt="2023-10-23T15:00:00+08:00"),)+result.turns[1:])
    elif fault=="confirmation_clock":result=replace(result,turns=(replace(result.turns[0],confirmedAt="2023-10-24T14:30:00+08:00"),)+result.turns[1:])
    elif fault=="platform":result=replace(result,turns=(replace(result.turns[0],plateauDates=()),)+result.turns[1:])
    elif fault=="missing_reference":result=replace(result,colorSegments=(replace(result.colorSegments[0],turnIds=("missing",)),)+result.colorSegments[1:])
    elif fault=="direction":result=replace(result,priceSegments=(replace(result.priceSegments[0],direction="DOWN"),)+result.priceSegments[1:])
    elif fault=="open_end":result=replace(result,priceSegments=(replace(result.priceSegments[0],isEnded=False),)+result.priceSegments[1:])
    elif fault=="unknown_fields":result=replace(result,priceSegments=(replace(result.priceSegments[0],generated=False),)+result.priceSegments[1:])
    elif fault=="mapping":result=replace(result,mappings=())
    with pytest.raises(c.DailyWaveInputError): c.validate_review_result(result)


def test_closed_candidate_later_confirmation_and_removed_pending_do_not_mutate_history():
    rows=[row("2023-10-20",120,5,4,2),row("2023-10-23",100,4,5,-2),
        row("2023-10-24",110,5,4,2),row("2023-10-25",120,6,5,2),
        row("2023-10-26",115,6,6.5,-1),row("2023-10-27",112,6,6.5,-1),
        row("2023-10-30",113,5,5.5,-1)]
    previous=review(rows[:5]);old=previous.to_dict();later=review(rows)
    assert previous.to_dict()==old
    assert up(later).start==up(previous).start and up(later).end==up(previous).end
    assert up(later).endKnownAt==up(previous).endKnownAt
    dif=next(t for t in later.turns if t.metric=="DIF" and t.kind=="MAX")
    assert (dif.firstDate,dif.lastDate,dif.confirmedAt)==("2023-10-25","2023-10-27","2023-10-30T15:00:00+08:00")
    assert dif.id in up(later).difTurnIds
    # Literal platform occurs on Oct25-27: it intersects the red starting Oct24
    # and the green starting Oct26, not the earlier Oct23 green segment.
    by_start={segment.startDate:segment for segment in later.colorSegments}
    assert dif.id in by_start["2023-10-24"].turnIds and dif.id in by_start["2023-10-26"].turnIds
    assert up(later).id in later.asofChanges[-1].updatedPriceSegmentIds
    old_tail={t.id for t in previous.pendingTurns if t.metric=="CLOSE"}
    current_ids={t.id for t in later.turns+later.pendingTurns}
    assert not old_tail<=current_ids
    for mapping in later.mappings:
        assert set(mapping.priceTurnIds)<=current_ids


def test_tail_can_both_touch_start_and_later_strictly_break_it():
    rows=rising()[:2]+[row(day,price,5,4,2) for day,price in (
        ("2023-10-24",110),("2023-10-25",120),("2023-10-26",100),("2023-10-27",90))]
    tail=up(review(rows)).tailReview
    assert tail.strictlyBrokeStart is True
    assert tail.touchedStart is True


def test_auxiliary_left_incomplete_color_is_retained_but_not_counted_in_main_coverage():
    result=review(rising())
    assert result.colorSegments[0].isLeftComplete is False
    assert result.colorSegments[0].startDate=="2023-10-20"
    assert result.coverage.leftIncompleteColorSegmentIds==()
    assert result.coverage.counts.leftIncomplete==0
    main_only=review(rising()[2:])
    assert main_only.coverage.leftIncompleteColorSegmentIds==(main_only.colorSegments[0].id,)
    assert main_only.coverage.counts.leftIncomplete==1


@pytest.mark.parametrize("mode",["long_color","long_platform","alternating"])
def test_1300_points_are_bounded_without_repeated_scanning_or_truncated_success(mode,monkeypatch):
    main=date(2023,10,24);rows=[]
    for i in range(1300):
        day=(main+timedelta(days=i-500)).isoformat()
        h=2 if i>=500 or i==0 else -2
        if mode=="alternating":h=2 if i%2 else -2
        dif=5 if mode=="long_platform" else i%11
        close=100 if mode=="long_platform" else 100+i%17+i//17
        rows.append(row(day,close,dif,dif-h/2,h))
    original=c.LocalExtremaScanner.step;count=0
    def step(self,*args,**kwargs):
        nonlocal count
        count+=1
        return original(self,*args,**kwargs)
    monkeypatch.setattr(c.LocalExtremaScanner,"step",step)
    try:
        result=review(rows)
    except c.DailyWaveBudgetExceeded as exc:
        # A detailed alternating result may legitimately exceed the fixed 2MiB.
        assert mode=="alternating" and "字节上限" in str(exc)
    else:
        assert len(result.sourcePoints)==800 and len(result.asofChanges)==800
        assert result.coverage.mainPointCount==800
    assert count==2600


def touch_example(tail, direction="UP"):
    """Package literal price paths; expected touch dates below are independent."""
    dates=("2023-10-24","2023-10-25","2023-10-26","2023-10-27",
           "2023-10-30","2023-10-31","2023-11-01","2023-11-02")
    rows=rising()[:2]+[row(day,price,5,4,2)
        for day,price in zip(dates,(110,120,*tail))]
    if direction=="DOWN":
        rows=[dict(item,close=str(Decimal(300)-Decimal(item["close"])),
            dif=str(-Decimal(item["dif"])),dea=str(-Decimal(item["dea"])),
            macd=str(-Decimal(item["macd"]))) for item in rows]
    return rows


def touch_issues(segment):
    return tuple(issue for issue in segment.issues if issue.message=="终点后价格接触起始收盘")


@pytest.mark.parametrize("direction",["UP","DOWN"])
@pytest.mark.parametrize("tail,touch_dates,break_dates",[
    ((110,105),(),()),
    ((100,110),("2023-10-26",),()),
    ((90,95),(),("2023-10-26",)),
    ((100,90),("2023-10-26",),("2023-10-27",)),
    ((100,110,100,90),("2023-10-26","2023-10-30"),("2023-10-31",)),
])
def test_touch_issue_dates_are_actual_equal_prices_in_both_directions(direction,tail,touch_dates,break_dates):
    segment=review(touch_example(tail,direction)).priceSegments[0]
    assert segment.direction==direction
    assert (segment.start.close,segment.end.close)==((Decimal(100),Decimal(120))
        if direction=="UP" else (Decimal(200),Decimal(180)))
    assert (segment.start.date,segment.end.date)==("2023-10-23","2023-10-25")
    assert segment.tailReview.touchedStart is bool(touch_dates)
    assert segment.tailReview.strictlyBrokeStart is bool(break_dates)
    assert tuple(issue.dates for issue in touch_issues(segment))==((touch_dates,) if touch_dates else ())
    breaks=tuple(issue.dates for issue in segment.issues if issue.message=="终点后价格严格突破起始收盘")
    assert breaks==((break_dates,) if break_dates else ())


@pytest.mark.parametrize("direction",["UP","DOWN"])
def test_strict_new_endpoint_discards_only_old_tail_touch_dates(direction):
    rows=touch_example((100,130,100,90),direction)
    before=review(rows[:5]);saved=before.to_dict()
    reset=review(rows[:6]).priceSegments[0]
    final=review(rows).priceSegments[0]
    assert touch_issues(before.priceSegments[0])[0].dates==("2023-10-26",)
    assert reset.end.date=="2023-10-27"
    assert reset.tailReview.range==DateRange("2023-10-27","2023-10-27")
    assert reset.tailReview.touchedStart is False and touch_issues(reset)==()
    assert touch_issues(final)[0].dates==("2023-10-30",)
    assert final.end.close==(Decimal(130) if direction=="UP" else Decimal(170))
    assert final.tailReview.strictlyBrokeStart is True
    assert before.to_dict()==saved


@pytest.mark.parametrize("direction",["UP","DOWN"])
def test_equal_endpoint_keeps_earliest_date_and_all_tail_touch_dates(direction):
    rows=touch_example((100,120,100,90),direction)
    previous=review(rows[:5]);saved=previous.to_dict()
    final=review(rows).priceSegments[0]
    assert final.end.date=="2023-10-25"
    assert final.end.tiedDates==("2023-10-25","2023-10-27")
    assert final.tailReview.range==DateRange("2023-10-25","2023-10-31")
    assert touch_issues(final)[0].dates==("2023-10-26","2023-10-30")
    assert final.tailReview.strictlyBrokeStart is True
    assert previous.to_dict()==saved


def test_statistics_copy_does_not_share_close_date_or_extreme_lists():
    def point(day):
        return c.DailyPoint(day,Decimal(100),Decimal(5),Decimal(4),Decimal(2))
    original=c._Statistics()
    original.add(point("2023-10-24"))
    copied=original.copy()
    old=original.freeze()
    original.add(point("2023-10-25"))
    assert copied.close_dates=={Decimal(100):["2023-10-24"]}
    copied.add(point("2023-10-26"))
    assert original.close_dates=={Decimal(100):["2023-10-24","2023-10-25"]}
    assert copied.close_dates=={Decimal(100):["2023-10-24","2023-10-26"]}
    assert original.freeze().maxClose.dates==("2023-10-24","2023-10-25")
    assert copied.freeze().maxClose.dates==("2023-10-24","2023-10-26")
    assert old.maxClose.dates==("2023-10-24",)
