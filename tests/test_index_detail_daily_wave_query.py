"""Source fixture follows IndexFactorPro DATE/Float53 and TradeCalendar DATE/bool.

The fixtures are isolated query input, not proof of physical database coverage.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from src.biz.queries.wealth.market.index_detail_daily_wave.query import DailyWaveQuery, DailyWaveSourceError
from src.biz.queries.wealth.market.index_detail_daily_wave import query_service as module
from src.biz.services.wealth.market.index_detail_daily_wave.budget import DailyWaveBudgetExceeded
from src.biz.services.wealth.market.index_detail_daily_wave.budget import DailyWaveInputError
from src.biz.services.wealth.market.index_detail_daily_wave import budget as budget_module
from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC
from src.biz.services.wealth.market.index_detail_daily_wave.types import DateRange

WHEN=datetime(2026,10,25,tzinfo=timezone(timedelta(hours=8)))
SPEC=replace(DEFAULT_SPEC,requested_start="2024-01-10",requested_end="2024-01-20",
             absolute_start="2024-01-01",context_batch_points=2,max_context_points=4)


def source(day, h=2.0):
    # Literal valid source tuples; no MACD calculation by the producer fixture.
    dif,dea = (5.0,4.0) if h==2.0 else (4.0,5.0) if h==-2.0 else (4.0,4.0)
    return dict(ts_code="000001.SH",trade_date=date(2024,1,day),close=100.0+day,
        macd_dif_bfq=dif,macd_dea_bfq=dea,macd_bfq=h)


class FakeQuery:
    def __init__(self, main=None, batches=None, calendar_change=None):
        self.main=[source(10),source(11)] if main is None else main
        self.batches=[[source(9,-2.0),source(8),source(5,-2.0)]] if batches is None else batches
        self.calls=[]
        self.calendar_change=calendar_change

    async def load_main_window(self,session,**kwargs):
        self.calls.append(("main",kwargs))
        return tuple(self.main)

    async def load_context_window(self,session,**kwargs):
        self.calls.append(("context",kwargs))
        return tuple(self.batches[sum(name=="context" for name,_ in self.calls)-1])

    async def load_calendar(self,session,**kwargs):
        self.calls.append(("calendar",kwargs))
        chosen=set(row["trade_date"] for row in self.main)
        before=self.main[0]["trade_date"]
        for batch in self.batches[:sum(name=="context" for name,_ in self.calls)]:
            chosen.update(row["trade_date"] for row in batch[:2])
        start,end=kwargs["context_start"],kwargs["observation_end"]
        rows=[dict(exchange="SSE",trade_date=start+timedelta(days=i),
                   is_open=start+timedelta(days=i) in chosen) for i in range((end-start).days+1)]
        if self.calendar_change: rows=self.calendar_change(rows)
        return tuple(rows)


def service(query, events=None, **overrides):
    events=events if events is not None else []
    @asynccontextmanager
    async def factory(*,budget):
        events.append(("enter",budget.deadline))
        try: yield object()
        finally: events.append("closed")
    return module.DailyWaveQueryService(factory,query=query,clock=lambda:WHEN,
        new_id=lambda:"00000000-0000-0000-0000-000000000001",**overrides)


def test_fixed_query_projections_bounds_sort_order_and_no_null_filter():
    statements=[]
    class Session:
        async def execute_read(self,statement,parameters=None):
            statements.append(statement)
            return ()
    async def run():
        query=DailyWaveQuery()
        await query.load_main_window(Session(),start_date=date(2023,10,24),end_date=date(2026,10,21),spec=DEFAULT_SPEC)
        await query.load_context_window(Session(),before_date=date(2023,10,24),spec=DEFAULT_SPEC)
        await query.load_calendar(Session(),context_start=date(2022,10,24),observation_end=date(2026,10,21),spec=DEFAULT_SPEC)
    asyncio.run(run())
    assert [column.key for column in statements[0].selected_columns]==[
        "ts_code","trade_date","close","macd_dif_bfq","macd_dea_bfq","macd_bfq"]
    assert [column.key for column in statements[2].selected_columns]==["exchange","trade_date","is_open"]
    compiled=[s.compile(dialect=postgresql.dialect()) for s in statements]
    assert compiled[0].params["param_1"]==801 and compiled[1].params["param_1"]==251 and compiled[2].params["param_1"]==2001
    assert "DESC" in str(compiled[1]) and "core_serving.index_factor_pro" in str(compiled[0])
    assert all("IS NOT NULL" not in str(item) for item in compiled)
    assert "is_open =" not in str(compiled[2])


def test_250_equivalent_is_enough_probe_is_not_converted_and_connection_closes_before_compute(monkeypatch):
    query=FakeQuery()
    query.batches[0][-1]["close"]=float("nan")  # Probe identity/date only.
    events=[]
    original=module.build_review
    calls=[]
    def build(*args,**kwargs):
        assert events[-1]=="closed"
        calls.append(args[0])
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"build_review",build)
    result=asyncio.run(service(query,events).build(spec=SPEC))
    assert [name for name,_ in query.calls]==["main","context","calendar"]
    assert len(calls)==1 and len(calls[0])==4
    assert result.contextStart=="2024-01-08" and result.observationEnd=="2024-01-11"
    assert result.requestedEnd=="2024-01-20" and result.status=="ready"
    assert result.priceSegments[0].generated


def test_context_expands_once_only_if_needed_and_never_beyond_maximum():
    query=FakeQuery(batches=[[source(9),source(8),source(7,-2.0)],
                            [source(7,-2.0),source(6),source(5,-2.0)]])
    result=asyncio.run(service(query).build(spec=SPEC))
    contexts=[args for name,args in query.calls if name=="context"]
    assert [args["before_date"] for args in contexts]==[date(2024,1,10),date(2024,1,8)]
    assert result.contextStart=="2024-01-06"
    assert len(result.colorSegments)==3 and result.priceSegments[0].generated
    query=FakeQuery(batches=[[source(9),source(8),source(7)],[source(7),source(6),source(5)]])
    result=asyncio.run(service(query).build(spec=SPEC))
    assert len([name for name,_ in query.calls if name=="context"])==2
    assert result.priceSegments[0].generated is False


@pytest.mark.parametrize("column,value",[
    ("close",None),("close",True),("close",100),("close","100"),("close",float("nan")),
    ("close",0.0),("macd_dif_bfq",float("inf")),("trade_date","20240110"),
    ("trade_date",WHEN),("ts_code","399001.SZ"),
])
def test_source_wrong_type_null_nonfinite_date_and_object_are_rejected(column,value):
    item=source(10);item[column]=value
    with pytest.raises(DailyWaveSourceError):module.normalize_source_row(item,calculated_at=WHEN,spec=SPEC)


def test_precision_completion_and_h_source_are_preserved():
    item=source(10);item.update(close=4160.45,macd_dif_bfq=26.912,macd_dea_bfq=20.0,macd_bfq=13.824)
    result=module.normalize_source_row(item,calculated_at=WHEN,spec=SPEC)
    assert result==dict(tsCode="000001.SH",date="2024-01-10",close="4160.45",dif="26.912",dea="20",macd="13.824",completed=True)
    with pytest.raises(DailyWaveSourceError,match="尚未完成"):
        module.normalize_source_row(item,calculated_at=datetime(2024,1,10,14,tzinfo=WHEN.tzinfo),spec=SPEC)
    query=FakeQuery();query.main[0]["macd_bfq"]=999.0
    with pytest.raises(DailyWaveSourceError,match="MACD"):
        asyncio.run(service(query).build(spec=SPEC))


@pytest.mark.parametrize("change",[
    lambda rows:rows[1:], lambda rows:rows[:-1],lambda rows:rows+[rows[-1]],
    lambda rows:[dict(row,is_open=True) for row in rows],
    lambda rows:[dict(row,is_open=False) for row in rows],
    lambda rows:[dict(row,is_open=1) for row in rows],
])
def test_calendar_missing_duplicate_closed_extra_wrong_bool_rejected(change):
    # This independent fixture contains closed dates; all-open is genuinely wrong.
    query=FakeQuery(batches=[[source(9,-2.0),source(5),source(4,-2.0)]],calendar_change=change)
    with pytest.raises(DailyWaveSourceError):asyncio.run(service(query).build(spec=SPEC))


def test_empty_skips_context_calendar_and_partial_or_duplicate_rows_do_not_succeed():
    query=FakeQuery(main=[])
    result=asyncio.run(service(query).build(spec=SPEC))
    assert result.status=="empty" and len(query.calls)==1
    query=FakeQuery(main=[source(10),source(10)])
    with pytest.raises(DailyWaveSourceError,match="唯一"):
        asyncio.run(service(query).build(spec=SPEC))
    query=FakeQuery(main=[source(11),source(10)])
    with pytest.raises(DailyWaveSourceError):asyncio.run(service(query).build(spec=SPEC))
    query=FakeQuery(main=[source(10)]*801)
    with pytest.raises(DailyWaveBudgetExceeded):asyncio.run(service(query).build(spec=SPEC))


def test_output_contract_error_is_not_misclassified_as_source_error(monkeypatch):
    def broken(*args,**kwargs):
        raise DailyWaveInputError("价格候选引用了不存在的色段")
    monkeypatch.setattr(module,"build_review",broken)
    with pytest.raises(DailyWaveInputError,match="不存在的色段"):
        asyncio.run(service(FakeQuery()).build(spec=SPEC))


@pytest.mark.parametrize("deadline,expected",[(None,108.0),(105.0,105.0),(120.0,108.0)])
def test_deadline_default_earlier_and_later_values_reach_session_and_calculator(monkeypatch,deadline,expected):
    # Independent clock: the existing eight seconds starts at literal 100.
    monkeypatch.setattr(budget_module,"time",SimpleNamespace(monotonic=lambda:100.0))
    original=module.build_review
    calculation_deadlines=[]
    def build(*args,**kwargs):
        calculation_deadlines.append(kwargs["deadline"])
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"build_review",build)
    events=[]
    result=asyncio.run(service(FakeQuery(),events).build(spec=SPEC,deadline=deadline))
    assert result.status=="ready"
    assert events==[("enter",expected),"closed"]
    assert calculation_deadlines==[expected]


@pytest.mark.parametrize("deadline",[99.0,100.0])
def test_expired_deadline_stops_before_creating_a_session(monkeypatch,deadline):
    monkeypatch.setattr(budget_module,"time",SimpleNamespace(monotonic=lambda:100.0))
    events=[];query=FakeQuery()
    with pytest.raises(DailyWaveBudgetExceeded):
        asyncio.run(service(query,events).build(spec=SPEC,deadline=deadline))
    assert events==[] and query.calls==[]


@pytest.mark.parametrize("deadline",[True,"105",float("nan"),float("inf"),-float("inf")])
def test_invalid_deadline_is_rejected_before_any_read(deadline):
    events=[];query=FakeQuery()
    with pytest.raises(DailyWaveInputError,match="deadline"):
        asyncio.run(service(query,events).build(spec=SPEC,deadline=deadline))
    assert events==[] and query.calls==[]


def test_time_spent_reading_does_not_restart_the_supplied_deadline(monkeypatch):
    now=[100.0]
    monkeypatch.setattr(budget_module,"time",SimpleNamespace(monotonic=lambda:now[0]))
    class AdvancingQuery(FakeQuery):
        async def load_main_window(self,*args,**kwargs):
            result=await super().load_main_window(*args,**kwargs)
            now[0]=101.0
            return result
        async def load_context_window(self,*args,**kwargs):
            result=await super().load_context_window(*args,**kwargs)
            now[0]=102.0
            return result
        async def load_calendar(self,*args,**kwargs):
            result=await super().load_calendar(*args,**kwargs)
            now[0]=103.0
            return result
    original=module.build_review
    def build(*args,**kwargs):
        assert kwargs["deadline"]==105.0
        assert now[0]==103.0
        now[0]=104.0
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"build_review",build)
    events=[];query=AdvancingQuery()
    result=asyncio.run(service(query,events).build(spec=SPEC,deadline=105.0))
    assert result.status=="ready"
    assert events==[("enter",105.0),"closed"]
    assert [name for name,_ in query.calls]==["main","context","calendar"]


def test_deadline_reached_after_main_read_closes_without_starting_more_reads(monkeypatch):
    now=[100.0]
    monkeypatch.setattr(budget_module,"time",SimpleNamespace(monotonic=lambda:now[0]))
    class ExpiringQuery(FakeQuery):
        async def load_main_window(self,*args,**kwargs):
            result=await super().load_main_window(*args,**kwargs)
            now[0]=105.0
            return result
    events=[];query=ExpiringQuery()
    with pytest.raises(DailyWaveBudgetExceeded):
        asyncio.run(service(query,events).build(spec=SPEC,deadline=105.0))
    assert events==[("enter",105.0),"closed"]
    assert [name for name,_ in query.calls]==["main"]
