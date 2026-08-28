from __future__ import annotations

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
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query_service import (
    SectorAnalysisMetaFacts,
)
from src.biz.queries.wealth.market.sector_analysis.sector_dual_momentum_query_service import (
    SectorDualMomentumQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_snapshot_query_service import (
    SectorMomentumSnapshot,
    SectorMomentumSnapshotRow,
)
from src.biz.schemas.wealth.market.sector_dual_momentum import (
    SectorDualMomentumResultsResponseDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    SectorMomentumFactVersionMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDateAvailabilityFact,
    SectorRankFact,
    SectorReturnFact,
    SectorTradingDateResolution,
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


def _resolution(*, delayed: bool = False, missing: bool = False):
    expected = _availability(
        TARGET_DATE,
        "MISSING" if missing else ("PARTIAL" if delayed else "COMPLETE"),
        0 if missing else (3 if delayed else 4),
    )
    observed = (
        None
        if missing
        else (_availability(PREVIOUS_DATE, "COMPLETE", 4) if delayed else expected)
    )
    return SectorTradingDateResolution(
        coverage_start_date=PREVIOUS_DATE,
        coverage_end_date=TARGET_DATE,
        expected=expected,
        observed=observed,
        is_explicit=missing,
    )


def _snapshot(*, delayed: bool = False, missing: bool = False):
    hierarchy = _hierarchy()
    facts = (
        ("5", 1, "100", "NONE"),
        ("1", 2, "50", "NONE"),
        ("0", 3, "0", "NONE"),
        (None, None, None, "DATE_MISSING"),
    )
    rows = tuple(
        SectorMomentumSnapshotRow(
            node=node,
            return_fact=SectorReturnFact(
                sector_code=node.sector_code,
                trade_date=TARGET_DATE,
                return_pct=Decimal(value) if value is not None else None,
                missing_reason=reason,  # type: ignore[arg-type]
            ),
            rank_fact=SectorRankFact(
                sector_code=node.sector_code,
                return_pct=Decimal(value) if value is not None else None,
                strength_rank=rank,
                percentile=Decimal(percentile) if percentile is not None else None,
            ),
        )
        for node, (value, rank, percentile, reason) in zip(
            hierarchy.nodes,
            facts,
            strict=True,
        )
    )
    if missing:
        rows = tuple(
            SectorMomentumSnapshotRow(
                node=row.node,
                return_fact=SectorReturnFact(
                    row.node.sector_code,
                    TARGET_DATE,
                    None,
                    "DATE_MISSING",
                ),
                rank_fact=SectorRankFact(row.node.sector_code, None, None, None),
            )
            for row in rows
        )
    return SectorMomentumSnapshot(
        context=_context(),
        hierarchy=hierarchy,
        resolution=_resolution(delayed=delayed, missing=missing),
        scope="LEVEL_1",
        period=20,
        level1_code=None,
        level2_code=None,
        rows=rows,
    )


class _MetaService:
    def load(self, _session, *, market):
        assert market == "CN_A"
        return SectorAnalysisMetaFacts(
            context=_context(),
            hierarchy=_hierarchy(),
            coverage_start_date=PREVIOUS_DATE,
            coverage_end_date=TARGET_DATE,
            trade_dates=(
                _availability(PREVIOUS_DATE, "COMPLETE", 4),
                _availability(TARGET_DATE, "PARTIAL", 3),
            ),
        )


class _SnapshotService:
    def __init__(self, *, snapshot=None, failure: Exception | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.failure = failure
        self.calls = 0

    def build(self, _session, **kwargs):
        self.calls += 1
        assert kwargs["expected_hierarchy_version"] == "v1"
        assert kwargs["date_errors_are_selection"] is True
        if self.failure is not None:
            raise self.failure
        return self.snapshot


def _service(snapshot_service: _SnapshotService | None = None):
    return SectorDualMomentumQueryService(
        meta_service=_MetaService(),  # type: ignore[arg-type]
        snapshot_service=snapshot_service or _SnapshotService(),  # type: ignore[arg-type]
    )


def test_meta_uses_dedicated_formula_contract_and_public_delayed_date() -> None:
    response = _service().build_meta(object(), market="CN_A")  # type: ignore[arg-type]

    assert response.status == "DELAYED"
    assert response.tradingDay.expectedTradeDate == TARGET_DATE
    assert response.tradingDay.observedTradeDate == PREVIOUS_DATE
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
    response = _service(_SnapshotService(snapshot=_snapshot(missing=True))).build_results(
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


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (SectorHierarchyUnavailableError("sensitive"), "SA_HIERARCHY_UNAVAILABLE"),
        (RuntimeError("SELECT secret"), "SA_QUERY_FAILED"),
    ),
)
def test_results_failures_return_safe_error_shells(failure, expected_code) -> None:
    response = _service(_SnapshotService(failure=failure)).build_results(
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
            _SnapshotService(
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
