from __future__ import annotations

from src.foundation.models.core_serving_light.bse_mapping import BseMappingLight
from src.foundation.models.core_serving_light.cctv_news import CctvNewsLight
from src.foundation.models.core_serving_light.equity_daily_bar_light import EquityDailyBarLight
from src.foundation.models.core_serving_light.major_news import MajorNewsLight
from src.foundation.models.core_serving_light.namechange import NamechangeLight
from src.foundation.models.core_serving_light.news import NewsLight
from src.foundation.models.core_serving_light.st import StLight
from src.foundation.models.core_serving_light.stock_company import StockCompanyLight

__all__ = [
    "BseMappingLight",
    "CctvNewsLight",
    "EquityDailyBarLight",
    "MajorNewsLight",
    "NamechangeLight",
    "NewsLight",
    "StLight",
    "StockCompanyLight",
]
