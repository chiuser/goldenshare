"""Fee changes interleave with real validation, then final acceptance rechecks."""
import asyncio
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.models.wealth.trading_assistant.accounts import Initialization
from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
from src.biz.schemas.wealth.market.trading_assistant.accounts import TradeCommand, CorrectTradeCommand, UpdateFeesCommand
from src.biz.schemas.wealth.market.trading_assistant.targets import TradeTarget
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core.trade_calendar import TradeCalendar


def ids():
    return dict(requestId=str(uuid4()), attemptId=str(uuid4()))


def test_fee_change_between_validation_and_acceptance_and_original_snapshot(database):
    with database.begin() as connection:
        account, initial, fee = seed_account(connection)
        connection.execute(update(Initialization).where(Initialization.initialization_id == initial).values(initial_cash="100000.00"))
        connection.execute(insert(Security).values(ts_code="600003.SH", name="费用测试", exchange="SSE", security_type="EQUITY", curr_type="CNY", source="test"))
        connection.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=date(2026,9,11), is_open=True, pretrade_date=date(2026,9,10)))

    async def run():
        engine = create_async_engine(database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(),
            now=lambda:datetime(2026,9,11,8,tzinfo=timezone.utc), executor_id="fee-race")
        original = deps.ledger.validator.validate
        runs, next_fee = [], []
        async def interleave(*args, **kwargs):
            proof = await original(*args, **kwargs)
            runs.append(proof)
            if len(runs) == 1:
                changed = await deps.accounts.update_fees(owner_id=1, account_id=account, command=UpdateFeesCommand(**ids(),
                    expectedFeeVersionId=str(fee), commissionRateWan="10.00", minimumCommission="9.00", stampTaxRatePct="0.10"))
                assert changed.status == "SAVED"
                next_fee.append(changed.receipt["result"]["feeVersionId"])
            return proof
        deps.ledger.validator.validate = interleave
        try:
            args = dict(tsCode="600003.SH", direction="BUY", tradeDate="2026-09-11", price="10.00", quantity=1000)
            first = await deps.ledger.save(owner_id=1, account_id=account, operation="TRADE_CREATE", command=TradeCommand(**ids(), **args))
            assert first.status == "SAVED", first.rejection
            assert len(runs) == 2  # One bounded revalidation, no acceptance under the old fee.
            assert first.receipt["result"]["feeVersionId"] == next_fee[0]
            assert first.receipt["result"]["commissionAmount"] == "10.00"
            assert first.receipt["result"]["stampTaxAmount"] == "0.00"
            deps.ledger.validator.validate = original
            second = await deps.ledger.save(owner_id=1, account_id=account, operation="TRADE_CREATE", command=TradeCommand(**ids(), **args))
            assert second.status == "SAVED" and second.receipt["result"]["tradeId"] != first.receipt["result"]["tradeId"]
            changed = await deps.accounts.update_fees(owner_id=1, account_id=account, command=UpdateFeesCommand(**ids(),
                expectedFeeVersionId=next_fee[0], commissionRateWan="20.00", minimumCommission="20.00", stampTaxRatePct="0.20"))
            assert changed.status == "SAVED"
            target = TradeTarget(kind="TRADE", accountId=str(account), recordId=first.receipt["result"]["tradeId"])
            corrected = await deps.ledger.save(owner_id=1, account_id=account, operation="TRADE_CORRECT", target=target,
                command=CorrectTradeCommand(**ids(), **{**args, "price":"11.00"}, expectedRevision="1"))
            assert corrected.status == "SAVED", corrected.rejection
            assert corrected.receipt["result"]["commissionAmount"] == "11.00"
            assert corrected.receipt["result"]["feeVersionId"] == next_fee[0]
            return UUID(target.recordId)
        finally:
            await engine.dispose()
    first_id = asyncio.run(run())
    with Session(database) as session:
        old = session.get(LedgerRevision,(first_id,1))
        assert str(old.commission_amount) == "10.00" and str(old.stamp_tax_rate) == "0.0010"
        assert len(session.scalars(select(LedgerRevision).where(LedgerRevision.account_id == account)).all()) == 3
