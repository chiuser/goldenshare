"""P3 step 1: real product query/cache/restore/clone, artificial input boundary only.

The reader and calendar are the sole external-source substitutes. There is no
database, App, frozen input, API call or old/new algorithm comparison. The
literal prices/DIFs have four NONE bars, then TOP DULL against March 3--4.
Additional literals follow product LLD v1 sections 4, 7, 11.3 and 12.1. The
1000-bar checks use the actual query batch budget, with an artificial calendar;
they do not claim to validate real exchange-day completeness.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
import hashlib
from types import SimpleNamespace

import pytest

from src.biz.queries.wealth.market.index_detail_xxm import query_service
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService, XxmCache
from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE, ENDPOINTS
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


DATES = ("2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07", "2025-03-10")
RAW = tuple(XxmBar(stamp, *value) for stamp, value in zip(DATES,
    ((100, 10, 9, 2), (101, 12, 11, 2), (99, 9, 10, -2),
     (100, 9, 8, 2), (102, 10, 9, 2), (103, 9.8, 8.8, 2))))
KEY = ("product-r4-snapshot-consumer-unit", "day", MAIN_SPEC.spec_hash)
REFERENCE = {"startTime": "2025-03-03", "endTime": "2025-03-04", "price": 101, "dif": 12,
             "priceAt": "2025-03-04", "difAt": "2025-03-04"}


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
    assert calc.active_structure is None


def test_product_latest_snapshot_copy_stays_independent(source_boundary):
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


def test_product_history_checkpoint_restore_stays_independent(source_boundary, monkeypatch):
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
    assert child.active_structure is None
    child.history[1][0].dif = -999
    assert entry.calculator.snapshot() == before and entry.checkpoints[3] == checkpoint_before
    assert original_budget.source_batch_rows == 1000


def test_product_incremental_load_uses_validated_snapshot(source_boundary):
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
    assert not new.structure_records
    assert new.points[:3] == old_points
    assert tuple(new.fingerprints[:3]) == old_fingerprints and len(new.fingerprints) == 5
    assert old.calculator.snapshot() == old_progress and old.points == old_points
    assert service.cache.get(KEY) is new
    assert reads == ["2025-03-05", "2025-03-07"]


def test_product_invalid_snapshot_does_not_replace_cached_result(source_boundary, monkeypatch):
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
    assert new.events[-1]["relatedStructureId"] in new.structure_records
    assert new.structure_records[new.events[-1]["relatedStructureId"]]["priceExtreme"] == 103
    assert old.calculator.snapshot() == original and old.points == before_points and old.events == before_events
    assert service.cache.get(KEY) is new
    assert reads == ["2025-03-07", "2025-03-10", "2025-03-10"]


def daily_source(monkeypatch, bars):
    """Replace only external input/context; run the actual loading and restore."""
    days = tuple(date.fromisoformat(bar.time) for bar in bars)
    source = {"bars": bars, "reads": []}

    def calendar(session, *, end):
        return tuple(day for day in days if day <= end)

    def reader(session, *, completed, check):
        check()
        source["reads"].append(completed)
        return tuple(bar for bar in source["bars"] if completed and bar.time <= completed)

    monkeypatch.setattr(query_service, "calendar_dates", calendar)
    monkeypatch.setattr(query_service, "read_daily", reader)
    service = IndexDetailXxmQueryService(cache=XxmCache())

    def load(count, *, key=KEY):
        day = days[count - 1]
        return service._load_series(None, key=key, period="day",
            now=datetime.combine(day, datetime.min.time(), CN_ZONE).replace(hour=16),
            business_date=day, remaining=lambda: None)[0]

    return service, load, source


def entry_facts(entry):
    return deepcopy((entry.calculator.snapshot(), entry.raw, entry.signature, entry.processed,
                     entry.points, entry.events, entry.structure_records, entry.fingerprints, entry.checkpoints,
                     entry.open_dates, entry.validated_through))


class CheckedCheckpoints(dict):
    def __init__(self, values):
        super().__init__(values)
        self.reads = []

    def __getitem__(self, key):
        assert key > 0, "checkpoint[0] must never be read"
        self.reads.append(key)
        return super().__getitem__(key)


@pytest.mark.parametrize("empty", [False, True])
def test_count_zero_returns_new_empty_state_without_snapshot_or_checkpoint(monkeypatch, empty):
    _, load, source = daily_source(monkeypatch, RAW)
    if empty:
        source["bars"] = ()
    entry = load(5)
    checkpoints = CheckedCheckpoints(entry.checkpoints)
    entry = replace(entry, checkpoints=checkpoints)

    def forbidden_snapshot():
        raise AssertionError("count=0 must construct empty state without reading the latest snapshot")

    monkeypatch.setattr(entry.calculator, "snapshot", forbidden_snapshot)
    checks = []
    child = entry.calculator_at(0, lambda: checks.append(True))
    assert type(child) is XxmCalculator and child is not entry.calculator
    assert child.spec is MAIN_SPEC and child.spec.algorithm_version == "xxm-direction-v0.2-r4"
    assert (child.period, child.source_identity, child.ts_code) == (
        entry.calculator.period, entry.calculator.source_identity, entry.calculator.ts_code)
    assert child.processed == 0 and child.previous is None and child.wave is None
    assert child.state == "NONE" and child.reference is None and child.history == {1: [], -1: []}
    assert child.active_structure is None
    assert not checkpoints.reads and len(checks) >= 2


@pytest.mark.parametrize("count,checkpoint_reads", [(0, []), (999, []), (1000, [1000]), (1001, [1000])])
def test_real_thousand_bar_checkpoint_boundaries(monkeypatch, count, checkpoint_reads):
    assert query_service.BUDGET.source_batch_rows == 1000
    first = date(2020, 1, 1)
    # One constant red segment: no historical red segment, no event, no pending
    # history. These literal facts determine each prefix without a second run.
    bars = tuple(XxmBar((first + timedelta(days=index)).isoformat(), 100, 10, 9, 2)
                 for index in range(1002))
    _, load, _ = daily_source(monkeypatch, bars)
    entry = load(1002)
    assert set(entry.checkpoints) == {1000}
    assert entry.checkpoints[1000]["processed"] == 1000
    assert entry.checkpoints[1000]["previous"]["time"] == bars[999].time
    checkpoints = CheckedCheckpoints(entry.checkpoints)
    entry = replace(entry, checkpoints=checkpoints)
    before = entry_facts(entry)
    checks = []
    child = entry.calculator_at(count, lambda: checks.append(True))
    assert type(child) is XxmCalculator and child.spec is MAIN_SPEC
    assert child.processed == count and child.state == "NONE" and child.reference is None
    assert child.history == {1: [], -1: []}
    assert child.active_structure is None
    if count:
        assert child.previous == bars[count - 1]
        assert child.wave.sign == 1 and child.wave.count == count
        assert child.wave.start == bars[0].time and child.wave.end == bars[count - 1].time
        assert child.wave.price == 100 and child.wave.dif == 10
        assert child.wave.price_at == bars[0].time and child.wave.dif_at == bars[0].time
    else:
        assert child.previous is None and child.wave is None
    assert checkpoints.reads == checkpoint_reads and len(checks) >= 2
    assert entry_facts(entry) == before


def test_past_prefix_and_empty_response_do_not_use_future_confirmation(source_boundary):
    _, load, _ = source_boundary
    old = load(5)
    before = IndexDetailXxmQueryService._response(old, period="day", expected=DATES[4],
        start_date=None, limit=1000, check=lambda: None)
    new = load(6)
    past = IndexDetailXxmQueryService._response(new, period="day", expected=DATES[4],
        start_date=None, limit=1000, check=lambda: None)
    assert past.model_dump() == before.model_dump()
    assert past.source.inputId == new.fingerprints[4] != new.fingerprints[5]
    assert past.dataStatus.asOf == DATES[4]
    assert past.points[-1].ordinaryState == "DULL" and past.points[-1].activeReference.model_dump() == REFERENCE
    assert [(event.type, event.route) for event in past.events] == [("DULL", "activation")]
    assert not past.structures
    empty = IndexDetailXxmQueryService._response(new, period="day", expected="2025-03-02",
        start_date=None, limit=1000, check=lambda: None)
    assert empty.dataStatus.status == "EMPTY" and empty.dataStatus.asOf is None
    assert empty.source.inputId == hashlib.sha256(b"empty").hexdigest()
    assert empty.source.startTime is None and empty.source.computedThrough is None
    assert not empty.points and not empty.events and not empty.structures


def test_increment_failure_after_real_step_preserves_old_entry(monkeypatch):
    bars = RAW + (XxmBar("2025-03-11", 104, 9.7, 8.7, 2),)
    service, load, _ = daily_source(monkeypatch, bars)
    old = load(6)
    before = entry_facts(old)
    assert old.structure_records and old.calculator.active_structure is not None
    original_step = XxmCalculator.step

    def interrupted_step(self, bar):
        result = original_step(self, bar)
        if bar.time == "2025-03-11":
            # The independent candidate has advanced, but a higher close alone
            # cannot cancel the assessing structure under LLD 3.6/RC59.
            assert self.processed == 7 and self.active_structure["status"] == "ASSESSING"
            assert self.active_structure["priceExtreme"] == 103
            assert result.events == () and result.structures == ()
            raise RuntimeError("artificial interruption after real step")
        return result

    with monkeypatch.context() as local:
        local.setattr(XxmCalculator, "step", interrupted_step)
        with pytest.raises(RuntimeError, match="artificial interruption"):
            load(7)
    assert service.cache.get(KEY) is old and entry_facts(old) == before
    new = load(7)
    assert new is not old and new.calculator.processed == 7
    assert new.calculator.state == "STRUCTURE" and new.calculator.active_structure is not None
    assert new.points[:6] == old.points and new.events == old.events
    structure_id = old.calculator.active_structure["id"]
    assert new.structure_records[structure_id]["status"] == "ASSESSING"
    assert new.structure_records[structure_id]["priceExtreme"] == 103
    assert new.calculator.wave.price == 104
    past = IndexDetailXxmQueryService._response(new, period="day", expected=DATES[5],
        start_date=None, limit=1000, check=lambda: None)
    original = IndexDetailXxmQueryService._response(old, period="day", expected=DATES[5],
        start_date=None, limit=1000, check=lambda: None)
    assert past.model_dump() == original.model_dump()
    assert past.structures[0].status == "ASSESSING" and past.structures[0].lockedAt is None
    assert service.cache.get(KEY) is new and entry_facts(old) == before


@pytest.mark.parametrize("change_origin", [False, True])
def test_source_revision_rebuilds_without_restoring_old_progress(monkeypatch, change_origin):
    service, load, source = daily_source(monkeypatch, RAW)
    old = load(5)
    before = entry_facts(old)
    source["bars"] = RAW[1:] if change_origin else (replace(RAW[0], dif=20, dea=19), *RAW[1:])

    def forbidden_snapshot():
        raise AssertionError("a revised source cannot continue the old cached progress")

    with monkeypatch.context() as local:
        local.setattr(old.calculator, "snapshot", forbidden_snapshot)
        new = load(5)
    assert new is not old and service.cache.get(KEY) is new
    assert new.calculator.processed == (4 if change_origin else 5)
    assert new.calculator.state == "DULL" and new.calculator.reference.dif == (12 if change_origin else 20)
    assert new.calculator.reference.start == (DATES[1] if change_origin else DATES[0])
    assert new.calculator.source_identity == f"day|{DATES[1] if change_origin else DATES[0]}|bfq"
    assert new.points[0]["time"] == (DATES[1] if change_origin else DATES[0])
    assert new.fingerprints[-1] != old.fingerprints[-1]
    assert entry_facts(old) == before


def test_load_entry_cache_separates_rule_connection_and_source_identity(monkeypatch, tmp_path):
    service, _, _ = daily_source(monkeypatch, RAW)
    stamp = datetime(2025, 3, 7, 16, tzinfo=CN_ZONE)
    context = SimpleNamespace(trade_date=stamp.date(), generated_at=stamp)
    monkeypatch.setattr(query_service.MarketPageContextQuery, "resolve_context", lambda *a, **k: context)

    class SessionIdentity:
        def __init__(self):
            self.bind = object()

        def get_bind(self):
            return self.bind

    session = SessionIdentity()
    actual_key = (id(session.bind), service.lake_identity, "day", MAIN_SPEC.spec_hash)
    # This is a stale cache-key fixture, not a relabelled old algorithm result.
    old_hash = "6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d"
    assert MAIN_SPEC.algorithm_version == "xxm-direction-v0.2-r4" and MAIN_SPEC.spec_hash != old_hash
    old_key = (*actual_key[:-1], old_hash)
    old = service._load_series(None, key=old_key, period="day", now=stamp,
        business_date=stamp.date(), remaining=lambda: None)[0]
    with service.load_entry(session, period="day", now=stamp) as (entry, *_):
        assert entry is not old and entry.calculator.spec is MAIN_SPEC
        assert service.cache.get(actual_key) is entry
    with service.load_entry(session, period="day", now=stamp) as (same, *_):
        assert same is entry
    other_session = SessionIdentity()
    with service.load_entry(other_session, period="day", now=stamp) as (other_connection, *_):
        assert other_connection is not entry
    # Substitute reader construction so this identity test never opens a lake.
    monkeypatch.setattr(query_service, "minute_reader", lambda root: object())
    other_source = IndexDetailXxmQueryService(lake_root=tmp_path / "other-source", cache=service.cache)
    with other_source.load_entry(session, period="day", now=stamp) as (other_origin, *_):
        assert other_origin is not entry
    assert service.cache.get(actual_key) is entry and service.cache.get(old_key) is old


def test_clone_restores_formal_identity_and_isolates_mutable_state(source_boundary):
    _, load, _ = source_boundary
    entry = load(6)
    parent = entry.calculator
    before = entry_facts(entry)
    child = clone(parent)
    assert type(child) is XxmCalculator and child is not parent
    assert child.spec is MAIN_SPEC and child.spec.algorithm_version == "xxm-direction-v0.2-r4"
    assert (child.ts_code, child.period, child.source_identity) == (parent.ts_code, parent.period, parent.source_identity)
    assert child.processed == 6 and child.state == "STRUCTURE" and child.reference.reference() == REFERENCE
    assert child.active_structure["formedAt"] == DATES[5] and child.active_structure["priceExtreme"] == 103
    child.active_structure["originalReference"]["dif"] = -999
    child.history[1][0].price = -999
    child.reference.dif = -999
    child.wave.price = 999
    assert entry_facts(entry) == before


def test_clone_rejects_wrong_source_snapshot_without_changing_parent(source_boundary, monkeypatch):
    _, load, _ = source_boundary
    entry = load(5)
    before = entry_facts(entry)
    bad = deepcopy(entry.calculator.snapshot())
    bad["sourceIdentity"] = "different-artificial-source"
    with monkeypatch.context() as local:
        local.setattr(entry.calculator, "snapshot", lambda: deepcopy(bad))
        with pytest.raises(ValueError):
            clone(entry.calculator)
    assert entry_facts(entry) == before


@pytest.mark.parametrize("period", ["day", "m60", "m90", "m120"])
def test_historical_prefix_and_zero_return_to_dull_clone_in_every_period(monkeypatch, period):
    # LLD 3.6/4.1 and RC47/52: bar6 forms a bottom structure; bar7 is
    # zero, its -8.8 -> -9.0 return exceeds 1%, so it returns directly
    # to DULL despite C100 > previous valley99. Zero never adds a bar.
    values = ((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2),
              (98, -9, -8, -2), (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2),
              (100, -9, -9, 0))
    days = tuple(date.fromisoformat(stamp) for stamp in DATES) + (date(2025, 3, 11),)
    if period == "day":
        stamps = tuple(day.isoformat() for day in days)
    else:
        stamps = tuple(datetime.combine(day, endpoint, CN_ZONE).isoformat()
                       for day in days for endpoint in ENDPOINTS[int(period[1:])])[:7]
    bars = tuple(XxmBar(stamp, *value) for stamp, value in zip(stamps, values, strict=True))
    monkeypatch.setattr(query_service, "calendar_dates",
                        lambda session, *, end: tuple(day for day in days if day <= end))
    monkeypatch.setattr(query_service, "read_daily", lambda session, *, completed, check: bars)
    monkeypatch.setattr(query_service, "read_minutes", lambda *a, **k: bars)
    service = IndexDetailXxmQueryService(cache=XxmCache())
    service.reader = SimpleNamespace(history_source_signature=lambda request, *, dataset: ("artificial", dataset))

    def load(count):
        stamp = stamps[count - 1]
        now = (datetime.combine(date.fromisoformat(stamp), datetime.min.time(), CN_ZONE).replace(hour=16)
               if period == "day" else datetime.fromisoformat(stamp) + timedelta(minutes=1))
        return service._load_series(None, key=("four-period-prefix", period, MAIN_SPEC.spec_hash),
            period=period, now=now, business_date=now.date(), remaining=lambda: None)[0]

    old = load(6)
    before = entry_facts(old)
    full = load(7)
    assert entry_facts(old) == before
    assert full.calculator.processed == 7 and full.calculator.state == "DULL"
    assert full.calculator.wave.sign == -1 and full.calculator.wave.count == 3
    assert full.calculator.previous.hist == 0 and full.calculator.active_structure is None
    assert full.calculator.reference.price == 99 and full.calculator.reference.dif == -11
    assert [(event["type"], event["route"]) for event in full.events] == [
        ("DULL", "activation"), ("STRUCTURE", "dif_turn"), ("DULL", "dif_return")]
    structure = next(iter(full.structure_records.values()))
    assert structure["status"] == "DISAPPEARED" and structure["disappearedAt"] == stamps[6]
    assert structure["disappearanceReason"] == "dif_return"

    # Actual prefix replay returns the earlier active structure, not the
    # latest DULL state or the later disappearance fact.
    past = full.calculator_at(6, lambda: None)
    assert type(past) is XxmCalculator and past.spec is MAIN_SPEC
    assert past.processed == 6 and past.previous.time == stamps[5]
    assert past.state == "STRUCTURE" and past.active_structure["status"] == "ASSESSING"
    assert past.active_structure["priceExtreme"] == 97
    assert past.active_structure["disappearedAt"] is None
    assert past.snapshot() == old.calculator.snapshot()
    response = service._response(full, period=period, expected=stamps[5], start_date=None,
        limit=1000, check=lambda: None)
    assert response.structures[0].status == "ASSESSING"
    assert response.structures[0].disappearedAt is None
    assert response.structures[0].lockedAt is None

    full_before = entry_facts(full)
    child = clone(full.calculator)
    assert type(child) is XxmCalculator and child.period == period and child.spec is MAIN_SPEC
    assert child.state == "DULL" and child.active_structure is None and child.previous.hist == 0
    child.reference.dif = 999
    child.history[-1][0].price = 999
    child.wave.price = 999
    assert entry_facts(full) == full_before and entry_facts(old) == before
