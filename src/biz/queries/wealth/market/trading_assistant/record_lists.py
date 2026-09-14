"""Bounded raw/day-group pages over complete, version-fixed source facts."""
from datetime import date, datetime
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import and_, or_, select, tuple_

from src.biz.schemas.wealth.market.trading_assistant.records import TradeRecord, CashFlowRecord, TradeDayGroup, RecordsResponse
from src.biz.schemas.wealth.market.trading_assistant.common import StockRef
from src.biz.schemas.wealth.market.trading_assistant.value_types import BusinessDate, EntityId, Instant
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from .calculation_status import CalculationStatusQuery
from .record_cursor import RecordCursor
from .record_sources import record_facts, filtered_records, with_published_closed, trade_day_groups
from .record_scope import read_record_scope, read_record_names
from .record_projection import project_record
from .record_group_projection import project_trade_day_group


def _key(row, grouped):
    if grouped:
        return dict(date=row.occurred_on.isoformat(), accountId=str(row.account_id), tsCode=row.ts_code, direction=row.direction)
    return dict(date=row.occurred_on.isoformat(), recordedAt=row.recorded_at.isoformat(), recordId=str(row.ledger_id))


def _parse_key(key, grouped):
    expected = {"date", "accountId", "tsCode", "direction"} if grouped else {"date", "recordedAt", "recordId"}
    if not isinstance(key, dict) or set(key) != expected:
        raise ValueError("Invalid record keyset")
    day = date.fromisoformat(TypeAdapter(BusinessDate).validate_python(key["date"]))
    if grouped:
        account = UUID(TypeAdapter(EntityId).validate_python(key["accountId"]))
        if str(account) != key["accountId"] or not isinstance(key["tsCode"], str) or not key["tsCode"] or key["direction"] not in ("BUY", "SELL"):
            raise ValueError("Invalid day group keyset")
        return day, account, key["tsCode"], key["direction"]
    instant = TypeAdapter(Instant).validate_python(key["recordedAt"])
    record = UUID(TypeAdapter(EntityId).validate_python(key["recordId"]))
    if str(record) != key["recordId"]:
        raise ValueError("Noncanonical record key")
    return day, datetime.fromisoformat(instant.replace("Z", "+00:00")), record


class RecordListsQuery:
    def __init__(self, policy):
        self.policy = policy
        self.status = CalculationStatusQuery(policy)

    def read(self, session, *, owner_id, basis, query, kind, deadline, grouped=False):
        scope, coverage = read_record_scope(session, owner_id=owner_id, basis=basis, query=query, deadline=deadline, policy=self.policy)
        filters = query.model_dump(exclude={"readContext", "cursor", "limit"})
        cursor = RecordCursor(kind="TRADE_DAY_GROUPS" if grouped else kind, filters=filters, context=basis.context)
        after = cursor.decode(query.cursor, validate_key=lambda key: _parse_key(key, grouped))
        source = record_facts(owner_id=owner_id, basis=basis)
        if kind == "TRADE":
            source = with_published_closed(source)
        source = filtered_records(source, kind=kind, start=date.fromisoformat(query.requestedStartDate),
            end=date.fromisoformat(query.requestedEndDate), stock=getattr(query, "tsCode", None), direction=query.direction)
        if grouped:
            source = trade_day_groups(source)
        statement = select(source)
        if grouped:
            tail = (source.c.account_id, source.c.ts_code, source.c.direction)
            if after:
                statement = statement.where(or_(source.c.occurred_on < after[0],
                    and_(source.c.occurred_on == after[0], tuple_(*tail) > tuple_(*after[1:]))))
            statement = statement.order_by(source.c.occurred_on.desc(), *tail)
        else:
            keys = (source.c.occurred_on, source.c.recorded_at, source.c.ledger_id)
            if after:
                statement = statement.where(tuple_(*keys) < tuple_(*after))
            statement = statement.order_by(*(key.desc() for key in keys))
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(statement.limit(query.limit + 1)).all()
        next_cursor = cursor.encode(_key(rows[query.limit - 1], grouped)) if len(rows) > query.limit else None
        rows = rows[:query.limit]
        names = read_record_names(session, [row.ts_code for row in rows] if kind == "TRADE" else [],
                                  deadline=deadline, policy=self.policy)
        accounts = {ref.accountId: ref for ref in scope.accounts}
        items, unavailable = [], {}
        for row in rows:
            account = accounts[str(row.account_id)]
            stock = StockRef(tsCode=row.ts_code, name=names[row.ts_code]) if kind == "TRADE" else None
            if kind == "CASH_FLOW":
                items.append(project_record(row, account_ref=account, stock_ref=stock))
                continue
            state, reason = "Ready", None
            if row.direction == "BUY":
                state, reason = "Empty", "买入记录不产生闭环"
            elif (row.closed_count != row.trade_count if grouped else row.closed_source_id is None):
                if row.account_id not in unavailable:
                    progress = self.status.read(session, owner_id=owner_id, account_id=row.account_id, deadline=deadline)
                    unavailable[row.account_id] = ("Error" if progress.stage == "FAILED" else "Delayed"
                        if progress.stage in ("WAITING_DATA", "PUBLISHED") else "Recalculating",
                        progress.reason or "闭环结果尚未完整发布")
                state, reason = unavailable[row.account_id]
            if grouped:
                items.append(project_trade_day_group(row, account_ref=account, stock_ref=stock, closed_state=state, reason=reason))
            else:
                items.append(project_record(row, account_ref=account, stock_ref=stock,
                    closed_state=state, closed_reason=reason))
        deadline.remaining_ms()
        if not items:
            coverage = coverage.model_copy(update={"dataStatus": "Empty"})
        model = TradeDayGroup if grouped else TradeRecord if kind == "TRADE" else CashFlowRecord
        return RecordsResponse[model](scope=scope, requestedStartDate=query.requestedStartDate,
            requestedEndDate=query.requestedEndDate, readContext=basis.context, coverage=coverage, items=items, nextCursor=next_cursor)
