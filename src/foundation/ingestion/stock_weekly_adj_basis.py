"""Indexed per-stock actual trading dates and exact same-day factors (LLD 11.2)."""

from sqlalchemy import literal, select, tuple_, union_all

from src.foundation.datasets.stock_weekly_adj_contracts import WeeklyAdjContractError
from src.foundation.models.core_serving.equity_adj_factor import (
    EquityAdjFactor as Factor,
)
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar as Daily


def load_daily_basis_dates(session, lookups):
    """Shared date query for week-price and target roles; caller bounds each block."""
    queries = []
    for code, role, begin, end in lookups:
        query = select(Daily.trade_date).where(
            Daily.ts_code == code,
            Daily.source == "tushare",
            Daily.trade_date <= end,
        )
        if begin is not None:
            query = query.where(Daily.trade_date >= begin)
        queries.append(
            select(
                literal(code),
                literal(role),
                query.order_by(Daily.trade_date.desc()).limit(1).scalar_subquery(),
            )
        )
    return {
        (code, role): day for code, role, day in session.execute(union_all(*queries))
    }


def load_weekly_factor_targets(session, codes, cutoff, *, check=lambda: None):
    result = {}
    codes = sorted(set(codes))
    for start in range(0, len(codes), 128):
        check()
        chunk = codes[start : start + 128]
        dates = load_daily_basis_dates(
            session, [(code, "target", None, cutoff) for code in chunk]
        )
        keys = [
            (code, dates[(code, "target")]) for code in chunk if dates[(code, "target")]
        ]
        factors = (
            dict(
                session.execute(
                    select(Factor.ts_code, Factor.adj_factor).where(
                        tuple_(Factor.ts_code, Factor.trade_date).in_(keys)
                    )
                ).all()
            )
            if keys
            else {}
        )
        for code in chunk:
            day, value = dates[(code, "target")], factors.get(code)
            if day is None or value is None or not value.is_finite() or value <= 0:
                raise WeeklyAdjContractError(
                    f"{code} 缺少最后实际交易日或同日有效因子",
                    "weekly_adj.factor_coverage_missing",
                )
            result[code] = (day, value)
        check()
    return result
