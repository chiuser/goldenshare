from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from src.foundation.models.core.indicator_state import IndicatorState
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.ops.models.ops.job_execution import JobExecution


INDICATOR_VERSION = 1
Q8 = Decimal("0.00000001")
ONE = Decimal("1")
ADJUSTMENTS = ("forward", "backward")
WARMUP_DAYS = 250
KDJ_WINDOW = 9
ADJ_FACTOR_EPSILON = 1e-8


@dataclass(slots=True)
class _DailyPrice:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None


@dataclass(slots=True)
class _IndicatorBuildPayload:
    fetched: int = 0
    macd_rows: list[dict[str, Any]] = field(default_factory=list)
    kdj_rows: list[dict[str, Any]] = field(default_factory=list)
    rsi_rows: list[dict[str, Any]] = field(default_factory=list)
    std_macd_rows: list[dict[str, Any]] = field(default_factory=list)
    std_kdj_rows: list[dict[str, Any]] = field(default_factory=list)
    std_rsi_rows: list[dict[str, Any]] = field(default_factory=list)
    state_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _RsiIncrementalState:
    avg_gain: float
    avg_loss: float
    prev_close: float


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
        ts_code_raw = kwargs.get("ts_code")
        ts_code = str(ts_code_raw).strip().upper() if ts_code_raw else None
        source_key = str(kwargs.get("source_key") or "tushare").strip().lower()
        execution_id = kwargs.get("execution_id")

        ts_codes = self._load_ts_codes(ts_code=ts_code)
        if not ts_codes:
            return 0, 0, None, "无可处理股票日线数据"

        self._ensure_meta_rows()

        fetched_total = 0
        written_total = 0
        latest_end_date: date | None = None
        total_codes = len(ts_codes)
        progress_step = max(1, total_codes // 100)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_codes,
            message=f"units=0/{total_codes} unit=stock",
        )
        for index, code in enumerate(ts_codes, start=1):
            self.ensure_not_canceled(execution_id)
            bounds = self._load_trade_bounds(ts_code=code)
            if bounds is None:
                continue
            start_date, end_date = bounds
            latest_end_date = end_date if latest_end_date is None else max(latest_end_date, end_date)
            fetched, written = self._build_for_ts_code(
                code,
                start_date=start_date,
                end_date=end_date,
                source_key=source_key,
                run_type=run_type,
            )
            fetched_total += fetched
            written_total += written
            if index == total_codes or index % progress_step == 0:
                self._update_progress(
                    execution_id=execution_id,
                    current=index,
                    total=total_codes,
                    message=f"units={index}/{total_codes} unit=stock ts_code={code} fetched={fetched} written={written}",
                )

        message = f"stocks={len(ts_codes)} bars={fetched_total}"
        return fetched_total, written_total, latest_end_date, message

    def _update_progress(self, *, execution_id: int | None, current: int, total: int, message: str) -> None:
        if execution_id is None:
            return
        execution = self.session.get(JobExecution, execution_id)
        if execution is None:
            return
        execution.progress_current = current
        execution.progress_total = total
        execution.progress_percent = int((current / total) * 100) if total else None
        execution.progress_message = message
        execution.last_progress_at = datetime.now(timezone.utc)
        self.session.commit()

    def _build_for_ts_code(
        self,
        ts_code: str,
        *,
        start_date: date,
        end_date: date,
        source_key: str = "tushare",
        run_type: str = "FULL",
    ) -> tuple[int, int]:
        total_payload = _IndicatorBuildPayload()
        cached_full_rows: list[_DailyPrice] | None = None
        cached_full_factor_map: dict[date, Decimal] | None = None

        def _get_cached_full_inputs() -> tuple[list[_DailyPrice], dict[date, Decimal]]:
            nonlocal cached_full_rows, cached_full_factor_map
            if cached_full_rows is None:
                cached_full_rows = self._load_daily_rows(ts_code=ts_code, end_date=end_date)
                if not cached_full_rows:
                    cached_full_factor_map = {}
                    return [], {}
                cached_full_factor_map = self._load_factor_map(
                    ts_code=ts_code,
                    start_date=cached_full_rows[0].trade_date,
                    end_date=end_date,
                )
            return cached_full_rows, cached_full_factor_map or {}

        for adjustment in ADJUSTMENTS:
            if run_type == "INCREMENTAL":
                payload = self._build_adjustment_incremental(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                    source_key=source_key,
                    adjustment=adjustment,
                )
                if payload is None:
                    full_rows, full_factor_map = _get_cached_full_inputs()
                    payload = self._build_adjustment_full(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                        source_key=source_key,
                        adjustment=adjustment,
                        raw_rows=full_rows,
                        factor_map=full_factor_map,
                    )
            else:
                full_rows, full_factor_map = _get_cached_full_inputs()
                payload = self._build_adjustment_full(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                    source_key=source_key,
                    adjustment=adjustment,
                    raw_rows=full_rows,
                    factor_map=full_factor_map,
                )
            total_payload.fetched += payload.fetched
            total_payload.macd_rows.extend(payload.macd_rows)
            total_payload.kdj_rows.extend(payload.kdj_rows)
            total_payload.rsi_rows.extend(payload.rsi_rows)
            total_payload.std_macd_rows.extend(payload.std_macd_rows)
            total_payload.std_kdj_rows.extend(payload.std_kdj_rows)
            total_payload.std_rsi_rows.extend(payload.std_rsi_rows)
            total_payload.state_rows.extend(payload.state_rows)

        written = 0
        written += self.dao.indicator_macd.bulk_upsert(total_payload.macd_rows)
        written += self.dao.indicator_kdj.bulk_upsert(total_payload.kdj_rows)
        written += self.dao.indicator_rsi.bulk_upsert(total_payload.rsi_rows)
        self.dao.indicator_macd_std.bulk_upsert(total_payload.std_macd_rows)
        self.dao.indicator_kdj_std.bulk_upsert(total_payload.std_kdj_rows)
        self.dao.indicator_rsi_std.bulk_upsert(total_payload.std_rsi_rows)
        self.dao.indicator_state.bulk_upsert(total_payload.state_rows)
        return total_payload.fetched, written

    def _build_adjustment_full(
        self,
        *,
        ts_code: str,
        start_date: date,
        end_date: date,
        source_key: str,
        adjustment: str,
        raw_rows: list[_DailyPrice] | None = None,
        factor_map: dict[date, Decimal] | None = None,
    ) -> _IndicatorBuildPayload:
        resolved_raw_rows = raw_rows if raw_rows is not None else self._load_daily_rows(ts_code=ts_code, end_date=end_date)
        if not resolved_raw_rows:
            return _IndicatorBuildPayload()

        resolved_factor_map = factor_map if factor_map is not None else self._load_factor_map(
            ts_code=ts_code,
            start_date=resolved_raw_rows[0].trade_date,
            end_date=end_date,
        )
        anchor = self._resolve_anchor(
            ts_code=ts_code,
            adjustment=adjustment,
            factor_map=resolved_factor_map,
        )
        adjusted_rows = self._adjust_rows(resolved_raw_rows, factor_map=resolved_factor_map, anchor=anchor)
        closes = [self._to_float(row.close) for row in adjusted_rows]
        highs = [self._to_float(row.high) for row in adjusted_rows]
        lows = [self._to_float(row.low) for row in adjusted_rows]

        dif, dea, macd_bar, macd_state = self._macd(closes)
        k, d, j, kdj_state = self._kdj(highs, lows, closes)
        rsi6, state6 = self._rsi(closes, 6)
        rsi12, state12 = self._rsi(closes, 12)
        rsi24, state24 = self._rsi(closes, 24)

        payload = _IndicatorBuildPayload()
        for idx, row in enumerate(adjusted_rows):
            if row.trade_date < start_date or row.trade_date > end_date:
                continue
            bar_count = idx + 1
            is_valid = bar_count >= WARMUP_DAYS
            payload.fetched += 1
            payload.macd_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "dif": self._to_decimal(dif[idx]),
                    "dea": self._to_decimal(dea[idx]),
                    "macd_bar": self._to_decimal(macd_bar[idx]),
                    "is_valid": is_valid,
                }
            )
            payload.std_macd_rows.append(
                {
                    "source_key": source_key,
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "dif": self._to_decimal(dif[idx]),
                    "dea": self._to_decimal(dea[idx]),
                    "macd_bar": self._to_decimal(macd_bar[idx]),
                    "is_valid": is_valid,
                }
            )
            payload.kdj_rows.append(
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
            payload.std_kdj_rows.append(
                {
                    "source_key": source_key,
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "k": self._to_decimal(k[idx]),
                    "d": self._to_decimal(d[idx]),
                    "j": self._to_decimal(j[idx]),
                }
            )
            payload.rsi_rows.append(
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
            payload.std_rsi_rows.append(
                {
                    "source_key": source_key,
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "rsi_6": self._to_decimal(rsi6[idx]),
                    "rsi_12": self._to_decimal(rsi12[idx]),
                    "rsi_24": self._to_decimal(rsi24[idx]),
                }
            )

        last_trade_date = adjusted_rows[-1].trade_date
        last_factor = resolved_factor_map.get(last_trade_date)
        bar_count_total = len(adjusted_rows)
        payload.state_rows.extend(
            [
                {
                    "ts_code": ts_code,
                    "source_key": source_key,
                    "adjustment": adjustment,
                    "indicator_name": "macd",
                    "version": INDICATOR_VERSION,
                    "last_trade_date": last_trade_date,
                    "state_json": {
                        "ema_fast": macd_state["ema_fast"],
                        "ema_slow": macd_state["ema_slow"],
                        "dea": macd_state["dea"],
                        "bar_count": bar_count_total,
                        "last_adj_factor": self._to_float(last_factor),
                    },
                },
                {
                    "ts_code": ts_code,
                    "source_key": source_key,
                    "adjustment": adjustment,
                    "indicator_name": "kdj",
                    "version": INDICATOR_VERSION,
                    "last_trade_date": last_trade_date,
                    "state_json": {
                        "k": kdj_state["k"],
                        "d": kdj_state["d"],
                        "bar_count": bar_count_total,
                    },
                },
                {
                    "ts_code": ts_code,
                    "source_key": source_key,
                    "adjustment": adjustment,
                    "indicator_name": "rsi",
                    "version": INDICATOR_VERSION,
                    "last_trade_date": last_trade_date,
                    "state_json": {
                        "period_6": state6,
                        "period_12": state12,
                        "period_24": state24,
                        "bar_count": bar_count_total,
                    },
                },
            ]
        )
        return payload

    def _build_adjustment_incremental(
        self,
        *,
        ts_code: str,
        start_date: date,
        end_date: date,
        source_key: str,
        adjustment: str,
    ) -> _IndicatorBuildPayload | None:
        macd_state = self._load_indicator_state(
            ts_code=ts_code,
            source_key=source_key,
            adjustment=adjustment,
            indicator_name="macd",
        )
        kdj_state = self._load_indicator_state(
            ts_code=ts_code,
            source_key=source_key,
            adjustment=adjustment,
            indicator_name="kdj",
        )
        rsi_state = self._load_indicator_state(
            ts_code=ts_code,
            source_key=source_key,
            adjustment=adjustment,
            indicator_name="rsi",
        )
        if macd_state is None or kdj_state is None or rsi_state is None:
            return None

        last_trade_date = macd_state.last_trade_date
        if last_trade_date > end_date:
            return None

        bar_count = self._state_int(macd_state.state_json.get("bar_count"))
        if bar_count is None or bar_count <= 0:
            return None

        observed_count = self._count_daily_rows_until(ts_code=ts_code, end_date=last_trade_date)
        if observed_count != bar_count:
            return None

        snapshot_factor = self._state_float(macd_state.state_json.get("last_adj_factor"))
        current_factor = self._to_float(self._load_factor_on_date(ts_code=ts_code, trade_date=last_trade_date))
        if snapshot_factor is None and current_factor is not None:
            return None
        if snapshot_factor is not None and current_factor is None:
            return None
        if snapshot_factor is not None and current_factor is not None and abs(snapshot_factor - current_factor) > ADJ_FACTOR_EPSILON:
            return None

        ema_fast = self._state_float(macd_state.state_json.get("ema_fast"))
        ema_slow = self._state_float(macd_state.state_json.get("ema_slow"))
        dea_prev = self._state_float(macd_state.state_json.get("dea"))
        prev_k = self._state_float(kdj_state.state_json.get("k"))
        prev_d = self._state_float(kdj_state.state_json.get("d"))
        if ema_fast is None or ema_slow is None or dea_prev is None or prev_k is None or prev_d is None:
            return None

        period6 = self._parse_rsi_state(rsi_state.state_json, "period_6")
        period12 = self._parse_rsi_state(rsi_state.state_json, "period_12")
        period24 = self._parse_rsi_state(rsi_state.state_json, "period_24")
        if period6 is None or period12 is None or period24 is None:
            return None

        new_rows = self._load_daily_rows_after(ts_code=ts_code, after_date=last_trade_date, end_date=end_date)
        if not new_rows:
            return _IndicatorBuildPayload()

        context_rows = self._load_recent_daily_rows_before(
            ts_code=ts_code,
            before_trade_date=new_rows[0].trade_date,
            limit=KDJ_WINDOW - 1,
        )
        combined_rows = [*context_rows, *new_rows]

        factor_map = self._load_factor_map(
            ts_code=ts_code,
            start_date=combined_rows[0].trade_date,
            end_date=end_date,
        )
        anchor = self._resolve_anchor(
            ts_code=ts_code,
            adjustment=adjustment,
            factor_map=factor_map,
        )
        adjusted_rows = self._adjust_rows(combined_rows, factor_map=factor_map, anchor=anchor)
        context_size = len(context_rows)
        adjusted_new_rows = adjusted_rows[context_size:]
        closes_new = [self._to_float(row.close) for row in adjusted_new_rows]
        highs_all = [self._to_float(row.high) for row in adjusted_rows]
        lows_all = [self._to_float(row.low) for row in adjusted_rows]
        closes_all = [self._to_float(row.close) for row in adjusted_rows]

        dif_values, dea_values, macd_values, ema_fast_last, ema_slow_last, dea_last = self._macd_incremental(
            closes_new,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            dea=dea_prev,
        )
        k_values, d_values, j_values, k_last, d_last = self._kdj_incremental(
            highs_all,
            lows_all,
            closes_all,
            start_index=context_size,
            prev_k=prev_k,
            prev_d=prev_d,
        )
        rsi6, state6 = self._rsi_incremental(closes_new, period=6, state=period6)
        rsi12, state12 = self._rsi_incremental(closes_new, period=12, state=period12)
        rsi24, state24 = self._rsi_incremental(closes_new, period=24, state=period24)

        payload = _IndicatorBuildPayload()
        for idx, row in enumerate(adjusted_new_rows):
            current_bar_count = bar_count + idx + 1
            is_valid = current_bar_count >= WARMUP_DAYS
            payload.fetched += 1
            payload.macd_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "dif": self._to_decimal(dif_values[idx]),
                    "dea": self._to_decimal(dea_values[idx]),
                    "macd_bar": self._to_decimal(macd_values[idx]),
                    "is_valid": is_valid,
                }
            )
            payload.std_macd_rows.append(
                {
                    "source_key": source_key,
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "dif": self._to_decimal(dif_values[idx]),
                    "dea": self._to_decimal(dea_values[idx]),
                    "macd_bar": self._to_decimal(macd_values[idx]),
                    "is_valid": is_valid,
                }
            )
            payload.kdj_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "k": self._to_decimal(k_values[idx]),
                    "d": self._to_decimal(d_values[idx]),
                    "j": self._to_decimal(j_values[idx]),
                }
            )
            payload.std_kdj_rows.append(
                {
                    "source_key": source_key,
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "k": self._to_decimal(k_values[idx]),
                    "d": self._to_decimal(d_values[idx]),
                    "j": self._to_decimal(j_values[idx]),
                }
            )
            payload.rsi_rows.append(
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
            payload.std_rsi_rows.append(
                {
                    "source_key": source_key,
                    "ts_code": ts_code,
                    "trade_date": row.trade_date,
                    "adjustment": adjustment,
                    "version": INDICATOR_VERSION,
                    "rsi_6": self._to_decimal(rsi6[idx]),
                    "rsi_12": self._to_decimal(rsi12[idx]),
                    "rsi_24": self._to_decimal(rsi24[idx]),
                }
            )

        latest_trade_date = adjusted_new_rows[-1].trade_date
        latest_factor = factor_map.get(latest_trade_date)
        latest_bar_count = bar_count + len(adjusted_new_rows)
        payload.state_rows.extend(
            [
                {
                    "ts_code": ts_code,
                    "source_key": source_key,
                    "adjustment": adjustment,
                    "indicator_name": "macd",
                    "version": INDICATOR_VERSION,
                    "last_trade_date": latest_trade_date,
                    "state_json": {
                        "ema_fast": ema_fast_last,
                        "ema_slow": ema_slow_last,
                        "dea": dea_last,
                        "bar_count": latest_bar_count,
                        "last_adj_factor": self._to_float(latest_factor),
                    },
                },
                {
                    "ts_code": ts_code,
                    "source_key": source_key,
                    "adjustment": adjustment,
                    "indicator_name": "kdj",
                    "version": INDICATOR_VERSION,
                    "last_trade_date": latest_trade_date,
                    "state_json": {
                        "k": k_last,
                        "d": d_last,
                        "bar_count": latest_bar_count,
                    },
                },
                {
                    "ts_code": ts_code,
                    "source_key": source_key,
                    "adjustment": adjustment,
                    "indicator_name": "rsi",
                    "version": INDICATOR_VERSION,
                    "last_trade_date": latest_trade_date,
                    "state_json": {
                        "period_6": state6,
                        "period_12": state12,
                        "period_24": state24,
                        "bar_count": latest_bar_count,
                    },
                },
            ]
        )
        return payload

    def _ensure_meta_rows(self) -> None:
        self.dao.indicator_meta.bulk_upsert(
            [
                {
                    "indicator_name": "macd",
                    "version": INDICATOR_VERSION,
                    "params_json": {
                        "fast": 12,
                        "slow": 26,
                        "signal": 9,
                        "bar_multiplier": 2,
                        "warmup_days": WARMUP_DAYS,
                        "seed_rule": "first_close",
                    },
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

    def _resolve_anchor(self, *, ts_code: str, adjustment: str, factor_map: dict[date, Decimal]) -> Decimal:
        anchor = self._load_anchor(ts_code=ts_code, adjustment=adjustment)
        if anchor is None and factor_map:
            anchor = max(factor_map.values()) if adjustment == "forward" else min(factor_map.values())
        if anchor is None or anchor == 0:
            return ONE
        return anchor

    def _adjust_rows(
        self,
        rows: list[_DailyPrice],
        *,
        factor_map: dict[date, Decimal],
        anchor: Decimal,
    ) -> list[_DailyPrice]:
        adjusted: list[_DailyPrice] = []
        for row in rows:
            factor = factor_map.get(row.trade_date)
            adjusted.append(
                _DailyPrice(
                    trade_date=row.trade_date,
                    open=self._adjust_price(row.open, factor, anchor),
                    high=self._adjust_price(row.high, factor, anchor),
                    low=self._adjust_price(row.low, factor, anchor),
                    close=self._adjust_price(row.close, factor, anchor),
                )
            )
        return adjusted

    def _load_daily_rows(
        self,
        *,
        ts_code: str,
        end_date: date,
        start_date: date | None = None,
    ) -> list[_DailyPrice]:
        stmt = (
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
        )
        if start_date is not None:
            stmt = stmt.where(EquityDailyBar.trade_date >= start_date)
        rows = self.session.execute(stmt).all()
        return [_DailyPrice(*row) for row in rows]

    def _load_daily_rows_after(
        self,
        *,
        ts_code: str,
        after_date: date,
        end_date: date,
    ) -> list[_DailyPrice]:
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
                EquityDailyBar.trade_date > after_date,
                EquityDailyBar.trade_date <= end_date,
            )
            .order_by(EquityDailyBar.trade_date.asc())
        ).all()
        return [_DailyPrice(*row) for row in rows]

    def _load_recent_daily_rows_before(
        self,
        *,
        ts_code: str,
        before_trade_date: date,
        limit: int,
    ) -> list[_DailyPrice]:
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
                EquityDailyBar.trade_date < before_trade_date,
            )
            .order_by(EquityDailyBar.trade_date.desc())
            .limit(limit)
        ).all()
        return [_DailyPrice(*row) for row in reversed(rows)]

    def _count_daily_rows_until(self, *, ts_code: str, end_date: date) -> int:
        count = self.session.scalar(
            select(func.count())
            .select_from(EquityDailyBar)
            .where(
                EquityDailyBar.ts_code == ts_code,
                EquityDailyBar.trade_date <= end_date,
            )
        )
        return int(count or 0)

    def _load_factor_map(self, *, ts_code: str, start_date: date, end_date: date) -> dict[date, Decimal]:
        factors = self.session.execute(
            select(EquityAdjFactor.trade_date, EquityAdjFactor.adj_factor)
            .where(
                EquityAdjFactor.ts_code == ts_code,
                EquityAdjFactor.trade_date >= start_date,
                EquityAdjFactor.trade_date <= end_date,
            )
        ).all()
        return {row.trade_date: row.adj_factor for row in factors if row.adj_factor is not None}

    def _load_factor_on_date(self, *, ts_code: str, trade_date: date) -> Decimal | None:
        return self.session.scalar(
            select(EquityAdjFactor.adj_factor).where(
                EquityAdjFactor.ts_code == ts_code,
                EquityAdjFactor.trade_date == trade_date,
            )
        )

    def _load_anchor(self, *, ts_code: str, adjustment: str) -> Decimal | None:
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

    def _load_indicator_state(
        self,
        *,
        ts_code: str,
        source_key: str,
        adjustment: str,
        indicator_name: str,
    ) -> IndicatorState | None:
        return self.session.get(
            IndicatorState,
            (ts_code, source_key, adjustment, indicator_name, INDICATOR_VERSION),
        )

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
    def _state_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (float, int)):
            return float(value)
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _state_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    def _parse_rsi_state(self, state_json: dict[str, Any], key: str) -> _RsiIncrementalState | None:
        period_state = state_json.get(key)
        if not isinstance(period_state, dict):
            return None
        avg_gain = self._state_float(period_state.get("avg_gain"))
        avg_loss = self._state_float(period_state.get("avg_loss"))
        prev_close = self._state_float(period_state.get("prev_close"))
        if avg_gain is None or avg_loss is None or prev_close is None:
            return None
        return _RsiIncrementalState(avg_gain=avg_gain, avg_loss=avg_loss, prev_close=prev_close)

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

    def _macd(
        self,
        closes: list[float | None],
    ) -> tuple[list[float | None], list[float | None], list[float | None], dict[str, float | None]]:
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
    def _macd_incremental(
        closes: list[float | None],
        *,
        ema_fast: float,
        ema_slow: float,
        dea: float,
    ) -> tuple[list[float | None], list[float | None], list[float | None], float, float, float]:
        alpha_fast = 2.0 / (12.0 + 1.0)
        alpha_slow = 2.0 / (26.0 + 1.0)
        alpha_signal = 2.0 / (9.0 + 1.0)

        dif_values: list[float | None] = []
        dea_values: list[float | None] = []
        macd_values: list[float | None] = []

        fast = ema_fast
        slow = ema_slow
        signal = dea
        for close in closes:
            if close is None:
                dif_values.append(None)
                dea_values.append(None)
                macd_values.append(None)
                continue
            fast = alpha_fast * close + (1.0 - alpha_fast) * fast
            slow = alpha_slow * close + (1.0 - alpha_slow) * slow
            dif = fast - slow
            signal = alpha_signal * dif + (1.0 - alpha_signal) * signal
            bar = (dif - signal) * 2.0
            dif_values.append(dif)
            dea_values.append(signal)
            macd_values.append(bar)
        return dif_values, dea_values, macd_values, fast, slow, signal

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
            start = max(0, idx - (KDJ_WINDOW - 1))
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
    def _kdj_incremental(
        highs: list[float | None],
        lows: list[float | None],
        closes: list[float | None],
        *,
        start_index: int,
        prev_k: float,
        prev_d: float,
    ) -> tuple[list[float | None], list[float | None], list[float | None], float, float]:
        k_values: list[float | None] = []
        d_values: list[float | None] = []
        j_values: list[float | None] = []
        k_curr = prev_k
        d_curr = prev_d
        for idx in range(start_index, len(closes)):
            close_value = closes[idx]
            start = max(0, idx - (KDJ_WINDOW - 1))
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
            k_curr = (2.0 / 3.0) * k_curr + (1.0 / 3.0) * rsv
            d_curr = (2.0 / 3.0) * d_curr + (1.0 / 3.0) * k_curr
            j_curr = 3.0 * k_curr - 2.0 * d_curr
            k_values.append(k_curr)
            d_values.append(d_curr)
            j_values.append(j_curr)
        return k_values, d_values, j_values, k_curr, d_curr

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

    @staticmethod
    def _rsi_incremental(
        closes: list[float | None],
        *,
        period: int,
        state: _RsiIncrementalState,
    ) -> tuple[list[float | None], dict[str, float]]:
        values: list[float | None] = []
        avg_gain = state.avg_gain
        avg_loss = state.avg_loss
        prev_close = state.prev_close

        for close in closes:
            if close is None:
                values.append(None)
                continue
            delta = close - prev_close
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
            avg_gain = ((avg_gain * (period - 1)) + gain) / period
            avg_loss = ((avg_loss * (period - 1)) + loss) / period
            value = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
            values.append(value)
            prev_close = close

        return values, {"avg_gain": avg_gain, "avg_loss": avg_loss, "prev_close": prev_close}

    def _load_ts_codes(self, *, ts_code: str | None = None) -> list[str]:
        stmt = select(EquityDailyBar.ts_code).distinct().order_by(EquityDailyBar.ts_code.asc())
        if ts_code:
            stmt = stmt.where(EquityDailyBar.ts_code == ts_code)
        return list(self.session.scalars(stmt))

    def _load_trade_bounds(self, *, ts_code: str) -> tuple[date, date] | None:
        row = self.session.execute(
            select(
                func.min(EquityDailyBar.trade_date),
                func.max(EquityDailyBar.trade_date),
            ).where(EquityDailyBar.ts_code == ts_code)
        ).one()
        start_date, end_date = row
        if start_date is None or end_date is None:
            return None
        return start_date, end_date
