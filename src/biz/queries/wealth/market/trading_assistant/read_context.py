"""Owned current-estimate read bases; design §4.31, no stored read sessions.

The caller supplies a server-validated business cutoff, not a request timestamp.
Use a fresh read transaction: capture fixes REPEATABLE READ before any SELECT,
and downstream result queries must use the same session and returned references.
"""
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr, ValidationError, model_validator
from sqlalchemy import and_, select, text

from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion
from src.biz.models.wealth.trading_assistant.publication import PublicationReceipt
from src.biz.schemas.wealth.market.trading_assistant.common import Contract, ReadContext, ReadContextAccount
from src.biz.schemas.wealth.market.trading_assistant.value_types import EntityId, Instant
from src.biz.services.wealth.market.trading_assistant.account_acceptance import accepted_time
from src.biz.services.wealth.market.trading_assistant.current_fee_basis import CurrentFeeBasis
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import fee_snapshot
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget, facts_digest
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


class ContextToken(Contract):
    v: StrictInt
    accountMode: Literal["ALL", "SINGLE"]
    accountId: EntityId | None
    targetThrough: Instant
    basisDigest: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def valid_scope(self):
        if self.v != 1 or (self.accountMode == "SINGLE") != (self.accountId is not None):
            raise ValueError("Invalid context version or scope")
        return self


def encode_context(value: ContextToken) -> str:
    payload = json.dumps(value.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_context(value: str) -> ContextToken:
    try:
        if not isinstance(value, str) or not value or any(
                c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
            raise ValueError("Invalid base64url")
        payload = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        result = ContextToken.model_validate_json(payload)
        # Reject duplicates, noncanonical encodings, extra keys and lossy coercion.
        if encode_context(result) != value:
            raise ValueError("Noncanonical context")
        return result
    except (ValueError, TypeError, UnicodeDecodeError, ValidationError) as error:
        raise WriteProtocolConflict("TA_REQUEST_INVALID") from error


@dataclass(frozen=True, slots=True)
class OwnedReadContext:
    context: ReadContext
    fees: tuple[CurrentFeeBasis, ...]


class CurrentReadContextQuery:
    def __init__(self, policy):
        self.policy = policy

    def capture(self, session, *, owner_id: int, account_mode: str, account_id: UUID | None,
                target_through: datetime, deadline, context_token: str | None = None) -> OwnedReadContext:
        if account_mode not in ("ALL", "SINGLE") or (account_mode == "SINGLE") != (account_id is not None):
            raise WriteProtocolConflict("TA_REQUEST_INVALID")
        requested = decode_context(context_token) if context_token is not None else None
        through = accepted_time(target_through)
        # The existing authenticated dependency supplies owner_id. Tokens carry
        # no authorization. Never accept a client cutoff as the trusted cutoff.
        deadline.remaining_ms()
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        source_mode = requested.accountMode if requested else account_mode
        source_id = UUID(requested.accountId) if requested and requested.accountId else account_id
        if source_mode == "ALL":
            source_id = None
        accounts, fees, bases = self._accounts(session, owner_id, source_id, deadline)
        if source_mode == "SINGLE" and not accounts:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        if account_mode == "ALL" and source_mode != "ALL":
            raise WriteProtocolConflict("TA_REQUEST_INVALID")
        selected = [i for i,a in enumerate(accounts) if account_id is None or a.accountId == str(account_id)]
        if account_mode == "SINGLE" and not selected:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        full = self._context(owner_id, source_mode, source_id, through, accounts, bases)
        if requested and encode_context(requested) != full.contextToken:
            raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
        selected_accounts = [accounts[i] for i in selected]
        selected_bases = [bases[i] for i in selected]
        result = self._context(owner_id, account_mode, account_id, through, selected_accounts, selected_bases)
        deadline.remaining_ms()
        return OwnedReadContext(result, tuple(fees[i] for i in selected))

    @staticmethod
    def _context(owner, mode, account, through, accounts, bases):
        digest = facts_digest(dict(ownerId=str(owner), accounts=[a.model_dump() for a in accounts],
                                  valuationBases=bases, targetThrough=through))
        token = ContextToken(v=1, accountMode=mode, accountId=str(account) if account else None,
                             targetThrough=through, basisDigest=digest)
        return ReadContext(contextToken=encode_context(token), accounts=accounts, targetThrough=through)

    def _accounts(self, session, owner, account_id, deadline):
        accounts, fees, bases, after = [], [], [], None
        while True:
            apply_sql_budget(session, deadline, self.policy)
            query = select(Account.account_id, Account.fact_version, Account.calculation_target_version,
                Account.published_generation_id, FeeVersion.fee_version_id, FeeVersion.commission_rate,
                FeeVersion.minimum_commission, FeeVersion.stamp_tax_rate, PublicationReceipt.manifest_digest
            ).select_from(Account).join(FeeVersion, and_(FeeVersion.account_id == Account.account_id,
                FeeVersion.fee_version_id == Account.current_fee_version_id)).outerjoin(PublicationReceipt,
                and_(PublicationReceipt.account_id == Account.account_id,
                     PublicationReceipt.generation_id == Account.published_generation_id)).where(Account.owner_id == owner)
            if account_id is not None:
                query = query.where(Account.account_id == account_id)
            if after is not None:
                query = query.where(Account.account_id > after)
            rows = session.execute(query.order_by(Account.account_id).limit(self.policy.page_rows)).all()
            for row in rows:
                if row.published_generation_id and row.manifest_digest is None:
                    raise ValueError("Published account has no publication receipt")
                accounts.append(ReadContextAccount(accountId=str(row.account_id), factVersion=str(row.fact_version),
                    calculationTargetVersion=str(row.calculation_target_version),
                    publishedGenerationId=str(row.published_generation_id) if row.published_generation_id else None))
                fees.append(CurrentFeeBasis(row.account_id, row.fee_version_id, fee_snapshot(row)))
                bases.append(dict(feeVersionId=str(row.fee_version_id),
                    manifestDigest=bytes(row.manifest_digest).hex() if row.manifest_digest is not None else None))
            if len(rows) < self.policy.page_rows:
                return accounts, fees, bases
            after = rows[-1].account_id
