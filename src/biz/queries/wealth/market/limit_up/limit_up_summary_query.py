from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.limit_step import LimitStep


_SKY_MARKERS = ("天地板", "天地天板")
_FLOOR_MARKERS = ("地天板", "天地天板")
_EXCLUDE_MARKERS = ("昨日地天板", "前一交易日地天板", "昨日天地板", "前一交易日天地板")
_BOARD_COUNT_PATTERN = re.compile(r"(\d+)")


@dataclass(frozen=True, slots=True)
class LimitUpSummaryFacts:
    limit_up_total: int
    limit_up_st: int
    limit_down_total: int
    limit_down_st: int
    broken_total: int
    broken_st: int
    non_st_limit_up: int
    non_st_broken: int
    sealing_rate_non_st: float | None
    streak_count: int
    max_board: int
    sky_to_floor_count: int
    floor_to_sky_count: int

    @property
    def has_summary_data(self) -> bool:
        return (self.limit_up_total + self.limit_down_total + self.broken_total) > 0


class LimitUpSummaryQuery:
    """Load summary stats for limit-up module."""

    def load(self, session: Session, *, trade_date: date) -> LimitUpSummaryFacts:
        up_codes = self._load_distinct_codes(session, trade_date=trade_date, limit_type="涨停池")
        down_codes = self._load_distinct_codes(session, trade_date=trade_date, limit_type="跌停池")
        broken_codes = self._load_distinct_codes(session, trade_date=trade_date, limit_type="炸板池")
        st_codes = self._load_st_codes(session, trade_date=trade_date)

        limit_up_total = len(up_codes)
        limit_down_total = len(down_codes)
        broken_total = len(broken_codes)
        limit_up_st = len(up_codes & st_codes)
        limit_down_st = len(down_codes & st_codes)
        broken_st = len(broken_codes & st_codes)

        non_st_limit_up = max(limit_up_total - limit_up_st, 0)
        non_st_broken = max(broken_total - broken_st, 0)
        touch_count = non_st_limit_up + non_st_broken
        sealing_rate_non_st = float(non_st_limit_up / touch_count) if touch_count > 0 else None

        streak_count, max_board = self._load_streak_stats(session, trade_date=trade_date, st_codes=st_codes)
        sky_to_floor_count, floor_to_sky_count = self._load_pattern_counts(session, trade_date=trade_date)

        return LimitUpSummaryFacts(
            limit_up_total=limit_up_total,
            limit_up_st=limit_up_st,
            limit_down_total=limit_down_total,
            limit_down_st=limit_down_st,
            broken_total=broken_total,
            broken_st=broken_st,
            non_st_limit_up=non_st_limit_up,
            non_st_broken=non_st_broken,
            sealing_rate_non_st=sealing_rate_non_st,
            streak_count=streak_count,
            max_board=max_board,
            sky_to_floor_count=sky_to_floor_count,
            floor_to_sky_count=floor_to_sky_count,
        )

    @staticmethod
    def _load_distinct_codes(session: Session, *, trade_date: date, limit_type: str) -> set[str]:
        rows = session.scalars(
            select(LimitListThs.ts_code)
            .where(
                LimitListThs.trade_date == trade_date,
                LimitListThs.limit_type == limit_type,
            )
            .distinct()
        ).all()
        return {item for item in rows if item}

    @staticmethod
    def _load_st_codes(session: Session, *, trade_date: date) -> set[str]:
        rows = session.scalars(
            select(EquityStockSt.ts_code).where(
                EquityStockSt.trade_date == trade_date,
            )
        ).all()
        return {item for item in rows if item}

    def _load_streak_stats(self, session: Session, *, trade_date: date, st_codes: set[str]) -> tuple[int, int]:
        rows = session.execute(
            select(
                LimitStep.ts_code,
                LimitStep.nums,
            ).where(
                LimitStep.trade_date == trade_date,
            )
        ).all()
        board_by_code: dict[str, int] = {}
        for row in rows:
            ts_code = row.ts_code
            if not ts_code or ts_code in st_codes:
                continue
            board_count = self._parse_board_count(row.nums)
            if board_count <= 0:
                continue
            current = board_by_code.get(ts_code, 0)
            if board_count > current:
                board_by_code[ts_code] = board_count

        streak_count = sum(1 for value in board_by_code.values() if value >= 2)
        max_board = max(board_by_code.values(), default=0)
        return streak_count, max_board

    @staticmethod
    def _parse_board_count(raw_nums: str | None) -> int:
        if raw_nums is None:
            return 0
        text = raw_nums.strip()
        if not text:
            return 0
        match = _BOARD_COUNT_PATTERN.search(text)
        if match is None:
            return 0
        try:
            return int(match.group(1))
        except ValueError:
            return 0

    def _load_pattern_counts(self, session: Session, *, trade_date: date) -> tuple[int, int]:
        rows = session.execute(
            select(
                LimitListThs.ts_code,
                LimitListThs.tag,
                LimitListThs.status,
                LimitListThs.lu_desc,
            ).where(
                LimitListThs.trade_date == trade_date,
            )
        ).all()

        text_by_code: dict[str, list[str]] = {}
        for row in rows:
            if not row.ts_code:
                continue
            values = [value.strip() for value in [row.tag, row.status, row.lu_desc] if value and value.strip()]
            if not values:
                continue
            text_by_code.setdefault(row.ts_code, []).extend(values)

        sky_to_floor_count = 0
        floor_to_sky_count = 0
        for values in text_by_code.values():
            text = " ".join(values)
            if any(marker in text for marker in _EXCLUDE_MARKERS):
                continue
            is_sky = any(marker in text for marker in _SKY_MARKERS)
            is_floor = any(marker in text for marker in _FLOOR_MARKERS)
            if is_sky:
                sky_to_floor_count += 1
            if is_floor:
                floor_to_sky_count += 1
        return sky_to_floor_count, floor_to_sky_count
