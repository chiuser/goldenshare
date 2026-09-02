from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndexTurnoverInsightIdentity:
    ts_code: str
    index_name: str


INDEX_TURNOVER_INSIGHT_UNIVERSE: tuple[IndexTurnoverInsightIdentity, ...] = (
    IndexTurnoverInsightIdentity("000001.SH", "上证指数"),
    IndexTurnoverInsightIdentity("399001.SZ", "深证成指"),
    IndexTurnoverInsightIdentity("399006.SZ", "创业板"),
    IndexTurnoverInsightIdentity("000688.SH", "科创50"),
    IndexTurnoverInsightIdentity("000680.SH", "科创综指"),
    IndexTurnoverInsightIdentity("000905.SH", "中证500"),
    IndexTurnoverInsightIdentity("000510.SH", "中证A500"),
    IndexTurnoverInsightIdentity("000300.SH", "沪深300"),
    IndexTurnoverInsightIdentity("000852.SH", "中证1000"),
    IndexTurnoverInsightIdentity("000016.SH", "上证50"),
)
