from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.security_serving import Security


_KLINE_FIELD_NAMES: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_change",
    "vol",
    "amount",
    "ma_bfq_5",
    "ma_bfq_10",
    "ma_bfq_20",
    "ma_bfq_30",
    "ma_bfq_60",
    "ma_bfq_90",
    "ma_bfq_250",
    "boll_upper_bfq",
    "boll_mid_bfq",
    "boll_lower_bfq",
    "macd_dif_bfq",
    "macd_dea_bfq",
    "macd_bfq",
    "kdj_k_bfq",
    "kdj_d_bfq",
    "kdj_bfq",
)

KLINE_COLUMNS = tuple(getattr(IndexFactorPro, field_name) for field_name in _KLINE_FIELD_NAMES)

_A_SHARE_EXCHANGES = ("SSE", "SZSE", "BSE")


def _a_share_security_conditions() -> tuple[Any, ...]:
    return (
        Security.security_type == "EQUITY",
        Security.exchange.in_(_A_SHARE_EXCHANGES),
        Security.curr_type == "CNY",
    )


def _resolved_constituent_pct_chg(*, contribution_trade_date: date) -> Any:
    is_suspended = (
        select(EquitySuspendD.id)
        .where(
            EquitySuspendD.ts_code == IndexWeight.con_code,
            EquitySuspendD.trade_date == contribution_trade_date,
            EquitySuspendD.suspend_type == "S",
        )
        .exists()
    )
    return case(
        (EquityDailyBar.pct_chg.is_not(None), EquityDailyBar.pct_chg),
        (is_suspended, 0),
        else_=None,
    )


class IndexDetailQuery:
    """Read index-detail facts with explicit field projections."""

    def load_identity(self, session: Session, *, ts_code: str) -> dict[str, Any] | None:
        statement = select(
            IndexBasic.ts_code,
            IndexBasic.name,
            IndexBasic.market,
            IndexBasic.publisher,
            IndexBasic.category,
        ).where(IndexBasic.ts_code == ts_code)
        row = session.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def load_latest_quote(
        self,
        session: Session,
        *,
        ts_code: str,
        expected_trade_date: date,
    ) -> dict[str, Any] | None:
        latest_date = (
            select(func.max(IndexDailyServing.trade_date))
            .where(
                IndexDailyServing.ts_code == ts_code,
                IndexDailyServing.trade_date <= expected_trade_date,
            )
            .scalar_subquery()
        )
        statement = (
            select(
                IndexDailyServing.ts_code,
                IndexDailyServing.trade_date,
                IndexDailyServing.open,
                IndexDailyServing.high,
                IndexDailyServing.low,
                IndexDailyServing.close,
                IndexDailyServing.pre_close,
                IndexDailyServing.change_amount,
                IndexDailyServing.pct_chg,
                IndexFactorPro.trade_date.label("factor_trade_date"),
                IndexFactorPro.vol.label("factor_vol"),
                IndexFactorPro.amount.label("factor_amount"),
            )
            .outerjoin(
                IndexFactorPro,
                and_(
                    IndexFactorPro.ts_code == IndexDailyServing.ts_code,
                    IndexFactorPro.trade_date == IndexDailyServing.trade_date,
                ),
            )
            .where(
                IndexDailyServing.ts_code == ts_code,
                IndexDailyServing.trade_date == latest_date,
            )
        )
        row = session.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def load_daily_basic(
        self,
        session: Session,
        *,
        ts_code: str,
        trade_date: date,
    ) -> dict[str, Any] | None:
        statement = select(
            IndexDailyBasic.trade_date,
            IndexDailyBasic.pe,
            IndexDailyBasic.pe_ttm,
            IndexDailyBasic.pb,
            IndexDailyBasic.turnover_rate,
            IndexDailyBasic.float_mv,
            IndexDailyBasic.total_mv,
        ).where(
            IndexDailyBasic.ts_code == ts_code,
            IndexDailyBasic.trade_date == trade_date,
        )
        row = session.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def load_weight_trade_date(
        self,
        session: Session,
        *,
        ts_code: str,
        contribution_trade_date: date,
    ) -> date | None:
        return session.scalar(
            select(func.max(IndexWeight.trade_date)).where(
                IndexWeight.index_code == ts_code,
                IndexWeight.trade_date <= contribution_trade_date,
            )
        )

    def load_breadth(
        self,
        session: Session,
        *,
        ts_code: str,
        contribution_trade_date: date,
        weight_trade_date: date,
    ) -> dict[str, int]:
        resolved_pct_chg = _resolved_constituent_pct_chg(
            contribution_trade_date=contribution_trade_date
        )
        statement = (
            select(
                func.count().label("total_count"),
                func.count(resolved_pct_chg).label("matched_count"),
                func.sum(case((resolved_pct_chg > 0, 1), else_=0)).label("up_count"),
                func.sum(case((resolved_pct_chg == 0, 1), else_=0)).label("flat_count"),
                func.sum(case((resolved_pct_chg < 0, 1), else_=0)).label("down_count"),
            )
            .select_from(IndexWeight)
            .join(
                Security,
                and_(
                    Security.ts_code == IndexWeight.con_code,
                    *_a_share_security_conditions(),
                ),
            )
            .outerjoin(
                EquityDailyBar,
                and_(
                    EquityDailyBar.ts_code == IndexWeight.con_code,
                    EquityDailyBar.trade_date == contribution_trade_date,
                ),
            )
            .where(
                IndexWeight.index_code == ts_code,
                IndexWeight.trade_date == weight_trade_date,
            )
        )
        row = session.execute(statement).mappings().one()
        return {
            "total_count": int(row["total_count"] or 0),
            "matched_count": int(row["matched_count"] or 0),
            "up_count": int(row["up_count"] or 0),
            "flat_count": int(row["flat_count"] or 0),
            "down_count": int(row["down_count"] or 0),
        }

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
            IndexFactorPro.ts_code == ts_code,
            IndexFactorPro.trade_date <= end_date,
        ]
        if start_date is not None:
            conditions.append(IndexFactorPro.trade_date >= start_date)
        statement = select(*KLINE_COLUMNS).where(*conditions).order_by(desc(IndexFactorPro.trade_date)).limit(limit)
        rows = [dict(row) for row in session.execute(statement).mappings().all()]
        rows.reverse()
        return rows

    def count_effective_history_before(
        self,
        session: Session,
        *,
        ts_code: str,
        first_trade_date: date,
    ) -> int:
        count = session.scalar(
            select(func.count())
            .select_from(IndexFactorPro)
            .where(
                IndexFactorPro.ts_code == ts_code,
                IndexFactorPro.trade_date < first_trade_date,
                IndexFactorPro.close.is_not(None),
            )
        )
        return int(count or 0)

    def load_latest_daily_date(
        self,
        session: Session,
        *,
        ts_code: str,
        end_date: date,
    ) -> date | None:
        return session.scalar(
            select(func.max(IndexDailyServing.trade_date)).where(
                IndexDailyServing.ts_code == ts_code,
                IndexDailyServing.trade_date <= end_date,
            )
        )

    def load_latest_daily_anchor(
        self,
        session: Session,
        *,
        ts_code: str,
        expected_trade_date: date,
    ) -> dict[str, Any] | None:
        statement = (
            select(IndexDailyServing.trade_date, IndexDailyServing.pre_close)
            .where(
                IndexDailyServing.ts_code == ts_code,
                IndexDailyServing.trade_date <= expected_trade_date,
            )
            .order_by(desc(IndexDailyServing.trade_date))
            .limit(1)
        )
        row = session.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def load_weight_batch_stats(
        self,
        session: Session,
        *,
        ts_code: str,
        weight_trade_date: date,
    ) -> dict[str, int]:
        statement = (
            select(
                func.count().label("total_count"),
                func.count(IndexWeight.weight).label("weight_count"),
                func.count(func.distinct(IndexWeight.con_code)).label("distinct_constituent_count"),
            )
            .select_from(IndexWeight)
            .join(
                Security,
                and_(
                    Security.ts_code == IndexWeight.con_code,
                    *_a_share_security_conditions(),
                ),
            )
            .where(
                IndexWeight.index_code == ts_code,
                IndexWeight.trade_date == weight_trade_date,
            )
        )
        row = session.execute(statement).mappings().one()
        return {
            "total_count": int(row["total_count"] or 0),
            "weight_count": int(row["weight_count"] or 0),
            "distinct_constituent_count": int(row["distinct_constituent_count"] or 0),
        }

    def load_weight_rows(
        self,
        session: Session,
        *,
        ts_code: str,
        contribution_trade_date: date,
        weight_trade_date: date,
    ) -> list[dict[str, Any]]:
        resolved_pct_chg = _resolved_constituent_pct_chg(
            contribution_trade_date=contribution_trade_date
        )
        statement = (
            select(
                IndexWeight.con_code,
                IndexWeight.weight,
                Security.name,
                resolved_pct_chg.label("pct_chg"),
            )
            .select_from(IndexWeight)
            .join(
                Security,
                and_(
                    Security.ts_code == IndexWeight.con_code,
                    *_a_share_security_conditions(),
                ),
            )
            .outerjoin(
                EquityDailyBar,
                and_(
                    EquityDailyBar.ts_code == IndexWeight.con_code,
                    EquityDailyBar.trade_date == contribution_trade_date,
                ),
            )
            .where(
                IndexWeight.index_code == ts_code,
                IndexWeight.trade_date == weight_trade_date,
            )
            .order_by(desc(IndexWeight.weight), IndexWeight.con_code)
        )
        return [dict(row) for row in session.execute(statement).mappings().all()]
