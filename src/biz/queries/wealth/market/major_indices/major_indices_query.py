from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


@dataclass(frozen=True, slots=True)
class MajorIndicesSnapshotRow:
    ts_code: str
    close: Decimal | None
    change_amount: Decimal | None
    pct_chg: Decimal | None
    amount: Decimal | None


class MajorIndicesQuery:
    """Load major indices source facts."""

    def load_index_names(self, session: Session, *, index_codes: list[str]) -> dict[str, str | None]:
        if not index_codes:
            return {}
        rows = session.execute(
            select(IndexBasic.ts_code, IndexBasic.name).where(IndexBasic.ts_code.in_(tuple(index_codes)))
        ).all()
        return {row.ts_code: row.name for row in rows}

    def load_snapshot_rows(
        self,
        session: Session,
        *,
        trade_date: date,
        index_codes: list[str],
    ) -> dict[str, MajorIndicesSnapshotRow]:
        if not index_codes:
            return {}
        rows = session.execute(
            select(
                IndexDailyServing.ts_code,
                IndexDailyServing.close,
                IndexDailyServing.change_amount,
                IndexDailyServing.pct_chg,
                IndexDailyServing.amount,
            ).where(
                IndexDailyServing.trade_date == trade_date,
                IndexDailyServing.ts_code.in_(tuple(index_codes)),
            )
        ).all()
        return {
            row.ts_code: MajorIndicesSnapshotRow(
                ts_code=row.ts_code,
                close=row.close,
                change_amount=row.change_amount,
                pct_chg=row.pct_chg,
                amount=row.amount,
            )
            for row in rows
        }

