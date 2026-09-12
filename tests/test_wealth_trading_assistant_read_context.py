"""CTX: isolated PostgreSQL snapshots and strict, untrusted wire tokens."""
import base64
import json
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, deadline
from tests.test_wealth_trading_assistant_publication_storage import publication_db
from tests.test_wealth_trading_assistant_account_acceptance import create, NOW, register
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.queries.wealth.market.trading_assistant.read_context import (
    CurrentReadContextQuery, ContextToken, encode_context, decode_context)
from src.biz.schemas.wealth.market.trading_assistant.accounts import UpdateFeesCommand
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountFeesScope
from src.biz.services.wealth.market.trading_assistant.account_acceptance import AccountAcceptance
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def wire(document):
    return base64.urlsafe_b64encode(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")


@pytest.mark.parametrize("change", [dict(v=True), dict(v=2), dict(accountMode="SINGLE"),
    dict(accountId=str(uuid4())), dict(basisDigest="x"*64), dict(extra="bad"), dict(targetThrough="2026-09-12")])
def test_invalid_token_structure(change):
    document = dict(v=1,accountMode="ALL",accountId=None,targetThrough="2026-09-11T17:00:00Z",basisDigest="a"*64)
    with pytest.raises(WriteProtocolConflict, match="TA_REQUEST_INVALID"):
        decode_context(wire(document | change))


def test_token_roundtrip_and_noncanonical_rejected():
    token = ContextToken(v=1,accountMode="ALL",accountId=None,targetThrough="2026-09-11T17:00:00Z",basisDigest="a"*64)
    encoded = encode_context(token)
    assert decode_context(encoded) == token
    for value in (encoded+"=", "", "[]", wire({}), wire([]), "_", wire(token.model_dump() | {"v":"1"})):
        with pytest.raises(WriteProtocolConflict, match="TA_REQUEST_INVALID"):
            decode_context(value)


def test_owned_context_fee_update_paging_and_repeatable_read(publication_db):
    protocol, _, saved = create(publication_db)
    account = UUID(saved.receipt["result"]["account"]["accountId"])
    original = saved.receipt["result"]["fees"]["feeVersionId"]
    # Force account pagination without truncating the ALL scope.
    query = CurrentReadContextQuery(replace(TradingAssistantExecutionPolicyV1(), page_rows=1))
    def capture(mode="SINGLE", identity=account, token=None, owner=1, through=NOW):
        with Session(publication_db) as session, session.begin():
            return query.capture(session,owner_id=owner,account_mode=mode,account_id=identity,
                                 target_through=through,context_token=token,deadline=deadline())
    old = capture()
    all_old = capture("ALL", None)
    assert old.context.accounts[0].publishedGenerationId is None
    assert capture(token=old.context.contextToken) == old
    _, _, added = create(publication_db)
    second = UUID(added.receipt["result"]["account"]["accountId"])
    assert capture(token=old.context.contextToken) == old
    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
        capture("ALL", None, all_old.context.contextToken)
    complete = capture("ALL", None)
    assert [a.accountId for a in complete.context.accounts] == sorted([str(account), str(second)])
    assert capture(token=complete.context.contextToken).context == old.context  # ALL → owned SINGLE
    with pytest.raises(WriteProtocolConflict, match="TA_REQUEST_INVALID"):
        capture("ALL", None, old.context.contextToken)
    with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
        capture(token=old.context.contextToken, owner=2)
    with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
        capture(identity=uuid4(), token=complete.context.contextToken)
    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
        capture(token=old.context.contextToken, through=NOW+timedelta(days=1))
    tampered = decode_context(old.context.contextToken).model_copy(update={"basisDigest":"f"*64})
    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
        capture(token=encode_context(tampered))
    # A concurrent fee save cannot change the middle of an existing read response.
    with Session(publication_db) as reading, reading.begin():
        fixed = query.capture(reading,owner_id=1,account_mode="SINGLE",account_id=account,
                              target_through=NOW,deadline=deadline())
        assert reading.scalar(text("SHOW transaction_read_only")) == "on"
        assert reading.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        change = UpdateFeesCommand(requestId=str(uuid4()),attemptId=str(uuid4()),expectedFeeVersionId=original,
            commissionRateWan="10.00",minimumCommission="9.00",stampTaxRatePct="0.10")
        attempt = register(publication_db,protocol,change,AccountFeesScope(scopeType="ACCOUNT_FEES",accountId=str(account)),"FEES_UPDATE")
        with Session(publication_db) as writing, writing.begin():
            locked = protocol.lock_execution(writing,attempt,now=NOW,executor_id="account-test",deadline=deadline())
            AccountAcceptance(protocol).update_fees(writing,locked,change,account_id=account,now=NOW)
        assert reading.scalar(select(Account.current_fee_version_id).where(Account.account_id==account)) == UUID(original)
        assert fixed.fees[0].fee_version_id == UUID(original)
    with pytest.raises(WriteProtocolConflict, match="TA_READ_CONTEXT_CHANGED"):
        capture(token=old.context.contextToken)
    refreshed = capture()
    assert refreshed.context.accounts == old.context.accounts  # Not a historical recalculation.
    assert refreshed.fees[0].fee_version_id != UUID(original)
    assert refreshed.context.contextToken != old.context.contextToken
    with pytest.raises(DBAPIError):
        with Session(publication_db) as session, session.begin():
            query.capture(session,owner_id=1,account_mode="SINGLE",account_id=account,target_through=NOW,deadline=deadline())
            session.execute(update(Account).where(Account.account_id==account).values(name="must not write"))
