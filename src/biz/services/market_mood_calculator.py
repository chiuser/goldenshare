from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import ceil
from statistics import median
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_stk_limit import EquityStkLimit
from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.security_serving import Security

DEFAULT_INDEX_BENCHMARKS: dict[str, str] = {
    "沪深300": "000300.SH",
    "中证1000": "000852.SH",
    "中证500": "000905.SH",
    "中证A500": "000510.CSI",
    "上证50": "000016.SH",
    "北证50": "899050.BJ",
    "科创50": "000688.SH",
    "上证指数": "000001.SH",
    "深证成指": "399001.SZ",
    "创业板指": "399006.SZ",
}


@dataclass(slots=True)
class MarketMoodResult:
    trade_date: date
    temperature: dict[str, Any]
    emotion: dict[str, Any]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date.isoformat(),
            "temperature": _jsonable(self.temperature),
            "emotion": _jsonable(self.emotion),
            "diagnostics": _jsonable(self.diagnostics),
        }


class MarketMoodCalculator:
    def __init__(
        self,
        *,
        sample_threshold: int = 5,
        tick: Decimal = Decimal("0.01"),
        board_lookback_days: int = 120,
        theme_min_members: int = 10,
        index_benchmarks: dict[str, str] | None = None,
    ) -> None:
        self.sample_threshold = sample_threshold
        self.tick = tick
        self.board_lookback_days = board_lookback_days
        self.theme_min_members = theme_min_members
        self.index_benchmarks = index_benchmarks or dict(DEFAULT_INDEX_BENCHMARKS)

    def calculate_for_trade_date(
        self,
        session: Session,
        *,
        trade_date: date,
        exchange: str = "SSE",
    ) -> MarketMoodResult:
        open_dates = self._load_open_dates(session, trade_date=trade_date, exchange=exchange, limit=320)
        if trade_date not in open_dates:
            raise ValueError(f"{trade_date.isoformat()} 不是交易日，无法计算。")
        idx_t = open_dates.index(trade_date)
        if idx_t < 21:
            raise ValueError("历史交易日不足 21 天，无法计算高位崩塌率。")

        prev_trade_date = open_dates[idx_t - 1]
        ret20_base_date = open_dates[idx_t - 21]
        history_20_dates = open_dates[idx_t - 20 : idx_t]

        board_start_idx = max(0, idx_t - self.board_lookback_days)
        board_dates = open_dates[board_start_idx : idx_t + 1]
        board_start_date = board_dates[0]

        rows_by_date = self._load_daily_joined_rows(
            session,
            start_date=board_start_date,
            end_date=trade_date,
        )
        list_threshold_by_date = _build_list_threshold_map(open_dates=open_dates)
        day_metrics: dict[date, dict[str, dict[str, Any]]] = {}
        for current_date in board_dates:
            day_metrics[current_date] = self._build_day_metrics(
                rows_by_code=rows_by_date.get(current_date, {}),
                list_threshold_date=list_threshold_by_date.get(current_date),
            )

        board_count_by_date = _build_board_count_series(
            board_dates=board_dates,
            day_metrics=day_metrics,
        )

        today = day_metrics[trade_date]["eligible"]
        prev = day_metrics[prev_trade_date]["eligible"]
        today_codes = set(today)
        prev_codes = set(prev)
        universe_size = len(today_codes)

        market_amount_today = _sum_decimal([metric["amount"] for metric in today.values()])
        market_amount_history = []
        for d in history_20_dates:
            day_amount = _sum_decimal([metric["amount"] for metric in day_metrics.get(d, {}).get("eligible", {}).values()])
            if day_amount is not None:
                market_amount_history.append(day_amount)
        market_amount_ratio_20 = _safe_ratio(
            market_amount_today,
            _median_decimal(market_amount_history),
            min_count=self.sample_threshold,
            count=len(market_amount_history),
        )

        red_count = sum(1 for metric in today.values() if metric["red"])
        strong3_count = sum(1 for metric in today.values() if metric["r"] is not None and metric["r"] >= Decimal("0.03"))
        weak3_count = sum(1 for metric in today.values() if metric["r"] is not None and metric["r"] <= Decimal("-0.03"))
        limit_down_count = sum(1 for metric in today.values() if metric["close_down"])

        mainline = self._compute_mainline_metrics(
            session=session,
            trade_date=trade_date,
            history_dates=history_20_dates,
            day_metrics=day_metrics,
            market_amount_today=market_amount_today,
        )

        high_collapse_rate, high_pool_size, collapse_base_count = self._compute_high_collapse_rate(
            session=session,
            trade_date=trade_date,
            prev_trade_date=prev_trade_date,
            ret20_base_date=ret20_base_date,
            rows_by_date=rows_by_date,
            today_eligible=today,
            prev_eligible=prev,
        )

        board_today = board_count_by_date.get(trade_date, {})
        board_prev = board_count_by_date.get(prev_trade_date, {})

        tradable_up_count = sum(1 for metric in today.values() if metric["tradable_up"])
        tradable_touch_count = sum(1 for metric in today.values() if metric["tradable_touch_up"])
        blast_count = sum(1 for metric in today.values() if metric["blast"])

        board2plus_count = sum(
            1 for ts_code in today_codes if board_today.get(ts_code, 0) >= 2
        )
        max_board = max(board_today.values(), default=0)

        advance_base_codes = {ts_code for ts_code in today_codes & prev_codes if prev[ts_code]["close_up"]}
        advance_success_count = sum(1 for ts_code in advance_base_codes if today[ts_code]["close_up"])

        ypool_codes = {
            ts_code
            for ts_code in today_codes & prev_codes
            if prev[ts_code]["tradable_up"]
        }
        open_premium_values = []
        close_premium_values = []
        for ts_code in ypool_codes:
            prev_close = prev[ts_code]["close"]
            open_today = today[ts_code]["open"]
            close_today = today[ts_code]["close"]
            if prev_close in (None, Decimal("0")):
                continue
            if open_today is not None:
                open_premium_values.append((open_today / prev_close) - Decimal("1"))
            if close_today is not None:
                close_premium_values.append((close_today / prev_close) - Decimal("1"))

        big_loss_count = sum(
            1
            for metric in today.values()
            if metric["tradable_touch_up"]
            and metric["r"] is not None
            and metric["limit_pct"] is not None
            and metric["r"] <= Decimal("-0.3") * metric["limit_pct"]
        )

        high_board_prev_codes = {ts_code for ts_code, count in board_prev.items() if count >= 2}
        high_board_base_codes = high_board_prev_codes & today_codes
        high_board_kill_count = sum(
            1
            for ts_code in high_board_base_codes
            if (not today[ts_code]["close_up"]) and today[ts_code]["r"] is not None and today[ts_code]["r"] < 0
        )

        bucket_codes = {
            "10": {ts_code for ts_code, metric in today.items() if metric["bucket"] == "10"},
            "20": {ts_code for ts_code, metric in today.items() if metric["bucket"] == "20"},
        }
        bucket_stats = {
            bucket: self._compute_bucket_stats(
                bucket_codes=codes,
                today=today,
                prev=prev,
                prev_codes=prev_codes,
            )
            for bucket, codes in bucket_codes.items()
        }
        structure_tag = _resolve_structure_tag(
            msi10=bucket_stats["10"]["msi"],
            msi20=bucket_stats["20"]["msi"],
        )

        index_returns = self._load_index_returns(session, trade_date=trade_date, prev_trade_date=prev_trade_date)
        small_vs_large = None
        if index_returns.get("中证1000") is not None and index_returns.get("沪深300") is not None:
            small_vs_large = index_returns["中证1000"] - index_returns["沪深300"]

        temperature = {
            "universe_size": universe_size,
            "red_rate": _ratio_from_counts(red_count, universe_size, self.sample_threshold),
            "median_return": _median_metric(today, "r", self.sample_threshold),
            "strong3_rate": _ratio_from_counts(strong3_count, universe_size, self.sample_threshold),
            "weak3_rate": _ratio_from_counts(weak3_count, universe_size, self.sample_threshold),
            "market_amount": market_amount_today,
            "market_amount_ratio_20": market_amount_ratio_20,
            "small_vs_large": small_vs_large,
            "top3_mainlines": mainline["top3_mainlines"],
            "mainline_concentration": mainline["mainline_concentration"],
            "limit_down_rate": _ratio_from_counts(limit_down_count, universe_size, self.sample_threshold),
            "high_collapse_rate": high_collapse_rate,
        }

        emotion = {
            "universe_size": universe_size,
            "tradable_up_count": tradable_up_count,
            "tradable_up_rate": _ratio_from_counts(tradable_up_count, universe_size, self.sample_threshold),
            "seal_success_rate": _ratio_from_counts(tradable_up_count, tradable_touch_count, self.sample_threshold),
            "blast_rate": _ratio_from_counts(blast_count, tradable_touch_count, self.sample_threshold),
            "board2plus_count": board2plus_count,
            "board2plus_rate": _ratio_from_counts(board2plus_count, universe_size, self.sample_threshold),
            "max_board": max_board,
            "advance_rate": _ratio_from_counts(advance_success_count, len(advance_base_codes), self.sample_threshold),
            "open_premium": _median_with_threshold(open_premium_values, self.sample_threshold),
            "close_premium": _median_with_threshold(close_premium_values, self.sample_threshold),
            "big_loss_rate": _ratio_from_counts(big_loss_count, tradable_touch_count, self.sample_threshold),
            "high_board_break_kill_rate": _ratio_from_counts(
                high_board_kill_count,
                len(high_board_base_codes),
                self.sample_threshold,
            ),
            "msi10": bucket_stats["10"]["msi"],
            "msi20": bucket_stats["20"]["msi"],
            "structure_tag": structure_tag,
        }

        diagnostics = {
            "prev_trade_date": prev_trade_date,
            "ret20_base_date": ret20_base_date,
            "sample_threshold": self.sample_threshold,
            "theme_day_coverage": mainline["theme_day_coverage"],
            "high_pool_size": high_pool_size,
            "high_pool_effective_size": collapse_base_count,
            "index_returns": index_returns,
            "bucket_stats": bucket_stats,
        }

        return MarketMoodResult(
            trade_date=trade_date,
            temperature=temperature,
            emotion=emotion,
            diagnostics=diagnostics,
        )

    def _load_open_dates(self, session: Session, *, trade_date: date, exchange: str, limit: int) -> list[date]:
        stmt = (
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit)
        )
        return list(reversed(list(session.scalars(stmt))))

    def _load_daily_joined_rows(
        self,
        session: Session,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[date, dict[str, dict[str, Any]]]:
        st_subq = (
            select(
                EquityStockSt.trade_date.label("trade_date"),
                EquityStockSt.ts_code.label("ts_code"),
            )
            .where(
                EquityStockSt.trade_date >= start_date,
                EquityStockSt.trade_date <= end_date,
                EquityStockSt.type == "ST",
            )
            .distinct()
            .subquery()
        )
        suspend_subq = (
            select(
                EquitySuspendD.trade_date.label("trade_date"),
                EquitySuspendD.ts_code.label("ts_code"),
            )
            .where(
                EquitySuspendD.trade_date >= start_date,
                EquitySuspendD.trade_date <= end_date,
            )
            .distinct()
            .subquery()
        )

        stmt = (
            select(
                EquityDailyBar.trade_date,
                EquityDailyBar.ts_code,
                EquityDailyBar.open,
                EquityDailyBar.high,
                EquityDailyBar.low,
                EquityDailyBar.close,
                EquityDailyBar.pre_close,
                EquityDailyBar.vol,
                EquityDailyBar.amount,
                Security.list_date,
                EquityStkLimit.pre_close.label("limit_pre_close"),
                EquityStkLimit.up_limit,
                EquityStkLimit.down_limit,
                (st_subq.c.ts_code.is_not(None)).label("is_st"),
                (suspend_subq.c.ts_code.is_not(None)).label("is_suspend"),
            )
            .join(Security, Security.ts_code == EquityDailyBar.ts_code)
            .outerjoin(
                EquityStkLimit,
                and_(
                    EquityStkLimit.ts_code == EquityDailyBar.ts_code,
                    EquityStkLimit.trade_date == EquityDailyBar.trade_date,
                ),
            )
            .outerjoin(
                st_subq,
                and_(
                    st_subq.c.ts_code == EquityDailyBar.ts_code,
                    st_subq.c.trade_date == EquityDailyBar.trade_date,
                ),
            )
            .outerjoin(
                suspend_subq,
                and_(
                    suspend_subq.c.ts_code == EquityDailyBar.ts_code,
                    suspend_subq.c.trade_date == EquityDailyBar.trade_date,
                ),
            )
            .where(
                EquityDailyBar.trade_date >= start_date,
                EquityDailyBar.trade_date <= end_date,
                Security.security_type == "EQUITY",
                Security.exchange.in_(("SSE", "SZSE")),
            )
        )

        rows_by_date: dict[date, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in session.execute(stmt):
            rows_by_date[row.trade_date][row.ts_code] = {
                "ts_code": row.ts_code,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "pre_close": row.pre_close,
                "vol": row.vol,
                "amount": row.amount,
                "list_date": row.list_date,
                "limit_pre_close": row.limit_pre_close,
                "up_limit": row.up_limit,
                "down_limit": row.down_limit,
                "is_st": bool(row.is_st),
                "is_suspend": bool(row.is_suspend),
            }
        return rows_by_date

    def _build_day_metrics(
        self,
        *,
        rows_by_code: dict[str, dict[str, Any]],
        list_threshold_date: date | None,
    ) -> dict[str, dict[str, Any]]:
        eligible: dict[str, dict[str, Any]] = {}
        if list_threshold_date is None:
            return {"eligible": eligible}

        for ts_code, row in rows_by_code.items():
            list_date = row.get("list_date")
            if list_date is None or list_date > list_threshold_date:
                continue
            if row.get("is_st") or row.get("is_suspend"):
                continue

            close = _to_decimal(row.get("close"))
            pre_close = _to_decimal(row.get("pre_close"))
            open_ = _to_decimal(row.get("open"))
            high = _to_decimal(row.get("high"))
            low = _to_decimal(row.get("low"))
            up_limit = _to_decimal(row.get("up_limit"))
            down_limit = _to_decimal(row.get("down_limit"))
            amount = _to_decimal(row.get("amount"))
            vol = _to_decimal(row.get("vol"))

            if close is None or pre_close in (None, Decimal("0")):
                continue
            limit_pct = _compute_limit_pct(
                up_limit=up_limit,
                limit_pre_close=_to_decimal(row.get("limit_pre_close")),
                fallback_pre_close=pre_close,
            )
            if limit_pct is None or limit_pct <= 0:
                continue

            r = (close / pre_close) - Decimal("1")
            red = r > 0

            close_up = bool(up_limit is not None and close >= up_limit - self.tick)
            close_down = bool(down_limit is not None and close <= down_limit + self.tick)
            touch_up = bool(up_limit is not None and high is not None and high >= up_limit - self.tick)
            oneword_up = bool(
                up_limit is not None
                and open_ is not None
                and high is not None
                and low is not None
                and close is not None
                and abs(open_ - up_limit) <= self.tick
                and abs(high - up_limit) <= self.tick
                and abs(low - up_limit) <= self.tick
                and abs(close - up_limit) <= self.tick
            )
            tradable_up = close_up and (not oneword_up)
            tradable_touch_up = bool(touch_up and low is not None and up_limit is not None and low < up_limit - self.tick)
            blast = tradable_touch_up and (not close_up)

            bucket = None
            if Decimal("0.095") <= limit_pct <= Decimal("0.105"):
                bucket = "10"
            elif Decimal("0.195") <= limit_pct <= Decimal("0.205"):
                bucket = "20"

            eligible[ts_code] = {
                "ts_code": ts_code,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "pre_close": pre_close,
                "amount": amount,
                "vol": vol,
                "up_limit": up_limit,
                "down_limit": down_limit,
                "limit_pct": limit_pct,
                "r": r,
                "red": red,
                "close_up": close_up,
                "close_down": close_down,
                "touch_up": touch_up,
                "oneword_up": oneword_up,
                "tradable_up": tradable_up,
                "tradable_touch_up": tradable_touch_up,
                "blast": blast,
                "bucket": bucket,
            }

        return {"eligible": eligible}

    def _compute_mainline_metrics(
        self,
        *,
        session: Session,
        trade_date: date,
        history_dates: list[date],
        day_metrics: dict[date, dict[str, dict[str, Any]]],
        market_amount_today: Decimal | None,
    ) -> dict[str, Any]:
        scan_dates = list(history_dates) + [trade_date]
        theme_amount_history: dict[str, list[Decimal]] = defaultdict(list)
        theme_today_payload: dict[str, dict[str, Any]] = {}
        theme_today_member_codes: dict[str, set[str]] = {}
        theme_day_coverage = 0

        for current_date in scan_dates:
            members, theme_name_by_code = self._load_theme_members(session, trade_date=current_date)
            if members:
                theme_day_coverage += 1
            day_eligible = day_metrics.get(current_date, {}).get("eligible", {})
            for theme_code, codes in members.items():
                matched = [day_eligible[code] for code in codes if code in day_eligible]
                if not matched:
                    continue
                theme_amount = _sum_decimal([item["amount"] for item in matched])
                if theme_amount is None:
                    continue
                theme_amount_history[theme_code].append(theme_amount)
                if current_date != trade_date:
                    continue
                theme_today_member_codes[theme_code] = {item["ts_code"] for item in matched}
                ret_median = _median_decimal([item["r"] for item in matched])
                red_rate = _ratio_from_counts(sum(1 for item in matched if item["red"]), len(matched), self.sample_threshold)
                theme_today_payload[theme_code] = {
                    "theme_code": theme_code,
                    "theme_name": theme_name_by_code.get(theme_code) or theme_code,
                    "member_count": len(matched),
                    "theme_return": ret_median,
                    "theme_red_rate": red_rate,
                    "theme_amount": theme_amount,
                }

        score_candidates: dict[str, dict[str, Any]] = {}
        for theme_code, payload in theme_today_payload.items():
            if payload["member_count"] < self.theme_min_members:
                continue
            history_amounts = theme_amount_history.get(theme_code, [])
            if not history_amounts:
                continue
            if len(history_amounts) <= 1:
                continue
            previous_amounts = history_amounts[:-1]
            amount_ratio = _safe_ratio(
                payload["theme_amount"],
                _median_decimal(previous_amounts),
                min_count=self.sample_threshold,
                count=len(previous_amounts),
            )
            if payload["theme_return"] is None or payload["theme_red_rate"] is None or amount_ratio is None:
                continue
            score_candidates[theme_code] = {
                **payload,
                "theme_amount_ratio": amount_ratio,
            }

        rank_ret = _rank_percentile({k: v["theme_return"] for k, v in score_candidates.items()})
        rank_red = _rank_percentile({k: v["theme_red_rate"] for k, v in score_candidates.items()})
        rank_amt = _rank_percentile({k: v["theme_amount_ratio"] for k, v in score_candidates.items()})

        scored = []
        for theme_code, payload in score_candidates.items():
            score = (
                Decimal("0.4") * rank_ret.get(theme_code, Decimal("0"))
                + Decimal("0.3") * rank_red.get(theme_code, Decimal("0"))
                + Decimal("0.3") * rank_amt.get(theme_code, Decimal("0"))
            )
            scored.append({**payload, "theme_score": score})
        scored.sort(key=lambda item: item["theme_score"], reverse=True)
        top3 = scored[:3]

        mainline_concentration = None
        if top3 and market_amount_today not in (None, Decimal("0")):
            union_codes: set[str] = set()
            for item in top3:
                union_codes.update(theme_today_member_codes.get(item["theme_code"], set()))
            today_eligible = day_metrics.get(trade_date, {}).get("eligible", {})
            union_amount = _sum_decimal([today_eligible[code]["amount"] for code in union_codes if code in today_eligible])
            mainline_concentration = _safe_ratio(
                union_amount,
                market_amount_today,
                min_count=1,
                count=len(union_codes),
            )

        return {
            "top3_mainlines": top3,
            "mainline_concentration": mainline_concentration,
            "theme_day_coverage": theme_day_coverage,
        }

    def _load_theme_members(self, session: Session, *, trade_date: date) -> tuple[dict[str, set[str]], dict[str, str]]:
        stmt = (
            select(
                DcMember.ts_code.label("theme_code"),
                DcMember.con_code.label("stock_code"),
                DcIndex.name.label("theme_name"),
            )
            .join(
                DcIndex,
                and_(
                    DcIndex.trade_date == DcMember.trade_date,
                    DcIndex.ts_code == DcMember.ts_code,
                ),
            )
            .where(
                DcMember.trade_date == trade_date,
                DcIndex.idx_type == "概念板块",
            )
        )
        members: dict[str, set[str]] = defaultdict(set)
        theme_name_by_code: dict[str, str] = {}
        for row in session.execute(stmt):
            members[row.theme_code].add(row.stock_code)
            if row.theme_name:
                theme_name_by_code[row.theme_code] = row.theme_name
        return members, theme_name_by_code

    def _compute_high_collapse_rate(
        self,
        *,
        session: Session,
        trade_date: date,
        prev_trade_date: date,
        ret20_base_date: date,
        rows_by_date: dict[date, dict[str, dict[str, Any]]],
        today_eligible: dict[str, dict[str, Any]],
        prev_eligible: dict[str, dict[str, Any]],
    ) -> tuple[Decimal | None, int, int]:
        if not prev_eligible:
            return None, 0, 0

        ts_codes = list(prev_eligible.keys())
        stmt = select(
            EquityAdjFactor.trade_date,
            EquityAdjFactor.ts_code,
            EquityAdjFactor.adj_factor,
        ).where(
            EquityAdjFactor.ts_code.in_(ts_codes),
            EquityAdjFactor.trade_date.in_((ret20_base_date, prev_trade_date)),
        )
        factor_map: dict[tuple[date, str], Decimal] = {}
        for row in session.execute(stmt):
            if row.adj_factor is not None:
                factor_map[(row.trade_date, row.ts_code)] = row.adj_factor

        base_rows = rows_by_date.get(ret20_base_date, {})
        ret20_values: list[tuple[str, Decimal]] = []
        for ts_code in ts_codes:
            prev_row = rows_by_date.get(prev_trade_date, {}).get(ts_code)
            base_row = base_rows.get(ts_code)
            if prev_row is None or base_row is None:
                continue
            close_prev = _to_decimal(prev_row.get("close"))
            close_base = _to_decimal(base_row.get("close"))
            factor_prev = _to_decimal(factor_map.get((prev_trade_date, ts_code)))
            factor_base = _to_decimal(factor_map.get((ret20_base_date, ts_code)))
            if (
                close_prev is None
                or close_base in (None, Decimal("0"))
                or factor_prev is None
                or factor_base in (None, Decimal("0"))
            ):
                continue
            adj_prev = close_prev * factor_prev
            adj_base = close_base * factor_base
            if adj_base == 0:
                continue
            ret20_values.append((ts_code, (adj_prev / adj_base) - Decimal("1")))

        if len(ret20_values) < self.sample_threshold:
            return None, len(ret20_values), 0

        ret20_values.sort(key=lambda item: item[1], reverse=True)
        high_pool_size = max(1, ceil(len(ret20_values) * 0.1))
        high_pool_codes = [ts_code for ts_code, _ in ret20_values[:high_pool_size]]

        numerator = 0
        denominator = 0
        for ts_code in high_pool_codes:
            metric = today_eligible.get(ts_code)
            if metric is None:
                continue
            if metric.get("limit_pct") is None or metric.get("r") is None:
                continue
            denominator += 1
            if metric["r"] <= Decimal("-0.7") * metric["limit_pct"]:
                numerator += 1
        return _ratio_from_counts(numerator, denominator, self.sample_threshold), len(ret20_values), denominator

    def _load_index_returns(
        self,
        session: Session,
        *,
        trade_date: date,
        prev_trade_date: date,
    ) -> dict[str, Decimal | None]:
        ts_codes = list(self.index_benchmarks.values())
        stmt = select(
            IndexDailyServing.ts_code,
            IndexDailyServing.trade_date,
            IndexDailyServing.close,
            IndexDailyServing.pre_close,
        ).where(
            IndexDailyServing.ts_code.in_(ts_codes),
            IndexDailyServing.trade_date.in_((trade_date, prev_trade_date)),
        )
        rows_by_code: dict[str, dict[date, tuple[Decimal | None, Decimal | None]]] = defaultdict(dict)
        for row in session.execute(stmt):
            rows_by_code[row.ts_code][row.trade_date] = (row.close, row.pre_close)

        result: dict[str, Decimal | None] = {}
        for name, ts_code in self.index_benchmarks.items():
            current = rows_by_code.get(ts_code, {}).get(trade_date)
            if current is None:
                result[name] = None
                continue
            close, pre_close = current
            close_d = _to_decimal(close)
            pre_close_d = _to_decimal(pre_close)
            if close_d is None or pre_close_d in (None, Decimal("0")):
                result[name] = None
                continue
            result[name] = (close_d / pre_close_d) - Decimal("1")
        return result

    def _compute_bucket_stats(
        self,
        *,
        bucket_codes: set[str],
        today: dict[str, dict[str, Any]],
        prev: dict[str, dict[str, Any]],
        prev_codes: set[str],
    ) -> dict[str, Any]:
        denom = len(bucket_codes)
        tradable_up_count = sum(1 for ts_code in bucket_codes if today[ts_code]["tradable_up"])
        tradable_touch_count = sum(1 for ts_code in bucket_codes if today[ts_code]["tradable_touch_up"])
        seal_success_rate = _ratio_from_counts(tradable_up_count, tradable_touch_count, self.sample_threshold)
        tradable_up_rate = _ratio_from_counts(tradable_up_count, denom, self.sample_threshold)

        advance_base_codes = {ts_code for ts_code in bucket_codes & prev_codes if prev[ts_code]["close_up"]}
        advance_success_count = sum(1 for ts_code in advance_base_codes if today[ts_code]["close_up"])
        advance_rate = _ratio_from_counts(advance_success_count, len(advance_base_codes), self.sample_threshold)

        ypool_bucket = {
            ts_code
            for ts_code in bucket_codes & prev_codes
            if prev[ts_code]["tradable_up"]
        }
        close_premium_values = []
        for ts_code in ypool_bucket:
            prev_close = prev[ts_code]["close"]
            close_today = today[ts_code]["close"]
            if prev_close in (None, Decimal("0")) or close_today is None:
                continue
            close_premium_values.append((close_today / prev_close) - Decimal("1"))
        close_premium = _median_with_threshold(close_premium_values, self.sample_threshold)

        msi = None
        if (
            tradable_up_rate is not None
            and seal_success_rate is not None
            and advance_rate is not None
            and close_premium is not None
        ):
            msi = (
                Decimal("0.30") * (tradable_up_rate * Decimal("100"))
                + Decimal("0.25") * (seal_success_rate * Decimal("100"))
                + Decimal("0.20") * (advance_rate * Decimal("100"))
                + Decimal("0.25") * (close_premium * Decimal("100"))
            )
        return {
            "sample_size": denom,
            "tradable_up_rate": tradable_up_rate,
            "seal_success_rate": seal_success_rate,
            "advance_rate": advance_rate,
            "close_premium": close_premium,
            "msi": msi,
        }


def _build_list_threshold_map(*, open_dates: list[date]) -> dict[date, date | None]:
    index_by_date = {d: idx for idx, d in enumerate(open_dates)}
    threshold_by_date: dict[date, date | None] = {}
    for d in open_dates:
        idx = index_by_date[d]
        threshold_by_date[d] = open_dates[idx - 19] if idx >= 19 else None
    return threshold_by_date


def _build_board_count_series(
    *,
    board_dates: list[date],
    day_metrics: dict[date, dict[str, dict[str, Any]]],
) -> dict[date, dict[str, int]]:
    series: dict[date, dict[str, int]] = {}
    prev_streak: dict[str, int] = {}
    for d in board_dates:
        today = day_metrics.get(d, {}).get("eligible", {})
        today_streak: dict[str, int] = {}
        for ts_code, metric in today.items():
            if metric["close_up"]:
                today_streak[ts_code] = prev_streak.get(ts_code, 0) + 1
            else:
                today_streak[ts_code] = 0
        prev_streak = today_streak
        series[d] = today_streak
    return series


def _resolve_structure_tag(*, msi10: Decimal | None, msi20: Decimal | None) -> str | None:
    if msi10 is None and msi20 is None:
        return None
    if msi10 is None or msi20 is None:
        return "样本不足"
    if msi10 - msi20 >= Decimal("10"):
        return "10cm主导"
    if msi20 - msi10 >= Decimal("10"):
        return "20cm主导"
    if abs(msi10 - msi20) < Decimal("10") and msi10 >= Decimal("30") and msi20 >= Decimal("30"):
        return "双线共振"
    if msi20 > msi10:
        return "接力弱，弹性强"
    if msi10 > msi20:
        return "接力强，弹性一般"
    return "双线均衡"


def _compute_limit_pct(
    *,
    up_limit: Decimal | None,
    limit_pre_close: Decimal | None,
    fallback_pre_close: Decimal | None,
) -> Decimal | None:
    base = limit_pre_close if limit_pre_close not in (None, Decimal("0")) else fallback_pre_close
    if up_limit is None or base in (None, Decimal("0")):
        return None
    return (up_limit / base) - Decimal("1")


def _ratio_from_counts(numerator: int, denominator: int, threshold: int) -> Decimal | None:
    if denominator < threshold or denominator <= 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _median_metric(day_metrics: dict[str, dict[str, Any]], key: str, threshold: int) -> Decimal | None:
    values = [item[key] for item in day_metrics.values() if item.get(key) is not None]
    if len(values) < threshold:
        return None
    return _median_decimal(values)


def _median_with_threshold(values: list[Decimal], threshold: int) -> Decimal | None:
    if len(values) < threshold:
        return None
    return _median_decimal(values)


def _safe_ratio(
    numerator: Decimal | None,
    denominator: Decimal | None,
    *,
    min_count: int,
    count: int,
) -> Decimal | None:
    if count < min_count:
        return None
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return numerator / denominator


def _sum_decimal(values: list[Decimal | None]) -> Decimal | None:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    total = Decimal("0")
    for value in filtered:
        total += value
    return total


def _median_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values)))


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _rank_percentile(values: dict[str, Decimal | float | None]) -> dict[str, Decimal]:
    cleaned = {k: Decimal(str(v)) for k, v in values.items() if v is not None}
    if not cleaned:
        return {}
    ordered = sorted(cleaned.items(), key=lambda item: item[1])
    n = len(ordered)
    if n == 1:
        key = ordered[0][0]
        return {key: Decimal("100")}

    index_by_key = {key: idx for idx, (key, _) in enumerate(ordered)}
    ties: dict[Decimal, list[int]] = defaultdict(list)
    for idx, (_, value) in enumerate(ordered):
        ties[value].append(idx)

    ranks: dict[str, Decimal] = {}
    for key, value in cleaned.items():
        tied_indexes = ties[value]
        avg_idx = sum(tied_indexes) / len(tied_indexes)
        ranks[key] = Decimal(str((avg_idx / (n - 1)) * 100))
    _ = index_by_key
    return ranks


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value
