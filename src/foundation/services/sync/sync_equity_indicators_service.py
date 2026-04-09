from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from src.foundation.config.settings import get_settings
from src.foundation.models.core.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core.equity_daily_bar import EquityDailyBar
from src.foundation.models.core.equity_price_restore_factor import EquityPriceRestoreFactor
from src.foundation.services.sync.base_sync_service import BaseSyncService


INDICATOR_VERSION = 1
Q8 = Decimal("0.00000001")
ONE = Decimal("1")
ADJUSTMENTS = ("forward", "backward")


@dataclass(slots=True)
class _DailyPrice:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None


def _parse_date_or_none(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"invalid date value: {value!r}")


class SyncEquityIndicatorsService(BaseSyncService):
    job_name = "sync_equity_indicators"
    target_table = "core.ind_macd"

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = _parse_date_or_none(kwargs.get("trade_date"))
        ts_code = kwargs.get("ts_code")
        execution_id = kwargs.get("execution_id")

        if run_type == "INCREMENTAL":
            if trade_date is None:
                raise ValueError("trade_date is required for incremental equity_indicators sync")
            start_date = trade_date
            end_date = trade_date
        else:
            start_date = _parse_date_or_none(kwargs.get("start_date")) or date.fromisoformat(get_settings().history_start_date)
            end_date = _parse_date_or_none(kwargs.get("end_date")) or self._latest_trade_date()
            if end_date is None:
                return 0, 0, None, "未找到股票日线数据"
            if start_date > end_date:
                raise ValueError("start_date cannot be greater than end_date")

        ts_codes = self._load_ts_codes(start_date=start_date, end_date=end_date, ts_code=ts_code)
        if not ts_codes:
            return 0, 0, end_date, "指定区间无可处理股票日线数据"

        self._ensure_meta_rows()

        fetched_total = 0
        written_total = 0
        for code in ts_codes:
            self.ensure_not_canceled(execution_id)
            fetched, written = self._build_for_ts_code(code, start_date=start_date, end_date=end_date)
            fetched_total += fetched
            written_total += written

        message = f"stocks={len(ts_codes)} days={fetched_total}"
        return fetched_total, written_total, end_date, message

    def _build_for_ts_code(self, ts_code: str, *, start_date: date, end_date: date) -> tuple[int, int]:
        all_rows = self._load_daily_rows(ts_code=ts_code, end_date=end_date)
        if not all_rows:
            return 0, 0

        factor_map = self._load_factor_map(ts_code=ts_code, start_date=all_rows[0].trade_date, end_date=end_date)
        forward_anchor = self._load_anchor(ts_code=ts_code, adjustment="forward") or ONE
        backward_anchor = self._load_anchor(ts_code=ts_code, adjustment="backward") or ONE
        if forward_anchor == 0:
            forward_anchor = ONE
        if backward_anchor == 0:
            backward_anchor = ONE

        macd_rows: list[dict[str, Any]] = []
        kdj_rows: list[dict[str, Any]] = []
        rsi_rows: list[dict[str, Any]] = []
        fetched = 0

        for adjustment in ADJUSTMENTS:
            anchor = forward_anchor if adjustment == "forward" else backward_anchor
            closes = [self._to_float(self._adjust_price(row.close, factor_map.get(row.trade_date), anchor)) for row in all_rows]
            highs = [self._to_float(self._adjust_price(row.high, factor_map.get(row.trade_date), anchor)) for row in all_rows]
            lows = [self._to_float(self._adjust_price(row.low, factor_map.get(row.trade_date), anchor)) for row in all_rows]

            dif, dea, macd_bar, macd_state = self._macd(closes)
            k, d, j, kdj_state = self._kdj(highs, lows, closes)
            rsi6, state6 = self._rsi(closes, 6)
            rsi12, state12 = self._rsi(closes, 12)
            rsi24, state24 = self._rsi(closes, 24)

            rows_written_scope = [row for row in all_rows if start_date <= row.trade_date <= end_date]
            fetched += len(rows_written_scope)

            for idx, row in enumerate(all_rows):
                if row.trade_date < start_date or row.trade_date > end_date:
                    continue
                macd_rows.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": row.trade_date,
                        "adjustment": adjustment,
                        "version": INDICATOR_VERSION,
                        "dif": self._to_decimal(dif[idx]),
                        "dea": self._to_decimal(dea[idx]),
                        "macd_bar": self._to_decimal(macd_bar[idx]),
                    }
                )
                kdj_rows.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": row.trade_date,
                        "adjustment": adjustment,
                        "version": INDICATOR_VERSION,
                        "k": self._to_decimal(k[idx]),
                        "d": self._to_decimal(d[idx]),
                        "j": self._to_decimal(j[idx]),
                    }
                )
                rsi_rows.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": row.trade_date,
                        "adjustment": adjustment,
                        "version": INDICATOR_VERSION,
                        "rsi_6": self._to_decimal(rsi6[idx]),
                        "rsi_12": self._to_decimal(rsi12[idx]),
                        "rsi_24": self._to_decimal(rsi24[idx]),
                    }
                )

            last_trade_date = all_rows[-1].trade_date
            self.dao.indicator_state.bulk_upsert(
                [
                    {
                        "ts_code": ts_code,
                        "adjustment": adjustment,
                        "indicator_name": "macd",
                        "version": INDICATOR_VERSION,
                        "last_trade_date": last_trade_date,
                        "state_json": macd_state,
                    },
                    {
                        "ts_code": ts_code,
                        "adjustment": adjustment,
                        "indicator_name": "kdj",
                        "version": INDICATOR_VERSION,
                        "last_trade_date": last_trade_date,
                        "state_json": kdj_state,
                    },
                    {
                        "ts_code": ts_code,
                        "adjustment": adjustment,
                        "indicator_name": "rsi",
                        "version": INDICATOR_VERSION,
                        "last_trade_date": last_trade_date,
                        "state_json": {
                            "period_6": state6,
                            "period_12": state12,
                            "period_24": state24,
                        },
                    },
                ]
            )

        written = 0
        written += self.dao.indicator_macd.bulk_upsert(macd_rows)
        written += self.dao.indicator_kdj.bulk_upsert(kdj_rows)
        written += self.dao.indicator_rsi.bulk_upsert(rsi_rows)
        return fetched, written

    def _ensure_meta_rows(self) -> None:
        self.dao.indicator_meta.bulk_upsert(
            [
                {
                    "indicator_name": "macd",
                    "version": INDICATOR_VERSION,
                    "params_json": {"fast": 12, "slow": 26, "signal": 9, "bar_multiplier": 2},
                },
                {
                    "indicator_name": "kdj",
                    "version": INDICATOR_VERSION,
                    "params_json": {"period": 9, "k_smooth": 3, "d_smooth": 3},
                },
                {
                    "indicator_name": "rsi",
                    "version": INDICATOR_VERSION,
                    "params_json": {"periods": [6, 12, 24], "method": "wilder"},
                },
            ]
        )

    def _load_daily_rows(self, *, ts_code: str, end_date: date) -> list[_DailyPrice]:
        rows = self.session.execute(
            select(
                EquityDailyBar.trade_date,
                EquityDailyBar.open,
                EquityDailyBar.high,
                EquityDailyBar.low,
                EquityDailyBar.close,
            )
            .where(
                EquityDailyBar.ts_code == ts_code,
                EquityDailyBar.trade_date <= end_date,
            )
            .order_by(EquityDailyBar.trade_date.asc())
        ).all()
        return [_DailyPrice(*row) for row in rows]

    def _load_factor_map(self, *, ts_code: str, start_date: date, end_date: date) -> dict[date, Decimal]:
        if self._factor_source() == "adj_factor":
            factors = self.session.execute(
                select(EquityAdjFactor.trade_date, EquityAdjFactor.adj_factor)
                .where(
                    EquityAdjFactor.ts_code == ts_code,
                    EquityAdjFactor.trade_date >= start_date,
                    EquityAdjFactor.trade_date <= end_date,
                )
            ).all()
            return {row.trade_date: row.adj_factor for row in factors if row.adj_factor is not None}
        factors = self.session.execute(
            select(EquityPriceRestoreFactor.trade_date, EquityPriceRestoreFactor.cum_factor)
            .where(
                EquityPriceRestoreFactor.ts_code == ts_code,
                EquityPriceRestoreFactor.trade_date >= start_date,
                EquityPriceRestoreFactor.trade_date <= end_date,
            )
        ).all()
        return {row.trade_date: row.cum_factor for row in factors if row.cum_factor is not None}

    def _load_anchor(self, *, ts_code: str, adjustment: str) -> Decimal | None:
        if self._factor_source() == "adj_factor":
            if adjustment == "forward":
                return self.session.scalar(
                    select(EquityAdjFactor.adj_factor)
                    .where(EquityAdjFactor.ts_code == ts_code)
                    .order_by(EquityAdjFactor.trade_date.desc())
                    .limit(1)
                )
            return self.session.scalar(
                select(EquityAdjFactor.adj_factor)
                .where(EquityAdjFactor.ts_code == ts_code)
                .order_by(EquityAdjFactor.trade_date.asc())
                .limit(1)
            )
        if adjustment == "forward":
            return self.session.scalar(
                select(EquityPriceRestoreFactor.cum_factor)
                .where(EquityPriceRestoreFactor.ts_code == ts_code)
                .order_by(EquityPriceRestoreFactor.trade_date.desc())
                .limit(1)
            )
        return self.session.scalar(
            select(EquityPriceRestoreFactor.cum_factor)
            .where(EquityPriceRestoreFactor.ts_code == ts_code)
            .order_by(EquityPriceRestoreFactor.trade_date.asc())
            .limit(1)
        )

    @staticmethod
    def _factor_source() -> str:
        return get_settings().equity_adjustment_factor_source

    @staticmethod
    def _adjust_price(value: Decimal | None, factor: Decimal | None, anchor: Decimal) -> Decimal | None:
        if value is None or factor is None:
            return value
        scale = factor / anchor if anchor != 0 else ONE
        return (value * scale).quantize(Q8)

    @staticmethod
    def _to_float(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _to_decimal(value: float | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value)).quantize(Q8)

    @staticmethod
    def _ema(values: list[float | None], period: int) -> tuple[list[float | None], float | None]:
        result: list[float | None] = []
        alpha = 2.0 / (period + 1.0)
        prev: float | None = None
        for value in values:
            if value is None:
                result.append(None)
                continue
            if prev is None:
                prev = value
            else:
                prev = alpha * value + (1.0 - alpha) * prev
            result.append(prev)
        return result, prev

    def _macd(self, closes: list[float | None]) -> tuple[list[float | None], list[float | None], list[float | None], dict[str, float | None]]:
        ema12, ema12_last = self._ema(closes, 12)
        ema26, ema26_last = self._ema(closes, 26)
        dif: list[float | None] = []
        for idx in range(len(closes)):
            if ema12[idx] is None or ema26[idx] is None:
                dif.append(None)
            else:
                dif.append(ema12[idx] - ema26[idx])
        dea, dea_last = self._ema(dif, 9)
        macd: list[float | None] = []
        for idx in range(len(closes)):
            if dif[idx] is None or dea[idx] is None:
                macd.append(None)
            else:
                macd.append((dif[idx] - dea[idx]) * 2.0)
        return dif, dea, macd, {"ema_fast": ema12_last, "ema_slow": ema26_last, "dea": dea_last}

    @staticmethod
    def _kdj(
        highs: list[float | None],
        lows: list[float | None],
        closes: list[float | None],
    ) -> tuple[list[float | None], list[float | None], list[float | None], dict[str, float]]:
        k_values: list[float | None] = []
        d_values: list[float | None] = []
        j_values: list[float | None] = []
        prev_k = 50.0
        prev_d = 50.0
        for idx, close_value in enumerate(closes):
            start = max(0, idx - 8)
            window_highs = [item for item in highs[start: idx + 1] if item is not None]
            window_lows = [item for item in lows[start: idx + 1] if item is not None]
            if close_value is None or not window_highs or not window_lows:
                k_values.append(None)
                d_values.append(None)
                j_values.append(None)
                continue
            high_max = max(window_highs)
            low_min = min(window_lows)
            rsv = 50.0 if high_max == low_min else ((close_value - low_min) / (high_max - low_min) * 100.0)
            current_k = (2.0 / 3.0) * prev_k + (1.0 / 3.0) * rsv
            current_d = (2.0 / 3.0) * prev_d + (1.0 / 3.0) * current_k
            current_j = 3.0 * current_k - 2.0 * current_d
            k_values.append(current_k)
            d_values.append(current_d)
            j_values.append(current_j)
            prev_k, prev_d = current_k, current_d
        return k_values, d_values, j_values, {"k": prev_k, "d": prev_d}

    @staticmethod
    def _rsi(closes: list[float | None], period: int) -> tuple[list[float | None], dict[str, float | None]]:
        values: list[float | None] = [None] * len(closes)
        prev_close: float | None = None
        avg_gain: float | None = None
        avg_loss: float | None = None
        init_gains: list[float] = []
        init_losses: list[float] = []

        for idx, close in enumerate(closes):
            if close is None:
                prev_close = None
                continue
            if prev_close is None:
                prev_close = close
                continue
            delta = close - prev_close
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)

            if avg_gain is None or avg_loss is None:
                init_gains.append(gain)
                init_losses.append(loss)
                if len(init_gains) == period:
                    avg_gain = sum(init_gains) / period
                    avg_loss = sum(init_losses) / period
                    values[idx] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
            else:
                avg_gain = ((avg_gain * (period - 1)) + gain) / period
                avg_loss = ((avg_loss * (period - 1)) + loss) / period
                values[idx] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
            prev_close = close

        return values, {"avg_gain": avg_gain, "avg_loss": avg_loss, "prev_close": prev_close}

    def _load_ts_codes(self, *, start_date: date, end_date: date, ts_code: str | None = None) -> list[str]:
        stmt = (
            select(EquityDailyBar.ts_code)
            .where(
                EquityDailyBar.trade_date >= start_date,
                EquityDailyBar.trade_date <= end_date,
            )
            .distinct()
            .order_by(EquityDailyBar.ts_code.asc())
        )
        if ts_code:
            stmt = stmt.where(EquityDailyBar.ts_code == ts_code)
        return list(self.session.scalars(stmt))

    def _latest_trade_date(self) -> date | None:
        return self.session.scalar(select(func.max(EquityDailyBar.trade_date)))
