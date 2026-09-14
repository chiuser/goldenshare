"""One published closed-sale reader for range and complete-round navigation."""
from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, select, tuple_

from src.biz.models.wealth.trading_assistant.calculation import PositionState
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.schemas.wealth.market.trading_assistant.common import StockRef
from src.biz.schemas.wealth.market.trading_assistant.records import ClosedRecordsResponse, ClosedRecordsSummary
from src.biz.schemas.wealth.market.trading_assistant.scopes import RangeRecordsQuery, RangeRecordsScope, RoundRecordsQuery, RoundRecordsScope
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .calculation_status import CalculationStatusQuery
from .record_closed_projection import closed_metadata, project_closed
from .record_cursor import RecordCursor
from .record_lists import _key, _parse_key
from .record_scope import read_record_names, read_record_scope
from .record_sources import record_facts, with_published_closed, filtered_records


class ClosedRecordsQuery:
    def __init__(self, policy):
        self.policy = policy
        self.status = CalculationStatusQuery(policy)

    def round_range(self, session, *, query, basis, deadline):
        ref = next(r for r in basis.context.accounts if r.accountId == query.accountId)
        if ref.publishedGenerationId is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        pub, position = PublicationDay, PositionState
        apply_sql_budget(session, deadline, self.policy)
        row = session.execute(select(position.ts_code, func.min(position.opened_on).label("opened_on"),
            func.max(position.closed_on).label("closed_on"), func.max(pub.trade_date).label("through")
        ).join(pub, and_(pub.account_id == position.account_id, pub.day_result_id == position.day_result_id))
            .where(pub.account_id == UUID(query.accountId), pub.generation_id == UUID(ref.publishedGenerationId),
                position.round_id == UUID(query.roundId)).group_by(position.ts_code)).one_or_none()
        if row is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        return RangeRecordsQuery(accountMode="SINGLE", accountId=query.accountId, stockMode="SINGLE", tsCode=row.ts_code,
            requestedStartDate=row.opened_on.isoformat(), requestedEndDate=(row.closed_on or row.through).isoformat(),
            cursor=query.cursor, limit=query.limit, readContext=query.readContext)

    def read(self, session, *, owner_id, basis, query, deadline):
        is_round = isinstance(query, RoundRecordsQuery)
        ranged = self.round_range(session, query=query, basis=basis, deadline=deadline) if is_round else query
        scope, coverage = read_record_scope(session, owner_id=owner_id, basis=basis, query=ranged, deadline=deadline, policy=self.policy)
        cursor = RecordCursor(kind="CLOSED_ROUND" if is_round else "CLOSED_RANGE",
            filters=query.model_dump(exclude={"readContext", "cursor", "limit"}), context=basis.context)
        after = cursor.decode(query.cursor, validate_key=lambda key: _parse_key(key, False))
        source = filtered_records(with_published_closed(record_facts(owner_id=owner_id, basis=basis)),
            kind="TRADE", start=date.fromisoformat(ranged.requestedStartDate), end=date.fromisoformat(ranged.requestedEndDate),
            stock=ranged.tsCode, direction="SELL")
        published = select(source).where(source.c.closed_source_id.is_not(None))
        if is_round:
            published = published.where(source.c.round_id == UUID(query.roundId))
        published = published.subquery("closed_page_source")
        apply_sql_budget(session, deadline, self.policy)
        totals = session.execute(select(func.count().label("count"), func.sum(published.c.closed_profit_amount).label("profit"))).one()
        apply_sql_budget(session, deadline, self.policy)
        missing = session.scalars(select(source.c.account_id).where(source.c.closed_source_id.is_(None)).distinct()).all()
        unavailable = {}
        if is_round and UUID(query.accountId) not in missing:
            progress = self.status.read(session, owner_id=owner_id, account_id=UUID(query.accountId), deadline=deadline)
            if progress.stage != "PUBLISHED":
                missing.append(UUID(query.accountId))
        for account in missing:
            progress = self.status.read(session, owner_id=owner_id, account_id=account, deadline=deadline)
            unavailable[str(account)] = ("Error" if progress.stage == "FAILED" else "Delayed"
                if progress.stage in ("WAITING_DATA", "PUBLISHED") else "Recalculating", progress.reason or "闭环结果尚未完整发布")
        keys = (published.c.occurred_on, published.c.recorded_at, published.c.ledger_id)
        statement = select(published)
        if after:
            statement = statement.where(tuple_(*keys) > tuple_(*after) if is_round else tuple_(*keys) < tuple_(*after))
        statement = statement.order_by(*(key.asc() if is_round else key.desc() for key in keys))
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(statement.limit(query.limit + 1)).all()
        next_cursor = cursor.encode(_key(rows[query.limit - 1], False)) if len(rows) > query.limit else None
        rows = rows[:query.limit]
        metadata, rounds = closed_metadata(session, rows, deadline=deadline, policy=self.policy)
        names = read_record_names(session, [r.ts_code for r in rows], deadline=deadline, policy=self.policy)
        accounts = {a.accountId:a for a in scope.accounts}
        items = [project_closed(row, account_ref=accounts[str(row.account_id)],
            stock_ref=StockRef(tsCode=row.ts_code, name=names[row.ts_code]), metadata=metadata, rounds=rounds) for row in rows]
        state, reason = ("Ready", None) if totals.count else ("Empty", None)
        if unavailable:
            state = "Partial" if totals.count else next((s for s in ("Error", "Recalculating", "Delayed") if any(v[0] == s for v in unavailable.values())))
            reason = next(iter(unavailable.values()))[1]
        covers = [entry.model_copy(update={"dataStatus": unavailable[entry.accountId][0], "reason": unavailable[entry.accountId][1]})
            if entry.accountId in unavailable else entry for entry in coverage.accounts]
        coverage = coverage.model_copy(update={"dataStatus":state, "reason":reason, "isFinal":not unavailable, "accounts":covers})
        deadline.remaining_ms()
        return ClosedRecordsResponse(scope=scope, requestedStartDate=ranged.requestedStartDate,
            requestedEndDate=ranged.requestedEndDate, readContext=basis.context, coverage=coverage,
            items=items, nextCursor=next_cursor,
            recordsScope=RoundRecordsScope(accountId=query.accountId, roundId=query.roundId) if is_round else
                RangeRecordsScope(scope=scope, requestedStartDate=ranged.requestedStartDate, requestedEndDate=ranged.requestedEndDate),
            summary=ClosedRecordsSummary(closedTradeCount=None if unavailable else totals.count,
                closedProfitAmount=None if unavailable else format_cents(numeric_cents(totals.profit)) if totals.profit is not None else "0.00",
                dataStatus=state, reason=reason))
