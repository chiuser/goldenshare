"""Shared classification for preparation and calculation; never leak SQL/input."""
from sqlalchemy.exc import DBAPIError

from .calculation_inputs import CalculationDataUnavailable
from .market_facts import MarketFactsUnavailable


def classify_calculation_failure(error):
    if isinstance(error, (MarketFactsUnavailable, CalculationDataUnavailable)):
        return "WAITING_DATA", "核算所需行情或交易日历暂未就绪。"
    if isinstance(error, TimeoutError):
        return "TRANSIENT", "本次处理超时，稍后重试。"
    if isinstance(error, DBAPIError):
        state = getattr(error.orig, "sqlstate", None)
        if state in ("40001", "40P01", "55P03", "57014") or (
                isinstance(state, str) and state.startswith("08")):
            return "TRANSIENT", "数据库暂时不可用，稍后重试。"
    return "FAILED", "本次核算核验未通过，已停止自动重试。"
