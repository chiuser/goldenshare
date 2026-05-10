from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.limit_step import LimitStep
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


_BOARD_COUNT_PATTERN = re.compile(r"(\d+)")
_UNKNOWN_TEXT = "--"


@dataclass(frozen=True, slots=True)
class LimitSectorView:
    sector_code: str
    sector_name: str
    sector_type: str
    limit_up_count: int


@dataclass(frozen=True, slots=True)
class LimitLeaderView:
    stock_code: str
    stock_name: str | None
    latest_price: float | None
    change_pct: float | None
    rank: int
    streak_label: str
    recent_limit_text: str
    first_limit_time: str
    open_times: int
    sealed_amount_display_text: str


@dataclass(frozen=True, slots=True)
class LimitStructureResult:
    trade_date: date
    selected_sector_code: str
    selected_stock_code: str
    sectors: list[LimitSectorView]
    leader_stocks: dict[str, list[LimitLeaderView]]

    @property
    def has_structure_data(self) -> bool:
        return bool(self.sectors) and bool(self.selected_sector_code)


class LimitUpStructureQuery:
    """Load sector distribution and leader stocks for limit-up module."""

    def __init__(
        self,
        *,
        st_excluded_sector_codes: tuple[str, ...],
        recent_limit_window_days: int,
        top_sector_limit: int = 5,
        top_stock_limit: int = 3,
    ) -> None:
        self._st_excluded_sector_codes = st_excluded_sector_codes
        self._recent_limit_window_days = recent_limit_window_days
        self._top_sector_limit = top_sector_limit
        self._top_stock_limit = top_stock_limit

    def load(self, session: Session, *, trade_date: date) -> LimitStructureResult:
        st_codes = self._load_st_codes(session, trade_date=trade_date)
        sectors = self._load_top_sectors(session, trade_date=trade_date)
        if not sectors:
            return LimitStructureResult(
                trade_date=trade_date,
                selected_sector_code="",
                selected_stock_code="",
                sectors=[],
                leader_stocks={},
            )

        limit_up_codes = self._load_limit_up_codes(session, trade_date=trade_date)
        recent_trade_dates = self._load_recent_trade_dates(
            session,
            end_trade_date=trade_date,
            limit_days=self._recent_limit_window_days,
        )

        sector_code_set = {sector.sector_code for sector in sectors}
        member_map = self._load_sector_member_map(session, trade_date=trade_date, sector_codes=sector_code_set)
        all_candidate_codes: set[str] = set()
        for sector_code in sector_code_set:
            all_candidate_codes.update(member_map.get(sector_code, {}).keys())

        board_count_by_code = self._load_board_count_map(session, trade_date=trade_date, codes=all_candidate_codes)
        recent_limit_count_by_code = self._load_recent_limit_count_map(
            session,
            trade_dates=recent_trade_dates,
            codes=all_candidate_codes,
        )
        daily_snapshot_map = self._load_daily_snapshot_map(session, trade_date=trade_date, codes=all_candidate_codes)
        fallback_market_map = self._load_market_snapshot_map(session, trade_date=trade_date, codes=all_candidate_codes)

        leader_stocks: dict[str, list[LimitLeaderView]] = {}
        for sector in sectors:
            member_name_map = member_map.get(sector.sector_code, {})
            non_st_member_codes = set(member_name_map.keys()) - st_codes
            strict_candidate_codes = non_st_member_codes & limit_up_codes
            fallback_candidate_codes = non_st_member_codes - strict_candidate_codes

            strict_rows = self._build_leader_candidate_rows(
                codes=strict_candidate_codes,
                member_name_map=member_name_map,
                board_count_by_code=board_count_by_code,
                recent_limit_count_by_code=recent_limit_count_by_code,
                daily_snapshot_map=daily_snapshot_map,
                fallback_market_map=fallback_market_map,
                recent_window_days=self._recent_limit_window_days,
            )
            fallback_rows = self._build_leader_candidate_rows(
                codes=fallback_candidate_codes,
                member_name_map=member_name_map,
                board_count_by_code=board_count_by_code,
                recent_limit_count_by_code=recent_limit_count_by_code,
                daily_snapshot_map=daily_snapshot_map,
                fallback_market_map=fallback_market_map,
                recent_window_days=self._recent_limit_window_days,
            )

            sorted_rows = sorted(strict_rows, key=self._leader_sort_key) + sorted(fallback_rows, key=self._leader_sort_key)
            top_rows = sorted_rows[: self._top_stock_limit]
            leader_stocks[sector.sector_code] = [
                LimitLeaderView(
                    stock_code=row["stock_code"],
                    stock_name=row["stock_name"],
                    latest_price=row["latest_price"],
                    change_pct=row["change_pct"],
                    rank=index + 1,
                    streak_label=row["streak_label"],
                    recent_limit_text=row["recent_limit_text"],
                    first_limit_time=row["first_limit_time"],
                    open_times=row["open_times"],
                    sealed_amount_display_text=row["sealed_amount_display_text"],
                )
                for index, row in enumerate(top_rows)
            ]

        selected_sector_code = sectors[0].sector_code if sectors else ""
        selected_sector_rows = leader_stocks.get(selected_sector_code, [])
        selected_stock_code = selected_sector_rows[0].stock_code if selected_sector_rows else ""
        return LimitStructureResult(
            trade_date=trade_date,
            selected_sector_code=selected_sector_code,
            selected_stock_code=selected_stock_code,
            sectors=sectors,
            leader_stocks=leader_stocks,
        )

    def _load_top_sectors(self, session: Session, *, trade_date: date) -> list[LimitSectorView]:
        rows = session.execute(
            select(
                LimitCptList.ts_code,
                LimitCptList.name,
                LimitCptList.up_nums,
                LimitCptList.rank,
            ).where(
                LimitCptList.trade_date == trade_date,
            )
        ).all()

        parsed_rows: list[tuple[int, int, str, str]] = []
        for row in rows:
            sector_code = (row.ts_code or "").strip()
            if not sector_code:
                continue
            if sector_code in self._st_excluded_sector_codes:
                continue
            sector_name = (row.name or "").strip() or sector_code
            limit_up_count = int(row.up_nums or 0)
            rank_value = self._parse_rank_value(row.rank)
            parsed_rows.append((rank_value, -limit_up_count, sector_code, sector_name))

        parsed_rows.sort()
        result: list[LimitSectorView] = []
        for rank_value, minus_count, sector_code, sector_name in parsed_rows:
            _ = rank_value
            result.append(
                LimitSectorView(
                    sector_code=sector_code,
                    sector_name=sector_name,
                    sector_type=self._infer_sector_type(sector_name=sector_name),
                    limit_up_count=-minus_count,
                )
            )
            if len(result) >= self._top_sector_limit:
                break
        return result

    @staticmethod
    def _parse_rank_value(raw_rank: str | None) -> int:
        if raw_rank is None:
            return 10_000
        text = raw_rank.strip()
        if not text:
            return 10_000
        try:
            return int(text)
        except ValueError:
            return 10_000

    @staticmethod
    def _infer_sector_type(*, sector_name: str) -> str:
        if "行业" in sector_name:
            return "INDUSTRY"
        if "地域" in sector_name:
            return "REGION"
        return "CONCEPT"

    @staticmethod
    def _load_st_codes(session: Session, *, trade_date: date) -> set[str]:
        rows = session.scalars(
            select(EquityStockSt.ts_code).where(
                EquityStockSt.trade_date == trade_date,
            )
        ).all()
        return {item for item in rows if item}

    @staticmethod
    def _load_limit_up_codes(session: Session, *, trade_date: date) -> set[str]:
        rows = session.scalars(
            select(LimitListThs.ts_code)
            .where(
                LimitListThs.trade_date == trade_date,
                LimitListThs.limit_type == "涨停池",
            )
            .distinct()
        ).all()
        return {item for item in rows if item}

    @staticmethod
    def _load_recent_trade_dates(session: Session, *, end_trade_date: date, limit_days: int) -> list[date]:
        rows = session.scalars(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(limit_days)
        ).all()
        return list(sorted(rows))

    @staticmethod
    def _load_sector_member_map(
        session: Session,
        *,
        trade_date: date,
        sector_codes: set[str],
    ) -> dict[str, dict[str, str | None]]:
        if not sector_codes:
            return {}
        rows = session.execute(
            select(
                ThsMember.ts_code,
                ThsMember.con_code,
                ThsMember.con_name,
            ).where(
                ThsMember.ts_code.in_(sector_codes),
                or_(ThsMember.in_date.is_(None), ThsMember.in_date <= trade_date),
                or_(ThsMember.out_date.is_(None), ThsMember.out_date >= trade_date),
            )
        ).all()
        result: dict[str, dict[str, str | None]] = {}
        for row in rows:
            sector_code = row.ts_code
            stock_code = row.con_code
            if not sector_code or not stock_code:
                continue
            result.setdefault(sector_code, {})[stock_code] = row.con_name
        return result

    def _load_board_count_map(self, session: Session, *, trade_date: date, codes: set[str]) -> dict[str, int]:
        if not codes:
            return {}
        rows = session.execute(
            select(
                LimitStep.ts_code,
                LimitStep.nums,
            ).where(
                LimitStep.trade_date == trade_date,
                LimitStep.ts_code.in_(codes),
            )
        ).all()
        board_count_by_code: dict[str, int] = {}
        for row in rows:
            if not row.ts_code:
                continue
            board_count = self._parse_board_count(raw_nums=row.nums)
            if board_count <= 0:
                continue
            current = board_count_by_code.get(row.ts_code, 0)
            if board_count > current:
                board_count_by_code[row.ts_code] = board_count
        return board_count_by_code

    @staticmethod
    def _parse_board_count(*, raw_nums: str | None) -> int:
        if raw_nums is None:
            return 0
        match = _BOARD_COUNT_PATTERN.search(raw_nums.strip())
        if match is None:
            return 0
        try:
            return int(match.group(1))
        except ValueError:
            return 0

    @staticmethod
    def _load_recent_limit_count_map(
        session: Session,
        *,
        trade_dates: list[date],
        codes: set[str],
    ) -> dict[str, int]:
        if not trade_dates or not codes:
            return {}
        rows = session.execute(
            select(
                LimitListThs.ts_code,
                LimitListThs.trade_date,
            ).where(
                LimitListThs.trade_date.in_(trade_dates),
                LimitListThs.limit_type == "涨停池",
                LimitListThs.ts_code.in_(codes),
            )
        ).all()
        date_bucket: dict[str, set[date]] = {}
        for row in rows:
            if not row.ts_code or row.trade_date is None:
                continue
            date_bucket.setdefault(row.ts_code, set()).add(row.trade_date)
        return {stock_code: len(trade_date_set) for stock_code, trade_date_set in date_bucket.items()}

    @staticmethod
    def _load_daily_snapshot_map(
        session: Session,
        *,
        trade_date: date,
        codes: set[str],
    ) -> dict[str, dict[str, str | int | float | Decimal | None]]:
        if not codes:
            return {}
        rows = session.execute(
            select(
                LimitListThs.ts_code,
                LimitListThs.name,
                LimitListThs.price,
                LimitListThs.pct_chg,
                LimitListThs.first_lu_time,
                LimitListThs.open_num,
                LimitListThs.limit_amount,
            ).where(
                LimitListThs.trade_date == trade_date,
                LimitListThs.ts_code.in_(codes),
            )
        ).all()
        snapshot: dict[str, dict[str, str | int | float | Decimal | None]] = {}
        for row in rows:
            ts_code = row.ts_code
            if not ts_code:
                continue
            current = snapshot.setdefault(
                ts_code,
                {
                    "name": None,
                    "price": None,
                    "pct_chg": None,
                    "first_lu_time": None,
                    "open_num": None,
                    "limit_amount": None,
                },
            )
            if current["name"] is None and row.name:
                current["name"] = row.name
            if current["price"] is None and row.price is not None:
                current["price"] = row.price
            if current["pct_chg"] is None and row.pct_chg is not None:
                current["pct_chg"] = row.pct_chg
            if current["first_lu_time"] is None and row.first_lu_time:
                current["first_lu_time"] = row.first_lu_time
            if current["open_num"] is None and row.open_num is not None:
                current["open_num"] = row.open_num
            if current["limit_amount"] is None and row.limit_amount is not None:
                current["limit_amount"] = row.limit_amount
        return snapshot

    @staticmethod
    def _load_market_snapshot_map(
        session: Session,
        *,
        trade_date: date,
        codes: set[str],
    ) -> dict[str, dict[str, float | None]]:
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
        return {
            row.ts_code: {
                "close": float(row.close) if row.close is not None else None,
                "pct_chg": float(row.pct_chg) if row.pct_chg is not None else None,
            }
            for row in rows
            if row.ts_code
        }

    def _build_leader_candidate_rows(
        self,
        *,
        codes: set[str],
        member_name_map: dict[str, str | None],
        board_count_by_code: dict[str, int],
        recent_limit_count_by_code: dict[str, int],
        daily_snapshot_map: dict[str, dict[str, str | int | float | Decimal | None]],
        fallback_market_map: dict[str, dict[str, float | None]],
        recent_window_days: int,
    ) -> list[dict[str, str | int | float | None]]:
        result: list[dict[str, str | int | float | None]] = []
        for code in codes:
            snapshot = daily_snapshot_map.get(code, {})
            fallback = fallback_market_map.get(code, {})
            stock_name = snapshot.get("name") or member_name_map.get(code)
            price = snapshot.get("price")
            pct_chg = snapshot.get("pct_chg")
            latest_price = float(price) if isinstance(price, Decimal) else (float(price) if isinstance(price, (int, float)) else None)
            change_pct = float(pct_chg) if isinstance(pct_chg, Decimal) else (float(pct_chg) if isinstance(pct_chg, (int, float)) else None)
            if latest_price is None:
                latest_price = fallback.get("close")
            if change_pct is None:
                change_pct = fallback.get("pct_chg")
            board_count = int(board_count_by_code.get(code, 0))
            recent_count = int(recent_limit_count_by_code.get(code, 0))
            first_limit_time = str(snapshot.get("first_lu_time") or _UNKNOWN_TEXT)
            open_num_raw = snapshot.get("open_num")
            open_times = int(open_num_raw) if isinstance(open_num_raw, int) else 0
            sealed_amount_display_text = self._format_sealed_amount(snapshot.get("limit_amount"))
            result.append(
                {
                    "stock_code": code,
                    "stock_name": stock_name.strip() if isinstance(stock_name, str) and stock_name.strip() else None,
                    "latest_price": latest_price,
                    "change_pct": change_pct,
                    "current_board_count": board_count,
                    "recent_limit_count_n": recent_count,
                    "streak_label": self._to_streak_label(board_count),
                    "recent_limit_text": f"{recent_window_days}天{recent_count}板",
                    "first_limit_time": first_limit_time,
                    "open_times": open_times,
                    "sealed_amount_display_text": sealed_amount_display_text,
                }
            )
        return result

    @staticmethod
    def _leader_sort_key(item: dict[str, str | int | float | None]) -> tuple:
        board_count = int(item.get("current_board_count") or 0)
        recent_count = int(item.get("recent_limit_count_n") or 0)
        change_pct = item.get("change_pct")
        change_pct_value = float(change_pct) if isinstance(change_pct, (int, float)) else float("-inf")
        stock_code = str(item.get("stock_code") or "")
        return (-board_count, -recent_count, -change_pct_value, stock_code)

    @staticmethod
    def _to_streak_label(board_count: int) -> str:
        if board_count <= 1:
            return "首板"
        if board_count >= 5:
            return "5板+"
        return f"{board_count}连板"

    @staticmethod
    def _format_sealed_amount(value: str | int | float | Decimal | None) -> str:
        if value is None:
            return _UNKNOWN_TEXT
        amount = float(value)
        if amount >= 100000000:
            return f"{amount / 100000000:.1f}亿"
        if amount >= 10000:
            return f"{amount / 10000:.1f}万"
        return f"{amount:.0f}"
