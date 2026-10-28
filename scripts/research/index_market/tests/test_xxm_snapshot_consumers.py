"""R4-17: real r2 query/cache/restore, artificial input boundary only.

The reader and calendar are the sole external-source substitutes. There is no
database, App, frozen input, API call or r2/r4 comparison in this module. The
literal prices/DIFs have four NONE bars, then TOP DULL against March 3--4.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime

import pytest

from src.biz.queries.wealth.market.index_detail_xxm import query_service
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService, XxmCache
from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


DATES = ("2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07", "2025-03-10")
RAW = tuple(XxmBar(stamp, *value) for stamp, value in zip(DATES,
    ((100, 10, 9, 2), (101, 12, 11, 2), (99, 9, 10, -2),
     (100, 9, 8, 2), (102, 10, 9, 2), (103, 9.8, 8.8, 2))))
KEY = ("r2-snapshot-consumer-unit", "day")
REFERENCE = {"startTime": "2025-03-03", "endTime": "2025-03-04", "price": 101, "dif": 12}


@pytest.fixture
def source_boundary(monkeypatch):
    reads = []
    def calendar(session, *, end):
        assert session is None
        return tuple(date.fromisoformat(s) for s in DATES if date.fromisoformat(s) <= end)
    def reader(session, *, completed, check):
        assert session is None and completed in DATES
        check()
        reads.append(completed)
        return tuple(b for b in RAW if b.time <= completed)
    monkeypatch.setattr(query_service, "calendar_dates", calendar)
    monkeypatch.setattr(query_service, "read_daily", reader)
    service = IndexDetailXxmQueryService(cache=XxmCache())
    def load(count):
        day = date.fromisoformat(DATES[count - 1])
        return service._load_series(None, key=KEY, period="day",
            now=datetime(day.year, day.month, day.day, 16, tzinfo=CN_ZONE),
            business_date=day, remaining=lambda: None)[0]
    return service, load, reads


def assert_fifth_bar_dull(calc):
    assert calc.processed == 5 and calc.previous.time == "2025-03-07"
    assert calc.state == "DULL" and calc.wave.start == "2025-03-06"
    assert calc.wave.count == 2 and calc.wave.price == 102 and calc.wave.dif == 10
    assert calc.reference.reference() == REFERENCE
    assert calc.pending is None and calc.pending_bottom_history is None and calc.pending_rearm is None


def test_r2_latest_snapshot_copy_stays_independent(source_boundary):
    _, load, reads = source_boundary
    entry = load(5)
    before = deepcopy(entry.calculator.snapshot())
    returned_points = deepcopy(entry.points)
    child = entry.calculator_at(5, lambda: None)
    assert_fifth_bar_dull(child)
    assert [p["ordinaryState"] for p in entry.points] == ["NONE", "NONE", "NONE", "NONE", "DULL"]
    assert [(e["type"], e["route"]) for e in entry.events] == [("DULL", "activation")]
    assert child is not entry.calculator
    child.wave.price = 999
    child.reference.dif = -999
    child.history[1][0].price = -999
    assert entry.calculator.snapshot() == before and entry.points == returned_points
    assert reads == ["2025-03-07"]


def test_r2_history_checkpoint_restore_stays_independent(source_boundary, monkeypatch):
    # Only this test replaces the query module's batch interval. Runtime and
    # source-reader budgets remain unchanged; five literal bars reach offset=3.
    original_budget = query_service.BUDGET
    monkeypatch.setattr(query_service, "BUDGET", replace(original_budget, source_batch_rows=3))
    _, load, _ = source_boundary
    entry = load(5)
    checkpoint = entry.checkpoints[3]
    assert checkpoint["processed"] == 3 and checkpoint["previous"]["time"] == "2025-03-05"
    assert checkpoint["wave"]["sign"] == -1 and checkpoint["wave"]["count"] == 1
    before = deepcopy(entry.calculator.snapshot())
    checkpoint_before = deepcopy(checkpoint)
    child = entry.calculator_at(4, lambda: None)
    assert child.processed == 4 and child.previous.time == "2025-03-06"
    assert child.state == "NONE" and child.reference is None
    assert child.wave.sign == 1 and child.wave.start == "2025-03-06" and child.wave.count == 1
    assert child.wave.price == 100 and child.wave.dif == 9
    assert child.history[1][0].reference() == REFERENCE
    assert child.pending is None and child.pending_bottom_history is None and child.pending_rearm is None
    child.history[1][0].dif = -999
    assert entry.calculator.snapshot() == before and entry.checkpoints[3] == checkpoint_before
    assert original_budget.source_batch_rows == 1000


def test_r2_incremental_load_uses_validated_snapshot(source_boundary):
    service, load, reads = source_boundary
    old = load(3)
    old_progress = deepcopy(old.calculator.snapshot())
    old_points = deepcopy(old.points)
    old_fingerprints = tuple(old.fingerprints)
    assert old.calculator.processed == 3 and old.calculator.wave.sign == -1
    new = load(5)
    assert new is not old and new.calculator is not old.calculator
    assert_fifth_bar_dull(new.calculator)
    assert [p["time"] for p in new.points] == list(DATES[:5])
    assert len(new.events) == 1 and new.events[0]["type"] == "DULL"
    assert new.events[0]["eventReference"] == REFERENCE
    assert not new.histories and not new.bottom_histories and not new.rearm_records
    assert new.points[:3] == old_points
    assert tuple(new.fingerprints[:3]) == old_fingerprints and len(new.fingerprints) == 5
    assert old.calculator.snapshot() == old_progress and old.points == old_points
    assert service.cache.get(KEY) is new
    assert reads == ["2025-03-05", "2025-03-07"]


def test_r2_invalid_snapshot_does_not_replace_cached_result(source_boundary, monkeypatch):
    service, load, reads = source_boundary
    old = load(5)
    original = deepcopy(old.calculator.snapshot())
    before_points, before_events = deepcopy(old.points), deepcopy(old.events)
    bad = deepcopy(original)
    bad["reference"] = None  # Corrupt only the copied input; real restore must reject DULL without a reference.
    with monkeypatch.context() as local:
        local.setattr(old.calculator, "snapshot", lambda: deepcopy(bad))
        with pytest.raises(ValueError):
            load(6)
    assert service.cache.get(KEY) is old
    assert old.calculator.snapshot() == original
    assert old.points == before_points and old.events == before_events
    new = load(6)
    assert new is not old and new.calculator.processed == 6
    assert new.calculator.state == "STRUCTURE" and new.calculator.reference.reference() == REFERENCE
    assert [(e["type"], e["route"]) for e in new.events] == [("DULL", "activation"), ("STRUCTURE", "dif_turn")]
    assert new.events[-1]["relatedTopHistoryId"] in new.histories
    assert new.histories[new.events[-1]["relatedTopHistoryId"]]["pricePeak"] == 103
    assert old.calculator.snapshot() == original and old.points == before_points and old.events == before_events
    assert service.cache.get(KEY) is new
    assert reads == ["2025-03-07", "2025-03-10", "2025-03-10"]
