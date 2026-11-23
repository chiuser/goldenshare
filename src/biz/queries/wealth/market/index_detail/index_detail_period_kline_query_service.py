from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from goldenshare_technical_indicators.contracts import CalculationResult

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext
from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import (
    IndexDetailKlineQueryService, apply_calculated_kline_factors, count_calculated_kline_missing,
)
from src.biz.schemas.wealth.market.index_detail import (
    IndexDetailIndexRefDto, IndexDetailKlineResponseDto, IndexDetailSseKlineMetaDto,
)
from src.biz.services.wealth.market.index_detail.index_detail_field_mapper import build_kline_bar, build_page_context
from src.biz.services.wealth.market.index_detail.index_detail_universe import IndexDetailQueryError, IndexDetailRequestError
from src.foundation.clients.technical_indicator_index_period import check_period_key


@dataclass(frozen=True)
class IndexPeriodPage:
    context: MarketPageContext
    index_ref: IndexDetailIndexRefDto
    rows: tuple[Mapping[str, Any], ...]
    periods: tuple[date, ...]
    cutoffs: tuple[date, ...]
    end: date
    expected: date
    next_end: date | None
    result: CalculationResult | None = None


class IndexDetailPeriodKlineQueryService(IndexDetailKlineQueryService):
    """Select one index-period page and join the aligned price and indicator result."""

    def read_page(self, session, *, source, ts_code, period, start_date, end_date, limit, control,
                  calculate_recent=None):
        self._universe_service.require_supported(ts_code)
        control.check_active()
        if self._daily_lake is None:
            identity_row = self._query.load_identity(session, ts_code=ts_code)
            context = self._context_query.resolve_context(session, market="CN_A", requested_trade_date=end_date)
        else:
            identity_row = self._daily_lake.index_identity(ts_code)
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            control.check_active()
            calendar = self._daily_lake.calendar_rows(
                end=end_date or now.date(), recent_open_days=2, timeout_seconds=control.work_until - control.clock(),
            )
            context = self._context_query.resolve_local_context(
                None, market="CN_A", requested_trade_date=end_date, now=now, calendar_rows=calendar,
            )
        identity = self._build_identity_or_raise(identity_row, ts_code=ts_code)
        lookup = dict(session=session, period=period, ts_code=ts_code, control=control)
        end = end_date
        if end is None:
            control.check_active()
            quote = self._query.load_latest_quote(session, ts_code=ts_code, expected_trade_date=context.trade_date)
            if quote is None:
                raise IndexDetailQueryError(f"{ts_code} 无可用指数日行情截止日")
            end = quote["trade_date"]
        if start_date is not None and start_date > end:
            raise IndexDetailRequestError("startDate 不能晚于 endDate")
        expected = end if end_date is None or context.is_trading_day else context.prev_trade_date
        facts = result = next_end = None
        if calculate_recent is None:
            recent = source.index_period_page(**lookup, start=start_date, end=end, limit=limit + 1)
            ordered = tuple(reversed(recent))
            labels = tuple(check_period_key((row["period_start_date"], row["trade_date"]), period) for row in ordered)
            cutoffs = tuple(row["trade_date"] for row in ordered)
        else:
            calculation = calculate_recent(start_date, end, limit)
            result, facts = calculation.result, calculation.source_facts
            labels = tuple(bar.position for bar in facts.target_bars)
            cutoffs = tuple(bar.trade_date for bar in facts.target_bars)
            ordered = tuple(dict(pre_close=bar.pre_close, change_amount=bar.change_amount, pct_chg=bar.pct_chg)
                            for bar in facts.target_bars)
            next_end = facts.previous_target_date
        control.check_active()
        if any(a >= b for a, b in zip(labels, labels[1:])) or any(a >= b for a, b in zip(cutoffs, cutoffs[1:])):
            raise IndexDetailQueryError(f"{ts_code} {period} 行情日期重复或顺序错误")

        if not ordered:
            if expected is not None and (start_date is None or expected >= start_date):
                if facts is None:
                    first = source.index_period_boundary(**lookup, latest=False)
                    first_period = (
                        check_period_key((first["period_start_date"], first["trade_date"]), period)
                        if first is not None else None
                    )
                else:
                    first_period = facts.first_available_period
                if first_period is None or end >= first_period:
                    raise IndexDetailQueryError(f"{ts_code} {period} 应有行情未读到")
            else:
                expected = end
        else:
            if expected is None or cutoffs[-1] > expected:
                raise IndexDetailQueryError(f"{ts_code} {period} 行情日期与交易日历不一致")
            if cutoffs[-1] < expected:
                if facts is None:
                    latest = source.index_period_boundary(**lookup, latest=True)
                    latest_cutoff = latest["trade_date"] if latest is not None else None
                else:
                    latest_cutoff = facts.latest_available_date
                if latest_cutoff is None or latest_cutoff >= expected:
                    raise IndexDetailQueryError(f"{ts_code} {period} 已发布范围内缺少行情")
                if facts is None:
                    check_period_key((latest["period_start_date"], latest["trade_date"]), period)
            if len(ordered) > limit:
                next_end = cutoffs[0]
                ordered, labels, cutoffs = ordered[1:], labels[1:], cutoffs[1:]
        return IndexPeriodPage(
            context, IndexDetailIndexRefDto(tsCode=identity.tsCode, name=identity.name),
            ordered, labels, cutoffs, end, expected, next_end, result,
        )

    def query_period_kline(self, page, *, ts_code, period, start_date, limit, calculate=None):
        rows, missing_count = [], None
        if page.rows:
            result = page.result if calculate is None else calculate(page.periods[0], page.cutoffs[-1])
            if (result.times != page.periods or result.source_as_of != page.cutoffs
                    or result.range.count != len(page.rows)):
                raise IndexDetailQueryError(f"{ts_code} {period} 指标结果日期或根数与本页行情不一致")
            price = next(item for item in result.calculations if item.calculation_id == "price")
            prices = dict(price.fields)
            fields = ("open", "high", "low", "close", "volume", "amount")
            if any(name not in prices or len(prices[name]) != len(page.rows) for name in fields):
                raise IndexDetailQueryError(f"{ts_code} {period} 行情结果字段不完整")
            pct_scale = 100 if self._daily_lake is None else 1
            for index, (day, auxiliary) in enumerate(zip(result.source_as_of, page.rows, strict=True)):
                volume, amount = prices["volume"][index], prices["amount"][index]
                pct = auxiliary["pct_chg"]
                rows.append({
                    "trade_date": day,
                    **{name: prices[name][index] for name in fields[:4]},
                    "vol": None if volume is None else volume / 100,
                    "amount": None if amount is None else amount / 1000,
                    "pre_close": auxiliary["pre_close"],
                    "change": auxiliary["change_amount"],
                    "pct_change": None if pct is None else pct * pct_scale,
                })
            apply_calculated_kline_factors(ts_code, rows, tuple(item for item in result.calculations if item is not price))
            missing_count = count_calculated_kline_missing(rows, result.statistics.source_rows - result.range.count)
        data_status = self._status_resolver.resolve(
            expected_trade_date=page.expected, observed_trade_date=page.cutoffs[-1] if rows else None,
            empty=not rows, partial=bool(missing_count),
        )
        return IndexDetailKlineResponseDto(
            pageContext=build_page_context(page.context), indexRef=page.index_ref, period=period,
            bars=[build_kline_bar(row) for row in rows],
            meta=IndexDetailSseKlineMetaDto(
                count=len(rows), limit=limit, startDate=start_date, endDate=page.end, nextEndDate=page.next_end,
            ),
            dataStatus=data_status,
        ), missing_count
