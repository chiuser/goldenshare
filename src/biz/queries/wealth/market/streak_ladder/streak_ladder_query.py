from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.streak_ladder.streak_ladder_builder import StreakLadderRow
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


@dataclass(frozen=True, slots=True)
class StreakLadderRowsResult:
    rows: list[StreakLadderRow]
    invalid_board_count: int
    invalid_sample_ts_code: str | None
    invalid_sample_raw_value: str | None


class StreakLadderQuery:
    """Load two-day streak-ladder source rows from core_serving facts."""

    def load_rows(self, session: Session, *, trade_date: date) -> StreakLadderRowsResult:
        raw_rows = session.execute(
            select(
                EquityLimitList.ts_code,
                EquityLimitList.name,
                EquityLimitList.industry,
                EquityLimitList.limit_type,
                EquityLimitList.limit_times,
                EquityLimitList.close,
                EquityLimitList.pct_chg,
                EquityLimitList.fd_amount,
                EquityLimitList.limit_amount,
                EquityLimitList.open_times,
                EquityLimitList.first_time,
            ).where(
                EquityLimitList.trade_date == trade_date,
                EquityLimitList.limit_type == "U",
            )
        ).all()

        codes_to_fill = {
            row.ts_code
            for row in raw_rows
            if row.ts_code
            and not self._is_valid_limit_up_metrics(
                close=row.close,
                pct_chg=row.pct_chg,
            )
        }
        fallback_map = self._load_daily_bar_map(session, trade_date=trade_date, codes=codes_to_fill)

        valid_rows: list[StreakLadderRow] = []
        invalid_count = 0
        invalid_sample_ts_code: str | None = None
        invalid_sample_raw_value: str | None = None

        for row in raw_rows:
            if not row.ts_code:
                invalid_count += 1
                if invalid_sample_ts_code is None:
                    invalid_sample_ts_code = None
                    invalid_sample_raw_value = str(row.limit_times) if row.limit_times is not None else None
                continue

            board_count = self._parse_board_count(row.limit_times)
            if board_count <= 0:
                invalid_count += 1
                if invalid_sample_ts_code is None:
                    invalid_sample_ts_code = row.ts_code
                    invalid_sample_raw_value = str(row.limit_times) if row.limit_times is not None else None
                continue

            close = row.close
            pct_chg = row.pct_chg
            if not self._is_valid_limit_up_metrics(close=close, pct_chg=pct_chg):
                fallback = fallback_map.get(row.ts_code)
                if fallback is not None:
                    close = fallback[0]
                    pct_chg = fallback[1]
            if not self._is_valid_limit_up_metrics(close=close, pct_chg=pct_chg):
                continue

            valid_rows.append(
                StreakLadderRow(
                    ts_code=row.ts_code,
                    stock_name=row.name,
                    sector_name=row.industry,
                    limit_type=row.limit_type,
                    board_count=board_count,
                    latest_price=close,
                    change_pct=pct_chg,
                    fd_amount=row.fd_amount,
                    limit_amount=row.limit_amount,
                    open_times=row.open_times,
                    first_limit_time=row.first_time,
                )
            )

        return StreakLadderRowsResult(
            rows=valid_rows,
            invalid_board_count=invalid_count,
            invalid_sample_ts_code=invalid_sample_ts_code,
            invalid_sample_raw_value=invalid_sample_raw_value,
        )

    @staticmethod
    def _parse_board_count(raw_value: int | None) -> int:
        if raw_value is None:
            return 0
        try:
            board_count = int(raw_value)
        except (TypeError, ValueError):
            return 0
        return board_count if board_count > 0 else 0

    @staticmethod
    def _load_daily_bar_map(
        session: Session,
        *,
        trade_date: date,
        codes: set[str],
    ) -> dict[str, tuple[Decimal | None, Decimal | None]]:
        if not codes:
            return {}
        rows = session.execute(
            select(
                EquityDailyBar.ts_code,
                EquityDailyBar.close,
                EquityDailyBar.pct_chg,
            ).where(
                EquityDailyBar.trade_date == trade_date,
                EquityDailyBar.ts_code.in_(codes),
            )
        ).all()
        result: dict[str, tuple[Decimal | None, Decimal | None]] = {}
        for row in rows:
            if not row.ts_code:
                continue
            result[row.ts_code] = (row.close, row.pct_chg)
        return result

    @staticmethod
    def _is_valid_limit_up_metrics(
        *,
        close: Decimal | None,
        pct_chg: Decimal | None,
    ) -> bool:
        return bool(close is not None and pct_chg is not None and close > 0 and pct_chg > 0)
