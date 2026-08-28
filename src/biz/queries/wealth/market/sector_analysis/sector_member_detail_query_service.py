from __future__ import annotations

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_member_detail_query import (
    SectorMemberDetailQuery,
)
from src.biz.schemas.wealth.market.sector_analysis import (
    SectorMemberDetailResponseDto,
    SectorMemberRowDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_analysis_exception_builder import (
    SectorAnalysisExceptionBuilder,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_detail_contract import (
    SectorMemberDetailRequest,
    SectorMemberFactMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_return_calculator import (
    SectorMemberReturnCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
)


class SectorMemberDetailQueryService:
    """Compose the frozen level-3 membership and its EOD return facts."""

    def __init__(
        self,
        *,
        hierarchy_query: SectorHierarchyQuery | None = None,
        member_query: SectorMemberDetailQuery | None = None,
        calculator: SectorMemberReturnCalculator | None = None,
    ) -> None:
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._query = member_query or SectorMemberDetailQuery()
        self._calculator = calculator or SectorMemberReturnCalculator()
        self._exceptions = SectorAnalysisExceptionBuilder()

    def build_members(
        self,
        session: Session,
        *,
        request: SectorMemberDetailRequest,
    ) -> SectorMemberDetailResponseDto:
        sector_name = "当前行业"
        try:
            if request.market != "CN_A":
                raise SectorScopeInvalidError("只支持 CN_A 市场")
            hierarchy = self._hierarchy_query.load(session)
            if hierarchy.baseline_version != request.hierarchy_version:
                raise SectorMemberFactMismatchError("hierarchy version changed")
            node = hierarchy.nodes_by_code.get(request.sector_code)
            if node is None or node.industry_level != 3:
                raise SectorSelectionInvalidError(
                    "sectorCode 必须是当前分类版本中的三级行业"
                )
            sector_name = node.sector_name

            open_dates = self._query.load_open_window(
                session,
                trade_date=request.trade_date,
                period=request.period,
            )
            members = self._query.load_members(
                session,
                trade_date=request.trade_date,
                sector_code=request.sector_code,
            )
            if not members:
                exception = self._exceptions.build("SA_MEMBER_SOURCE_EMPTY")
                return SectorMemberDetailResponseDto(
                    status="EMPTY",
                    message=exception.message,
                    exceptionCode=exception.code,
                    tradeDate=request.trade_date,
                    hierarchyVersion=request.hierarchy_version,
                    sectorCode=request.sector_code,
                    sectorName=sector_name,
                    period=request.period,
                    direction=request.direction,
                    totalMemberCount=0,
                    closeAvailableCount=0,
                    calculableCount=0,
                    rows=[],
                )
            stock_codes = tuple(row.stock_code for row in members)
            daily_facts = self._query.load_daily_facts(
                session,
                stock_codes=stock_codes,
                open_dates=open_dates,
            )
            calculated = self._calculator.calculate(
                members=members,
                daily_facts=daily_facts,
                open_dates=open_dates,
                target_date=request.trade_date,
                period=request.period,
            )
            sorted_rows = self._calculator.sort(calculated, direction=request.direction)
            return SectorMemberDetailResponseDto(
                status="READY",
                message=None,
                exceptionCode=None,
                tradeDate=request.trade_date,
                hierarchyVersion=request.hierarchy_version,
                sectorCode=request.sector_code,
                sectorName=sector_name,
                period=request.period,
                direction=request.direction,
                totalMemberCount=len(sorted_rows),
                closeAvailableCount=sum(row.close is not None for row in sorted_rows),
                calculableCount=sum(row.return_pct is not None for row in sorted_rows),
                rows=[
                    SectorMemberRowDto(
                        stockName=row.stock_name,
                        stockCode=row.stock_code,
                        close=row.close,
                        returnPct=row.return_pct,
                    )
                    for row in sorted_rows
                ],
            )
        except (
            SectorMemberFactMismatchError,
            SectorScopeInvalidError,
            SectorSelectionInvalidError,
        ):
            raise
        except Exception:  # noqa: BLE001
            exception = self._exceptions.build("SA_MEMBER_QUERY_FAILED")
            return SectorMemberDetailResponseDto(
                status="ERROR",
                message=exception.message,
                exceptionCode=exception.code,
                tradeDate=request.trade_date,
                hierarchyVersion=request.hierarchy_version,
                sectorCode=request.sector_code,
                sectorName=sector_name,
                period=request.period,
                direction=request.direction,
                totalMemberCount=0,
                closeAvailableCount=0,
                calculableCount=0,
                rows=[],
            )
