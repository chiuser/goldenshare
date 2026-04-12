from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select

from src.foundation.config.settings import get_settings
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core.equity_dividend import EquityDividend
from src.foundation.models.core.equity_price_restore_factor import EquityPriceRestoreFactor
from src.foundation.services.sync.base_sync_service import BaseSyncService


Q8 = Decimal("0.00000001")
ONE = Decimal("1")
ZERO = Decimal("0")


@dataclass(slots=True)
class _EventFactor:
    ex_date: date
    single_factor: Decimal


def _parse_date_or_none(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"invalid date value: {value!r}")


class SyncEquityPriceRestoreFactorService(BaseSyncService):
    job_name = "sync_equity_price_restore_factor"
    target_table = "core.equity_price_restore_factor"

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = _parse_date_or_none(kwargs.get("trade_date"))
        ts_code = kwargs.get("ts_code")
        execution_id = kwargs.get("execution_id")

        if run_type == "INCREMENTAL":
            if trade_date is None:
                raise ValueError("trade_date is required for incremental equity_price_restore_factor sync")
            start_date = trade_date
            end_date = trade_date
            result_date = trade_date
        else:
            start_date = _parse_date_or_none(kwargs.get("start_date")) or date.fromisoformat(get_settings().history_start_date)
            end_date = _parse_date_or_none(kwargs.get("end_date")) or self._latest_trade_date()
            if end_date is None:
                return 0, 0, None, "未找到股票日线数据"
            if start_date > end_date:
                raise ValueError("start_date cannot be greater than end_date")
            result_date = end_date

        ts_codes = self._load_ts_codes(start_date=start_date, end_date=end_date, ts_code=ts_code)
        if not ts_codes:
            return 0, 0, result_date, "指定区间无可处理股票日线数据"

        fetched_total = 0
        written_total = 0
        events_applied_total = 0
        for code in ts_codes:
            self.ensure_not_canceled(execution_id)
            fetched, written, events_applied = self._build_for_ts_code(code, start_date=start_date, end_date=end_date)
            fetched_total += fetched
            written_total += written
            events_applied_total += events_applied

        message = f"stocks={len(ts_codes)} days={fetched_total} events={events_applied_total}"
        return fetched_total, written_total, result_date, message

    def _build_for_ts_code(self, ts_code: str, *, start_date: date, end_date: date) -> tuple[int, int, int]:
        rows = list(
            self.session.execute(
                select(EquityDailyBar.trade_date, EquityDailyBar.close)
                .where(
                    EquityDailyBar.ts_code == ts_code,
                    EquityDailyBar.trade_date >= start_date,
                    EquityDailyBar.trade_date <= end_date,
                )
                .order_by(EquityDailyBar.trade_date.asc())
            )
        )
        if not rows:
            return 0, 0, 0

        prev_factor = self._factor_before(ts_code=ts_code, before_date=rows[0].trade_date) or ONE
        events_by_trade_date = self._load_event_factors_by_trade_date(
            ts_code=ts_code,
            start_date=rows[0].trade_date,
            end_date=rows[-1].trade_date,
        )

        output_rows: list[dict[str, Any]] = []
        events_applied = 0
        current = prev_factor
        for row in rows:
            trade_date = row.trade_date
            event_factors = events_by_trade_date.get(trade_date, [])
            single_factor: Decimal | None = None
            event_ex_date: date | None = None
            event_applied = False
            if event_factors:
                event_applied = True
                events_applied += len(event_factors)
                combined_single = ONE
                for event in event_factors:
                    combined_single = (combined_single * event.single_factor).quantize(Q8)
                    current = (current * event.single_factor).quantize(Q8)
                    event_ex_date = event.ex_date
                single_factor = combined_single
            output_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "cum_factor": current.quantize(Q8),
                    "single_factor": single_factor,
                    "event_applied": event_applied,
                    "event_ex_date": event_ex_date,
                }
            )

        written = self.dao.equity_price_restore_factor.bulk_upsert(output_rows)
        return len(rows), written, events_applied

    def _load_event_factors_by_trade_date(
        self,
        *,
        ts_code: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, list[_EventFactor]]:
        previous_trade_before_start = self.session.scalar(
            select(func.max(EquityDailyBar.trade_date)).where(
                EquityDailyBar.ts_code == ts_code,
                EquityDailyBar.trade_date < start_date,
            )
        )
        if previous_trade_before_start is not None:
            dividend_predicate = and_(
                EquityDividend.ts_code == ts_code,
                EquityDividend.div_proc == "实施",
                EquityDividend.ex_date.is_not(None),
                EquityDividend.ex_date > previous_trade_before_start,
                EquityDividend.ex_date <= end_date,
            )
        else:
            dividend_predicate = and_(
                EquityDividend.ts_code == ts_code,
                EquityDividend.div_proc == "实施",
                EquityDividend.ex_date.is_not(None),
                EquityDividend.ex_date <= end_date,
            )

        event_rows = list(
            self.session.execute(
                select(
                    EquityDividend.ex_date,
                    func.coalesce(func.sum(EquityDividend.cash_div_tax), ZERO).label("cash_div_tax"),
                    func.coalesce(func.sum(EquityDividend.stk_div), ZERO).label("stk_div"),
                )
                .where(dividend_predicate)
                .group_by(EquityDividend.ex_date)
                .order_by(EquityDividend.ex_date.asc())
            )
        )
        if not event_rows:
            return {}

        result: dict[date, list[_EventFactor]] = {}
        for event in event_rows:
            ex_date = event.ex_date
            if ex_date is None:
                continue
            prev_close = self._close_before(ts_code=ts_code, ex_date=ex_date)
            if prev_close is None or prev_close <= ZERO:
                continue
            apply_trade_date = self._first_trade_on_or_after(ts_code=ts_code, ex_date=ex_date, end_date=end_date)
            if apply_trade_date is None or apply_trade_date < start_date:
                continue
            cash_div_tax = event.cash_div_tax or ZERO
            stk_div = event.stk_div or ZERO
            denominator = (ONE + stk_div) * prev_close
            numerator = prev_close - cash_div_tax
            if denominator <= ZERO or numerator <= ZERO:
                continue
            single_factor = (numerator / denominator).quantize(Q8)
            result.setdefault(apply_trade_date, []).append(_EventFactor(ex_date=ex_date, single_factor=single_factor))
        return result

    def _factor_before(self, *, ts_code: str, before_date: date) -> Decimal | None:
        return self.session.scalar(
            select(EquityPriceRestoreFactor.cum_factor)
            .where(
                EquityPriceRestoreFactor.ts_code == ts_code,
                EquityPriceRestoreFactor.trade_date < before_date,
            )
            .order_by(EquityPriceRestoreFactor.trade_date.desc())
            .limit(1)
        )

    def _close_before(self, *, ts_code: str, ex_date: date) -> Decimal | None:
        return self.session.scalar(
            select(EquityDailyBar.close)
            .where(
                EquityDailyBar.ts_code == ts_code,
                EquityDailyBar.trade_date < ex_date,
            )
            .order_by(EquityDailyBar.trade_date.desc())
            .limit(1)
        )

    def _first_trade_on_or_after(self, *, ts_code: str, ex_date: date, end_date: date) -> date | None:
        return self.session.scalar(
            select(EquityDailyBar.trade_date)
            .where(
                EquityDailyBar.ts_code == ts_code,
                EquityDailyBar.trade_date >= ex_date,
                EquityDailyBar.trade_date <= end_date,
            )
            .order_by(EquityDailyBar.trade_date.asc())
            .limit(1)
        )

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
