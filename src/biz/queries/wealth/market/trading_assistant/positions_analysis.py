"""Current-held-stock analysis, reusing the fixed positions projection."""
from collections import defaultdict

from src.biz.schemas.wealth.market.trading_assistant.positions import (
    ContributionExtreme, HoldingContributions, IndustryAllocation, PositionsAnalysis)
from src.biz.schemas.wealth.market.trading_assistant.value_types import decimal_cents
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from .positions_projection import weight


def contributions(rows, field, *, unavailable=False, status="Partial", reason=None):
    known = [(row, decimal_cents(getattr(row, field))) for row in rows
             if not unavailable and getattr(row, field) is not None]
    unknown = len(rows) - len(known)
    positive = sorted([(row, value) for row, value in known if value > 0],
                      key=lambda item: (-item[1], item[0].stockRef.tsCode))
    negative = sorted([(row, value) for row, value in known if value < 0],
                      key=lambda item: (item[1], item[0].stockRef.tsCode))

    def extreme(items):
        if unknown or not items:
            return None
        row, value = items[0]
        return ContributionExtreme(stockRef=row.stockRef, profitAmount=format_cents(value))

    return HoldingContributions(maxPositive=extreme(positive), maxNegative=extreme(negative),
        positiveCount=len(positive), negativeCount=len(negative), flatCount=sum(value == 0 for _, value in known),
        positiveAmount=format_cents(sum(value for _, value in positive)),
        negativeAmount=format_cents(sum(value for _, value in negative)), unknownCount=unknown,
        dataStatus=(status if status not in ("Ready", "Empty") else "Partial") if unknown else "Ready" if rows else "Empty",
        reason=(reason or "部分持仓收益尚未就绪，合计仅含已知部分") if unknown else None)


def industry_allocations(rows, memberships, denominator):
    grouped = defaultdict(list)
    for row in rows:
        grouped[memberships[row.stockRef.tsCode].code].append(row)
    result = []
    for code, members in grouped.items():
        names = {memberships[row.stockRef.tsCode].name for row in members}
        if code is not None and (len(names) != 1 or None in names):
            raise ValueError("A dated industry code has inconsistent names")
        value = (sum(decimal_cents(row.marketValue) for row in members)
                 if all(row.marketValue is not None for row in members) else None)
        result.append(IndustryAllocation(industryCode=code, industryName=next(iter(names)) if code else "未分类",
            marketValue=None if value is None else format_cents(value), weightPct=weight(value, denominator),
            classificationStatus="CLASSIFIED" if code else "UNCLASSIFIED"))
    return sorted(result, key=lambda item: (item.marketValue is None,
        -decimal_cents(item.marketValue) if item.marketValue is not None else 0, item.industryCode or "~"))


class PositionsAnalysisQuery:
    def __init__(self, positions):
        self.positions = positions

    def read(self, session, *, owner_id, account_mode, basis, cutoff, deadline):
        data = self.positions.read(session, owner_id=owner_id, account_mode=account_mode,
                                   basis=basis, cutoff=cutoff, deadline=deadline)
        memberships = self.positions.industry.read(session, codes=[row.stockRef.tsCode for row in data.items],
            trade_date=cutoff.valuation_date, deadline=deadline)
        total = None if data.summary.stockMarketValue is None else decimal_cents(data.summary.stockMarketValue)
        top5 = (sum(decimal_cents(row.marketValue) for row in data.items[:5]) if total is not None else None)
        unavailable = cutoff.valuation_date != cutoff.today or cutoff.reason is not None
        return PositionsAnalysis(scope=data.scope, readContext=data.readContext, coverage=data.coverage,
            largestPosition=data.summary.largestPosition, top3WeightPct=data.summary.top3WeightPct,
            top5WeightPct=weight(top5, total), cashWeightPct=data.summary.cashWeightPct, cashAmount=data.summary.cashAmount,
            industries=industry_allocations(data.items, memberships, total),
            cumulative=contributions(data.items, "holdingProfitAmount", status=data.coverage.dataStatus,
                                     reason=data.coverage.reason),
            daily=contributions(data.items, "dayProfitAmount", unavailable=unavailable,
                status="Delayed" if unavailable else data.coverage.dataStatus,
                reason="当日收盘结果尚未就绪" if unavailable else data.coverage.reason))
