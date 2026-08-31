from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    TEMPLATE_KEY,
    TEMPLATE_VERSION,
)


class SectorDailyInsightTemplateRenderer:
    """Render deterministic facts only; no inferred cause or forward-looking claim."""

    def render(
        self,
        *,
        category: str,
        sector_name: str,
        values: Mapping[str, object],
        evidence_types: tuple[str, ...],
    ) -> tuple[str, str, str]:
        if category == "HEAD_GAINER":
            text = f"{sector_name}当日上涨{self._pct(values.get('return_pct_1d'))}。"
        elif category == "HEAD_LOSER":
            text = f"{sector_name}当日下跌{self._pct(values.get('return_pct_1d'), absolute=True)}。"
        elif category == "STRENGTHENING":
            text = (
                f"{sector_name}的20日同层级百分位较上一交易日提高"
                f"{self._pct(values.get('percentile_change_pp'), suffix='个百分点')}。"
            )
        elif category == "WEAKENING":
            text = (
                f"{sector_name}的20日同层级百分位较上一交易日下降"
                f"{self._pct(values.get('percentile_change_pp'), absolute=True, suffix='个百分点')}。"
            )
        else:
            raise ValueError(f"unsupported insight category: {category}")
        if evidence_types:
            text += f" 佐证：{'、'.join(evidence_types)}。"
        return TEMPLATE_KEY, TEMPLATE_VERSION, text

    @staticmethod
    def _pct(value: object, *, absolute: bool = False, suffix: str = "%") -> str:
        if not isinstance(value, Decimal) or not value.is_finite():
            return f"--{suffix}"
        normalized = abs(value) if absolute else value
        return f"{normalized.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}{suffix}"
