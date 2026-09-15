"""Completed rounds: closing-date selection with whole-round amounts."""
from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, or_, select, tuple_

from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.schemas.wealth.market.trading_assistant.common import StockRef
from src.biz.schemas.wealth.market.trading_assistant.records import CompletedRound, CompletedRoundsResponse
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.calculation.returns import profit_result
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from .closed_records import ClosedRecordsQuery
from .record_cursor import RecordCursor
from .record_scope import read_record_names
from .round_sources import published_rounds


def round_key(key):
    if not isinstance(key, list) or len(key) != 4 or not all(isinstance(value, str) for value in key):
        raise ValueError("Invalid completed-round key")
    day, account, stock, round_id = key
    parsed_day, parsed_account, parsed_round = date.fromisoformat(day), UUID(account), UUID(round_id)
    if (parsed_day.isoformat() != day or str(parsed_account) != account or str(parsed_round) != round_id
            or not stock or len(stock) > 32):
        raise ValueError("Noncanonical completed-round key")
    return parsed_day, parsed_account, stock, parsed_round


class CompletedRoundsQuery:
    def __init__(self, policy):
        self.policy = policy
        self.closed = ClosedRecordsQuery(policy)

    def read(self, session, *, owner_id, basis, query, deadline):
        # Every completed round must have a sale on its closing date. Reuse the
        # published-sale completeness check; no sale is a known zero, not a
        # valuation error. Do not infer closed rounds from today's holdings.
        evidence = self.closed.read(session, owner_id=owner_id, basis=basis,
            query=query.model_copy(update={"cursor":None, "limit":1}), deadline=deadline)
        cursor = RecordCursor(kind="COMPLETED_ROUNDS", filters=query.model_dump(
            exclude={"readContext", "cursor", "limit"}), context=basis.context)
        after = cursor.decode(query.cursor, validate_key=round_key)
        rounds = published_rounds(basis)
        selected = select(rounds).where(rounds.c.closed_on >= date.fromisoformat(query.requestedStartDate),
            rounds.c.closed_on <= date.fromisoformat(query.requestedEndDate))
        if query.tsCode is not None:
            selected = selected.where(rounds.c.ts_code == query.tsCode)
        source = selected.subquery("completed_rounds")
        apply_sql_budget(session, deadline, self.policy)
        total = session.scalar(select(func.count()).select_from(source))
        statement = select(source, InitialPosition.opened_on.label("initial_opened_on")).join(Account,
            and_(Account.account_id == source.c.account_id, Account.owner_id == owner_id)).outerjoin(InitialPosition,
            and_(InitialPosition.account_id == Account.account_id,
                InitialPosition.initialization_id == Account.current_initialization_id,
                InitialPosition.ts_code == source.c.ts_code, InitialPosition.opened_on == source.c.opened_on))
        stable = (source.c.account_id, source.c.ts_code, source.c.round_id)
        if after:
            statement = statement.where(or_(source.c.closed_on < after[0],
                and_(source.c.closed_on == after[0], tuple_(*stable) > tuple_(*after[1:]))))
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(statement.order_by(source.c.closed_on.desc(), *stable).limit(query.limit + 1)).all()
        next_cursor = None
        if len(rows) > query.limit:
            last = rows[query.limit - 1]
            next_cursor = cursor.encode([last.closed_on.isoformat(), str(last.account_id), last.ts_code, str(last.round_id)])
        rows = rows[:query.limit]
        names = read_record_names(session, [row.ts_code for row in rows], deadline=deadline, policy=self.policy)
        accounts = {account.accountId:account for account in evidence.scope.accounts}
        items = []
        for row in rows:
            investment, net = numeric_cents(row.cumulative_buy_input), numeric_cents(row.cumulative_sell_net)
            if int(row.quantity) != 0:
                raise ValueError("Completed round retains a position")
            result = profit_result(net - investment, investment, participates=True)
            items.append(CompletedRound(accountId=str(row.account_id), accountName=accounts[str(row.account_id)].name,
                stockRef=StockRef(tsCode=row.ts_code, name=names[row.ts_code]), roundId=str(row.round_id),
                roundNumber=row.round_number, openedOn=row.opened_on.isoformat(), closedOn=row.closed_on.isoformat(),
                openingSource="INITIALIZATION" if row.initial_opened_on else "TRADE",
                roundProfitAmount=format_cents(result.profit_cents), roundReturnPct=result.return_pct))
        complete = evidence.summary.closedTradeCount is not None
        state = ("Ready" if total else "Empty") if complete else ("Partial" if total else evidence.coverage.dataStatus)
        coverage = evidence.coverage.model_copy(update={"dataStatus":state})
        deadline.remaining_ms()
        return CompletedRoundsResponse(scope=evidence.scope, closedStartDate=query.requestedStartDate,
            closedEndDate=query.requestedEndDate, coverage=coverage, completedRoundCount=total if complete else None,
            items=items, nextCursor=next_cursor)
