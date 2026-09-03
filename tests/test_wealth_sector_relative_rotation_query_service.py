from __future__ import annotations

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

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
    SectorDataQueryError,
    SectorDateAvailabilityFact,
    SectorSelectionInvalidError,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_fact_reader import (
    SectorAnalysisFactReader, SectorPublishedCalendarDate, SectorPublishedCoverage,
    SectorPublishedRelativeRotationRow,
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


def _point(code, day=TARGET_DATE, **changes):
    rank = CODES.index(code) + 1
    percentile = (Decimal("100"), Decimal("66.7"), Decimal("33.3"), Decimal("0"))[rank - 1]
    return replace(SectorPublishedRelativeRotationRow(
        batch_id=uuid5(NAMESPACE_URL, str(day)), trade_date=day,
        comparison_scope="LEVEL_1", comparison_key="GLOBAL:L1",
        parent_sector_code=None, sector_code=code, sector_name=f"行业{rank}",
        industry_level=1, hierarchy_path=f"行业{rank}", period=5,
        return_pct=Decimal(5-rank), strength_rank=rank, rankable_count=4,
        percentile=percentile, calculation_status="CALCULABLE", missing_reason="NONE",
        comparison_trade_date=day-timedelta(days=5), comparison_return_pct=Decimal(5-rank),
        comparison_strength_rank=rank, comparison_rankable_count=4,
        comparison_percentile=percentile, percentile_delta_5d=Decimal(0),
        rotation_status="STRONG_NOT_IMPROVING" if percentile >= 50 else "WEAK_NOT_IMPROVING",
        coordinate_status="PLOTTABLE", group_interpretation="QUADRANT",
        current_missing_reason=None, comparison_missing_reason=None,
    ), **changes)


class _ContextQuery:
    def resolve_context(self, _session, *, market, requested_trade_date):
        assert market == "CN_A" and requested_trade_date is None
        return _context()


class _HierarchyQuery:
    def __init__(self, failure=None):
        self.failure = failure

    def load(self, _session):
        if self.failure:
            raise self.failure
        return _hierarchy()


class _Reader(SectorAnalysisFactReader):
    def __init__(self, *, unpublished=(), partial=(), changed=None, dates=OPEN_DATES):
        self.unpublished, self.partial = set(unpublished), set(partial)
        self.changed, self.dates = changed or {}, dates
        self.current_calls, self.history_calls = [], []

    def load_momentum_coverage(self, _session, **_kwargs):
        return SectorPublishedCoverage(
            self.dates[0], self.dates[-1], tuple(
                SectorPublishedCalendarDate(
                    SectorDateAvailabilityFact(
                        trade_date=day, availability=(
                            "MISSING" if day in self.unpublished
                            else "PARTIAL" if day in self.partial else "COMPLETE"
                        ),
                        expected_sector_count=4,
                        valid_sector_count=0 if day in self.unpublished else 3 if day in self.partial else 4,
                    ),
                    None if day in self.unpublished else uuid5(NAMESPACE_URL, str(day)),
                ) for day in self.dates
            ),
        )

    def load_relative_rotation_rows(self, _session, **kwargs):
        self.current_calls.append(kwargs)
        day = kwargs["trade_date"]
        return tuple(_point(code, day, **self.changed.get((day, code), {})) for code in CODES)

    def load_relative_rotation_history(self, _session, **kwargs):
        self.history_calls.append(kwargs)
        return tuple(_point(kwargs["selected_sector_code"], day)
                     for day in sorted(kwargs["batch_by_date"]))


class _NoOnlineCalculation(SectorMomentumCalculator):
    def calculate_for_dates(self, **_kwargs):
        pytest.fail("online return calculation is forbidden")

    def rank_strength(self, *_args, **_kwargs):
        pytest.fail("online ranking is forbidden")

    def rank_selected(self, *_args, **_kwargs):
        pytest.fail("online selected ranking is forbidden")


def _service(reader=None, failure=None):
    reader = reader or _Reader()
    return SectorRelativeRotationQueryService(
        context_query=_ContextQuery(), hierarchy_query=_HierarchyQuery(failure),
        fact_reader=reader, momentum_calculator=_NoOnlineCalculation(),
    ), reader


def _build_results(service, **overrides):
    kwargs = dict(
        market="CN_A", trade_date=TARGET_DATE, scope="LEVEL_1",
        level1_code=None, level2_code=None, period=5, trail_length=20,
        sector_code=None, hierarchy_version="v1", debug=True,
    )
    kwargs.update(overrides)
    return service.build_results(object(), **kwargs)

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


@pytest.mark.parametrize("length", [20, 30, 60])
def test_read_complete_current_pool_and_only_selected_published_history(length):
    service, reader = _service()
    result = _build_results(service, trail_length=length)
    assert result.status == "READY"
    analysis = result.analysis
    assert analysis.totalCount == analysis.currentCalculableCount == analysis.plottableCount == 4
    assert analysis.selectedSectorCode == CODES[0]
    assert analysis.selectedTrail.dateSlotCount == min(length, len(OPEN_DATES))
    assert analysis.selectedTrail.points[-1].tradeDate == TARGET_DATE
    assert len(reader.current_calls) == len(reader.history_calls) == 1
    history = reader.history_calls[0]
    assert history["selected_sector_code"] == CODES[0]
    assert len(history["batch_by_date"]) == analysis.selectedTrail.dateSlotCount - 1
    assert TARGET_DATE not in history["batch_by_date"]


@pytest.mark.parametrize("explicit", [True, False])
def test_published_partial_does_not_choose_older_complete_date(explicit):
    service, _ = _service(_Reader(partial=(TARGET_DATE,)))
    result = _build_results(service, trade_date=TARGET_DATE if explicit else None)
    assert result.status == "READY"
    assert result.tradingDay.observedTradeDate == TARGET_DATE
    assert result.tradingDay.observedAvailability == "PARTIAL"


def test_default_unpublished_uses_previous_published_partial_for_meta_and_results():
    service, reader = _service(_Reader(unpublished=(TARGET_DATE,), partial=(OPEN_DATES[-2],)))
    meta, result = service.build_meta(object(), market="CN_A"), _build_results(service, trade_date=None)
    for response in (meta, result):
        assert response.status == "DELAYED"
        assert response.tradingDay.observedTradeDate == OPEN_DATES[-2]
        assert response.tradingDay.observedAvailability == "PARTIAL"
    assert result.analysis.selectedTrail.points[-1].tradeDate == OPEN_DATES[-2]
    assert reader.current_calls[0]["trade_date"] == OPEN_DATES[-2]


def test_explicit_unpublished_is_empty_without_method_reads():
    service, reader = _service(_Reader(unpublished=(TARGET_DATE,)))
    result = _build_results(service)
    assert result.status == "EMPTY" and result.analysis is None
    assert reader.current_calls == reader.history_calls == []


def test_unpublished_history_keeps_real_calendar_slot_without_filling():
    missing = OPEN_DATES[-3]
    service, reader = _service(_Reader(unpublished=(missing,)))
    points = _build_results(service).analysis.selectedTrail.points
    assert len(points) == 20 and points[-3].tradeDate == missing
    assert points[-3].returnPct is points[-3].percentile is points[-3].percentileDelta5d is None
    assert points[-3].currentMissingReason == "DATE_MISSING"
    assert points[-3].coordinateStatus == "UNAVAILABLE"
    assert missing not in reader.history_calls[0]["batch_by_date"]


def test_first_published_day_does_not_invent_precoverage_history():
    service, reader = _service(_Reader(dates=(TARGET_DATE,)))
    result = _build_results(service)
    assert result.status == "READY" and result.analysis.selectedTrail.dateSlotCount == 1
    assert reader.history_calls[0]["batch_by_date"] == {}


def test_current_values_survive_missing_comparison_and_explicit_selection():
    changes = dict(
        comparison_return_pct=None, comparison_strength_rank=None,
        comparison_rankable_count=None, comparison_percentile=None,
        percentile_delta_5d=None, rotation_status="DATA_INSUFFICIENT",
        coordinate_status="UNAVAILABLE", comparison_missing_reason="DATE_MISSING",
        calculation_status="UNAVAILABLE", missing_reason="DATE_MISSING",
    )
    service, _ = _service(_Reader(changed={(TARGET_DATE, CODES[0]): changes}))
    assert _build_results(service).analysis.selectedSectorCode == CODES[1]
    result = _build_results(service, sector_code=CODES[0])
    item = next(item for item in result.analysis.items if item.sectorCode == CODES[0])
    assert item.returnPct == 4 and item.strengthRank == 1 and item.percentile == 100
    assert item.percentileDelta5d is None and item.comparisonMissingReason == "DATE_MISSING"
    assert result.analysis.currentCalculableCount == 4 and result.analysis.missingCoordinateCount == 1
    assert result.analysis.selectedTrail.points[-1].percentileDelta5d is None


def test_no_current_calculable_returns_empty_without_history():
    changes = dict(return_pct=None, strength_rank=None, rankable_count=None, percentile=None,
                   percentile_delta_5d=None, coordinate_status="UNAVAILABLE",
                   rotation_status="DATA_INSUFFICIENT", current_missing_reason="DATE_MISSING",
                   calculation_status="UNAVAILABLE", missing_reason="DATE_MISSING")
    service, reader = _service(_Reader(changed={(TARGET_DATE, code): changes for code in CODES}))
    result = _build_results(service)
    assert result.status == "EMPTY" and result.analysis is None
    assert len(reader.current_calls) == 1 and not reader.history_calls


@pytest.mark.parametrize(("overrides", "error"), [
    ({"sector_code": "BK9999.DC"}, SectorSelectionInvalidError),
    ({"hierarchy_version": "stale"}, SectorMomentumFactVersionMismatchError),
    ({"trade_date": date(2000, 1, 1)}, SectorSelectionInvalidError),
])
def test_invalid_selection_or_version_stops_before_method_reads(overrides, error):
    service, reader = _service()
    with pytest.raises(error):
        _build_results(service, **overrides)
    assert reader.current_calls == reader.history_calls == []


@pytest.mark.parametrize(("failure", "code"), [
    (SectorHierarchyUnavailableError("secret"), "SA_HIERARCHY_UNAVAILABLE"),
    (RuntimeError("SELECT secret"), "SA_QUERY_FAILED"),
])
def test_internal_failures_return_safe_error_shell(failure, code):
    service, _ = _service(failure=failure)
    result = _build_results(service)
    assert result.status == "ERROR" and result.exceptionCode == code
    assert result.analysis is None and "secret" not in result.model_dump_json()

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
