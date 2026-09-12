"""Owned raw revisions stay readable before derived results are published."""
import base64
import json
from uuid import UUID

from sqlalchemy import select, func

from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.schemas.wealth.market.trading_assistant.common import ReadContext, ReadContextAccount, Page
from src.biz.schemas.wealth.market.trading_assistant.records import TradeRecord, CashFlowRecord, TradeDetail, CashFlowDetail
from src.biz.services.wealth.market.trading_assistant.account_acceptance import accepted_time
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import scaled_integer
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget, facts_digest
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")


def decode(value):
    try:
        if not value or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
            raise ValueError()
        document = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if encode(document) != value:
            raise ValueError()
        return document
    except (ValueError, TypeError, UnicodeDecodeError) as error:
        raise WriteProtocolConflict("TA_REQUEST_INVALID") from error


class RecordDetailQuery:
    def __init__(self, policy, market):
        self.policy, self.market = policy, market

    def read(self, session, *, owner_id, record_id, kind, deadline, cursor=None, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100 or kind not in ("TRADE", "CASH_FLOW"):
            raise WriteProtocolConflict("TA_REQUEST_INVALID")
        apply_sql_budget(session, deadline, self.policy)
        pair = session.execute(select(Account, Ledger).join(Ledger, Ledger.account_id == Account.account_id)
            .where(Account.owner_id == owner_id, Ledger.ledger_id == record_id, Ledger.kind == kind)).one_or_none()
        if pair is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        account, ledger = pair
        initial = session.get(Initialization, account.current_initialization_id)
        accepted = session.scalar(select(func.max(LedgerRevision.accepted_at)).where(
            LedgerRevision.account_id == account.account_id, LedgerRevision.accepted_fact_version <= account.fact_version))
        # The raw-fact cutoff is persisted acceptance time, never response-generation time.
        through = accepted_time(max(initial.created_at, accepted or initial.created_at))
        context_account = ReadContextAccount(accountId=str(account.account_id), factVersion=str(account.fact_version),
            calculationTargetVersion=str(account.calculation_target_version),
            publishedGenerationId=str(account.published_generation_id) if account.published_generation_id else None)
        digest = facts_digest(dict(accounts=[context_account.model_dump()], targetThrough=through))
        context = ReadContext(accounts=[context_account], targetThrough=through, contextToken=encode(dict(
            v=1, accountMode="SINGLE", accountId=str(account.account_id), targetThrough=through, basisDigest=digest)))
        query_kind = kind + "_REVISIONS"
        filter_digest = facts_digest(dict(accountId=str(account.account_id), recordId=str(record_id), kind=kind))
        last_revision = None
        if cursor is not None:
            data = decode(cursor)
            if (not isinstance(data, dict) or set(data) != {"v", "queryKind", "filterDigest", "contextDigest", "lastKey"}
                    or type(data["v"]) is not int or data["v"] != 1 or data["queryKind"] != query_kind
                    or data["filterDigest"] != filter_digest or not isinstance(data["lastKey"], dict)
                    or set(data["lastKey"]) != {"revision"}):
                raise WriteProtocolConflict("TA_REQUEST_INVALID")
            value = data["lastKey"]["revision"]
            if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or value.startswith("0") or len(value) > 19:
                raise WriteProtocolConflict("TA_REQUEST_INVALID")
            if data["contextDigest"] != digest:
                raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
            last_revision = int(value)
            if last_revision > 9223372036854775807:
                raise WriteProtocolConflict("TA_REQUEST_INVALID")
        statement = select(LedgerRevision).where(LedgerRevision.ledger_id == record_id,
            LedgerRevision.accepted_fact_version <= account.fact_version).order_by(LedgerRevision.revision.desc())
        current = session.scalar(statement.limit(1))
        if current is None:
            raise ValueError("Persisted ledger has no revision")
        page_statement = statement.where(LedgerRevision.revision < last_revision) if last_revision else statement
        rows = session.scalars(page_statement.limit(limit + 1)).all()
        def project(row):
            common = dict(accountRef=dict(accountId=str(account.account_id), name=account.name, brokerName=account.broker_name),
                revision=str(row.revision), recordedAt=accepted_time(ledger.created_at), acceptedAt=accepted_time(row.accepted_at),
                direction=row.direction, note=row.note, status=row.status, netCashChange=format_cents(numeric_cents(row.net_cash_change)))
            if kind == "CASH_FLOW":
                return CashFlowRecord(**common, cashFlowId=str(record_id), occurredOn=row.occurred_on.isoformat(),
                    amount=format_cents(numeric_cents(row.cash_amount)))
            security = self.market.resolve_security(session, row.ts_code, deadline)
            return TradeRecord(**common, tradeId=str(record_id), tradeDate=row.occurred_on.isoformat(),
                stockRef=dict(tsCode=row.ts_code, name=security.name), quantity=row.quantity, price=format_cents(numeric_cents(row.price)),
                grossAmount=format_cents(numeric_cents(row.gross_amount)), feeVersionId=str(row.fee_version_id),
                commissionAmount=format_cents(numeric_cents(row.commission_amount)), stampTaxAmount=format_cents(numeric_cents(row.stamp_tax_amount)),
                commissionRateWan=format_cents(scaled_integer(row.commission_rate, 6)), minimumCommission=format_cents(numeric_cents(row.minimum_commission)),
                stampTaxRatePct=format_cents(scaled_integer(row.stamp_tax_rate, 4)))
        next_cursor = encode(dict(v=1, queryKind=query_kind, filterDigest=filter_digest, contextDigest=digest,
            lastKey=dict(revision=str(rows[limit-1].revision)))) if len(rows) > limit else None
        record = project(current)
        items = [project(row) for row in rows[:limit]]
        deadline.remaining_ms()
        if kind == "CASH_FLOW":
            return CashFlowDetail(record=record, revisions=Page[CashFlowRecord](items=items, nextCursor=next_cursor), readContext=context)
        applicable = current.direction == "SELL" and current.status == "ACTIVE"
        return TradeDetail(record=record, revisions=Page[TradeRecord](items=items, nextCursor=next_cursor), readContext=context,
            closedTrade=None, closedDataStatus="Recalculating" if applicable else "Empty",
            reason="闭环结果尚未发布" if applicable else "该记录无有效卖出闭环")
