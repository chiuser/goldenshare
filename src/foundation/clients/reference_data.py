"""Contracts for the two reference datasets read by the Web backend."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class TradeCalendarRow:
    exchange: str
    trade_date: date
    is_open: bool
    pretrade_date: date | None


@dataclass(frozen=True, slots=True)
class SecurityReferenceRow:
    ts_code: str
    name: str
    symbol: str | None
    area: str | None
    industry: str | None
    fullname: str | None
    enname: str | None
    cnspell: str | None
    market: str | None
    exchange: str | None
    curr_type: str | None
    list_status: str | None
    list_date: date | None
    delist_date: date | None
    is_hs: str | None
    act_name: str | None
    act_ent_type: str | None
    security_type: str
    source: str


@dataclass(frozen=True, slots=True)
class SecurityPlanningRow:
    ts_code: str
    name: str
    list_status: str
    source: str


class TradeCalendarReader(Protocol):
    def get(self, *, exchange: str, day: date) -> TradeCalendarRow | None: ...

    def range_rows(
        self,
        *,
        exchange: str,
        start: date,
        end: date,
        open_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[TradeCalendarRow, ...]: ...

    def recent_open_rows(
        self,
        *,
        exchange: str,
        bound: date,
        limit: int,
        include_bound: bool = True,
        start: date | None = None,
    ) -> tuple[TradeCalendarRow, ...]: ...

    def context_rows(
        self,
        *,
        exchange: str,
        end: date,
        recent_open_days: int,
        start: date | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[TradeCalendarRow, ...]: ...


class SecurityReferenceReader(Protocol):
    def get(
        self, *, ts_code: str, timeout_seconds: float | None = None
    ) -> SecurityReferenceRow | None: ...

    def read_by_codes(
        self, *, ts_codes: Sequence[str], timeout_seconds: float | None = None
    ) -> Mapping[str, SecurityReferenceRow]: ...

    def project_by_codes(
        self, *, ts_codes: Sequence[str], columns: Sequence[str]
    ) -> tuple[tuple, ...]: ...

    def search_a_shares(
        self, *, keyword: str, escaped_prefix: str, limit: int, exchanges: Sequence[str]
    ) -> tuple[tuple[str, str], ...]: ...

    def leaderboard_codes(self, *, trade_date: date) -> tuple[str, ...]: ...

    def suggest_equities(
        self, *, keyword: str, limit: int
    ) -> tuple[tuple[str, str], ...]: ...

    def planning_equities(self) -> tuple[SecurityPlanningRow, ...]: ...


@dataclass(frozen=True, slots=True)
class ReferenceData:
    calendar: TradeCalendarReader
    security: SecurityReferenceReader


class ReferenceDataReadError(RuntimeError):
    """The configured data source could not supply valid reference rows."""


def bind_reference_data(session: Session, reference_data: ReferenceData | None) -> None:
    if reference_data is not None:
        session.info[ReferenceData.__name__] = reference_data


def local_reference_data(session: Session) -> ReferenceData | None:
    info = getattr(session, "info", None)
    return info.get(ReferenceData.__name__) if isinstance(info, dict) else None
