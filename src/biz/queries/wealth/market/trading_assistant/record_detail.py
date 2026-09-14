"""Owned revisions and exact published closed results in one read snapshot."""
from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.schemas.wealth.market.trading_assistant.common import AccountRef, Page, StockRef
from src.biz.schemas.wealth.market.trading_assistant.records import TradeRecord, CashFlowRecord, TradeDetail, CashFlowDetail
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .calculation_status import CalculationStatusQuery
from .record_cursor import RecordCursor
from .record_projection import project_record
from .record_scope import read_record_names
from .record_sources import record_facts, with_published_closed
from .record_closed_projection import closed_metadata, project_closed


def _revision_key(key):
    if not isinstance(key, dict) or set(key) != {"revision"}:
        raise ValueError("Invalid revision key")
    value = key["revision"]
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or value.startswith("0") or len(value) > 19 or int(value) > 9223372036854775807):
        raise ValueError("Invalid revision")
    return int(value)


class RecordDetailQuery:
    def __init__(self, policy):
        self.policy = policy
        self.status = CalculationStatusQuery(policy)

    def owned_account(self, session, *, owner_id, record_id, kind, deadline):
        apply_sql_budget(session, deadline, self.policy)
        account = session.scalar(select(Account).join(Ledger, Ledger.account_id == Account.account_id)
            .where(Account.owner_id == owner_id, Ledger.ledger_id == record_id, Ledger.kind == kind))
        if account is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        return account

    def read(self, session, *, owner_id, account, basis, record_id, kind, deadline, cursor=None, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100 or kind not in ("TRADE", "CASH_FLOW"):
            raise WriteProtocolConflict("TA_REQUEST_INVALID")
        ref = next(r for r in basis.context.accounts if r.accountId == str(account.account_id))
        pager = RecordCursor(kind=kind + "_REVISIONS", filters=dict(accountId=ref.accountId,
            recordId=str(record_id), kind=kind), context=basis.context)
        after = pager.decode(cursor, validate_key=_revision_key)
        statement = select(*LedgerRevision.__table__.columns, Ledger.created_at.label("recorded_at"))\
            .join(Ledger, Ledger.ledger_id == LedgerRevision.ledger_id).where(
                LedgerRevision.account_id == account.account_id, LedgerRevision.ledger_id == record_id,
                LedgerRevision.accepted_fact_version <= int(ref.factVersion)).order_by(LedgerRevision.revision.desc())
        apply_sql_budget(session, deadline, self.policy)
        current = session.execute(statement.limit(1)).one_or_none()
        if current is None:
            raise ValueError("Persisted ledger has no revision")
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute((statement.where(LedgerRevision.revision < after) if after else statement).limit(limit + 1)).all()
        next_cursor = pager.encode(dict(revision=str(rows[limit - 1].revision))) if len(rows) > limit else None
        rows = rows[:limit]
        account_ref = AccountRef(accountId=ref.accountId, name=account.name, brokerName=account.broker_name)
        names = read_record_names(session, [r.ts_code for r in [current, *rows]] if kind == "TRADE" else [],
                                  deadline=deadline, policy=self.policy)
        closed, state, reason = None, "Empty", "该记录无有效卖出闭环"
        if kind == "TRADE" and current.direction == "SELL" and current.status == "ACTIVE":
            source = with_published_closed(record_facts(owner_id=owner_id, basis=basis))
            apply_sql_budget(session, deadline, self.policy)
            sale = session.execute(select(source).where(source.c.ledger_id == record_id,
                source.c.revision == current.revision, source.c.closed_source_id.is_not(None))).one_or_none()
            if sale is not None:
                metadata, rounds = closed_metadata(session, [sale], deadline=deadline, policy=self.policy)
                closed = project_closed(sale, account_ref=account_ref,
                    stock_ref=StockRef(tsCode=current.ts_code, name=names[current.ts_code]), metadata=metadata, rounds=rounds)
                state, reason = "Ready", None
            else:
                progress = self.status.read(session, owner_id=owner_id, account_id=account.account_id, deadline=deadline)
                state = "Error" if progress.stage == "FAILED" else "Delayed" if progress.stage in ("WAITING_DATA", "PUBLISHED") else "Recalculating"
                reason = progress.reason or "闭环结果尚未完整发布"

        def project(row):
            historical = row.revision != current.revision
            return project_record(row, account_ref=account_ref,
                stock_ref=StockRef(tsCode=row.ts_code, name=names[row.ts_code]) if kind == "TRADE" else None,
                closed_state="Empty" if historical else state,
                closed_reason="历史修订不关联当前闭环" if historical else reason)

        record = project(current)
        items = [project(row) for row in rows]
        deadline.remaining_ms()
        if kind == "CASH_FLOW":
            return CashFlowDetail(record=record, revisions=Page[CashFlowRecord](items=items, nextCursor=next_cursor), readContext=basis.context)
        return TradeDetail(record=record, revisions=Page[TradeRecord](items=items, nextCursor=next_cursor), readContext=basis.context,
            closedTrade=closed, closedDataStatus=state, reason=reason)
