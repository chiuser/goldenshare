from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core_serving.security_serving import Security


_FACTOR_FIELD_NAMES: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
    "turnover_rate",
    "volume_ratio",
    "ma_qfq_5",
    "ma_qfq_10",
    "ma_qfq_20",
    "ma_qfq_30",
    "ma_qfq_60",
    "ma_qfq_90",
    "ma_qfq_250",
    "boll_upper_qfq",
    "boll_mid_qfq",
    "boll_lower_qfq",
    "macd_dif_qfq",
    "macd_dea_qfq",
    "macd_qfq",
    "kdj_k_qfq",
    "kdj_d_qfq",
    "kdj_qfq",
)

FACTOR_COLUMNS = tuple(getattr(EquityFactorPro, field_name) for field_name in _FACTOR_FIELD_NAMES)


class StockDetailQuery:
    """Read stock detail facts from the current serving tables."""

    def load_security(self, session: Session, *, ts_code: str) -> Security | None:
        return session.get(Security, ts_code)

    def load_latest_factor_row(
        self,
        session: Session,
        *,
        ts_code: str,
        expected_trade_date: date,
    ) -> dict[str, Any] | None:
        statement = (
            select(*FACTOR_COLUMNS)
            .where(
                EquityFactorPro.ts_code == ts_code,
                EquityFactorPro.trade_date <= expected_trade_date,
            )
            .order_by(desc(EquityFactorPro.trade_date))
            .limit(1)
        )
        row = session.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def load_kline_rows(
        self,
        session: Session,
        *,
        ts_code: str,
        end_date: date,
        start_date: date | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        conditions = [
            EquityFactorPro.ts_code == ts_code,
            EquityFactorPro.trade_date <= end_date,
        ]
        if start_date is not None:
            conditions.append(EquityFactorPro.trade_date >= start_date)

        statement = (
            select(*FACTOR_COLUMNS)
            .where(*conditions)
            .order_by(desc(EquityFactorPro.trade_date))
            .limit(limit)
        )
        rows = [dict(row) for row in session.execute(statement).mappings().all()]
        rows.reverse()
        return rows
