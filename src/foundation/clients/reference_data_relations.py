"""Bind selected DG records to a PostgreSQL statement that also reads PG facts."""

from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import Boolean, Date, bindparam, column, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import TextClause

from src.foundation.clients.reference_data import local_reference_data
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.security_serving import Security


def _relation(name, columns, rows):
    records = [
        {
            field.name: value.isoformat() if isinstance(value, date) else value
            for field, value in zip(columns, values, strict=True)
        }
        for values in rows
    ]
    return (
        func.jsonb_to_recordset(bindparam(None, records, type_=JSONB))
        .table_valued(*columns)
        .render_derived(name=name, with_types=True)
    )


def calendar_relation(
    session: Session,
    *,
    start: date | None = None,
    end: date,
    open_only: bool = False,
    limit: int | None = None,
    exchange: str = "SSE",
):
    reference = local_reference_data(session)
    if reference is None:
        return TradeCalendar.__table__
    if limit is not None:
        rows = reference.calendar.recent_open_rows(
            exchange=exchange,
            bound=end,
            start=start,
            limit=limit,
        )
    else:
        rows = reference.calendar.range_rows(
            exchange=exchange,
            start=start or date.min,
            end=end,
            open_only=open_only,
        )
    fields = (
        column("exchange", TradeCalendar.__table__.c.exchange.type),
        column("trade_date", Date()),
        column("is_open", Boolean()),
        column("pretrade_date", Date()),
    )
    return _relation(
        "dg_trade_calendar",
        fields,
        (
            (row.exchange, row.trade_date, row.is_open, row.pretrade_date)
            for row in rows
        ),
    )


def security_relation(
    session: Session,
    *,
    columns: Sequence[str],
    codes: Iterable[str] | Select,
):
    table = Security.__table__
    reference = local_reference_data(session)
    if reference is None:
        return table
    keys = tuple(session.scalars(codes).all() if isinstance(codes, Select) else codes)
    rows = reference.security.project_by_codes(ts_codes=keys, columns=columns)
    return _relation(
        "dg_security", tuple(column(name, table.c[name].type) for name in columns), rows
    )


def bind_calendar_records(statement: TextClause, rows) -> TextClause:
    records = [
        {
            "exchange": row.exchange,
            "trade_date": row.trade_date.isoformat(),
            "is_open": row.is_open,
            "pretrade_date": row.pretrade_date.isoformat()
            if row.pretrade_date
            else None,
        }
        for row in rows
    ]
    return statement.bindparams(bindparam("dg_calendar_rows", records, type_=JSONB))
