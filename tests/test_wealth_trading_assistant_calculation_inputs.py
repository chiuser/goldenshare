"""Frozen input pages on a fresh PostgreSQL, never the configured database."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import subprocess
import sys
import textwrap
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import insert, select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputs, CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution, CalculationExecutionLost
from src.biz.services.wealth.market.trading_assistant.valuation_facts import DailyCloseFact

DAY = date(2026,9,11)
AT = datetime(2026,9,11,7,tzinfo=timezone.utc)
def deadline(): return Deadline.after_ms(2000)


@pytest.fixture(scope="module")
def migrated(database):
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000173").module
    assert migration.down_revision == "20260912_000172"
    with database.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
    return database


def setup(engine):
    execution = RecalculationExecution(TradingAssistantExecutionPolicyV1())
    with engine.begin() as conn:
        account, _, fee = seed_account(conn)
        conn.execute(insert(Recalculation).values(account_id=account, target_version=1, affected_from_date=DAY,
            next_attempt_at=datetime.now(timezone.utc)-timedelta(days=1), fence=0, transient_failure_count=0,
            updated_at=datetime.now(timezone.utc)))
    with Session(engine) as session, session.begin():
        lease = execution.claim(session, executor_id="freeze", deadline=deadline())
        assert lease.account_id == account
    store = CalculationInputs(execution)
    with Session(engine) as session, session.begin():
        generation = store.prepare_generation(session, lease, from_date=DAY, through_date=DAY,
                                             rule_version=1, deadline=deadline())
    return store, lease, generation, fee


def fact(code="000001.SZ", price="10.1234"):
    return DailyCloseFact(code,DAY,DAY if price else None,price,"tushare","a"*64,
                          None if price else "当日有效收盘价未就绪")


@pytest.mark.parametrize("holding_days", [(), (DAY,), (DAY-timedelta(days=7), DAY-timedelta(days=3))])
@pytest.mark.parametrize("superseded", [False, True])
def test_initialization_replay_range_is_derived_and_fixed(migrated, holding_days, superseded):
    execution = RecalculationExecution(TradingAssistantExecutionPolicyV1())
    with migrated.begin() as conn:
        account_id, initialization_id, _ = seed_account(conn)
        version = 2 if superseded else 1
        if superseded:
            conn.execute(insert(InitialPosition).values(account_id=account_id,
                initialization_id=initialization_id, ts_code="600000.SH", client_row_id="old",
                opened_on=DAY-timedelta(days=30), quantity=100, available_quantity=100, cost_price="10.00"))
            replacement_id = uuid4()
            conn.execute(insert(Initialization).values(initialization_id=replacement_id,
                account_id=account_id, revision=2, accepted_fact_version=2, initial_cash="100.00",
                created_at=AT, source_initialization_id=initialization_id))
            conn.execute(update(Account).where(Account.account_id == account_id).values(
                current_initialization_id=replacement_id, fact_version=2, calculation_target_version=2))
            initialization_id = replacement_id
        conn.execute(insert(Recalculation).values(account_id=account_id, target_version=version,
            affected_from_date=DAY, next_attempt_at=datetime.now(timezone.utc)-timedelta(days=1),
            fence=0, transient_failure_count=0, updated_at=datetime.now(timezone.utc)))
        for index, opened in enumerate(holding_days):
            conn.execute(insert(InitialPosition).values(account_id=account_id, initialization_id=initialization_id,
                ts_code=f"00000{index+1}.SZ", client_row_id=str(index), opened_on=opened,
                quantity=100, available_quantity=100, cost_price="10.00"))
    with Session(migrated) as session, session.begin():
        lease = execution.claim(session, executor_id="automatic-range", deadline=deadline())
        assert lease.account_id == account_id
    inputs = CalculationInputs(execution)
    expected_start = min((DAY, *holding_days))
    from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationDataUnavailable
    with pytest.raises(CalculationDataUnavailable):
        with Session(migrated) as session, session.begin():
            inputs.prepare_from_initialization(session, lease,
                through_date=expected_start-timedelta(days=1), rule_version=1, deadline=deadline())
    with pytest.raises(RuntimeError, match="rollback"):
        with Session(migrated) as session, session.begin():
            inputs.prepare_from_initialization(session, lease, through_date=DAY, rule_version=1, deadline=deadline())
            raise RuntimeError("rollback")
    with Session(migrated) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(CalculationGeneration).where(
            CalculationGeneration.account_id == account_id)) == 0
        identity = inputs.prepare_from_initialization(session, lease, through_date=DAY,
            rule_version=1, deadline=deadline())
    with Session(migrated) as session, session.begin():
        assert CalculationInputs(execution).prepare_from_initialization(session, lease,
            through_date=DAY, rule_version=1, deadline=deadline()) == identity
        generation = session.get(CalculationGeneration, identity)
        assert (generation.from_date, generation.through_date) == (expected_start, DAY)
        assert generation.initialization_id == initialization_id
        assert generation.fact_version == version
        assert session.get(Account, account_id).initialized_on == DAY  # No invented earlier cash.
    with pytest.raises(CalculationInputMismatch, match="fixed inputs"):
        with Session(migrated) as session, session.begin():
            inputs.prepare_from_initialization(session, lease, through_date=DAY+timedelta(days=1),
                rule_version=1, deadline=deadline())
    retire(migrated, lease)


def save(store, session, lease, generation, fee, facts, after=None):
    return store.save_valuation_page(session, lease, generation_id=generation, facts=facts,
        fee_version_id=fee, valuation_at=AT, after_stock=after, deadline=deadline())


def retire(engine, lease):
    with engine.begin() as conn:
        conn.execute(update(Recalculation).where(Recalculation.account_id==lease.account_id)
                     .values(next_attempt_at=datetime.now(timezone.utc)+timedelta(days=2)))


def test_freeze_idempotence_restart_readback_and_no_publication(migrated):
    store, lease, generation, fee = setup(migrated)
    with Session(migrated) as session, session.begin():
        assert store.prepare_generation(session, lease, from_date=DAY, through_date=DAY,
            rule_version=1, deadline=deadline()) == generation
        assert save(store,session,lease,generation,fee,(fact(),)) == {"afterStock":"000001.SZ"}
    # A new service/session resumes only the committed input state.
    resumed = CalculationInputs(RecalculationExecution(TradingAssistantExecutionPolicyV1()))
    with Session(migrated) as session, session.begin():
        save(resumed,session,lease,generation,fee,(fact(),))
        save(resumed,session,lease,generation,fee,(fact("600000.SH",None),),"000001.SZ")
    with Session(migrated) as session, session.begin():
        frozen = resumed.read_valuation_page(session,lease,generation_id=generation,
            trade_date=DAY,page_key="000001.SZ",deadline=deadline())
        assert frozen.facts==(fact(),) and frozen.fee_version_id==fee and frozen.after_stock is None
        missing = resumed.read_valuation_page(session,lease,generation_id=generation,
            trade_date=DAY,page_key="600000.SH",deadline=deadline())
        assert missing.facts==(fact("600000.SH",None),) and missing.after_stock=="000001.SZ"
    with Session(migrated) as session:
        rows = session.scalars(select(ValuationBasis).where(ValuationBasis.generation_id==generation)
                               .order_by(ValuationBasis.ts_code)).all()
        assert len(rows)==2 and rows[0].price==Decimal("10.1234")
        assert rows[0].fee_version_id==fee and rows[0].price_date==DAY
        assert rows[1].quality=="UNAVAILABLE" and rows[1].price is None
        assert session.scalar(select(func.count()).select_from(CalculationBatch)
                              .where(CalculationBatch.generation_id==generation))==2
        assert session.get(Account,lease.account_id).published_generation_id is None
        assert session.get(CalculationGeneration,generation).completed_trade_date_count==0
    with pytest.raises(CalculationInputMismatch):
        with Session(migrated) as session, session.begin():
            save(resumed,session,lease,generation,fee,(fact(price="10.9999"),))
    retire(migrated,lease)


def test_bad_cursor_fee_and_failure_preserve_previous_page(migrated):
    store, lease, generation, fee = setup(migrated)
    with Session(migrated) as session, session.begin():
        save(store,session,lease,generation,fee,(fact(),))
    with migrated.begin() as conn:
        _, _, other_fee = seed_account(conn)
    with pytest.raises(IntegrityError):
        with Session(migrated) as session, session.begin():
            save(store,session,lease,generation,other_fee,(fact("600000.SH"),),"000001.SZ")
    with pytest.raises(RuntimeError,match="process stopped"):
        with Session(migrated) as session, session.begin():
            save(store,session,lease,generation,fee,(fact("600000.SH"),),"000001.SZ")
            raise RuntimeError("process stopped before commit")
    for facts, cursor in [((fact("600000.SH"),),None), ((fact("600000.SH"),),"000002.SZ"),
                           ((fact("600000.SH"),fact()),"000001.SZ")]:
        with pytest.raises(CalculationInputMismatch):
            with Session(migrated) as session, session.begin():
                save(store,session,lease,generation,fee,facts,cursor)
    with Session(migrated) as session:
        assert session.scalar(select(func.count()).select_from(CalculationBatch)
                              .where(CalculationBatch.generation_id==generation))==1
        assert session.scalar(select(func.count()).select_from(ValuationBasis)
                              .where(ValuationBasis.generation_id==generation))==1
    with Session(migrated) as session, session.begin():
        save(store,session,lease,generation,fee,(fact("600000.SH"),),"000001.SZ")
    retire(migrated,lease)


def test_limits_stale_lease_and_frozen_generation(migrated):
    store, lease, generation, fee = setup(migrated)
    with pytest.raises(CalculationInputMismatch):
        with Session(migrated) as session, session.begin():
            store.prepare_generation(session,lease,from_date=date(2026,9,10),through_date=DAY,
                                     rule_version=1,deadline=deadline())
    for facts in [(fact(),)*501, (replace(fact(),source_version="x"*1048576),)]:
        with pytest.raises(ValueError):
            with Session(migrated) as session, session.begin():
                save(store,session,lease,generation,fee,facts)
    with migrated.begin() as conn:
        conn.execute(update(Recalculation).where(Recalculation.account_id==lease.account_id).values(fence=lease.fence+1))
    with pytest.raises(CalculationExecutionLost):
        with Session(migrated) as session, session.begin():
            save(store,session,lease,generation,fee,(fact(),))
    with Session(migrated) as session:
        assert session.scalar(select(func.count()).select_from(ValuationBasis)
                              .where(ValuationBasis.generation_id==generation))==0
    retire(migrated,lease)


def test_downgrade_refuses_existing_inputs(migrated):
    store,lease,generation,fee=setup(migrated)
    with Session(migrated) as session,session.begin():
        save(store,session,lease,generation,fee,(fact(),))
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260912_000173").module
    with pytest.raises(RuntimeError,match="must be retained"):
        with migrated.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
    retire(migrated,lease)


def test_corrupted_frozen_value_is_not_used(migrated):
    store,lease,generation,fee=setup(migrated)
    with Session(migrated) as session,session.begin():
        save(store,session,lease,generation,fee,(fact(),))
    with migrated.begin() as conn:
        conn.execute(update(ValuationBasis).where(ValuationBasis.generation_id==generation).values(price=Decimal("20")))
    with pytest.raises(CalculationInputMismatch,match="values changed"):
        with Session(migrated) as session,session.begin():
            store.read_valuation_page(session,lease,generation_id=generation,trade_date=DAY,
                                       page_key="000001.SZ",deadline=deadline())
    retire(migrated,lease)


@pytest.mark.parametrize("patch", [dict(price=None),dict(valuation_method=None),
    dict(price=Decimal("NaN")),dict(price_date=date(2026,9,10)),dict(quality="UNAVAILABLE")])
def test_database_rejects_inconsistent_valuation(migrated,patch):
    store,lease,generation,fee=setup(migrated)
    with Session(migrated) as session,session.begin():
        save(store,session,lease,generation,fee,(fact(),))
    with pytest.raises(IntegrityError):
        with migrated.begin() as conn:
            conn.execute(update(ValuationBasis).where(ValuationBasis.generation_id==generation).values(**patch))
    with Session(migrated) as session,session.begin():
        original=store.read_valuation_page(session,lease,generation_id=generation,trade_date=DAY,
            page_key="000001.SZ",deadline=deadline())
        assert original.facts==(fact(),)
    retire(migrated,lease)


def test_full_page_is_bounded_and_round_trips(migrated):
    store,lease,generation,fee=setup(migrated)
    facts=tuple(fact(f"{i:06}.SZ") for i in range(500))
    with Session(migrated) as session,session.begin():
        save(store,session,lease,generation,fee,facts)
    with Session(migrated) as session,session.begin():
        page=store.read_valuation_page(session,lease,generation_id=generation,trade_date=DAY,
                                       page_key="000499.SZ",deadline=deadline())
        assert page.facts==facts
        batch=session.get(CalculationBatch,(lease.account_id,generation,DAY,"VALUATION","","000499.SZ"))
        assert batch.row_count==500 and batch.accumulator=={"stockCount":500}
    retire(migrated,lease)


def test_process_exit_rolls_back_only_uncommitted_page(migrated):
    store,lease,generation,fee=setup(migrated)
    with Session(migrated) as session,session.begin():
        save(store,session,lease,generation,fee,(fact(),))
    assert migrated.url.host=="127.0.0.1"
    worker=textwrap.dedent('''
        import json,os,sys
        from uuid import UUID
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from tests.test_wealth_trading_assistant_calculation_inputs import save,fact
        from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputs
        from src.biz.services.wealth.market.trading_assistant.recalculation_execution import CalculationLease,RecalculationExecution
        from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
        args=json.loads(sys.argv[1])
        engine=create_engine(args['url'])
        assert engine.url.host=='127.0.0.1'
        lease=CalculationLease(UUID(args['account']),1,'freeze',args['fence'])
        store=CalculationInputs(RecalculationExecution(TradingAssistantExecutionPolicyV1()))
        with Session(engine) as session,session.begin():
            save(store,session,lease,UUID(args['generation']),UUID(args['fee']),(fact('600000.SH'),),'000001.SZ')
            if args['crash']: os._exit(27)
        engine.dispose()
    ''')
    args=dict(url=migrated.url.render_as_string(hide_password=False),account=str(lease.account_id),
              generation=str(generation),fee=str(fee),fence=lease.fence)
    for crash,expected_count in [(True,1),(False,2),(False,2)]:
        result=subprocess.run([sys.executable,"-c",worker,json.dumps(dict(args,crash=crash))],
                              capture_output=True,text=True,timeout=10)
        assert result.returncode==(27 if crash else 0),result.stderr
        with Session(migrated) as session:
            assert session.scalar(select(func.count()).select_from(CalculationBatch)
                                  .where(CalculationBatch.generation_id==generation))==expected_count
            assert session.scalar(select(func.count()).select_from(ValuationBasis)
                                  .where(ValuationBasis.generation_id==generation))==expected_count
    retire(migrated,lease)
