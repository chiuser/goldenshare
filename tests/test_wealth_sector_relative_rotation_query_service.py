from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from time import perf_counter

import pytest
from pydantic import ValidationError

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
    SectorHierarchyUnavailableError,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query_service import (
    SectorAnalysisMetaFacts,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_snapshot_query_service import (
    SectorMomentumSnapshotPreparation,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query import (
    SectorMomentumQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_relative_rotation_query_service import (
    SectorRelativeRotationQueryService,
)
from src.biz.schemas.wealth.market.sector_relative_rotation import (
    SectorRelativeRotationResultsResponseDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    SectorMomentumFactVersionMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDailyFact,
    SectorDataQueryError,
    SectorDateAvailabilityFact,
    SectorSelectionInvalidError,
    SectorTradingDateResolution,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_calculator import (
    SectorRelativeRotationCalculator,
)


OPEN_DATES = tuple(date(2026, 7, 1) + timedelta(days=index) for index in range(30))
TARGET_DATE = OPEN_DATES[-1]
CODES = ("BK1001.DC", "BK1002.DC", "BK1003.DC", "BK1004.DC")


def _context() -> MarketPageContext:
    return MarketPageContext(
        market="CN_A",
        trade_date=TARGET_DATE,
        prev_trade_date=OPEN_DATES[-2],
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 7, 30, 20, 1, tzinfo=timezone.utc),
        source="default",
    )


def _hierarchy() -> SectorHierarchySnapshot:
    nodes = tuple(
        SectorHierarchyNode(
            sector_code=code,
            sector_name=f"行业{index}",
            industry_level=1,
            parent_sector_code=None,
            parent_sector_name=None,
            root_sector_code=code,
            root_sector_name=f"行业{index}",
            hierarchy_path=f"行业{index}",
            display_order=index,
            is_leaf=True,
            baseline_version="v1",
        )
        for index, code in enumerate(CODES, start=1)
    )
    return SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={None: nodes},
    )


def _availability(
    trade_date: date,
    availability: str = "COMPLETE",
    valid_count: int = 4,
) -> SectorDateAvailabilityFact:
    return SectorDateAvailabilityFact(
        trade_date=trade_date,
        availability=availability,  # type: ignore[arg-type]
        expected_sector_count=4,
        valid_sector_count=valid_count,
    )


def _preparation(
    *,
    missing: bool = False,
    delayed: bool = False,
) -> SectorMomentumSnapshotPreparation:
    expected = _availability(
        TARGET_DATE,
        "MISSING" if missing else ("PARTIAL" if delayed else "COMPLETE"),
        0 if missing else (3 if delayed else 4),
    )
    observed = expected if not delayed else _availability(OPEN_DATES[-2], "COMPLETE", 4)
    return SectorMomentumSnapshotPreparation(
        context=_context(),
        hierarchy=_hierarchy(),
        resolution=SectorTradingDateResolution(
            coverage_start_date=OPEN_DATES[0],
            coverage_end_date=TARGET_DATE,
            expected=expected,
            observed=observed,
            is_explicit=missing,
        ),
        scope="LEVEL_1",
        period=5,
        level1_code=None,
        level2_code=None,
        pool=_hierarchy().nodes,
    )


class _ContextQuery:
    def __init__(self) -> None:
        self.calls = 0

    def resolve_context(self, _session, *, market, requested_trade_date):
        self.calls += 1
        assert market == "CN_A"
        assert requested_trade_date is None
        return _context()


class _MetaService:
    def load(self, _session, *, market):
        assert market == "CN_A"
        return SectorAnalysisMetaFacts(
            context=_context(),
            hierarchy=_hierarchy(),
            coverage_start_date=OPEN_DATES[0],
            coverage_end_date=TARGET_DATE,
            trade_dates=tuple(_availability(item) for item in OPEN_DATES),
        )


class _SnapshotService:
    def __init__(
        self,
        *,
        preparation: SectorMomentumSnapshotPreparation | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.preparation = preparation or _preparation()
        self.failure = failure
        self.calls = 0

    def prepare_for_context(self, _session, **kwargs):
        self.calls += 1
        assert kwargs["context"] == _context()
        assert kwargs["expected_hierarchy_version"] == "v1"
        assert kwargs["date_errors_are_selection"] is True
        if self.failure is not None:
            raise self.failure
        return self.preparation


class _MomentumQuery:
    def __init__(
        self,
        *,
        missing_facts: set[tuple[str, date]] | None = None,
        no_facts: bool = False,
    ) -> None:
        self.missing_facts = missing_facts or set()
        self.no_facts = no_facts
        self.open_calls = 0
        self.fact_calls = 0
        self.requested_count: int | None = None

    def load_open_dates(self, _session, *, end_date, count):
        self.open_calls += 1
        self.requested_count = count
        return tuple(item for item in OPEN_DATES if item <= end_date)[-count:]

    def load_facts(self, _session, *, sector_codes, start_date, end_date):
        self.fact_calls += 1
        if self.no_facts:
            return ()
        slopes = dict(zip(CODES, (4, 3, 2, 1), strict=True))
        return tuple(
            SectorDailyFact(
                sector_code=code,
                trade_date=trade_date,
                close=Decimal(100 + slopes[code] * index),
                pct_change=Decimal(slopes[code]),
            )
            for index, trade_date in enumerate(OPEN_DATES)
            for code in sector_codes
            if start_date <= trade_date <= end_date
            and (code, trade_date) not in self.missing_facts
        )


class _CountingCalculator(SectorMomentumCalculator):
    def __init__(self) -> None:
        self.calculate_for_dates_calls = 0
        self.rank_strength_calls = 0
        self.rank_selected_calls = 0

    def calculate_for_dates(self, **kwargs):
        self.calculate_for_dates_calls += 1
        return super().calculate_for_dates(**kwargs)

    def rank_strength(self, return_facts):
        self.rank_strength_calls += 1
        return super().rank_strength(return_facts)

    def rank_selected(self, return_facts, *, sector_code):
        self.rank_selected_calls += 1
        return super().rank_selected(return_facts, sector_code=sector_code)


class _CountingRelativeCalculator(SectorRelativeRotationCalculator):
    def __init__(self) -> None:
        self.current_calls = 0
        self.trail_calls = 0
        self.current_point_count = 0
        self.trail_point_count = 0

    def calculate_current_snapshot(self, **kwargs):
        self.current_calls += 1
        points = super().calculate_current_snapshot(**kwargs)
        self.current_point_count += len(points)
        return points

    def calculate_selected_trail(self, **kwargs):
        self.trail_calls += 1
        points = super().calculate_selected_trail(**kwargs)
        self.trail_point_count += len(points)
        return points


def _service(
    *,
    snapshot_service: _SnapshotService | None = None,
    query: _MomentumQuery | None = None,
    calculator: _CountingCalculator | None = None,
    relative_calculator: _CountingRelativeCalculator | None = None,
):
    context_query = _ContextQuery()
    momentum_query = query or _MomentumQuery()
    momentum_calculator = calculator or _CountingCalculator()
    rotation_calculator = relative_calculator or _CountingRelativeCalculator()
    return (
        SectorRelativeRotationQueryService(
            context_query=context_query,  # type: ignore[arg-type]
            meta_service=_MetaService(),  # type: ignore[arg-type]
            snapshot_service=snapshot_service or _SnapshotService(),  # type: ignore[arg-type]
            momentum_query=momentum_query,  # type: ignore[arg-type]
            momentum_calculator=momentum_calculator,
            relative_calculator=rotation_calculator,
        ),
        context_query,
        momentum_query,
        momentum_calculator,
        rotation_calculator,
    )


def _build_results(service, **overrides):
    kwargs = {
        "market": "CN_A",
        "trade_date": TARGET_DATE,
        "scope": "LEVEL_1",
        "level1_code": None,
        "level2_code": None,
        "period": 5,
        "trail_length": 20,
        "sector_code": None,
        "hierarchy_version": "v1",
        "debug": True,
    }
    kwargs.update(overrides)
    return service.build_results(object(), **kwargs)  # type: ignore[arg-type]


def test_meta_returns_frozen_formula_and_defaults() -> None:
    service, *_rest = _service()
    response = service.build_meta(object(), market="CN_A")  # type: ignore[arg-type]

    assert response.status == "READY"
    assert response.formula.model_dump() == {
        "formulaKey": "sector-relative-rotation",
        "formulaVersion": 1,
        "basisFormulaKey": "sector-cross-sectional-momentum",
        "basisFormulaVersion": 1,
        "periods": [5, 10, 20, 30],
        "improvementLookbackDays": 5,
        "trailLengths": [20, 30, 60],
        "minimumGroupSize": 3,
        "scopes": [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ],
        "xDomain": (0, 100),
        "xSplit": 50,
        "ySplit": 0,
    }
    assert response.defaults.model_dump() == {
        "scope": "LEVEL_1",
        "period": 20,
        "trailLength": 20,
        "quadrantFilter": "ALL",
    }


def test_results_read_once_and_materialize_only_current_snapshot_and_selected_trail() -> (
    None
):
    service, context_query, query, calculator, relative_calculator = _service()
    response = _build_results(service)

    assert response.status == "READY"
    assert response.analysis is not None
    assert response.analysis.totalCount == 4
    assert response.analysis.currentCalculableCount == 4
    assert response.analysis.plottableCount == 4
    assert response.analysis.selectedSectorCode == "BK1001.DC"
    assert response.analysis.selectedTrail.sectorCode == "BK1001.DC"
    assert response.analysis.selectedTrail.dateSlotCount == 20
    assert response.analysis.selectedTrail.points[-1].tradeDate == TARGET_DATE
    assert context_query.calls == 1
    assert query.open_calls == query.fact_calls == 1
    assert query.requested_count == 30
    assert calculator.calculate_for_dates_calls == 1
    assert calculator.rank_strength_calls == 2
    assert calculator.rank_selected_calls == 23
    assert relative_calculator.current_calls == 1
    assert relative_calculator.current_point_count == 4
    assert relative_calculator.trail_calls == 1
    assert relative_calculator.trail_point_count == 20


def test_missing_current_and_comparison_facts_keep_precise_reasons_and_slots() -> None:
    current_missing = ("BK1004.DC", TARGET_DATE)
    comparison_window_missing = ("BK1003.DC", OPEN_DATES[-11])
    query = _MomentumQuery(missing_facts={current_missing, comparison_window_missing})
    service, *_rest = _service(query=query)
    response = _build_results(service, sector_code="BK1004.DC")

    assert response.status == "READY"
    assert response.analysis is not None
    by_code = {item.sectorCode: item for item in response.analysis.items}
    assert by_code["BK1004.DC"].currentMissingReason == "DATE_MISSING"
    assert by_code["BK1004.DC"].coordinateStatus == "UNAVAILABLE"
    assert by_code["BK1003.DC"].currentMissingReason is None
    assert by_code["BK1003.DC"].comparisonMissingReason == "DATE_MISSING"
    assert response.analysis.selectedTrail.dateSlotCount == 20
    assert (
        response.analysis.selectedTrail.points[-1].currentMissingReason
        == "DATE_MISSING"
    )


def test_no_current_calculable_facts_returns_empty_without_analysis() -> None:
    service, _context, query, calculator, relative_calculator = _service(
        query=_MomentumQuery(no_facts=True)
    )
    response = _build_results(service)

    assert response.status == "EMPTY"
    assert response.exceptionCode == "SA_SOURCE_EMPTY"
    assert response.analysis is None
    assert query.open_calls == query.fact_calls == 1
    assert calculator.calculate_for_dates_calls == 1
    assert calculator.rank_strength_calls == 2
    assert calculator.rank_selected_calls == 0
    assert relative_calculator.current_calls == 1
    assert relative_calculator.current_point_count == 4
    assert relative_calculator.trail_calls == 0


def test_explicit_missing_date_stops_before_calendar_or_fact_reads() -> None:
    snapshot_service = _SnapshotService(preparation=_preparation(missing=True))
    service, _context, query, calculator, relative_calculator = _service(
        snapshot_service=snapshot_service
    )
    response = _build_results(service)

    assert response.status == "EMPTY"
    assert query.open_calls == query.fact_calls == 0
    assert calculator.calculate_for_dates_calls == 0
    assert calculator.rank_strength_calls == 0
    assert calculator.rank_selected_calls == 0
    assert relative_calculator.current_calls == 0
    assert relative_calculator.trail_calls == 0


def test_delayed_date_uses_observed_day_as_snapshot_and_trail_end() -> None:
    snapshot_service = _SnapshotService(preparation=_preparation(delayed=True))
    service, *_rest = _service(snapshot_service=snapshot_service)
    response = _build_results(service, trade_date=None)

    assert response.status == "DELAYED"
    assert response.analysis is not None
    assert response.tradingDay.observedTradeDate == OPEN_DATES[-2]
    assert response.analysis.selectedTrail.points[-1].tradeDate == OPEN_DATES[-2]


def test_explicit_selection_outside_pool_stops_before_window_reads() -> None:
    service, _context, query, calculator, relative_calculator = _service()

    with pytest.raises(SectorSelectionInvalidError):
        _build_results(service, sector_code="BK9999.DC")

    assert query.open_calls == query.fact_calls == 0
    assert calculator.calculate_for_dates_calls == 0
    assert calculator.rank_strength_calls == 0
    assert calculator.rank_selected_calls == 0
    assert relative_calculator.current_calls == 0
    assert relative_calculator.trail_calls == 0


def test_version_and_scope_errors_are_not_hidden_by_safe_error_shell() -> None:
    for failure in (
        SectorMomentumFactVersionMismatchError("stale"),
        SectorSelectionInvalidError("invalid date"),
    ):
        service, *_rest = _service(snapshot_service=_SnapshotService(failure=failure))
        with pytest.raises(type(failure)):
            _build_results(service)


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (SectorHierarchyUnavailableError("sensitive"), "SA_HIERARCHY_UNAVAILABLE"),
        (RuntimeError("SELECT secret"), "SA_QUERY_FAILED"),
    ),
)
def test_internal_failures_return_safe_error_shells(failure, expected_code) -> None:
    service, *_rest = _service(snapshot_service=_SnapshotService(failure=failure))
    response = _build_results(service)

    assert response.status == "ERROR"
    assert response.exceptionCode == expected_code
    assert response.analysis is None
    assert "SELECT" not in (response.message or "")


def test_strict_schema_rejects_counts_sort_coordinates_and_trail_tampering() -> None:
    service, *_rest = _service()
    response = _build_results(service)

    mutations = []
    payload = response.model_dump()
    payload["analysis"]["plottableCount"] -= 1
    mutations.append(payload)
    payload = response.model_dump()
    payload["analysis"]["items"] = list(reversed(payload["analysis"]["items"]))
    mutations.append(payload)
    payload = response.model_dump()
    payload["analysis"]["items"][0]["percentileDelta5d"] = None
    mutations.append(payload)
    payload = response.model_dump()
    payload["analysis"]["selectedTrail"]["dateSlotCount"] -= 1
    mutations.append(payload)
    payload = response.model_dump()
    payload["analysis"]["selectedTrail"]["points"][-1]["tradeDate"] = OPEN_DATES[-2]
    mutations.append(payload)
    payload = response.model_dump()
    payload["analysis"]["items"][0]["rotationStatus"] = "WEAK_NOT_IMPROVING"
    mutations.append(payload)
    payload = response.model_dump()
    payload["analysis"]["selectedTrail"]["points"][0]["returnPct"] = None
    mutations.append(payload)

    for mutation in mutations:
        with pytest.raises(ValidationError):
            SectorRelativeRotationResultsResponseDto.model_validate(mutation)


def test_maximum_sparse_core_compute_and_json_p95_stays_within_in_memory_budget() -> (
    None
):
    open_dates = tuple(date(2026, 4, 1) + timedelta(days=index) for index in range(95))
    target_date = open_dates[-1]
    codes = tuple(f"BK{3000 + index:04d}.DC" for index in range(337))
    nodes = tuple(
        SectorHierarchyNode(
            sector_code=code,
            sector_name=f"三级行业{index:03d}",
            industry_level=3,
            parent_sector_code=None,
            parent_sector_name=None,
            root_sector_code=code,
            root_sector_name=f"三级行业{index:03d}",
            hierarchy_path=f"三级行业{index:03d}",
            display_order=index,
            is_leaf=True,
            baseline_version="maximum-v1",
        )
        for index, code in enumerate(codes)
    )
    hierarchy = SectorHierarchySnapshot(
        baseline_version="maximum-v1",
        published_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={None: nodes},
    )
    context = MarketPageContext(
        market="CN_A",
        trade_date=target_date,
        prev_trade_date=open_dates[-2],
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 7, 4, 20, 1, tzinfo=timezone.utc),
        source="default",
    )
    complete = SectorDateAvailabilityFact(
        trade_date=target_date,
        availability="COMPLETE",
        expected_sector_count=len(codes),
        valid_sector_count=len(codes),
    )
    preparation = SectorMomentumSnapshotPreparation(
        context=context,
        hierarchy=hierarchy,
        resolution=SectorTradingDateResolution(
            coverage_start_date=open_dates[0],
            coverage_end_date=target_date,
            expected=complete,
            observed=complete,
            is_explicit=True,
        ),
        scope="LEVEL_3",
        period=30,
        level1_code=None,
        level2_code=None,
        pool=nodes,
    )
    facts = tuple(
        SectorDailyFact(
            sector_code=code,
            trade_date=trade_date,
            close=Decimal(100 + code_index) + Decimal(date_index),
            pct_change=Decimal("1"),
        )
        for date_index, trade_date in enumerate(open_dates)
        for code_index, code in enumerate(codes)
    )

    class LargeContextQuery:
        def resolve_context(self, _session, **_kwargs):
            return context

    class LargeSnapshotService:
        def prepare_for_context(self, _session, **_kwargs):
            return preparation

    class LargeMomentumQuery:
        def load_open_dates(self, _session, *, count, **_kwargs):
            assert count == 95
            return open_dates

        def load_facts(self, _session, **_kwargs):
            return facts

    momentum_calculator = _CountingCalculator()
    relative_calculator = _CountingRelativeCalculator()
    service = SectorRelativeRotationQueryService(
        context_query=LargeContextQuery(),  # type: ignore[arg-type]
        snapshot_service=LargeSnapshotService(),  # type: ignore[arg-type]
        momentum_query=LargeMomentumQuery(),  # type: ignore[arg-type]
        momentum_calculator=momentum_calculator,
        relative_calculator=relative_calculator,
    )
    # This is an in-memory core budget only. It intentionally excludes auth,
    # SQL execution, result transfer, and SQLAlchemy row materialization.
    durations = []
    for _index in range(20):
        started = perf_counter()
        response = service.build_results(
            object(),  # type: ignore[arg-type]
            market="CN_A",
            trade_date=target_date,
            scope="LEVEL_3",
            level1_code=None,
            level2_code=None,
            period=30,
            trail_length=60,
            sector_code=None,
            hierarchy_version="maximum-v1",
            debug=False,
        )
        response.model_dump_json()
        durations.append(perf_counter() - started)
        assert response.status == "READY"

    assert sorted(durations)[18] <= 0.4
    assert momentum_calculator.calculate_for_dates_calls == 20
    assert momentum_calculator.rank_strength_calls == 40
    assert momentum_calculator.rank_selected_calls == 20 * 63
    assert relative_calculator.current_calls == 20
    assert relative_calculator.current_point_count == 20 * 337
    assert relative_calculator.trail_calls == 20
    assert relative_calculator.trail_point_count == 20 * 60


def test_open_date_window_accepts_95_but_rejects_96() -> None:
    class SessionStub:
        def scalars(self, _statement):
            class Result:
                @staticmethod
                def all():
                    return tuple(reversed(OPEN_DATES))

            return Result()

    assert len(
        SectorMomentumQuery.load_open_dates(
            SessionStub(),  # type: ignore[arg-type]
            end_date=TARGET_DATE,
            count=95,
        )
    ) == len(OPEN_DATES)
    with pytest.raises(SectorDataQueryError):
        SectorMomentumQuery.load_open_dates(
            SessionStub(),  # type: ignore[arg-type]
            end_date=TARGET_DATE,
            count=96,
        )
