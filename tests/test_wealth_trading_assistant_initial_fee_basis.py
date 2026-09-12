"""First fee selection survives fee changes; no historical fee guessing."""
from uuid import UUID, uuid4
from fractions import Fraction

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_calculation_inputs import database, migrated, deadline, DAY, AT, fact
from tests.test_wealth_trading_assistant_account_acceptance import create, create_command, register, NOW
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.recovery import WriteAttempt
from src.biz.models.wealth.trading_assistant.calculation_inputs import ValuationBasis
from src.biz.schemas.wealth.market.trading_assistant.accounts import UpdateFeesCommand
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountFeesScope
from src.biz.services.wealth.market.trading_assistant.account_acceptance import AccountAcceptance
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputs, CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.initial_fee_basis import initial_fee_version
from src.biz.services.wealth.market.trading_assistant.new_valuation_fees import new_valuation_fee_version
from src.biz.services.wealth.market.trading_assistant.current_fee_basis import current_fee_basis
from src.biz.services.wealth.market.trading_assistant.calculation.daily import initialize_position, PositionState
from src.biz.services.wealth.market.trading_assistant.calculation.returns import value_round
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution


def test_first_history_freeze_after_fee_update_and_cross_owner_rejected(migrated):
    protocol, command, saved = create(migrated, create_command([dict(clientRowId="a",tsCode="000001.SZ",
        openedOn=DAY.isoformat(),quantity=1000,availableQuantity=1000,costPrice="10.00")]))
    account = UUID(saved.receipt["result"]["account"]["accountId"])
    original = UUID(saved.receipt["result"]["fees"]["feeVersionId"])
    change = UpdateFeesCommand(requestId=str(uuid4()),attemptId=str(uuid4()),expectedFeeVersionId=str(original),
        commissionRateWan="10.00",minimumCommission="9.00",stampTaxRatePct="0.10")
    state = register(migrated,protocol,change,AccountFeesScope(scopeType="ACCOUNT_FEES",accountId=str(account)),"FEES_UPDATE")
    with Session(migrated) as session, session.begin():
        locked = protocol.lock_execution(session,state,now=NOW,executor_id="account-test",deadline=deadline())
        AccountAcceptance(protocol).update_fees(session,locked,change,account_id=account,now=NOW)
    execution = RecalculationExecution(protocol.policy)
    with Session(migrated) as session, session.begin():
        lease = execution.claim(session,executor_id="first-history",deadline=deadline())
        assert lease.account_id == account
    inputs = CalculationInputs(execution)
    with Session(migrated) as session, session.begin():
        generation = inputs.prepare_generation(session,lease,from_date=DAY,through_date=DAY,rule_version=1,deadline=deadline())
        initial = initial_fee_version(session,owner_id=1,account_id=account,policy=protocol.policy,deadline=deadline())
        assert initial == original and session.get(Account,account).current_fee_version_id != original
        assert new_valuation_fee_version(session, execution, lease, generation_id=generation,
            business_date=DAY, deadline=deadline()) == original
        inputs.save_initial_history_page(session,lease,generation_id=generation,facts=(fact(),),
            valuation_at=AT,after_stock=None,deadline=deadline())
    with Session(migrated) as session, session.begin():
        inputs.save_initial_history_page(session,lease,generation_id=generation,facts=(fact(),),
            valuation_at=AT,after_stock=None,deadline=deadline())
    with Session(migrated) as session:
        assert session.scalar(select(ValuationBasis.fee_version_id).where(ValuationBasis.generation_id==generation)) == original
        value = session.scalar(select(ValuationBasis).where(ValuationBasis.generation_id==generation))
        frozen = {column.key:getattr(value,column.key) for column in ValuationBasis.__table__.columns}
        current_fee = session.get(Account,account).current_fee_version_id
        # No new trade is needed: the original holding immediately uses current
        # commission AND stamp tax, while the frozen history still uses original.
        basis = current_fee_basis(session, owner_id=1, account_id=account,
                                  policy=protocol.policy, deadline=deadline())
        assert basis.fee_version_id == current_fee
        holding = initialize_position(1000, 1000, 1000)
        estimate = value_round(holding, Fraction(10), basis.fees)
        assert estimate.liquidation.commission_cents == 1000
        assert estimate.liquidation.stamp_tax_cents == 1000
        assert estimate.result.profit_cents == -2000
    again = UpdateFeesCommand(requestId=str(uuid4()),attemptId=str(uuid4()),expectedFeeVersionId=str(current_fee),
        commissionRateWan="20.00",minimumCommission="12.00",stampTaxRatePct="0.20")
    state = register(migrated,protocol,again,AccountFeesScope(scopeType="ACCOUNT_FEES",accountId=str(account)),"FEES_UPDATE")
    with Session(migrated) as session, session.begin():
        locked = protocol.lock_execution(session,state,now=NOW,executor_id="account-test",deadline=deadline())
        AccountAcceptance(protocol).update_fees(session,locked,again,account_id=account,now=NOW)
    with Session(migrated) as session:
        value = session.scalar(select(ValuationBasis).where(ValuationBasis.generation_id==generation))
        assert {column.key:getattr(value,column.key) for column in ValuationBasis.__table__.columns} == frozen
        assert session.get(Account,account).calculation_target_version == lease.target_version
        basis = current_fee_basis(session, owner_id=1, account_id=account,
                                  policy=protocol.policy, deadline=deadline())
        assert basis.fee_version_id != current_fee
        estimate = value_round(holding, Fraction(10), basis.fees)
        assert estimate.liquidation.commission_cents == 2000
        assert estimate.liquidation.stamp_tax_cents == 2000
        assert estimate.result.profit_cents == -4000
        # Small holdings use the NEW minimum once; empty holdings charge nothing.
        small = value_round(initialize_position(1, 1, 1000), Fraction(10), basis.fees)
        assert small.liquidation.commission_cents == 1200
        empty = value_round(PositionState(0, 0, 0, 0, 0), None, basis.fees)
        assert empty.liquidation.commission_cents == empty.liquidation.stamp_tax_cents == 0
    with pytest.raises(CalculationInputMismatch):
        with Session(migrated) as session:
            current_fee_basis(session,owner_id=2,account_id=account,policy=protocol.policy,deadline=deadline())
    with pytest.raises(CalculationInputMismatch):
        with Session(migrated) as session:
            initial_fee_version(session,owner_id=2,account_id=account,policy=protocol.policy,deadline=deadline())
    # Broken evidence is an internal inconsistency, never an excuse to use current fees.
    broken = dict(saved.receipt)
    broken["result"] = dict(broken["result"],fees=dict(broken["result"]["fees"],feeVersionId=str(uuid4())))
    with migrated.begin() as conn:
        conn.execute(update(WriteAttempt).where(WriteAttempt.owner_id==1,WriteAttempt.request_id==UUID(command.requestId))
                     .values(receipt=broken))
    with pytest.raises(CalculationInputMismatch):
        with Session(migrated) as session:
            initial_fee_version(session,owner_id=1,account_id=account,policy=protocol.policy,deadline=deadline())
