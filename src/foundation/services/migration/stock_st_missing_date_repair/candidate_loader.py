from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.raw.raw_namechange import RawNamechange
from src.foundation.models.raw.raw_st import RawSt
from src.foundation.services.migration.stock_st_missing_date_repair.models import (
    StockStEventRecord,
    StockStMissingDateContext,
    StockStNamechangeRecord,
)


class StockStMissingDateCandidateLoader:
    def load_date_context(self, session: Session, trade_date: date) -> StockStMissingDateContext:
        prev_date = session.scalar(
            select(func.max(EquityStockSt.trade_date)).where(EquityStockSt.trade_date < trade_date)
        )
        next_date = session.scalar(
            select(func.min(EquityStockSt.trade_date)).where(EquityStockSt.trade_date > trade_date)
        )
        if prev_date is None or next_date is None:
            raise ValueError(f"缺失日期 {trade_date.isoformat()} 缺少相邻快照，无法重建。")

        prev_names = self._load_snapshot_names(session, prev_date)
        next_names = self._load_snapshot_names(session, next_date)
        same_day_st_events = self._load_same_day_st_events(session, trade_date)

        candidate_codes = sorted(set(prev_names) | set(next_names) | set(same_day_st_events))
        return StockStMissingDateContext(
            trade_date=trade_date,
            prev_date=prev_date,
            next_date=next_date,
            prev_names=prev_names,
            next_names=next_names,
            same_day_st_events=same_day_st_events,
            candidate_codes=tuple(candidate_codes),
        )

    def load_active_namechanges(
        self,
        session: Session,
        *,
        trade_date: date,
        candidate_codes: tuple[str, ...],
    ) -> dict[str, tuple[StockStNamechangeRecord, ...]]:
        if not candidate_codes:
            return {}
        rows = session.scalars(
            select(RawNamechange)
            .where(
                RawNamechange.ts_code.in_(candidate_codes),
                RawNamechange.start_date <= trade_date,
                func.coalesce(RawNamechange.end_date, date(9999, 12, 31)) >= trade_date,
            )
            .order_by(
                RawNamechange.ts_code,
                RawNamechange.start_date.desc().nullslast(),
                RawNamechange.ann_date.desc().nullslast(),
                RawNamechange.end_date.desc().nullslast(),
                RawNamechange.id.desc(),
            )
        ).all()
        grouped: dict[str, list[StockStNamechangeRecord]] = defaultdict(list)
        for row in rows:
            grouped[row.ts_code].append(
                StockStNamechangeRecord(
                    id=int(row.id),
                    ts_code=row.ts_code,
                    name=row.name,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    ann_date=row.ann_date,
                    change_reason=row.change_reason,
                )
            )
        return {ts_code: tuple(items) for ts_code, items in grouped.items()}

    @staticmethod
    def _load_snapshot_names(session: Session, trade_date: date) -> dict[str, str | None]:
        rows = session.execute(
            select(EquityStockSt.ts_code, EquityStockSt.name).where(EquityStockSt.trade_date == trade_date)
        ).all()
        return {str(ts_code): name for ts_code, name in rows}

    @staticmethod
    def _load_same_day_st_events(session: Session, trade_date: date) -> dict[str, tuple[StockStEventRecord, ...]]:
        rows = session.scalars(
            select(RawSt)
            .where(RawSt.imp_date == trade_date)
            .order_by(RawSt.ts_code, RawSt.pub_date, RawSt.id)
        ).all()
        grouped: dict[str, list[StockStEventRecord]] = defaultdict(list)
        for row in rows:
            grouped[row.ts_code].append(
                StockStEventRecord(
                    ts_code=row.ts_code,
                    name=row.name,
                    pub_date=row.pub_date,
                    imp_date=row.imp_date,
                    st_type=row.st_tpye,
                    st_reason=row.st_reason,
                    st_explain=row.st_explain,
                )
            )
        return {ts_code: tuple(items) for ts_code, items in grouped.items()}

