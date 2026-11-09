from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.queries.wealth.market.index_detail.index_detail_query import IndexDetailQuery
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailDataStatusDto,
    IndexDetailIdentityDto,
    IndexDetailIndexRefDto,
    IndexDetailWeightCoverageDto,
    IndexDetailWeightRowDto,
    IndexDetailWeightsResponseDto,
)
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


def _weight_row_sort_key(row: IndexDetailWeightRowDto) -> tuple[int, float, float, str]:
    contribution_point = row.contributionPoint
    return (
        1 if contribution_point is None else 0,
        0.0 if contribution_point is None else -contribution_point,
        -row.weight,
        row.conCode,
    )


class IndexDetailWeightsQueryService:
    """Assemble complete index weight batches and estimated contribution points."""

    def __init__(self) -> None:
        self._universe_service = IndexDetailUniverseService()
        self._context_query = MarketPageContextQuery()
        self._query = IndexDetailQuery()
        self._status_resolver = IndexDetailStatusResolver()

    def build_weights(self, session: Session, *, ts_code: str,
                      trade_date: date | None) -> IndexDetailWeightsResponseDto:
        return self.query_weights(session, ts_code=ts_code, trade_date=trade_date)[0]

    def query_weights(
        self,
        session: Session,
        *,
        ts_code: str,
        trade_date: date | None,
    ) -> tuple[IndexDetailWeightsResponseDto, bool]:
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
            ), True

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
            ), False

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

        rows.sort(key=_weight_row_sort_key)
        missing_count = len(rows) - available_count
        index_pre_close_missing = daily_anchor.get("pre_close") is None
        data_status = self._status_resolver.resolve(
            expected_trade_date=context.trade_date,
            observed_trade_date=contribution_trade_date,
            empty=False,
            partial=index_pre_close_missing,
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
        ), index_pre_close_missing

    def _build_empty_response(
        self,
        *,
        ts_code: str,
        name: str,
        contribution_trade_date: date,
        data_status: IndexDetailDataStatusDto,
    ) -> IndexDetailWeightsResponseDto:
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
        )

    def _load_identity_or_raise(self, session: Session, *, ts_code: str) -> IndexDetailIdentityDto:
        identity_row = self._query.load_identity(session, ts_code=ts_code)
        if identity_row is None:
            raise IndexDetailNotFoundError(f"未找到指数身份：{ts_code}")
        try:
            return build_identity(identity_row)
        except ValueError as exc:
            raise IndexDetailNotFoundError(f"指数身份缺少名称：{ts_code}") from exc
