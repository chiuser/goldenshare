from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

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
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_fact_reader import (
    SectorAnalysisFactReader,
    SectorPublishedCoverage,
    SectorPublishedCalendarDate,
    SectorPublishedDualMomentumRow,
)
from src.biz.queries.wealth.market.sector_analysis.sector_dual_momentum_query_service import (
    SectorDualMomentumQueryService,
)
from src.biz.schemas.wealth.market.sector_dual_momentum import (
    SectorDualMomentumResultsResponseDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    SectorMomentumFactVersionMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDateAvailabilityFact,
)


TARGET_DATE = date(2026, 8, 27)
PREVIOUS_DATE = TARGET_DATE - timedelta(days=1)


def _context() -> MarketPageContext:
    return MarketPageContext(
        market="CN_A",
        trade_date=TARGET_DATE,
        prev_trade_date=PREVIOUS_DATE,
        is_trading_day=True,
        session_status="CLOSED",
        generated_at=datetime(2026, 8, 27, 20, 1, tzinfo=timezone.utc),
        source="default",
    )


def _hierarchy() -> SectorHierarchySnapshot:
    nodes = tuple(
        SectorHierarchyNode(
            sector_code=f"BK100{index}.DC",
            sector_name=f"行业{index}",
            industry_level=1,
            parent_sector_code=None,
            parent_sector_name=None,
            root_sector_code=f"BK100{index}.DC",
            root_sector_name=f"行业{index}",
            hierarchy_path=f"行业{index}",
            display_order=index,
            is_leaf=True,
            baseline_version="v1",
        )
        for index in range(1, 5)
    )
    return SectorHierarchySnapshot(
        baseline_version="v1",
        published_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={None: nodes},
    )


def _availability(
    trade_date: date,
    availability: str,
    valid_count: int,
) -> SectorDateAvailabilityFact:
    return SectorDateAvailabilityFact(
        trade_date=trade_date,
        availability=availability,  # type: ignore[arg-type]
        expected_sector_count=4,
        valid_sector_count=valid_count,
    )


def _published_rows(*, missing: bool = False):
    hierarchy = _hierarchy()
    facts = (
        ("5", 1, "100", "NONE", "POSITIVE", "LEADING", "QUALIFIED", "QUALIFIED"),
        ("1", 2, "50", "NONE", "POSITIVE", "NOT_LEADING", "NOT_QUALIFIED", "UP_NOT_LEADING"),
        ("0", 3, "0", "NONE", "NOT_POSITIVE", "NOT_LEADING", "NOT_QUALIFIED", "NOT_UP_NOT_LEADING"),
        (None, None, None, "DATE_MISSING", "UNAVAILABLE", "UNAVAILABLE", "NOT_EVALUATED", "DATA_INSUFFICIENT"),
    )
    if missing:
        facts = (facts[-1],) * 4
    return tuple(
        SectorPublishedDualMomentumRow(
            batch_id=UUID(int=1), trade_date=TARGET_DATE,
            comparison_scope="LEVEL_1", comparison_key="GLOBAL:L1",
            parent_sector_code=None, sector_code=node.sector_code,
            sector_name=node.sector_name, industry_level=1,
            hierarchy_path=node.hierarchy_path, period=20,
            return_pct=Decimal(value) if value is not None else None,
            strength_rank=rank, rankable_count=3 if rank else None,
            percentile=Decimal(percentile) if percentile is not None else None,
            calculation_status="CALCULABLE" if value is not None else "UNAVAILABLE",
            missing_reason=reason, absolute_status=absolute, relative_status=relative,
            qualification_status=qualification, display_status=display,
            coordinate_status="PLOTTABLE" if rank else "UNAVAILABLE",
        )
        for node, (value, rank, percentile, reason, absolute, relative, qualification, display)
        in zip(hierarchy.nodes, facts, strict=True)
    )


class _ContextQuery:
    def resolve_context(self, _session, *, market, requested_trade_date):
        assert market == "CN_A" and requested_trade_date is None
        return _context()


class _HierarchyQuery:
    def load(self, _session):
        return _hierarchy()


class _Reader(SectorAnalysisFactReader):
    def __init__(self, *, rows=None, failure=None, unpublished=False):
        self.rows = rows if rows is not None else _published_rows()
        self.failure = failure
        self.unpublished = unpublished
        self.calls = 0

    def load_momentum_coverage(self, _session, **kwargs):
        return SectorPublishedCoverage(
            coverage_start_date=PREVIOUS_DATE,
            coverage_end_date=TARGET_DATE,
            calendar_dates=(
                SectorPublishedCalendarDate(_availability(PREVIOUS_DATE, "PARTIAL", 3), UUID(int=2)),
                SectorPublishedCalendarDate(
                    _availability(TARGET_DATE, "MISSING" if self.unpublished else "PARTIAL", 0 if self.unpublished else 3),
                    None if self.unpublished else UUID(int=1),
                ),
            ),
        )

    def load_dual_momentum_rows(self, _session, **kwargs):
        self.calls += 1
        assert kwargs["hierarchy"].baseline_version == "v1"
        if self.failure is not None:
            raise self.failure
        return self.rows


def _service(reader: _Reader | None = None):
    return SectorDualMomentumQueryService(
        context_query=_ContextQuery(),  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQuery(),  # type: ignore[arg-type]
        fact_reader=reader or _Reader(),
    )


def test_meta_uses_dedicated_formula_contract_and_public_delayed_date() -> None:
    response = _service(_Reader(unpublished=True)).build_meta(object(), market="CN_A")  # type: ignore[arg-type]

    assert response.status == "DELAYED"
    assert response.tradingDay.expectedTradeDate == TARGET_DATE
    assert response.tradingDay.observedTradeDate == PREVIOUS_DATE
    assert response.tradingDay.observedAvailability == "PARTIAL"
    assert response.formula.model_dump() == {
        "formulaKey": "sector-dual-momentum",
        "formulaVersion": 1,
        "basisFormulaKey": "sector-cross-sectional-momentum",
        "basisFormulaVersion": 1,
        "periods": [5, 10, 20, 30],
        "leadingThresholds": [70, 80, 90],
        "minimumGroupSize": 3,
        "scopes": [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ],
    }


def test_results_returns_full_canonical_analysis_and_all_five_counts() -> None:
    response = _service().build_results(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=20,
        leading_threshold=80,
        hierarchy_version="v1",
        debug=True,
    )

    assert response.status == "READY"
    assert response.analysis is not None
    assert response.analysis.totalCount == 4
    assert response.analysis.calculableCount == 3
    assert response.analysis.qualifiedCount == 1
    assert response.analysis.insufficientCount == 1
    assert response.analysis.plottableCount == 3
    assert [item.sectorCode for item in response.analysis.items] == [
        "BK1001.DC",
        "BK1002.DC",
        "BK1003.DC",
        "BK1004.DC",
    ]
    assert response.analysis.items[2].displayStatus == "NOT_UP_NOT_LEADING"
    assert response.analysis.items[-1].missingReason == "DATE_MISSING"


def test_zero_calculable_rows_are_empty_and_do_not_return_analysis() -> None:
    response = _service(_Reader(rows=_published_rows(missing=True))).build_results(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=20,
        leading_threshold=80,
        hierarchy_version="v1",
        debug=False,
    )

    assert response.status == "EMPTY"
    assert response.exceptionCode == "SA_SOURCE_EMPTY"
    assert response.analysis is None


def test_invalid_unavailable_stored_status_is_not_hidden_by_empty_shell() -> None:
    rows = _published_rows(missing=True)
    rows = (replace(rows[0], qualification_status="QUALIFIED"), *rows[1:])
    response = _service(_Reader(rows=rows)).build_results(
        object(), market="CN_A", trade_date=TARGET_DATE, scope="LEVEL_1",
        level1_code=None, level2_code=None, period=20, leading_threshold=80,
        hierarchy_version="v1", debug=False,
    )
    assert response.status == "ERROR"
    assert response.exceptionCode == "SA_QUERY_FAILED"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (SectorHierarchyUnavailableError("sensitive"), "SA_HIERARCHY_UNAVAILABLE"),
        (RuntimeError("SELECT secret"), "SA_QUERY_FAILED"),
    ),
)
def test_results_failures_return_safe_error_shells(failure, expected_code) -> None:
    response = _service(_Reader(failure=failure)).build_results(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=20,
        leading_threshold=80,
        hierarchy_version="v1",
        debug=False,
    )

    assert response.status == "ERROR"
    assert response.exceptionCode == expected_code
    assert response.analysis is None
    assert "SELECT" not in (response.message or "")


def test_version_mismatch_is_not_hidden_in_a_200_error_shell() -> None:
    with pytest.raises(SectorMomentumFactVersionMismatchError):
        _service(
            _Reader(
                failure=SectorMomentumFactVersionMismatchError("stale")
            )
        ).build_results(
            object(),  # type: ignore[arg-type]
            market="CN_A",
            trade_date=TARGET_DATE,
            scope="LEVEL_1",
            level1_code=None,
            level2_code=None,
            period=20,
            leading_threshold=80,
            hierarchy_version="v1",
            debug=False,
        )


def test_strict_results_schema_rejects_count_and_sort_tampering() -> None:
    response = _service().build_results(
        object(),  # type: ignore[arg-type]
        market="CN_A",
        trade_date=TARGET_DATE,
        scope="LEVEL_1",
        level1_code=None,
        level2_code=None,
        period=20,
        leading_threshold=80,
        hierarchy_version="v1",
        debug=False,
    )
    payload = response.model_dump()
    assert payload["analysis"] is not None
    payload["analysis"]["qualifiedCount"] = 0
    with pytest.raises(ValidationError):
        SectorDualMomentumResultsResponseDto.model_validate(payload)

    payload = response.model_dump()
    payload["analysis"]["items"] = list(reversed(payload["analysis"]["items"]))
    with pytest.raises(ValidationError):
        SectorDualMomentumResultsResponseDto.model_validate(payload)
