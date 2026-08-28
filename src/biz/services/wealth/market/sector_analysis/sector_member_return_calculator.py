from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from src.biz.services.wealth.market.sector_analysis.sector_member_detail_contract import (
    DuplicateSectorMemberFactError,
    SectorMemberDailyFact,
    SectorMemberReturnFact,
    SectorMemberReturnMissingReason,
    SectorMemberSourceFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorMomentumDirection,
    SectorMomentumPeriod,
)


RETURN_QUANTUM = Decimal("0.0001")


class SectorMemberReturnCalculator:
    """Pure member return calculation over the frozen SSE trading-day window."""

    def calculate(
        self,
        *,
        members: Iterable[SectorMemberSourceFact],
        daily_facts: Iterable[SectorMemberDailyFact],
        open_dates: tuple[date, ...],
        target_date: date,
        period: SectorMomentumPeriod,
    ) -> tuple[SectorMemberReturnFact, ...]:
        source_rows = tuple(members)
        source_codes = [row.stock_code for row in source_rows]
        if len(source_codes) != len(set(source_codes)):
            raise DuplicateSectorMemberFactError("duplicate member source fact")
        if tuple(sorted(set(open_dates))) != open_dates:
            raise ValueError("open-date window must be unique and ascending")
        if open_dates and open_dates[-1] != target_date:
            raise ValueError("open-date window must end at target date")

        daily_index = self._index_daily_facts(daily_facts)
        if len(open_dates) < period:
            required_dates: tuple[date, ...] = ()
        else:
            required_dates = open_dates[-period:]

        return tuple(
            self._calculate_one(
                member=member,
                daily_index=daily_index,
                required_dates=required_dates,
                target_date=target_date,
                period=period,
            )
            for member in source_rows
        )

    @staticmethod
    def sort(
        rows: Iterable[SectorMemberReturnFact],
        *,
        direction: SectorMomentumDirection,
    ) -> tuple[SectorMemberReturnFact, ...]:
        def key(row: SectorMemberReturnFact):
            if row.return_pct is None:
                return (1, Decimal(0), row.stock_code)
            ordered = -row.return_pct if direction == "GAINERS" else row.return_pct
            return (0, ordered, row.stock_code)

        return tuple(sorted(rows, key=key))

    @staticmethod
    def _index_daily_facts(
        daily_facts: Iterable[SectorMemberDailyFact],
    ) -> dict[tuple[str, date], SectorMemberDailyFact]:
        result: dict[tuple[str, date], SectorMemberDailyFact] = {}
        for fact in daily_facts:
            key = (fact.stock_code, fact.trade_date)
            if key in result:
                raise DuplicateSectorMemberFactError(
                    f"duplicate member daily fact: {fact.stock_code}@{fact.trade_date.isoformat()}"
                )
            result[key] = fact
        return result

    @classmethod
    def _calculate_one(
        cls,
        *,
        member: SectorMemberSourceFact,
        daily_index: dict[tuple[str, date], SectorMemberDailyFact],
        required_dates: tuple[date, ...],
        target_date: date,
        period: SectorMomentumPeriod,
    ) -> SectorMemberReturnFact:
        target_fact = daily_index.get((member.stock_code, target_date))
        close = cls._valid_close(target_fact.close if target_fact is not None else None)
        if len(required_dates) < period:
            return cls._result(member, close, None, "HISTORY_INSUFFICIENT")

        required_facts: list[SectorMemberDailyFact] = []
        for required_date in required_dates:
            fact = daily_index.get((member.stock_code, required_date))
            if fact is None:
                return cls._result(member, close, None, "DATE_MISSING")
            required_facts.append(fact)
        pct_changes = [fact.pct_change for fact in required_facts]
        if any(value is None or not value.is_finite() for value in pct_changes):
            return cls._result(member, close, None, "PCT_CHANGE_MISSING")

        compounded = Decimal(1)
        for value in pct_changes:
            assert value is not None
            compounded *= Decimal(1) + value / Decimal(100)
        return_pct = ((compounded - Decimal(1)) * Decimal(100)).quantize(
            RETURN_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        return cls._result(member, close, return_pct, "NONE")

    @staticmethod
    def _valid_close(value: Decimal | None) -> Decimal | None:
        if value is None or not value.is_finite() or value <= 0:
            return None
        return value

    @staticmethod
    def _result(
        member: SectorMemberSourceFact,
        close: Decimal | None,
        return_pct: Decimal | None,
        reason: SectorMemberReturnMissingReason,
    ) -> SectorMemberReturnFact:
        return SectorMemberReturnFact(
            stock_code=member.stock_code,
            stock_name=member.stock_name,
            close=close,
            return_pct=return_pct,
            return_missing_reason=reason,
        )
