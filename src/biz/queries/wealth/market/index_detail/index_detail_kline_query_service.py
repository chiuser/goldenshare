from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.queries.wealth.market.index_detail.index_detail_query import IndexDetailQuery
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailDataStatusDto,
    IndexDetailDebugInfoDto,
    IndexDetailIdentityDto,
    IndexDetailIndexRefDto,
    IndexDetailKlineMetaDto,
    IndexDetailKlineResponseDto,
    IndexDetailModuleDebugDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_exception_builder import IndexDetailExceptionBuilder
from src.biz.services.wealth.market.index_detail.index_detail_field_mapper import (
    build_identity,
    build_kline_bar,
    build_page_context,
)
from src.biz.services.wealth.market.index_detail.index_detail_status_resolver import IndexDetailStatusResolver
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailNotFoundError,
    IndexDetailRequestError,
    IndexDetailUniverseService,
)


_BASE_REQUIRED_FIELDS = ("open", "high", "low", "close", "pre_close", "change", "pct_change", "vol", "amount")
_TECHNICAL_REQUIRED_FIELDS = (
    "boll_upper_bfq",
    "boll_mid_bfq",
    "boll_lower_bfq",
    "macd_dif_bfq",
    "macd_dea_bfq",
    "macd_bfq",
    "kdj_k_bfq",
    "kdj_d_bfq",
    "kdj_bfq",
)
_MA_FIELDS: tuple[tuple[str, int], ...] = (
    ("ma_bfq_5", 5),
    ("ma_bfq_10", 10),
    ("ma_bfq_20", 20),
    ("ma_bfq_30", 30),
    ("ma_bfq_60", 60),
    ("ma_bfq_90", 90),
    ("ma_bfq_250", 250),
)


class IndexDetailKlineQueryService:
    """Assemble factor-only index daily K-line responses."""

    def __init__(self) -> None:
        self._universe_service = IndexDetailUniverseService()
        self._context_query = MarketPageContextQuery()
        self._query = IndexDetailQuery()
        self._status_resolver = IndexDetailStatusResolver()
        self._exception_builder = IndexDetailExceptionBuilder()

    def build_kline(
        self,
        session: Session,
        *,
        ts_code: str,
        period: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
        debug: bool,
    ) -> IndexDetailKlineResponseDto:
        if period != "day":
            raise IndexDetailRequestError("指数详情只支持 period=day")
        if limit < 1 or limit > 2000:
            raise IndexDetailRequestError("limit 必须在 1 到 2000 之间")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise IndexDetailRequestError("startDate 不能晚于 endDate")

        self._universe_service.require_supported(ts_code)
        identity = self._load_identity_or_raise(session, ts_code=ts_code)
        context = self._context_query.resolve_context(
            session,
            market="CN_A",
            requested_trade_date=end_date,
        )
        query_end_date = end_date or context.trade_date
        rows = self._query.load_kline_rows(
            session,
            ts_code=ts_code,
            end_date=query_end_date,
            start_date=start_date,
            limit=limit,
        )
        observed_trade_date = rows[-1]["trade_date"] if rows else None
        if not rows:
            data_status = self._status_resolver.resolve(
                expected_trade_date=query_end_date,
                observed_trade_date=None,
                empty=True,
                partial=False,
            )
            exceptions = [
                self._exception_builder.source_empty(
                    module="indexDetailKline",
                    message="指数因子日线无可用数据",
                )
            ]
            return IndexDetailKlineResponseDto(
                pageContext=build_page_context(context),
                indexRef=IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
                period="day",
                bars=[],
                meta=IndexDetailKlineMetaDto(
                    count=0,
                    limit=limit,
                    startDate=start_date,
                    endDate=query_end_date,
                ),
                dataStatus=data_status,
                debugInfo=(
                    IndexDetailDebugInfoDto(
                        modules=[self._module_debug(data_status, row_count=0, missing_count=None)],
                        exceptions=exceptions,
                    )
                    if debug
                    else None
                ),
            )

        missing_count = self._count_non_ma_missing(rows)
        ma_missing_after_warmup = self._has_ma_missing_after_effective_history(
            session,
            ts_code=ts_code,
            rows=rows,
        )
        if ma_missing_after_warmup:
            missing_count += 1
        latest_daily_date = self._query.load_latest_daily_date(
            session,
            ts_code=ts_code,
            end_date=query_end_date,
        )
        factor_lags_completed_daily = (
            latest_daily_date is not None
            and observed_trade_date is not None
            and observed_trade_date < latest_daily_date
        )
        if factor_lags_completed_daily:
            missing_count += 1
        partial = missing_count > 0
        data_status = self._status_resolver.resolve(
            expected_trade_date=query_end_date,
            observed_trade_date=observed_trade_date,
            empty=False,
            partial=partial,
        )
        exceptions = []
        if partial:
            exceptions.append(
                self._exception_builder.factor_partial(
                    module="indexDetailKline",
                    message="指数日线因子存在缺失或落后",
                )
            )
        if observed_trade_date is not None and observed_trade_date < query_end_date:
            exceptions.append(
                self._exception_builder.source_delayed(
                    module="indexDetailKline",
                    message="指数因子观测日期落后于查询上界",
                )
            )
        return IndexDetailKlineResponseDto(
            pageContext=build_page_context(context),
            indexRef=IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
            period="day",
            bars=[build_kline_bar(row) for row in rows],
            meta=IndexDetailKlineMetaDto(
                count=len(rows),
                limit=limit,
                startDate=start_date,
                endDate=query_end_date,
            ),
            dataStatus=data_status,
            debugInfo=(
                IndexDetailDebugInfoDto(
                    modules=[self._module_debug(data_status, row_count=len(rows), missing_count=missing_count)],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _count_non_ma_missing(rows: list[Mapping[str, Any]]) -> int:
        field_names = _BASE_REQUIRED_FIELDS + _TECHNICAL_REQUIRED_FIELDS
        return sum(1 for row in rows for field_name in field_names if row.get(field_name) is None)

    def _has_ma_missing_after_effective_history(
        self,
        session: Session,
        *,
        ts_code: str,
        rows: list[Mapping[str, Any]],
    ) -> bool:
        if not any(row.get(field_name) is None for row in rows for field_name, _period in _MA_FIELDS):
            return False
        effective_count = self._query.count_effective_history_before(
            session,
            ts_code=ts_code,
            first_trade_date=rows[0]["trade_date"],
        )
        for row in rows:
            if row.get("close") is not None:
                effective_count += 1
            for field_name, period in _MA_FIELDS:
                if row.get(field_name) is None and effective_count >= period:
                    return True
        return False

    @staticmethod
    def _module_debug(
        data_status: IndexDetailDataStatusDto,
        *,
        row_count: int,
        missing_count: int | None,
    ) -> IndexDetailModuleDebugDto:
        return IndexDetailModuleDebugDto(
            module="kline",
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
