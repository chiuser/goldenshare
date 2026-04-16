from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(slots=True)
class ServingLightRefreshResult:
    touched_rows: int


class ServingLightRefreshService:
    def refresh_equity_daily_bar(
        self,
        session: Session,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
    ) -> ServingLightRefreshResult:
        predicates = ["1=1"]
        params: dict[str, object] = {}
        if ts_code is not None:
            predicates.append("s.ts_code = :ts_code")
            params["ts_code"] = ts_code
        if start_date is not None:
            predicates.append("s.trade_date >= :start_date")
            params["start_date"] = start_date
        if end_date is not None:
            predicates.append("s.trade_date <= :end_date")
            params["end_date"] = end_date

        result = session.execute(
            text(
                f"""
                INSERT INTO core_serving_light.equity_daily_bar_light (
                    ts_code,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    pre_close,
                    change_amount,
                    pct_chg,
                    vol,
                    amount,
                    source,
                    created_at,
                    updated_at
                )
                SELECT
                    s.ts_code,
                    s.trade_date,
                    s.open,
                    s.high,
                    s.low,
                    s.close,
                    s.pre_close,
                    s.change_amount,
                    s.pct_chg,
                    s.vol,
                    s.amount,
                    s.source,
                    now(),
                    now()
                FROM core_serving.equity_daily_bar s
                WHERE {' AND '.join(predicates)}
                ON CONFLICT (ts_code, trade_date) DO UPDATE
                SET open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    pre_close = excluded.pre_close,
                    change_amount = excluded.change_amount,
                    pct_chg = excluded.pct_chg,
                    vol = excluded.vol,
                    amount = excluded.amount,
                    source = excluded.source,
                    updated_at = now()
                """
            ),
            params,
        )
        session.commit()
        return ServingLightRefreshResult(touched_rows=int(result.rowcount or 0))
