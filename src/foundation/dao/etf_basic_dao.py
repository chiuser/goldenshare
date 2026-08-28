from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core.etf_basic import EtfBasic


EtfExchange: TypeAlias = Literal["SH", "SZ"]

_NON_EXCHANGE_SUFFIX = "NON_EXCHANGE_SUFFIX"
_EXCHANGE_MISMATCH = "EXCHANGE_MISMATCH"
_STATUS_NOT_LISTED = "STATUS_NOT_LISTED"
_LIST_DATE_NULL = "LIST_DATE_NULL"
_LIST_DATE_AFTER_AS_OF = "LIST_DATE_AFTER_AS_OF"


@dataclass(frozen=True, slots=True)
class EtfRequestTarget:
    ts_code: str
    list_date: date
    exchange: EtfExchange


@dataclass(frozen=True, slots=True)
class EtfRequestabilitySnapshot:
    as_of_date: date
    exchange: EtfExchange | None
    targets: tuple[EtfRequestTarget, ...]
    serving_row_count: int
    requestable_count: int
    excluded_reason_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(
            self,
            "excluded_reason_counts",
            MappingProxyType(dict(self.excluded_reason_counts)),
        )


class EtfBasicDAO(BaseDAO[EtfBasic]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EtfBasic)

    def upsert_many(self, rows: list[dict]) -> int:
        return self.bulk_upsert(rows)

    def get_by_ts_code(self, ts_code: str) -> EtfBasic | None:
        return self.fetch_by_pk(ts_code)

    def load_requestability_snapshot(
        self,
        *,
        as_of_date: date,
        exchange: EtfExchange | None = None,
    ) -> EtfRequestabilitySnapshot:
        normalized_exchange = self._normalize_exchange(exchange)
        statement = select(EtfBasic)
        if normalized_exchange is not None:
            statement = statement.where(EtfBasic.ts_code.like(f"%.{normalized_exchange}"))
        rows = self.session.scalars(statement.order_by(EtfBasic.ts_code)).all()

        targets: list[EtfRequestTarget] = []
        excluded_reason_counts: dict[str, int] = {}
        for row in rows:
            exclusion_reason = self._classify_master_row(row, as_of_date=as_of_date)
            if exclusion_reason is None:
                targets.append(
                    EtfRequestTarget(
                        ts_code=row.ts_code,
                        list_date=cast(date, row.list_date),
                        exchange=cast(EtfExchange, row.exchange),
                    )
                )
                continue
            excluded_reason_counts[exclusion_reason] = (
                excluded_reason_counts.get(exclusion_reason, 0) + 1
            )

        return EtfRequestabilitySnapshot(
            as_of_date=as_of_date,
            exchange=normalized_exchange,
            targets=tuple(targets),
            serving_row_count=len(rows),
            requestable_count=len(targets),
            excluded_reason_counts=excluded_reason_counts,
        )

    def get_requestable_target(
        self,
        *,
        ts_code: str,
        as_of_date: date,
        exchange: EtfExchange | None = None,
    ) -> EtfRequestTarget | None:
        normalized_exchange = self._normalize_exchange(exchange)
        normalized_ts_code = self._normalize_ts_code(ts_code)
        if normalized_ts_code is None:
            return None
        if normalized_exchange is not None and not normalized_ts_code.endswith(f".{normalized_exchange}"):
            return None

        row = self.session.scalar(
            select(EtfBasic)
            .where(
                EtfBasic.ts_code == normalized_ts_code,
                *self._requestable_predicates(
                    as_of_date=as_of_date,
                    exchange=normalized_exchange,
                ),
            )
            .limit(1)
        )
        if row is None:
            return None
        return EtfRequestTarget(
            ts_code=row.ts_code,
            list_date=cast(date, row.list_date),
            exchange=cast(EtfExchange, row.exchange),
        )

    def requestable_targets_subquery(
        self,
        *,
        as_of_date: date,
        exchange: EtfExchange | None = None,
    ) -> Subquery:
        normalized_exchange = self._normalize_exchange(exchange)
        return (
            select(
                EtfBasic.ts_code.label("ts_code"),
                EtfBasic.list_date.label("list_date"),
                EtfBasic.exchange.label("exchange"),
                EtfBasic.csname.label("csname"),
                EtfBasic.extname.label("extname"),
                EtfBasic.cname.label("cname"),
                EtfBasic.etf_type.label("etf_type"),
                EtfBasic.list_status.label("list_status"),
            )
            .where(
                *self._requestable_predicates(
                    as_of_date=as_of_date,
                    exchange=normalized_exchange,
                )
            )
            .subquery("requestable_etf_targets")
        )

    @staticmethod
    def _normalize_exchange(exchange: str | None) -> EtfExchange | None:
        if exchange is None:
            return None
        normalized = exchange.strip().upper()
        if normalized not in {"SH", "SZ"}:
            raise ValueError("exchange 只支持 SH 或 SZ")
        return cast(EtfExchange, normalized)

    @staticmethod
    def _normalize_ts_code(ts_code: str) -> str | None:
        normalized = str(ts_code or "").strip().upper()
        if not normalized.endswith((".SH", ".SZ")):
            return None
        return normalized

    @staticmethod
    def _requestable_predicates(
        *,
        as_of_date: date,
        exchange: EtfExchange | None,
    ) -> tuple[ColumnElement[bool], ...]:
        if exchange == "SH":
            exchange_predicate = and_(
                EtfBasic.ts_code.like("%.SH"),
                EtfBasic.exchange == "SH",
            )
        elif exchange == "SZ":
            exchange_predicate = and_(
                EtfBasic.ts_code.like("%.SZ"),
                EtfBasic.exchange == "SZ",
            )
        else:
            exchange_predicate = or_(
                and_(EtfBasic.ts_code.like("%.SH"), EtfBasic.exchange == "SH"),
                and_(EtfBasic.ts_code.like("%.SZ"), EtfBasic.exchange == "SZ"),
            )
        return (
            EtfBasic.list_status == "L",
            EtfBasic.list_date.is_not(None),
            EtfBasic.list_date <= as_of_date,
            exchange_predicate,
        )

    @staticmethod
    def _classify_master_row(row: EtfBasic, *, as_of_date: date) -> str | None:
        if row.ts_code.endswith(".SH"):
            expected_exchange = "SH"
        elif row.ts_code.endswith(".SZ"):
            expected_exchange = "SZ"
        else:
            return _NON_EXCHANGE_SUFFIX
        if row.exchange != expected_exchange:
            return _EXCHANGE_MISMATCH
        if row.list_status != "L":
            return _STATUS_NOT_LISTED
        if row.list_date is None:
            return _LIST_DATE_NULL
        if row.list_date > as_of_date:
            return _LIST_DATE_AFTER_AS_OF
        return None
