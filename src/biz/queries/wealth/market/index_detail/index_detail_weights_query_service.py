from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.queries.wealth.market.index_detail.index_detail_query import IndexDetailQuery
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailDataStatusDto,
    IndexDetailDebugInfoDto,
    IndexDetailIdentityDto,
    IndexDetailIndexRefDto,
    IndexDetailModuleDebugDto,
    IndexDetailWeightCoverageDto,
    IndexDetailWeightRowDto,
    IndexDetailWeightsResponseDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_exception_builder import IndexDetailExceptionBuilder
from src.biz.services.wealth.market.index_detail.index_detail_field_mapper import build_identity, resolve_direction, to_float
from src.biz.services.wealth.market.index_detail.index_detail_status_resolver import IndexDetailStatusResolver
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailQueryError,
    IndexDetailUniverseService,
)
from src.biz.services.wealth.market.index_detail.index_weight_contribution_builder import (
    calculate_contribution_point,
)


_WEIGHTS_NOTE = "基于最新月度权重估算，非指数公司官方归因"


class IndexDetailWeightsQueryService:
    """Assemble complete index weight batches and estimated contribution points."""

    def __init__(self) -> None:
        self._universe_service = IndexDetailUniverseService()
        self._context_query = MarketPageContextQuery()
        self._query = IndexDetailQuery()
        self._status_resolver = IndexDetailStatusResolver()
        self._exception_builder = IndexDetailExceptionBuilder()

    def build_weights(
        self,
        session: Session,
        *,
        ts_code: str,
        trade_date: date | None,
        debug: bool,
    ) -> IndexDetailWeightsResponseDto:
        self._universe_service.require_supported(ts_code)
        identity = self._load_identity_or_raise(session, ts_code=ts_code)
        context = self._context_query.resolve_context(
            session,
            market="CN_A",
            requested_trade_date=trade_date,
        )
        daily_anchor = self._query.load_latest_daily_anchor(
            session,
            ts_code=ts_code,
            expected_trade_date=context.trade_date,
        )
        if daily_anchor is None:
            data_status = self._status_resolver.resolve(
                expected_trade_date=context.trade_date,
                observed_trade_date=None,
                empty=True,
                partial=False,
            )
            return self._build_empty_response(
                ts_code=identity.tsCode,
                name=identity.name,
                contribution_trade_date=context.trade_date,
                data_status=data_status,
                debug=debug,
                source_empty=True,
            )

        contribution_trade_date = daily_anchor["trade_date"]
        weight_trade_date = self._query.load_weight_trade_date(
            session,
            ts_code=ts_code,
            contribution_trade_date=contribution_trade_date,
        )
        if weight_trade_date is None:
            data_status = self._status_resolver.resolve(
                expected_trade_date=context.trade_date,
                observed_trade_date=None,
                empty=True,
                partial=False,
            )
            return self._build_empty_response(
                ts_code=identity.tsCode,
                name=identity.name,
                contribution_trade_date=contribution_trade_date,
                data_status=data_status,
                debug=debug,
                source_empty=False,
            )

        stats = self._query.load_weight_batch_stats(
            session,
            ts_code=ts_code,
            weight_trade_date=weight_trade_date,
        )
        if (
            stats["total_count"] == 0
            or stats["weight_count"] != stats["total_count"]
            or stats["distinct_constituent_count"] != stats["total_count"]
        ):
            raise IndexDetailQueryError("指数权重批次不完整")

        source_rows = self._query.load_weight_rows(
            session,
            ts_code=ts_code,
            contribution_trade_date=contribution_trade_date,
            weight_trade_date=weight_trade_date,
        )
        if len(source_rows) != stats["total_count"]:
            raise IndexDetailQueryError("指数权重批次查询行数不一致")

        rows: list[IndexDetailWeightRowDto] = []
        available_count = 0
        for source_row in source_rows:
            weight = to_float(source_row.get("weight"))
            if weight is None:
                raise IndexDetailQueryError("指数权重批次含空权重")
            change_pct = to_float(source_row.get("pct_chg"))
            contribution_point = calculate_contribution_point(
                index_pre_close=daily_anchor.get("pre_close"),
                weight=source_row.get("weight"),
                constituent_pct_chg=source_row.get("pct_chg"),
            )
            if contribution_point is not None:
                available_count += 1
            rows.append(
                IndexDetailWeightRowDto(
                    conCode=source_row["con_code"],
                    name=source_row.get("name"),
                    weight=weight,
                    changePct=change_pct,
                    contributionPoint=contribution_point,
                    direction=resolve_direction(change_pct),  # type: ignore[arg-type]
                )
            )

        missing_count = len(rows) - available_count
        data_status = self._status_resolver.resolve(
            expected_trade_date=context.trade_date,
            observed_trade_date=contribution_trade_date,
            empty=False,
            partial=missing_count > 0,
        )
        exceptions = []
        if missing_count > 0:
            exceptions.append(
                self._exception_builder.weight_contribution_partial(
                    message="部分 A 股成分贡献点输入缺失",
                )
            )
        if contribution_trade_date < context.trade_date:
            exceptions.append(
                self._exception_builder.source_delayed(
                    module="indexDetailWeights",
                    message="权重贡献日期落后于期望日期",
                )
            )
        return IndexDetailWeightsResponseDto(
            indexRef=IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
            contributionTradeDate=contribution_trade_date,
            weightTradeDate=weight_trade_date,
            isEstimated=True,
            rows=rows,
            coverage=IndexDetailWeightCoverageDto(
                totalCount=len(rows),
                returnedCount=len(rows),
                contributionAvailableCount=available_count,
                contributionMissingCount=missing_count,
                isTruncated=False,
            ),
            dataStatus=data_status,
            note=_WEIGHTS_NOTE,
            debugInfo=(
                IndexDetailDebugInfoDto(
                    modules=[self._module_debug(data_status, row_count=len(rows), missing_count=missing_count)],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    def _build_empty_response(
        self,
        *,
        ts_code: str,
        name: str,
        contribution_trade_date: date,
        data_status: IndexDetailDataStatusDto,
        debug: bool,
        source_empty: bool,
    ) -> IndexDetailWeightsResponseDto:
        exception = (
            self._exception_builder.source_empty(
                module="indexDetailWeights",
                message="指数日线无可用数据",
            )
            if source_empty
            else self._exception_builder.weight_empty(
                module="indexDetailWeights",
                message="指数无可用权重批次",
            )
        )
        return IndexDetailWeightsResponseDto(
            indexRef=IndexDetailIndexRefDto(tsCode=ts_code, name=name),
            contributionTradeDate=contribution_trade_date,
            weightTradeDate=None,
            isEstimated=True,
            rows=[],
            coverage=IndexDetailWeightCoverageDto(
                totalCount=0,
                returnedCount=0,
                contributionAvailableCount=0,
                contributionMissingCount=0,
                isTruncated=False,
            ),
            dataStatus=data_status,
            note=_WEIGHTS_NOTE,
            debugInfo=(
                IndexDetailDebugInfoDto(
                    modules=[self._module_debug(data_status, row_count=0, missing_count=None)],
                    exceptions=[exception],
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _module_debug(
        data_status: IndexDetailDataStatusDto,
        *,
        row_count: int,
        missing_count: int | None,
    ) -> IndexDetailModuleDebugDto:
        return IndexDetailModuleDebugDto(
            module="weights",
            status=data_status.status,
            expectedTradeDate=data_status.expectedTradeDate,
            observedTradeDate=data_status.observedTradeDate,
            rowCount=row_count,
            missingCount=missing_count,
        )

    def _load_identity_or_raise(self, session: Session, *, ts_code: str) -> IndexDetailIdentityDto:
        identity_row = self._query.load_identity(session, ts_code=ts_code)
        if identity_row is None:
            raise IndexDetailNotFoundError(f"未找到指数身份：{ts_code}")
        try:
            return build_identity(identity_row)
        except ValueError as exc:
            raise IndexDetailNotFoundError(f"指数身份缺少名称：{ts_code}") from exc
