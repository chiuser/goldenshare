"""Real request-driven acceptance with isolated PostgreSQL, no mock services."""
import asyncio
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, func, insert
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.app.runtime.trading_assistant_transactions import TradingAssistantTransactions
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.ledger import LedgerRevision
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.schemas.wealth.market.trading_assistant.accounts import CashFlowCommand, CorrectCashFlowCommand, VoidCommand
from src.biz.schemas.wealth.market.trading_assistant.targets import CashFlowTarget
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.ledger_commands import LedgerCommandService
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader


def ids():
    return dict(requestId=str(uuid4()),attemptId=str(uuid4()))


def test_account_creation_and_fee_updates_are_request_driven(database):
    from src.biz.schemas.wealth.market.trading_assistant.accounts import CreateAccountCommand, UpdateFeesCommand
    from src.biz.services.wealth.market.trading_assistant.account_commands import AccountCommandService
    from src.biz.models.wealth.trading_assistant.accounts import FeeVersion, Initialization

    async def execute():
        engine = create_async_engine(database.url)
        policy = TradingAssistantExecutionPolicyV1()
        service = AccountCommandService(TradingAssistantTransactions(engine), MarketFactsReader(policy), policy,
            lambda: datetime(2026, 9, 12, 8, tzinfo=timezone.utc), executor_id="account-test")
        try:
            command = CreateAccountCommand(**ids(), name="主账户", brokerName="测试券商", initialCash="10000.00",
                initialPositions=[], commissionRateWan="2.50", minimumCommission="5.00", stampTaxRatePct="0.05")
            created = await service.create(owner_id=1, command=command)
            assert created.status == "SAVED", created.rejection
            assert (await service.create(owner_id=1, command=command)).receipt == created.receipt
            result = created.receipt["result"]
            account_id = UUID(result["account"]["accountId"])
            old_fee = result["fees"]["feeVersionId"]
            assert result["account"]["initializedOn"] == "2026-09-12"
            changed = await service.update_fees(owner_id=1, account_id=account_id,
                command=UpdateFeesCommand(**ids(), expectedFeeVersionId=old_fee, commissionRateWan="3.00",
                    minimumCommission="6.00", stampTaxRatePct="0.06"))
            assert changed.status == "SAVED", changed.rejection
            assert changed.receipt["result"]["feeVersionId"] != old_fee
            stale = await service.update_fees(owner_id=1, account_id=account_id,
                command=UpdateFeesCommand(**ids(), expectedFeeVersionId=old_fee, commissionRateWan="4.00",
                    minimumCommission="6.00", stampTaxRatePct="0.06"))
            assert stale.status == "NOT_SAVED" and stale.rejection["code"] == "TA_FEE_VERSION_CONFLICT"
            from src.biz.queries.wealth.market.trading_assistant.accounts import AccountQueries
            from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
            queries = AccountQueries(policy, service.market)
            listed = await service.transactions.run(lambda s: queries.list(s, owner_id=1, deadline=Deadline.after_ms(5000)),
                deadline=Deadline.after_ms(5000), write=False)
            assert str(account_id) in [item.accountId for item in listed.items]
            detail = await service.transactions.run(lambda s: queries.initialization(s, owner_id=1, account_id=account_id,
                deadline=Deadline.after_ms(5000)), deadline=Deadline.after_ms(5000), write=False)
            assert detail.initialCash == "10000.00" and detail.initialPositions == []
            fees = await service.transactions.run(lambda s: queries.fees(s, owner_id=1, account_id=account_id,
                deadline=Deadline.after_ms(5000)), deadline=Deadline.after_ms(5000), write=False)
            assert (fees.commissionRateWan, fees.minimumCommission, fees.stampTaxRatePct) == ("3.00", "6.00", "0.06")
            return account_id
        finally:
            await engine.dispose()
    account_id = asyncio.run(execute())
    with Session(database) as session:
        assert session.get(Account, account_id).fact_version == 1
        assert session.get(Recalculation, account_id).target_version == 1
        assert session.scalar(select(func.count()).select_from(FeeVersion).where(FeeVersion.account_id == account_id)) == 2
        assert session.scalar(select(func.count()).select_from(Initialization).where(Initialization.account_id == account_id)) == 1
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account_id)) == 0


def test_cash_acceptance_correction_void_and_same_request_replay(database):
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
    now = datetime(2026,9,11,8,tzinfo=timezone.utc)
    async def execute():
        engine = create_async_engine(database.url)
        policy = TradingAssistantExecutionPolicyV1()
        service = LedgerCommandService(TradingAssistantTransactions(engine),MarketFactsReader(policy),policy,
                                       lambda:now,executor_id="test")
        async def save(operation,command,target=None):
            return await service.save(owner_id=1,account_id=account,operation=operation,command=command,target=target)
        try:
            inward = CashFlowCommand(**ids(),direction="IN",occurredOn="2026-09-11",amount="1000.00")
            first = await save("CASH_FLOW_CREATE",inward)
            assert first.status == "SAVED", first.rejection
            repeated = await save("CASH_FLOW_CREATE",inward)
            assert repeated.receipt == first.receipt
            out = await save("CASH_FLOW_CREATE",CashFlowCommand(**ids(),direction="OUT",occurredOn="2026-09-11",amount="700.00"))
            assert out.status == "SAVED", out.rejection
            rejected = await save("CASH_FLOW_CREATE",CashFlowCommand(**ids(),direction="OUT",occurredOn="2026-09-11",amount="700.00"))
            assert rejected.status == "NOT_SAVED" and rejected.rejection["field"] == "amount"
            assert rejected.rejection["message"] == "转出金额超过当前可用现金，请检查。"
            in_target = CashFlowTarget(accountId=str(account),kind="CASH_FLOW",recordId=first.receipt["result"]["cashFlowId"])
            out_target = CashFlowTarget(accountId=str(account),kind="CASH_FLOW",recordId=out.receipt["result"]["cashFlowId"])
            bad = await save("CASH_FLOW_CORRECT",CorrectCashFlowCommand(**ids(),expectedRevision="1",
                direction="IN",occurredOn="2026-09-11",amount="500.00"),in_target)
            assert bad.status == "NOT_SAVED"
            corrected = await save("CASH_FLOW_CORRECT",CorrectCashFlowCommand(**ids(),expectedRevision="1",
                direction="OUT",occurredOn="2026-09-11",amount="600.00"),out_target)
            assert corrected.status == "SAVED", corrected.rejection
            assert corrected.receipt["result"]["revision"] == "2"
            denied_void = await save("CASH_FLOW_VOID",VoidCommand(**ids(),expectedRevision="1"),in_target)
            assert denied_void.status == "NOT_SAVED"
            voided = await save("CASH_FLOW_VOID",VoidCommand(**ids(),expectedRevision="2"),out_target)
            assert voided.status == "SAVED" and voided.receipt["result"]["status"] == "VOID", voided.rejection
        finally:
            await engine.dispose()
    asyncio.run(execute())
    with Session(database) as session:
        assert session.get(Account,account).fact_version == 5
        assert session.get(Recalculation,account).target_version == 5
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == 4


def test_t_plus_one_and_stock_correction_validate_old_stock_future_sales(database):
    from src.foundation.models.core_serving.security_serving import Security
    from src.foundation.models.core.trade_calendar import TradeCalendar
    from src.biz.schemas.wealth.market.trading_assistant.accounts import TradeCommand,CorrectTradeCommand
    from src.biz.schemas.wealth.market.trading_assistant.targets import TradeTarget
    with database.begin() as conn:
        account,_,_ = seed_account(conn)
        for stock,exchange in [("600000.SH","SSE"),("000001.SZ","SZSE")]:
            conn.execute(insert(Security).values(ts_code=stock,name="测试股票",exchange=exchange,security_type="EQUITY",curr_type="CNY",source="test"))
        for day in (11,14):
            conn.execute(insert(TradeCalendar).values(exchange="SSE",trade_date=date(2026,9,day),
                is_open=True,pretrade_date=date(2026,9,10 if day == 11 else 11)))
    async def execute():
        engine = create_async_engine(database.url)
        policy = TradingAssistantExecutionPolicyV1()
        service = LedgerCommandService(TradingAssistantTransactions(engine),MarketFactsReader(policy),policy,
            lambda:datetime(2026,9,14,8,tzinfo=timezone.utc),executor_id="test")
        async def save(operation,command,target=None):
            return await service.save(owner_id=1,account_id=account,operation=operation,command=command,target=target)
        try:
            assert (await save("CASH_FLOW_CREATE",CashFlowCommand(**ids(),direction="IN",occurredOn="2026-09-11",amount="10000.00"))).status == "SAVED"
            buy = await save("TRADE_CREATE",TradeCommand(**ids(),tsCode="600000.SH",direction="BUY",tradeDate="2026-09-11",price="10.00",quantity=100))
            assert buy.status == "SAVED", buy.rejection
            same_day = await save("TRADE_CREATE",TradeCommand(**ids(),tsCode="600000.SH",direction="SELL",tradeDate="2026-09-11",price="11.00",quantity=100))
            assert same_day.status == "NOT_SAVED" and same_day.rejection["field"] == "quantity"
            sell = await save("TRADE_CREATE",TradeCommand(**ids(),tsCode="600000.SH",direction="SELL",tradeDate="2026-09-14",price="11.00",quantity=40))
            assert sell.status == "SAVED", sell.rejection
            from src.biz.queries.wealth.market.trading_assistant.entry_context import EntryContextQuery
            from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
            contexts = EntryContextQuery(policy, service.market)
            for day, expected_quantity, expected_available in ((11, "100", "0"), (14, "60", "60")):
                deadline = Deadline.after_ms(5000)
                context = await service.transactions.run(lambda s: contexts.read(s, owner_id=1, account_id=account,
                    occurred_on=date(2026,9,day), ts_code="600000.SH", now=service.now(), deadline=deadline),
                    deadline=deadline, write=False)
                assert (context.quantity, context.availableQuantity) == (expected_quantity, expected_available)
                assert context.availableCash == "9429.78"
            target = TradeTarget(accountId=str(account),kind="TRADE",recordId=buy.receipt["result"]["tradeId"])
            moved = await save("TRADE_CORRECT",CorrectTradeCommand(**ids(),tsCode="000001.SZ",direction="BUY",tradeDate="2026-09-11",
                price="10.00",quantity=100,expectedRevision="1"),target)
            assert moved.status == "NOT_SAVED" and moved.rejection["field"] == "quantity"
            voided = await save("TRADE_VOID",VoidCommand(**ids(),expectedRevision="1"),target)
            assert voided.status == "NOT_SAVED"
        finally:
            await engine.dispose()
    asyncio.run(execute())
    with Session(database) as session:
        assert session.get(Account,account).fact_version == 4
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == 3


def test_initialization_correction_keeps_origin_and_checks_removed_stock(database):
    from decimal import Decimal
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from src.foundation.models.core_serving.security_serving import Security
    from src.foundation.models.core.trade_calendar import TradeCalendar
    from src.biz.models.wealth.trading_assistant.accounts import InitialPosition, Initialization
    from src.biz.schemas.wealth.market.trading_assistant.accounts import TradeCommand, CorrectInitializationCommand
    with database.begin() as conn:
        account, initial, _ = seed_account(conn)
        conn.execute(pg_insert(Security).values(ts_code="600001.SH", name="测试期初股票", exchange="SSE",
            security_type="EQUITY", curr_type="CNY", source="test").on_conflict_do_nothing())
        conn.execute(pg_insert(TradeCalendar).values(exchange="SSE", trade_date=date(2026,9,11), is_open=True,
            pretrade_date=date(2026,9,10)).on_conflict_do_nothing())
        conn.execute(insert(InitialPosition).values(initialization_id=initial, account_id=account,
            ts_code="600001.SH", client_row_id="stable-row", opened_on=date(2026,9,11), quantity=100, available_quantity=100, cost_price=Decimal("10.00")))
    async def execute():
        engine = create_async_engine(database.url)
        policy = TradingAssistantExecutionPolicyV1()
        service = LedgerCommandService(TradingAssistantTransactions(engine), MarketFactsReader(policy), policy,
            lambda:datetime(2026,9,14,8,tzinfo=timezone.utc), executor_id="initial-test")
        try:
            sold = await service.save(owner_id=1, account_id=account, operation="TRADE_CREATE", command=TradeCommand(
                **ids(), tsCode="600001.SH", direction="SELL", tradeDate="2026-09-11", price="11.00", quantity=60))
            assert sold.status == "SAVED", sold.rejection
            invalid_stock = await service.save(owner_id=1, account_id=account, operation="INITIALIZATION_CORRECT",
                command=CorrectInitializationCommand(**ids(), expectedRevision="1", initialCash="0.00", initialPositions=[dict(
                    clientRowId="invalid-stock-row", tsCode="999999.SH", openedOn="2026-09-11", quantity=10, availableQuantity=10, costPrice="1.00")]))
            assert invalid_stock.status == "NOT_SAVED"
            assert invalid_stock.field_errors[0].field == "initialPositions.tsCode"
            assert invalid_stock.field_errors[0].clientRowId == "invalid-stock-row"
            row = dict(clientRowId="stable-row", tsCode="600001.SH", openedOn="2026-09-11", quantity=100, availableQuantity=50, costPrice="10.20")
            bad = await service.save(owner_id=1, account_id=account, operation="INITIALIZATION_CORRECT",
                command=CorrectInitializationCommand(**ids(), expectedRevision="1", initialCash="0.00", initialPositions=[row]))
            assert bad.status == "NOT_SAVED", bad
            assert bad.field_errors[0].field == "initialPositions.availableQuantity"
            assert bad.field_errors[0].clientRowId == "stable-row"
            assert bad.field_errors[0].affectedOn == "2026-09-11"
            removed = await service.save(owner_id=1, account_id=account, operation="INITIALIZATION_CORRECT",
                command=CorrectInitializationCommand(**ids(), expectedRevision="1", initialCash="0.00", initialPositions=[]))
            assert removed.status == "NOT_SAVED" and removed.field_errors[0].field == "initialPositions"
            row["availableQuantity"] = 60
            saved = await service.save(owner_id=1, account_id=account, operation="INITIALIZATION_CORRECT",
                command=CorrectInitializationCommand(**ids(), expectedRevision="1", initialCash="0.00", initialPositions=[row]))
            assert saved.status == "SAVED", saved.rejection
            assert saved.receipt["result"]["initializationRevision"] == "2"
            assert saved.receipt["result"]["affectedFromDate"] == "2026-09-11"
        finally:
            await engine.dispose()
    asyncio.run(execute())
    with Session(database) as session:
        assert session.get(Account, account).initialized_on == date(2026,9,11)
        assert session.get(Account, account).fact_version == 3
        assert session.scalar(select(func.count()).select_from(Initialization).where(Initialization.account_id == account)) == 2
        assert session.scalar(select(func.count()).select_from(LedgerRevision).where(LedgerRevision.account_id == account)) == 1
