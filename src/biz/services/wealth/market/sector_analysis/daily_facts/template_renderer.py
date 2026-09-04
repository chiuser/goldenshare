from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    TEMPLATE_KEY,
    TEMPLATE_VERSION,
)


class SectorDailyInsightTemplateRenderer:
    """Render deterministic facts only; no inferred cause or forward-looking claim."""

    _STATES = {
        "PRICE_VOLUME": ("price_volume_state", "20日量价状态", {
            "JOINT": "量价共同增强", "PRICE_ONLY": "价格增强",
            "AMOUNT_ONLY": "成交增强", "NEUTRAL": "量价均不明显",
        }),
        "DUAL_MOMENTUM": ("dual_qualification_20d_80", "20日双动量", {
            "QUALIFIED": "符合条件", "NOT_QUALIFIED": "不符合条件",
        }),
        "RELATIVE_ROTATION": ("rotation_status_20d", "20日相对轮动", {
            "LEADING_IMPROVING": "领先且改善", "WEAK_IMPROVING": "偏弱但改善",
            "STRONG_NOT_IMPROVING": "强势但未改善", "WEAK_NOT_IMPROVING": "偏弱且未改善",
        }),
    }
    _BREADTH = {
        "MEMBER_BREADTH": ("member_up_pct", "上涨成分股占比"),
        "TURNOVER_BREADTH": ("turnover_up_pct", "上涨成分股成交额占比"),
        "MA20_BREADTH": ("ma20_above_pct", "站上MA20成分股占比"),
    }
    _PRIORITY = (
        "PRICE_VOLUME", "MEMBER_BREADTH", "TURNOVER_BREADTH",
        "DUAL_MOMENTUM", "RELATIVE_ROTATION", "MA20_BREADTH",
    )

    @classmethod
    def select_evidence(
        cls, *, values: Mapping[str, object], qualifications: Mapping[str, object],
        suffix: str = "current",
    ) -> tuple[str, ...]:
        """Qualification is per metric and per day, not inferred from a non-null value."""
        available = []
        for kind in cls._PRIORITY:
            if kind in cls._STATES:
                field, _, labels = cls._STATES[kind]
                if values.get(f"{field}_{suffix}") in labels:
                    available.append(kind)
            else:
                field, _ = cls._BREADTH[kind]
                value = values.get(f"{field}_{suffix}")
                if qualifications.get(kind) == "ELIGIBLE" and cls._finite(value) and 0 <= value <= 100:
                    available.append(kind)
        return tuple(available)

    def render(
        self,
        *,
        category: str,
        sector_name: str,
        industry_level: int,
        values: Mapping[str, object],
        evidence_types: tuple[str, ...],
        previous_evidence_types: tuple[str, ...],
    ) -> tuple[str, str, str]:
        if len(evidence_types) > 2 or evidence_types != tuple(k for k in self._PRIORITY if k in evidence_types):
            raise ValueError("insight evidence must be unique, ordered and limited to two")
        if industry_level not in (1, 2, 3):
            raise ValueError("unsupported industry level")
        rank = self._rank(values, "current")
        previous_rank = self._rank(values, "previous")
        if category in ("HEAD_GAINER", "HEAD_LOSER"):
            parts = [f"{sector_name}当日{self._return(values.get('return_pct_1d'))}"]
            if rank:
                level_name = {1: "一级", 2: "二级", 3: "三级"}[industry_level]
                parts.append(f"20日强度位列{level_name}行业第{rank}")
            if self._finite(values.get("return_pct_5d")):
                parts.append(f"近5日{self._return(values['return_pct_5d'])}")
        elif category in ("STRENGTHENING", "WEAKENING"):
            if not rank or not previous_rank:
                raise ValueError("change insight requires both ranks and denominators")
            delta = values.get("percentile_change_pp")
            change = "提高" if category == "STRENGTHENING" else "下降"
            amount = self._pct(delta, absolute=True, suffix="个百分点")
            event_type = values.get("event_type")
            if event_type in ("COUNTER_TREND_STRENGTHENING", "RISING_BUT_WEAKENING"):
                relation = "相对抗跌" if category == "STRENGTHENING" else "相对滞后"
                parts = [
                    f"{sector_name}当日{self._return(values.get('return_pct_1d'))}",
                    f"但20日同组强度百分位{change}{amount}，属于{relation}",
                    f"20日名次由第{previous_rank}变为第{rank}",
                ]
            else:
                parts = [
                    f"{sector_name}20日强度由第{previous_rank}变为第{rank}",
                    f"强度百分位{change}{amount}",
                ]
        else:
            raise ValueError(f"unsupported insight category: {category}")
        parts.extend(self._evidence_text(kind, values, kind in previous_evidence_types) for kind in evidence_types)
        text = "；".join(parts) + "。"
        return TEMPLATE_KEY, TEMPLATE_VERSION, text

    @classmethod
    def _evidence_text(cls, kind: str, values: Mapping[str, object], previous_available: bool) -> str:
        if kind in cls._STATES:
            field, label, labels = cls._STATES[kind]
            current, previous = values.get(f"{field}_current"), values.get(f"{field}_previous")
            if current not in labels:
                raise ValueError("unavailable state cannot be insight evidence")
            if previous_available and previous in labels and previous != current:
                return f"{label}由“{labels[previous]}”变为“{labels[current]}”"
            return f"{label}为“{labels[current]}”"
        field, label = cls._BREADTH[kind]
        current, previous = values.get(f"{field}_current"), values.get(f"{field}_previous")
        current_text = cls._pct(current)
        if previous_available and cls._finite(previous) and cls._pct(previous) != current_text:
            direction = "升至" if current > previous else "降至"
            return f"{label}由{cls._pct(previous)}{direction}{current_text}"
        return f"{label}为{current_text}"

    @staticmethod
    def _rank(values: Mapping[str, object], prefix: str) -> str | None:
        rank, count = values.get(f"{prefix}_rank_20d"), values.get(f"{prefix}_rankable_count_20d")
        if type(rank) is int and type(count) is int and 1 <= rank <= count:
            return f"{rank}/{count}"
        return None

    @staticmethod
    def _finite(value: object) -> bool:
        return isinstance(value, Decimal) and value.is_finite()

    @classmethod
    def _return(cls, value: object) -> str:
        if not cls._finite(value):
            raise ValueError("insight return must be finite")
        if value == 0:
            return "持平"
        return ("上涨" if value > 0 else "下跌") + cls._pct(value, absolute=True)

    @staticmethod
    def _pct(value: object, *, absolute: bool = False, suffix: str = "%") -> str:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("insight number must be finite")
        normalized = abs(value) if absolute else value
        rounded = normalized.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{abs(rounded) if rounded == 0 else rounded}{suffix}"
