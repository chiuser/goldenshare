from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from src.biz.schemas.wealth.market.streak_ladder import (
    LadderV5PromotionLayerDto,
    LadderV5StockDto,
    StreakLadderV5Dto,
)


@dataclass(frozen=True, slots=True)
class StreakLadderRow:
    ts_code: str
    stock_name: str | None
    sector_name: str | None
    limit_type: str | None
    board_count: int
    latest_price: Decimal | None
    change_pct: Decimal | None
    fd_amount: Decimal | None
    limit_amount: Decimal | None
    open_times: int | None
    first_limit_time: str | None


@dataclass(frozen=True, slots=True)
class StreakLadderBuildResult:
    payload: StreakLadderV5Dto
    has_metric_missing: bool
    metric_missing_sample: str | None


class StreakLadderBuilder:
    """Build v5 streak-ladder payload from two-day row snapshots."""

    def build(
        self,
        *,
        trade_date: date,
        prev_trade_date: date,
        today_rows: list[StreakLadderRow],
        prev_rows: list[StreakLadderRow],
    ) -> StreakLadderBuildResult:
        today_by_code = {row.ts_code: row for row in today_rows}
        prev_by_level: dict[int, list[StreakLadderRow]] = {}
        today_by_level: dict[int, list[StreakLadderRow]] = {}
        for row in prev_rows:
            prev_by_level.setdefault(row.board_count, []).append(row)
        for row in today_rows:
            today_by_level.setdefault(row.board_count, []).append(row)

        highest = max((row.board_count for row in today_rows), default=0)

        has_metric_missing = False
        metric_missing_sample: str | None = None

        def to_stock(
            row: StreakLadderRow,
            *,
            advanced: bool,
            current_streak_level: int | None = None,
        ) -> LadderV5StockDto:
            nonlocal has_metric_missing, metric_missing_sample
            display_level = row.board_count if current_streak_level is None else current_streak_level
            latest_price = float(row.latest_price) if row.latest_price is not None else None
            change_pct = float(row.change_pct) if row.change_pct is not None else None
            limit_amount, limit_amount_label = _resolve_limit_amount(row)
            if (latest_price is None or change_pct is None or limit_amount is None) and metric_missing_sample is None:
                metric_missing_sample = row.ts_code
            if latest_price is None or change_pct is None or limit_amount is None:
                has_metric_missing = True
            return LadderV5StockDto(
                stockName=row.stock_name,
                stockCode=row.ts_code,
                latestPrice=latest_price,
                changePct=change_pct,
                sectorName=row.sector_name,
                limitAmount=float(limit_amount) if limit_amount is not None else None,
                limitAmountDisplayText=_format_limit_amount(limit_amount),
                limitAmountLabel=limit_amount_label,
                streakText=_build_streak_text(
                    current_streak_level=display_level,
                    source_board_count=row.board_count,
                ),
                openTimes=row.open_times,
                firstLimitTime=row.first_limit_time,
                currentStreakLevel=display_level,
                advanced=advanced,
            )

        above_five = sorted(
            [
                to_stock(row, advanced=True)
                for row in today_rows
                if row.board_count >= 6
            ],
            key=lambda item: (
                -item.currentStreakLevel,
                float("-inf") if item.changePct is None else -item.changePct,
                float("-inf") if item.latestPrice is None else -item.latestPrice,
                item.stockCode,
            ),
        )

        promotions: dict[int, LadderV5PromotionLayerDto] = {}
        max_normal = min(highest, 5)
        for level in range(max_normal, 1, -1):
            prev_candidates = prev_by_level.get(level - 1, [])
            today_candidates = {row.ts_code: row for row in today_by_level.get(level, [])}
            advanced_codes = {code for code in today_candidates if code in {item.ts_code for item in prev_candidates}}

            previous_stocks: list[LadderV5StockDto] = []
            for prev_row in prev_candidates:
                today_row = today_by_code.get(prev_row.ts_code)
                chosen_row = today_row or prev_row
                advanced = prev_row.ts_code in advanced_codes
                current_streak_level = today_row.board_count if today_row is not None else 0
                previous_stocks.append(
                    to_stock(
                        chosen_row,
                        advanced=advanced,
                        current_streak_level=current_streak_level,
                    )
                )

            current_stocks = [
                to_stock(today_candidates[code], advanced=True)
                for code in advanced_codes
            ]

            previous_stocks.sort(
                key=lambda item: (
                    0 if item.advanced else 1,
                    -item.currentStreakLevel,
                    float("-inf") if item.changePct is None else -item.changePct,
                    item.stockCode,
                )
            )
            current_stocks.sort(
                key=lambda item: (
                    float("-inf") if item.changePct is None else -item.changePct,
                    item.openTimes if item.openTimes is not None else 9_999,
                    item.stockCode,
                )
            )

            promotions[level] = LadderV5PromotionLayerDto(
                previousLabel=f"昨日{_to_chinese_level(level - 1)}",
                currentLabel=f"今日{_to_chinese_level(level)}",
                previousStocks=previous_stocks,
                currentStocks=current_stocks,
            )

        first_board = sorted(
            [to_stock(row, advanced=True) for row in today_rows if row.board_count == 1],
            key=lambda item: (
                float("-inf") if item.changePct is None else -item.changePct,
                item.openTimes if item.openTimes is not None else 9_999,
                item.stockCode,
            ),
        )

        payload = StreakLadderV5Dto(
            tradeDate=trade_date,
            prevTradeDate=prev_trade_date,
            highestStreakLevel=highest,
            aboveFive=above_five,
            promotions=promotions,
            firstBoard=first_board,
        )
        return StreakLadderBuildResult(
            payload=payload,
            has_metric_missing=has_metric_missing,
            metric_missing_sample=metric_missing_sample,
        )


def _to_chinese_level(level: int) -> str:
    if level <= 0:
        return "首板"
    if level == 1:
        return "首板"
    if level == 2:
        return "二板"
    if level == 3:
        return "三板"
    if level == 4:
        return "四板"
    if level == 5:
        return "五板"
    return f"{level}板"


def _resolve_limit_amount(row: StreakLadderRow) -> tuple[Decimal | None, str]:
    if row.limit_type == "D":
        return (row.limit_amount, "板上成交金额")
    return (row.fd_amount, "封单金额")


def _format_limit_amount(value: Decimal | None) -> str:
    if value is None:
        return "--"
    abs_value = abs(value)
    if abs_value >= Decimal("100000000"):
        amount = (value / Decimal("100000000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{amount}亿"
    if abs_value >= Decimal("10000"):
        amount = (value / Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{amount}万"
    amount = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return str(amount)


def _build_streak_text(*, current_streak_level: int, source_board_count: int) -> str:
    if current_streak_level <= 0:
        return f"昨日{_to_chinese_level(source_board_count)}"
    if current_streak_level == 1:
        return "首板"
    if current_streak_level <= 5:
        return f"{current_streak_level}连板"
    return f"{current_streak_level}板"
