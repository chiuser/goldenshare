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
