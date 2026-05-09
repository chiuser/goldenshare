from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from src.biz.queries.wealth.market.summary.summary_metrics_query import SummaryMetricsSnapshot
from src.biz.schemas.wealth.market.summary import MarketSummaryCardDto


_YUAN_PER_YI = Decimal("100000000")
_THOUSAND_YUAN_PER_YI = Decimal("100000")


@dataclass(frozen=True, slots=True)
class SummaryTemplateVariables:
    major_index_tone: str
    up_down_tone: str
    turnover_tone: str
    limit_up_down_tone: str
    fund_flow_tone: str
    flow_pattern_tone: str


@dataclass(frozen=True, slots=True)
class SummaryCardBuildResult:
    cards: list[MarketSummaryCardDto]
    template_variables: SummaryTemplateVariables


class SummaryCardBuilder:
    _CARD_LABELS: dict[str, str] = {
        "majorIndexUpCount": "主要指数涨跌比",
        "riseFallCount": "上涨 / 下跌",
        "turnoverTotal": "成交总额",
        "marketNetFlow": "大盘资金",
        "limitUpDown": "涨停 / 跌停",
        "flatCount": "平盘家数",
    }

    def build(self, *, card_keys: tuple[str, ...], metrics: SummaryMetricsSnapshot) -> SummaryCardBuildResult:
        template_variables = self._build_template_variables(metrics=metrics)
        cards: list[MarketSummaryCardDto] = []
        for card_key in card_keys:
            card = self._build_one_card(card_key=card_key, metrics=metrics)
            if card is not None:
                cards.append(card)
        return SummaryCardBuildResult(cards=cards, template_variables=template_variables)

    def _build_one_card(self, *, card_key: str, metrics: SummaryMetricsSnapshot) -> MarketSummaryCardDto | None:
        label = self._CARD_LABELS.get(card_key)
        if label is None:
            return None

        if card_key == "majorIndexUpCount":
            major_total = metrics.major_index_total_count
            major_up = metrics.major_index_up_count
            major_down = max(major_total - major_up, 0)
            value = f"{major_up}:{major_down}" if major_total > 0 else "--"
            direction = self._compare_direction(major_up, major_down)
            return MarketSummaryCardDto(
                cardKey=card_key,
                label=label,
                value=value,
                subText="上涨数量:下跌数量",
                direction=direction,
            )

        if card_key == "riseFallCount":
            direction = self._compare_direction(metrics.up_count, metrics.down_count)
            return MarketSummaryCardDto(
                cardKey=card_key,
                label=label,
                value=f"{metrics.up_count} / {metrics.down_count}",
                subText=f"平盘 {metrics.flat_count}",
                direction=direction,
            )

        if card_key == "turnoverTotal":
            turnover_delta_amount = self._turnover_delta_amount(metrics.turnover_total, metrics.prev_turnover_total)
            turnover_delta = self._turnover_delta_pct(metrics.turnover_total, metrics.prev_turnover_total)
            direction = self._decimal_direction(turnover_delta_amount)
            sub_text = "较昨日：--" if turnover_delta_amount is None else f"较昨日：{self._format_signed_turnover_delta_billion(turnover_delta_amount)}"
            return MarketSummaryCardDto(
                cardKey=card_key,
                label=label,
                value=self._format_turnover_billion(metrics.turnover_total),
                subText=sub_text,
                direction=direction,
            )

        if card_key == "marketNetFlow":
            flow_direction = self._decimal_direction(metrics.market_net_amount)
            sub_text = self._net_flow_text(metrics.market_net_amount)
            return MarketSummaryCardDto(
                cardKey=card_key,
                label=label,
                value=self._format_signed_billion(metrics.market_net_amount),
                subText=sub_text,
                direction=flow_direction,
            )

        if card_key == "limitUpDown":
            direction = self._compare_direction(metrics.limit_up_count, metrics.limit_down_count)
            return MarketSummaryCardDto(
                cardKey=card_key,
                label=label,
                value=f"{metrics.limit_up_count} / {metrics.limit_down_count}",
                subText=f"炸板 {metrics.broken_limit_count}",
                direction=direction,
            )

        if card_key == "flatCount":
            return MarketSummaryCardDto(
                cardKey=card_key,
                label=label,
                value=str(metrics.flat_count),
                subText="当前日统计",
                direction="FLAT",
            )
        return None

    def _build_template_variables(self, *, metrics: SummaryMetricsSnapshot) -> SummaryTemplateVariables:
        major_tone = self._major_index_tone(metrics.major_index_up_count, metrics.major_index_total_count)
        up_down_tone = self._up_down_tone(metrics.up_count, metrics.down_count)
        turnover_tone = self._turnover_tone(metrics.turnover_total, metrics.prev_turnover_total)
        limit_tone = self._limit_tone(metrics.limit_up_count, metrics.limit_down_count)
        fund_flow_tone = self._fund_flow_tone(metrics.market_net_amount)
        return SummaryTemplateVariables(
            major_index_tone=major_tone,
            up_down_tone=up_down_tone,
            turnover_tone=turnover_tone,
            limit_up_down_tone=limit_tone,
            fund_flow_tone=fund_flow_tone,
            flow_pattern_tone="分化",
        )

    @staticmethod
    def _major_index_direction(up_count: int, total_count: int) -> str:
        if total_count <= 0:
            return "UNKNOWN"
        if up_count > total_count / 2:
            return "UP"
        if up_count < total_count / 2:
            return "DOWN"
        return "FLAT"

    @staticmethod
    def _major_index_tone(up_count: int, total_count: int) -> str:
        if total_count <= 0:
            return "暂无统计"
        if up_count > total_count / 2:
            return "多数上涨"
        if up_count < total_count / 2:
            return "多数下跌"
        return "涨跌分化"

    @staticmethod
    def _up_down_tone(up_count: int, down_count: int) -> str:
        if up_count > down_count:
            return "多于"
        if up_count < down_count:
            return "少于"
        return "持平于"

    @staticmethod
    def _limit_tone(limit_up_count: int, limit_down_count: int) -> str:
        if limit_up_count > limit_down_count:
            return "家数高于"
        if limit_up_count < limit_down_count:
            return "家数低于"
        return "家数接近"

    def _turnover_tone(self, turnover_total: Decimal | None, prev_turnover_total: Decimal | None) -> str:
        delta_pct = self._turnover_delta_pct(turnover_total, prev_turnover_total)
        if delta_pct is None:
            return "变化不明"
        if delta_pct >= Decimal("1.0"):
            return "放大"
        if delta_pct <= Decimal("-1.0"):
            return "缩量"
        return "基本持平"

    @staticmethod
    def _fund_flow_tone(net_amount: Decimal | None) -> str:
        if net_amount is None:
            return "数据缺失"
        if net_amount > 0:
            return "净流入"
        if net_amount < 0:
            return "净流出"
        return "基本平衡"

    @staticmethod
    def _compare_direction(left: int, right: int) -> str:
        if left > right:
            return "UP"
        if left < right:
            return "DOWN"
        return "FLAT"

    @staticmethod
    def _decimal_direction(value: Decimal | None) -> str:
        if value is None:
            return "UNKNOWN"
        if value > 0:
            return "UP"
        if value < 0:
            return "DOWN"
        return "FLAT"

    @staticmethod
    def _turnover_delta_pct(turnover_total: Decimal | None, prev_turnover_total: Decimal | None) -> Decimal | None:
        if turnover_total is None or prev_turnover_total is None or prev_turnover_total == 0:
            return None
        delta = (turnover_total - prev_turnover_total) / prev_turnover_total * Decimal("100")
        return delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _turnover_delta_amount(turnover_total: Decimal | None, prev_turnover_total: Decimal | None) -> Decimal | None:
        if turnover_total is None or prev_turnover_total is None:
            return None
        return turnover_total - prev_turnover_total

    @staticmethod
    def _signed_percent(value: Decimal) -> str:
        prefix = "+" if value > 0 else ""
        return f"{prefix}{value:.2f}%"

    @staticmethod
    def _format_turnover_billion(value: Decimal | None) -> str:
        if value is None:
            return "--"
        # equity_daily_bar.amount uses "thousand yuan" unit.
        billion = (value / _THOUSAND_YUAN_PER_YI).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{billion}亿"

    @staticmethod
    def _format_signed_turnover_delta_billion(value: Decimal) -> str:
        billion = (value / _THOUSAND_YUAN_PER_YI).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        prefix = "+" if billion > 0 else ""
        return f"{prefix}{billion}亿"

    @staticmethod
    def _format_signed_billion(value: Decimal | None) -> str:
        if value is None:
            return "--"
        billion = (value / _YUAN_PER_YI).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        prefix = "+" if billion > 0 else ""
        return f"{prefix}{billion}亿"

    @staticmethod
    def _net_flow_text(net_amount: Decimal | None) -> str:
        if net_amount is None:
            return "数据缺失"
        if net_amount > 0:
            return "净流入"
        if net_amount < 0:
            return "净流出"
        return "基本平衡"
