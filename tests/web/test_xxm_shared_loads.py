from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from src.biz.queries.wealth.market.index_detail_xxm.shared_loads import SharedLoads


def test_waiters_share_work_without_a_completed_flight_becoming_a_stale_cache():
    loads = SharedLoads(max_entries=2)
    entered, release, waiting = Event(), Event(), Event()
    calls = []
    def loader():
        calls.append(1); entered.set()
        assert release.wait(2)
        return object()
    def waiter_budget():
        waiting.set()
        return 2
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(loads.load, ("day",), loader, lambda: 2)
        assert entered.wait(2)
        second = pool.submit(loads.load, ("day",), loader, waiter_budget)
        assert waiting.wait(2)
        release.set()
        assert first.result() is second.result()
    assert calls == [1] and not loads._pending
    newer = loads.load(("day",), lambda: "new source revision", lambda: 2)
    assert newer == "new source revision"


def test_failed_shared_work_is_propagated_and_can_be_retried():
    loads = SharedLoads(max_entries=2)
    entered, release, waiting = Event(), Event(), Event()
    def fail():
        entered.set(); assert release.wait(2)
        raise ValueError("source gap")
    def waiter_budget():
        waiting.set(); return 2
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(loads.load, (1,), fail, lambda: 2)
        assert entered.wait(2)
        second = pool.submit(loads.load, (1,), fail, waiter_budget)
        assert waiting.wait(2)
        release.set()
        for result in (first, second):
            with pytest.raises(ValueError, match="source gap"):
                result.result()
    assert not loads._pending
    assert loads.load((1,), lambda: 42, lambda: 2) == 42


def test_timed_out_waiter_does_not_cancel_the_leader_or_occupy_another_flight():
    loads = SharedLoads(max_entries=1)
    entered, release = Event(), Event()
    def loader():
        entered.set(); assert release.wait(2)
        return 42
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(loads.load, (1,), loader, lambda: 2)
        assert entered.wait(2)
        with pytest.raises(TimeoutError):
            loads.load((1,), lambda: pytest.fail("must join"), lambda: .001)
        with pytest.raises(TimeoutError, match="等待数"):
            loads.load((2,), lambda: pytest.fail("must reject capacity"), lambda: 2)
        release.set()
        assert first.result() == 42
    assert loads.load((2,), lambda: 43, lambda: 2) == 43


@pytest.mark.parametrize('second_fails', [False, True])
def test_product_shared_loads_separate_codes_with_identical_input(monkeypatch, second_fails):
    """Real public query/flights/core; only source and market context are isolated."""
    from datetime import date, datetime
    from threading import Barrier
    from types import SimpleNamespace
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
    from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE, XxmSourceError
    from goldenshare_technical_indicators.xxm.types import XxmBar

    codes = ('000001.SH', '399001.SZ')
    dates = ('2025-03-03','2025-03-04','2025-03-05','2025-03-06','2025-03-07','2025-03-10')
    values = ((100,10,2),(101,12,2),(99,9,-2),(100,9,2),(102,10,2),(103,9.8,2))
    bars = tuple(XxmBar(stamp,c,d,d-h/2,h) for stamp,(c,d,h) in zip(dates,values,strict=True))
    now = datetime(2025,3,10,20,tzinfo=CN_ZONE)
    context = SimpleNamespace(trade_date=now.date(), generated_at=now)

    def resolve_context(self, session, *, market, requested_trade_date, now):
        assert market == 'CN_A' and requested_trade_date is None
        return context

    def calendar(session, *, start, end):
        return tuple(date.fromisoformat(stamp) for stamp in dates
                     if start <= date.fromisoformat(stamp) <= end)

    def read_daily(session, *, ts_code, completed, check):
        assert ts_code in codes and completed == '2025-03-10'
        check()
        if second_fails and ts_code == codes[1]:
            raise XxmSourceError('isolated second-code source failure')
        return bars

    class SessionIdentity:
        bind = object()

        def get_bind(self):
            return self.bind

    monkeypatch.setattr(q.MarketPageContextQuery, 'resolve_context', resolve_context)
    monkeypatch.setattr(q, 'calendar_dates', calendar)
    monkeypatch.setattr(q, 'read_daily', read_daily)
    barrier = Barrier(2)
    called = []
    original = q.IndexDetailXxmQueryService._load_series

    def load_series(self, session, *, ts_code, key, period, now, business_date, remaining,
                    window_rows=None, requested_end=None, context=None):
        called.append(ts_code)
        # Without code in the public flight key, only one leader reaches this
        # real loading boundary and the barrier fails instead of hiding reuse.
        barrier.wait(timeout=2)
        return original(self, session, ts_code=ts_code, key=key, period=period, now=now,
                        business_date=business_date, remaining=remaining,
                        window_rows=window_rows, requested_end=requested_end, context=context)

    monkeypatch.setattr(q.IndexDetailXxmQueryService, '_load_series', load_series)
    service = q.IndexDetailXxmQueryService(cache=q.XxmCache())

    def load(code):
        with service.load_entry(SessionIdentity(), ts_code=code, period='day', now=now) as result:
            return result[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = [pool.submit(load, code) for code in codes]
        first = left.result(timeout=3)
        if second_fails:
            with pytest.raises(q.XxmQueryError) as error:
                right.result(timeout=3)
            assert error.value.code == 'XXM_SOURCE_CONTRACT_INVALID'
        else:
            second = right.result(timeout=3)
            assert first is not second and first.raw == second.raw
            assert first.fingerprints == second.fingerprints and first.events and second.events
            assert {event['id'] for event in first.events}.isdisjoint(event['id'] for event in second.events)
    assert sorted(called) == sorted(codes) and not service.cache.loads._pending
    first_key = next(key for key in service.cache.entries if key[-1] == codes[0])
    assert service.cache.get(first_key) is first and first.calculator.ts_code == codes[0]
