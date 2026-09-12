"""M2 final transaction tests; not route or production migration acceptance."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database
from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.models.wealth.trading_assistant.recovery import WriteRequest, ValidationCandidate
from src.biz.schemas.wealth.market.trading_assistant.accounts import CreateAccountCommand, UpdateFeesCommand
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountCreateScope, AccountFeesScope
from src.biz.services.wealth.market.trading_assistant.account_acceptance import AccountAcceptance
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.market_facts import SecurityFact
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol


NOW = datetime(2026,9,11,17,0,tzinfo=timezone.utc)


def register(database, protocol, command, scope, operation):
    with Session(database) as session, session.begin():
        return protocol.register(session,owner_id=1,request_id=UUID(command.requestId),attempt_id=UUID(command.attemptId),
            scope=scope,operation=operation,payload=command.model_dump(mode="json",exclude={
                "requestId","attemptId","expectedRequestStateVersion"}),now=NOW,executor_id="account-test",
            deadline=Deadline.after_ms(10000))


def create_command(positions=None):
    return CreateAccountCommand(requestId=str(uuid4()),attemptId=str(uuid4()),name="账户",brokerName="券商",
        commissionRateWan="2.35",minimumCommission="5.00",stampTaxRatePct="0.05",initialCash="0.00",
        initialPositions=positions or [])


def create(database, command=None):
    command = command or create_command()
    protocol = WriteProtocol(TradingAssistantExecutionPolicyV1())
    attempt = register(database,protocol,command,AccountCreateScope(scopeType="ACCOUNT_CREATE"),"ACCOUNT_CREATE")
    with Session(database) as session, session.begin():
        locked = protocol.lock_execution(session,attempt,now=NOW,executor_id="account-test",deadline=Deadline.after_ms(10000))
        result = AccountAcceptance(protocol).create(session,locked,command,now=NOW,securities={
            p.tsCode:SecurityFact(p.tsCode,"示例股票","SZSE","test","test-version") for p in command.initialPositions})
    return protocol,command,result


def test_creation_atomic_versions_receipt_and_beijing_date(database):
    protocol,command,saved = create(database,create_command([{"clientRowId":"row-1","tsCode":"000001.SZ",
        "quantity":3,"availableQuantity":0,"costPrice":"10.00"}]))
    assert saved.status == "SAVED"
    result = saved.receipt["result"]
    assert result["account"]["initializedOn"] == "2026-09-12"
    assert result["initialization"]["initialPositions"][0]["costAmount"] == "30.00"
    account_id = UUID(result["account"]["accountId"])
    with Session(database) as session:
        account = session.get(Account,account_id)
        assert account.fact_version == account.calculation_target_version == 1
        assert account.published_generation_id is None
        assert session.get(Recalculation,account_id).affected_from_date.isoformat() == "2026-09-12"
        assert session.scalar(select(func.count()).select_from(Ledger).where(Ledger.account_id == account_id)) == 0
        request = session.get(WriteRequest,(1,UUID(command.requestId)))
        assert request.input_payload is None
        assert session.get(ValidationCandidate,request.candidate_id).input_payload["initialCash"] == "0.00"
    replay = register(database,protocol,command,AccountCreateScope(scopeType="ACCOUNT_CREATE"),"ACCOUNT_CREATE")
    assert replay.receipt == saved.receipt and not replay.execute


def test_fees_update_is_prospective_and_same_value_is_noop(database):
    protocol,_,saved = create(database)
    account_id = UUID(saved.receipt["result"]["account"]["accountId"])
    original_fee = saved.receipt["result"]["fees"]["feeVersionId"]
    for commission,expected_count in (("2.35",1),("5.00",2)):
        command = UpdateFeesCommand(requestId=str(uuid4()),attemptId=str(uuid4()),expectedFeeVersionId=original_fee,
            commissionRateWan=commission,minimumCommission="5.00",stampTaxRatePct="0.05")
        attempt = register(database,protocol,command,AccountFeesScope(scopeType="ACCOUNT_FEES",accountId=str(account_id)),"FEES_UPDATE")
        with Session(database) as session,session.begin():
            locked = protocol.lock_execution(session,attempt,now=NOW,executor_id="account-test",deadline=Deadline.after_ms(10000))
            result = AccountAcceptance(protocol).update_fees(session,locked,command,account_id=account_id,now=NOW)
            assert result.receipt["result"]["commissionRateWan"] == commission
        with Session(database) as session:
            assert session.scalar(select(func.count()).select_from(FeeVersion).where(FeeVersion.account_id == account_id)) == expected_count
            account = session.get(Account,account_id)
            assert account.fact_version == account.calculation_target_version == 1
            assert session.get(FeeVersion,UUID(original_fee)).commission_rate.as_integer_ratio() == (47,200000)


def test_create_rollback_retains_input_but_no_half_account(database):
    protocol = WriteProtocol(TradingAssistantExecutionPolicyV1())
    command = create_command()
    attempt = register(database,protocol,command,AccountCreateScope(scopeType="ACCOUNT_CREATE"),"ACCOUNT_CREATE")
    account_id = None
    with pytest.raises(RuntimeError,match="injected"):
        with Session(database) as session,session.begin():
            locked = protocol.lock_execution(session,attempt,now=NOW,executor_id="account-test",deadline=Deadline.after_ms(10000))
            result = AccountAcceptance(protocol).create(session,locked,command,securities={},now=NOW)
            account_id = UUID(result.receipt["result"]["account"]["accountId"])
            raise RuntimeError("injected before commit")
    with Session(database) as session:
        assert session.get(Account,account_id) is None
        assert session.get(Recalculation,account_id) is None
        assert protocol.read(session,owner_id=1,request_id=UUID(command.requestId)).status == "PROCESSING"
        assert session.get(WriteRequest,(1,UUID(command.requestId))).candidate_id is not None
