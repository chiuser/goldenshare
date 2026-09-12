"""M2 physical constraints against a newly created, isolated PostgreSQL.

The frozen migration runs only in this new cluster, never the configured database.
This suite does not assert the command/API milestones are complete.
"""
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.app.models.app_user import AppUser  # Register only the existing FK target.
from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.models.wealth.trading_assistant.recovery import (
    WriteScope, WriteRequest, WriteAttempt, ValidationCandidate, ValidationCheckpoint)
from src.biz.models.wealth.trading_assistant.calculation import (
    Recalculation, CalculationGeneration, DayResult, PositionState, ClosedTrade)
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.queries.wealth.market.trading_assistant.effective_ledger import effective_ledger
from src.foundation.models.base import Base
from tests.wealth_watchlist_postgres_support import isolated_postgres, PG_BIN


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    assert (PG_BIN / "initdb").is_file(), "Existing PostgreSQL installation required"
    with isolated_postgres(tmp_path_factory.mktemp("ta-m2-pg")) as engine:
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA app"))
            conn.execute(text("CREATE SCHEMA core_serving"))
            conn.execute(text("CREATE TABLE app.app_user (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO app.app_user VALUES (1), (2)"))
            migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000171").module
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000172").module.upgrade()
            Base.metadata.create_all(conn, tables=[Security.__table__, TradeCalendar.__table__])
        yield engine


def test_migration_rollback_refuses_to_delete_accounting_data(database):
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000171").module
    assert migration.down_revision == "20260907_000170"
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
    with pytest.raises(RuntimeError,match="must be retained"):
        with database.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
    with database.connect() as conn:
        assert conn.scalar(select(Account.account_id).where(Account.account_id == account)) == account


def seed_account(conn, *, fee_override=None):
    account, initialization, fee = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    conn.execute(insert(Account).values(account_id=account, owner_id=1, name="测试",
        broker_name="测试券商", initialized_on=date(2026, 9, 11), created_at=now,
        current_initialization_id=initialization, current_fee_version_id=fee,
        fact_version=1, calculation_target_version=1))
    conn.execute(insert(FeeVersion).values(fee_version_id=fee, account_id=account,
        commission_rate="0.000235", minimum_commission="5.00", stamp_tax_rate="0.0005",
        created_at=now, **(fee_override or {})))
    conn.execute(insert(Initialization).values(initialization_id=initialization, account_id=account,
        revision=1, accepted_fact_version=1, initial_cash="0.00", created_at=now))
    return account, initialization, fee


def test_atomic_cyclic_versions_and_zero_cash(database):
    with database.begin() as conn:
        account, initialization, fee = seed_account(conn)
    with database.connect() as conn:
        assert conn.scalar(select(Account.current_fee_version_id).where(Account.account_id == account)) == fee
        assert conn.scalar(select(Initialization.initial_cash).where(Initialization.initialization_id == initialization)) == 0


def test_cross_account_current_fee_rejected(database):
    with database.begin() as conn:
        a, _, _ = seed_account(conn)
        _, _, b_fee = seed_account(conn)
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(Account.__table__.update().where(Account.account_id == a).values(current_fee_version_id=b_fee))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-0.01", "1.001"])
def test_initial_cash_rejects_nonfinite_negative_or_extra_precision(database, value):
    with database.begin() as conn:
        account, previous, _ = seed_account(conn)
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(insert(Initialization).values(initialization_id=uuid4(), account_id=account,
                revision=2, accepted_fact_version=2, initial_cash=value,
                source_initialization_id=previous, created_at=datetime.now(timezone.utc)))


def test_non_lot_quantity_and_zero_available(database):
    with database.begin() as conn:
        account, initialization, _ = seed_account(conn)
        conn.execute(insert(InitialPosition).values(account_id=account, initialization_id=initialization,
            ts_code="000001.SZ", client_row_id="row-a", opened_on=date(2026,9,11), quantity=3, available_quantity=0, cost_price="0.01"))
    with database.connect() as conn:
        assert conn.scalar(select(InitialPosition.quantity).where(InitialPosition.initialization_id == initialization)) == 3


@pytest.mark.parametrize("quantity,available", [(0, 0), (3, 4), (9007199254740992, 0)])
def test_bad_quantity_rejected(database, quantity, available):
    with database.begin() as conn:
        account, initialization, _ = seed_account(conn)
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(insert(InitialPosition).values(account_id=account, initialization_id=initialization,
                ts_code="000001.SZ", client_row_id="row-a", opened_on=date(2026,9,11), quantity=quantity,
                available_quantity=available, cost_price="0.01"))


def test_missing_required_version_rolls_back_account(database):
    account = uuid4()
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(insert(Account).values(account_id=account, owner_id=1, name="测试",
                broker_name="券商", initialized_on=date(2026, 9, 11), created_at=datetime.now(timezone.utc),
                current_initialization_id=uuid4(), current_fee_version_id=uuid4(),
                fact_version=1, calculation_target_version=1))
    with database.connect() as conn:
        assert conn.scalar(select(Account.account_id).where(Account.account_id == account)) is None


def test_effective_version_precedes_filters_and_void(database):
    now = datetime.now(timezone.utc)
    ledger = uuid4()
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(Ledger).values(ledger_id=ledger, account_id=account, kind="CASH_FLOW", created_at=now))
        for revision, day, status in ((1, 11, "ACTIVE"), (2, 12, "ACTIVE"), (3, 12, "VOID")):
            conn.execute(insert(LedgerRevision).values(ledger_id=ledger, revision=revision,
                account_id=account, kind="CASH_FLOW", accepted_fact_version=revision + 1,
                occurred_on=date(2026, 9, day), status=status, accepted_at=now,
                source_revision=revision - 1 if revision > 1 else None,
                direction="IN", net_cash_change="100.00", cash_amount="100.00"))
    with database.connect() as conn:
        original = effective_ledger(owner_id=1, account_id=account, fact_version=2)
        assert conn.scalar(select(original.c.occurred_on)) == date(2026, 9, 11)
        current = effective_ledger(owner_id=1, account_id=account, fact_version=3)
        assert conn.scalar(select(current.c.occurred_on)) == date(2026, 9, 12)
        assert conn.scalar(select(current.c.ledger_id).where(current.c.occurred_on == date(2026, 9, 11))) is None
        voided = effective_ledger(owner_id=1, account_id=account, fact_version=4)
        assert conn.scalar(select(voided.c.ledger_id)) is None
        foreign = effective_ledger(owner_id=2, account_id=account, fact_version=2)
        assert conn.scalar(select(foreign.c.ledger_id)) is None


def test_recovery_input_and_attempt_are_atomic(database):
    request, attempt = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with database.begin() as conn:
        conn.execute(insert(WriteScope).values(owner_id=1, scope_key=str(request), holder_request_id=request))
        conn.execute(insert(WriteRequest).values(owner_id=1, request_id=request, scope_key=str(request),
            operation_type="ACCOUNT_CREATE", input_schema_version=1, input_digest=b"a" * 32,
            input_payload={"name": "测试"}, current_attempt_id=attempt, state_version=0,
            created_at=now, updated_at=now))
        conn.execute(insert(WriteAttempt).values(owner_id=1, request_id=request, attempt_id=attempt,
            status="PROCESSING", fence=1, executor_id="test", lease_until=now, basis={}, started_at=now))
    with database.connect() as conn:
        assert conn.scalar(select(WriteScope.holder_request_id).where(WriteScope.scope_key == str(request))) == request
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(WriteRequest.__table__.update().where(WriteRequest.request_id == request).values(input_payload=None))
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(insert(WriteAttempt).values(owner_id=1, request_id=request, attempt_id=uuid4(),
                status="PROCESSING", fence=2, executor_id="test-2", lease_until=now, basis={}, started_at=now))


def test_derived_quantity_numeric_roundtrip_beyond_bigint(database):
    from decimal import localcontext
    from src.biz.services.wealth.market.trading_assistant.persistence_values import (
        integer_numeric, numeric_integer, quantity_text)
    quantity = 10**50 + 17
    with localcontext() as context:
        context.prec = 6
        with database.connect() as conn:
            actual = conn.scalar(text("SELECT CAST(:quantity AS NUMERIC)"), {"quantity":integer_numeric(quantity)})
        assert numeric_integer(actual) == quantity
        assert quantity_text(actual) == str(quantity)


def test_signed_money_conversion_ignores_decimal_context(database):
    from decimal import Decimal, localcontext
    from src.biz.services.wealth.market.trading_assistant.persistence_values import money_numeric, numeric_cents
    with localcontext() as context:
        context.prec = 6
        for cents in (0, -1, 10**55 + 17, -(10**55 + 17)):
            with database.connect() as conn:
                actual = conn.scalar(text("SELECT CAST(:value AS NUMERIC)"), {"value":money_numeric(cents)})
            assert numeric_cents(actual) == cents
    for bad in ("NaN", "Infinity", "0.001", "-0.001"):
        with pytest.raises(ValueError):
            numeric_cents(Decimal(bad))


def test_prospective_replacement_removes_old_date_before_paging(database):
    from src.biz.queries.wealth.market.trading_assistant.effective_ledger import validation_page, ReplacementFact
    from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
    ledger = uuid4()
    now = datetime.now(timezone.utc)
    with database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(Ledger).values(ledger_id=ledger, account_id=account, kind="CASH_FLOW", created_at=now))
        conn.execute(insert(LedgerRevision).values(ledger_id=ledger,revision=1,account_id=account,
            kind="CASH_FLOW",accepted_fact_version=2,occurred_on=date(2026,9,11),status="ACTIVE",
            accepted_at=now,direction="IN",net_cash_change="100.00",cash_amount="100.00"))
    arguments = dict(owner_id=1,account_id=account,fact_version=2,limit=1,
        policy=TradingAssistantExecutionPolicyV1(),replaced_ledger_id=ledger,
        replacement=ReplacementFact(ledger,date(2026,9,12),"CASH_FLOW","IN",None,None,20000))
    with database.connect() as conn:
        row = conn.execute(validation_page(**arguments)).one()
        assert row.occurred_on == date(2026,9,12) and row.net_cash_change == 200
        assert conn.execute(validation_page(**arguments,after=(row.occurred_on,row.ledger_id))).first() is None
        assert conn.execute(validation_page(**{**arguments,"owner_id":2})).first() is None
        assert conn.execute(validation_page(**{**arguments,"replacement":None})).first() is None
        # Validation did not write the proposed date/amount.
        assert conn.scalar(select(LedgerRevision.net_cash_change).where(LedgerRevision.ledger_id == ledger)) == 100


def test_request_registration_fencing_and_read_only_expiry(database):
    from datetime import timedelta
    from sqlalchemy.orm import Session
    from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocol, WriteProtocolConflict
    from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
    from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountCreateScope
    protocol = WriteProtocol(TradingAssistantExecutionPolicyV1())
    now = datetime.now(timezone.utc)
    request, attempt = uuid4(),uuid4()
    args = dict(owner_id=2,request_id=request,attempt_id=attempt,scope=AccountCreateScope(scopeType="ACCOUNT_CREATE"),
        operation="ACCOUNT_CREATE",payload={"name":"原始内容"},now=now,executor_id="test")
    with Session(database) as session, session.begin():
        started = protocol.register(session,**args,deadline=Deadline.after_ms(10000))
        assert started.execute and started.fence == 1
    with Session(database) as session, session.begin():
        same = protocol.register(session,**args,deadline=Deadline.after_ms(10000))
        assert not same.execute and same.state_version == 0
    with Session(database) as session, session.begin():
        assert protocol.read(session,owner_id=2,request_id=request).status == "PROCESSING"
        assert protocol.read(session,owner_id=1,request_id=request) is None
        assert protocol.read(session,owner_id=2,request_id=uuid4()) is None
    with pytest.raises(WriteProtocolConflict,match="TA_REQUEST_ID_CONFLICT"):
        with Session(database) as session, session.begin():
            protocol.register(session,**{**args,"payload":{"name":"变更内容"}},deadline=Deadline.after_ms(10000))
    with Session(database) as session, session.begin():
        stopped = protocol.expire(session,owner_id=2,request_id=request,key="ACCOUNT_CREATE",
                                  now=now+timedelta(seconds=16),deadline=Deadline.after_ms(10000))
        assert stopped.status == "NOT_SAVED" and stopped.fence == 2 and stopped.state_version == 1
    with pytest.raises(WriteProtocolConflict,match="TA_RECOVERY_STATE_CHANGED"):
        with Session(database) as session, session.begin():
            protocol.lock_execution(session,started,now=now,executor_id="test",deadline=Deadline.after_ms(10000))
    with Session(database) as session, session.begin():
        restarted = protocol.register(session,**{**args,"attempt_id":uuid4()},
            expected_state_version=1,deadline=Deadline.after_ms(10000))
        assert restarted.execute and restarted.state_version == 2 and restarted.fence == 3
        # Stop to release the shared ACCOUNT_CREATE scope for independent tests.
        from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryRejection
        locked = protocol.lock_execution(session,restarted,now=now,executor_id="test",deadline=Deadline.after_ms(10000))
        protocol.stop(session,locked,RecoveryRejection(code="TA_WRITE_FAILED",message="测试停止",field=None),now)


def seed_day_result(conn):
    account, initialization, _ = seed_account(conn)
    generation, day_result = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    conn.execute(insert(CalculationGeneration).values(generation_id=generation, account_id=account,
        target_version=1, fact_version=1, initialization_id=initialization, rule_version=1,
        from_date=date(2026,9,11), through_date=date(2026,9,11), stage="PREPARING",
        completed_trade_date_count=0, last_business_updated_at=now))
    conn.execute(insert(DayResult).values(day_result_id=day_result, account_id=account,
        origin_generation_id=generation, trade_date=date(2026,9,11), input_digest=b"d" * 32, status="BUILDING"))
    return account, day_result


@pytest.mark.parametrize("quantity", ["9007199254740992", "100000000000000000000000000000000000000000000000017"])
def test_derived_position_storage_has_no_input_or_bigint_cap(database, quantity):
    from decimal import Decimal
    with database.begin() as conn:
        account, day_result = seed_day_result(conn)
        conn.execute(insert(PositionState).values(account_id=account, day_result_id=day_result,
            ts_code="600000.SH", round_id=uuid4(), opened_on=date(2026,9,11), quantity=quantity,
            remaining_buy_cost="1.00", cumulative_buy_input="1.00", cumulative_sell_net="0.00"))
    with database.connect() as conn:
        assert conn.scalar(select(PositionState.quantity).where(PositionState.day_result_id == day_result)) == Decimal(quantity)
        assert conn.scalar(select(Account.published_generation_id).where(Account.account_id == account)) is None


@pytest.mark.parametrize("quantity", ["-1", "1.5", "NaN", "Infinity"])
def test_derived_position_rejects_invalid_numeric(database, quantity):
    with database.begin() as conn:
        account, day_result = seed_day_result(conn)
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(insert(PositionState).values(account_id=account, day_result_id=day_result,
                ts_code="600000.SH", round_id=uuid4(), opened_on=date(2026,9,11), quantity=quantity,
                remaining_buy_cost="1.00", cumulative_buy_input="1.00", cumulative_sell_net="0.00"))


@pytest.mark.parametrize("net", ["NaN", "Infinity", "-Infinity", "1.001"])
def test_derived_signed_proceeds_reject_invalid_numeric(database, net):
    with database.begin() as conn:
        account, day_result = seed_day_result(conn)
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(insert(PositionState).values(account_id=account,day_result_id=day_result,
                ts_code="600000.SH",round_id=uuid4(),opened_on=date(2026,9,11),quantity=1,
                remaining_buy_cost="1.00",cumulative_buy_input="1.00",cumulative_sell_net=net))


def test_cross_account_publication_pointer_rejected(database):
    with database.begin() as conn:
        first, _ = seed_day_result(conn)
        other, other_day = seed_day_result(conn)
        generation = conn.scalar(select(DayResult.origin_generation_id).where(DayResult.day_result_id == other_day))
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(Account.__table__.update().where(Account.account_id == first)
                         .values(published_generation_id=generation))


def test_security_and_complete_calendar_read_facts(database):
    from sqlalchemy.orm import Session
    from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader, MarketFactsUnavailable
    from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
    with database.begin() as conn:
        conn.execute(insert(Security).values(ts_code="600000.SH",name="浦发银行",exchange="SSE",security_type="EQUITY",curr_type="CNY",source="test"))
        for day, opened, previous in ((11,True,10),(12,False,11),(13,False,11),(14,True,11)):
            conn.execute(insert(TradeCalendar).values(exchange="SSE",trade_date=date(2026,9,day),
                is_open=opened,pretrade_date=date(2026,9,previous)))
    reader = MarketFactsReader(TradingAssistantExecutionPolicyV1())
    with Session(database) as session:
        stock = reader.resolve_security(session,"600000.SH",Deadline.after_ms(5000))
        assert stock.exchange == "SSE" and len(stock.source_version) == 64
        basis = reader.read_calendar(session,"SSE",date(2026,9,11),date(2026,9,14),Deadline.after_ms(5000))
        assert [day.is_open for day in basis.days] == [True,False,False,True]
        for market in ("SSE", "SZSE", "BSE"):
            shared = reader.read_calendar(session,market,date(2026,9,11),date(2026,9,14),Deadline.after_ms(5000))
            assert shared.exchange == market and shared.calendar_exchange == "SSE"
            assert shared.days == basis.days and shared.source_version == basis.source_version
            with pytest.raises(MarketFactsUnavailable):
                reader.read_calendar(session,market,date(2026,9,10),date(2026,9,14),Deadline.after_ms(5000))
        with pytest.raises(ValueError):
            reader.read_calendar(session,"HKEX",date(2026,9,11),date(2026,9,14),Deadline.after_ms(5000))


@pytest.mark.parametrize("code,currency", [("900901.SH", "USD"), ("200002.SZ", "HKD"), ("920099.BJ", None)])
def test_equity_exchange_alone_does_not_prove_a_share(database, code, currency):
    from sqlalchemy.orm import Session
    from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader, MarketFactsUnavailable, SecurityNotEligible
    from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
    with database.begin() as connection:
        connection.execute(insert(Security).values(ts_code=code, name="币种反例", exchange="SSE", security_type="EQUITY",
            curr_type=currency, source="test"))
    with Session(database) as session, pytest.raises(MarketFactsUnavailable if currency is None else SecurityNotEligible):
        MarketFactsReader(TradingAssistantExecutionPolicyV1()).resolve_security(session, code, Deadline.after_ms(5000))
