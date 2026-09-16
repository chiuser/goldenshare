"""Command → retained source → bounded worker → atomic result → real query.

Only newly created PostgreSQL and temporary Parquet are written. No production
source, account result or final rule result is inserted by this fixture.
"""
import asyncio
from datetime import timedelta
from uuid import UUID, uuid4
import pytest

from sqlalchemy import insert, select, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from tests.test_wealth_trading_assistant_rule_storage import rule_database
from tests.test_wealth_trading_assistant_rule_commands import command_database, NOW, plan
from tests.wealth_trading_assistant_fixture_support import fixed_fixture_clock
from tests.test_stock_mins_reader import _write_bars
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.clients.local_lake.stock_rule_minute_reader import StockRuleMinuteReader
from src.app.runtime.trading_assistant_container import build_trading_assistant_dependencies
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion, RuleExecution, RobotIdentity
from src.biz.schemas.wealth.market.trading_assistant.rules import ReviseConditionsCommand, CloseRuleCommand, CreateAlertCommand
from tests.test_wealth_trading_assistant_rule_commands import identity
from types import SimpleNamespace
from src.biz.models.wealth.trading_assistant.rule_checks import RuleResult, RuleCheck, RuleMarketBasis, RuleResultCheck
from src.biz.models.wealth.trading_assistant.rule_notifications import TriggerNotification
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.biz.services.wealth.market.trading_assistant.rule_calendar import session_minutes
from src.biz.services.wealth.market.trading_assistant.rule_work import RuleWork
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


@pytest.mark.parametrize("day_offset,is_open", [(3, True), (4, False)])
def test_explicit_full_halt_or_closed_calendar_completes_without_minute_source(command_database, day_offset, is_open):
    moment = NOW + timedelta(days=day_offset)
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=moment.date(),
            is_open=is_open, pretrade_date=NOW.date()))
        if is_open:
            conn.execute(insert(EquitySuspendD).values(row_key_hash=str(uuid4()), ts_code="000001.SZ",
                trade_date=moment.date(), suspend_type="S", suspend_timing=None))
    policy = TradingAssistantExecutionPolicyV1()
    async def create():
        engine = create_async_engine(command_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=policy, now=lambda: moment,
            executor_id="empty-check")
        # Future-checkpoint qualification is separate from this test's
        # completed source coverage; creation can precede a suspension fact.
        deps.rules.has_future_checkpoint = lambda *args: True
        try:
            return await deps.rules.create(owner_id=1, kind="PLAN", command=plan(account,
                deadlineAt=moment.replace(hour=15).isoformat()))
        finally:
            await engine.dispose()
    saved = asyncio.run(create())
    assert saved.status == "SAVED"
    rule_id = UUID(saved.receipt["result"]["ruleId"])
    class NoMinuteRead:
        def read_day(self, **kwargs):
            raise AssertionError("An explicitly empty session must not query minutes")
    sessions = sessionmaker(command_database, expire_on_commit=False)
    with fixed_fixture_clock(command_database, [moment.replace(hour=16)]):
        stages = [RuleWork(policy, sessions, minute_reader=NoMinuteRead()).run_once(executor_id="empty-check") for _ in range(3)]
        assert stages == ["PREPARED", "COMPLETED", "PUBLISHED"]
    with Session(command_database) as session:
        result = session.scalar(select(RuleResult).where(RuleResult.rule_id == rule_id))
        assert result.triggered is False
        basis = session.scalar(select(RuleMarketBasis).where(RuleMarketBasis.rule_id == rule_id))
        assert basis.material == [] and basis.coverage["required"] == []


def bars(root, *, missing=None, price=9):
    rows = [("000001.SZ", 1, NOW.date(), m.at.replace(tzinfo=None).isoformat(),
        price, price, price, price, 100, 900, "SZSE") for m in session_minutes(NOW.date()) if m.at != missing]
    target = root / "gold/quote/stk_mins_qfq/freq=1/ts_code=000001.SZ/year=2026/part-000.parquet"
    if target.exists():
        candidate = _write_bars(root / str(uuid4()), code="000001.SZ", freq=1, rows=rows)
        candidate.replace(target)
        return target
    return _write_bars(root, code="000001.SZ", freq=1, rows=rows)


def test_after_close_revision_revisits_the_new_same_day_segment(command_database, tmp_path):
    day = NOW.date() + timedelta(days=1)
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
        conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=day,
            is_open=True, pretrade_date=NOW.date()))
    clock = [NOW.replace(hour=16)]
    policy = TradingAssistantExecutionPolicyV1()
    async def save(rule_id=None):
        engine = create_async_engine(command_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=policy, now=lambda: clock[0], executor_id="after-close")
        try:
            if rule_id is None:
                return await deps.rules.create(owner_id=1, kind="PLAN", command=plan(account,
                    deadlineAt=(NOW + timedelta(days=1)).replace(hour=15).isoformat()))
            return await deps.rules.revise(owner_id=1, kind="PLAN", rule_id=rule_id,
                command=ReviseConditionsCommand(**identity(), expectedStateVersion="1",
                    priceCondition={"operator":"GTE", "lower":"20.00"}, volumeCondition=None))
        finally:
            await engine.dispose()
    created = asyncio.run(save())
    assert created.status == "SAVED"
    rule_id = UUID(created.receipt["result"]["ruleId"])
    sessions = sessionmaker(command_database, expire_on_commit=False)
    reader = StockRuleMinuteReader(tmp_path)
    rows = [("000001.SZ", 1, day, m.at.replace(tzinfo=None).isoformat(), 9, 9, 9, 9, 100, 900, "SZSE")
        for m in session_minutes(day)]
    _write_bars(tmp_path, code="000001.SZ", freq=1, rows=rows)
    with fixed_fixture_clock(command_database, clock):
        for expected in ("PREPARED", "COMPLETED", "ADVANCED"):
            assert RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="before-revision") == expected
        with Session(command_database) as session:
            assert session.get(RuleExecution, rule_id).next_trade_date == day
        clock[0] += timedelta(minutes=1)
        assert asyncio.run(save(rule_id)).status == "SAVED"
        with Session(command_database) as session:
            assert session.get(RuleExecution, rule_id).next_trade_date == NOW.date()
        clock[0] = clock[0] + timedelta(days=1)
        stages = []
        for _ in range(16):
            stages.append(RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="after-revision"))
            with Session(command_database) as session:
                result = session.scalar(select(RuleResult).where(RuleResult.rule_id == rule_id))
                if result is not None:
                    assert result.triggered is False
                    break
        else:
            pytest.fail(str(stages))


@pytest.fixture(scope="module", autouse=True)
def calendar(command_database):
    with command_database.begin() as conn:
        conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=NOW.date(),
            is_open=True, pretrade_date=NOW.date() - timedelta(days=1)))


def test_real_frozen_source_publish_true_false_and_no_recheck(command_database, tmp_path):
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
    policy = TradingAssistantExecutionPolicyV1()
    async def create():
        engine = create_async_engine(command_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=policy, now=lambda: NOW, executor_id="rule-setup")
        try:
            hit = await deps.rules.create(owner_id=1, kind="PLAN", command=plan(account))
            miss = await deps.rules.create(owner_id=1, kind="PLAN", command=plan(account,
                priceCondition={"operator": "GTE", "lower": "20.00"}))
            assert hit.status == miss.status == "SAVED"
            return [UUID(x.receipt["result"]["ruleId"]) for x in (hit, miss)]
        finally:
            await engine.dispose()
    hit_id, miss_id = asyncio.run(create())
    bars(tmp_path)
    clock = [NOW + timedelta(hours=6)]
    sessions = sessionmaker(command_database, expire_on_commit=False)
    reader = StockRuleMinuteReader(tmp_path)
    stages = []
    with fixed_fixture_clock(command_database, clock):
        for _ in range(12):
            stage = RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="test-worker")
            stages.append(stage)
            with Session(command_database) as session:
                states = session.scalars(select(Rule.state).where(Rule.rule_id.in_([hit_id, miss_id]))).all()
            if states == ["ENDED", "ENDED"]:
                break
        assert states == ["ENDED", "ENDED"], stages
        assert "PREPARED" in stages and "PUBLISHED" in stages
        with Session(command_database) as session:
            hit = session.scalar(select(RuleResult).where(RuleResult.rule_id == hit_id))
            miss = session.scalar(select(RuleResult).where(RuleResult.rule_id == miss_id))
            assert hit.triggered and hit.first_match_at == NOW + timedelta(minutes=1)
            assert hit.actual_price == 9 and not miss.triggered
            assert session.scalar(select(func.count()).select_from(RuleResultCheck)
                .where(RuleResultCheck.rule_id.in_([hit_id, miss_id]))) == 2
            assert session.scalar(select(func.count()).select_from(TriggerNotification)) == 0
            assert session.scalar(select(func.count()).select_from(Ledger)) == 0
            check_count = session.scalar(select(func.count()).select_from(RuleCheck))
            basis_count = session.scalar(select(func.count()).select_from(RuleMarketBasis))
        # A later price change does not wake an ended rule or alter its result.
        bars(tmp_path, price=21)
        assert RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="restarted") == "IDLE"
        with Session(command_database) as session:
            assert session.scalar(select(func.count()).select_from(RuleCheck)) == check_count
            assert session.scalar(select(func.count()).select_from(RuleMarketBasis)) == basis_count
            assert session.scalar(select(RuleResult.actual_price).where(RuleResult.rule_id == hit_id)) == 9


def test_missing_prefix_waits_then_restarts_from_new_immutable_basis(command_database, tmp_path):
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
    async def create():
        engine = create_async_engine(command_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(), now=lambda: NOW, executor_id="missing-setup")
        try:
            result = await deps.rules.create(owner_id=1, kind="PLAN", command=plan(account,
                priceCondition=None, volumeCondition={"operator": "GTE", "thresholdLots": "1.00"}))
            assert result.status == "SAVED"
            return UUID(result.receipt["result"]["ruleId"])
        finally:
            await engine.dispose()
    rule_id = asyncio.run(create())
    bars(tmp_path, missing=NOW.replace(hour=9, minute=31))
    clock = [NOW + timedelta(hours=6)]
    policy = TradingAssistantExecutionPolicyV1()
    sessions = sessionmaker(command_database, expire_on_commit=False)
    reader = StockRuleMinuteReader(tmp_path)
    with fixed_fixture_clock(command_database, clock):
        assert RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="first") == "PREPARED"
        assert RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="restart") == "WAITING_DATA"
        with Session(command_database) as session:
            assert session.get(Rule, rule_id).result_id is None
        bars(tmp_path)
        clock[0] += timedelta(seconds=61)
        assert RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="retry") == "PREPARED"
        assert RuleWork(policy, sessions, minute_reader=reader).run_once(executor_id="restart") == "PUBLISHED"
        with Session(command_database) as session:
            result = session.scalar(select(RuleResult).where(RuleResult.rule_id == rule_id))
            assert result.cumulative_volume_shares == 3200  # Includes auction and pre-effective minutes.
            assert session.scalar(select(func.count()).select_from(RuleMarketBasis).where(RuleMarketBasis.rule_id == rule_id)) == 2


def test_old_version_can_win_after_revision_and_result_prevents_late_close(command_database, tmp_path):
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
    clock = [NOW]
    async def command(action, rule_id=None):
        engine = create_async_engine(command_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(), now=lambda: clock[0], executor_id="version-test")
        try:
            if action == "create":
                return await deps.rules.create(owner_id=1, kind="PLAN", command=plan(account))
            if action == "revise":
                return await deps.rules.revise(owner_id=1, kind="PLAN", rule_id=rule_id,
                    command=ReviseConditionsCommand(**identity(), expectedStateVersion="1", priceCondition={"operator":"GTE","lower":"20.00"}, volumeCondition=None))
            return await deps.rules.close(owner_id=1, kind="PLAN", rule_id=rule_id,
                command=CloseRuleCommand(**identity(), expectedStateVersion="2"))
        finally:
            await engine.dispose()
    created = asyncio.run(command("create")); rule_id = UUID(created.receipt["result"]["ruleId"])
    original = UUID(created.receipt["result"]["ruleVersionId"])
    clock[0] += timedelta(hours=1)
    assert asyncio.run(command("revise", rule_id)).status == "SAVED"
    bars(tmp_path); clock[0] = NOW + timedelta(hours=6)
    with fixed_fixture_clock(command_database, clock):
        for _ in range(6):
            stage = RuleWork(TradingAssistantExecutionPolicyV1(), sessionmaker(command_database), minute_reader=StockRuleMinuteReader(tmp_path)).run_once(executor_id="old-version-worker")
            if stage == "PUBLISHED": break
        assert stage == "PUBLISHED"
        with Session(command_database) as session:
            result = session.scalar(select(RuleResult).where(RuleResult.rule_id == rule_id))
            assert result.trigger_version_id == original and result.first_match_at == NOW + timedelta(minutes=1)
        assert asyncio.run(command("close", rule_id)).status == "NOT_SAVED"
        with Session(command_database) as session:
            assert session.get(Rule, rule_id).state == "ENDED"


def test_close_during_source_read_discards_late_evidence_and_result(command_database, tmp_path):
    with command_database.begin() as conn:
        account, _, _ = seed_account(conn)
    clock = [NOW]
    async def command(rule_id=None):
        engine = create_async_engine(command_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(), now=lambda: clock[0], executor_id="close-race")
        try:
            if rule_id is None:
                return await deps.rules.create(owner_id=1, kind="PLAN", command=plan(account))
            return await deps.rules.close(owner_id=1, kind="PLAN", rule_id=rule_id,
                command=CloseRuleCommand(**identity(), expectedStateVersion="1"))
        finally:
            await engine.dispose()
    saved = asyncio.run(command()); rule_id = UUID(saved.receipt["result"]["ruleId"])
    bars(tmp_path); clock[0] += timedelta(hours=6)
    class ClosingReader:
        def read_day(self, **kwargs):
            material = StockRuleMinuteReader(tmp_path).read_day(**kwargs)
            assert asyncio.run(command(rule_id)).status == "SAVED"
            return material
    with fixed_fixture_clock(command_database, clock):
        assert RuleWork(TradingAssistantExecutionPolicyV1(), sessionmaker(command_database), minute_reader=ClosingReader()).run_once(executor_id="late-reader") == "SUPERSEDED"
    with Session(command_database) as session:
        assert session.get(Rule, rule_id).state == "CLOSED"
        for model in (RuleCheck, RuleMarketBasis, RuleResult, TriggerNotification):
            assert session.scalar(select(func.count()).select_from(model).where(model.rule_id == rule_id)) == 0


def test_alert_requires_qualified_robot_and_publishes_only_one_notification_intent(command_database, tmp_path):
    robot_id = uuid4()
    with command_database.begin() as conn:
        conn.execute(insert(RobotIdentity).values(robot_id=robot_id, owner_user_id=1))
    class QualifiedFixtureRobot:
        def resolve(self, session, owner_id, requested_id, deadline):
            return SimpleNamespace(name="隔离资格样本") if owner_id == 1 and requested_id == robot_id else None
        def names(self, session, *, owner_id, robot_ids, deadline):
            return {robot_id:"隔离资格样本"} if owner_id == 1 else {}
    async def create():
        engine = create_async_engine(command_database.url)
        deps = build_trading_assistant_dependencies(engine, policy=TradingAssistantExecutionPolicyV1(), now=lambda: NOW,
            executor_id="alert-setup", rule_robots=QualifiedFixtureRobot())
        try:
            result = await deps.rules.create(owner_id=1, kind="ALERT", command=CreateAlertCommand(**identity(), stockCode="000001.SZ",
                deadlineAt="2026-09-15T15:00:00+08:00", source="TRADING_ASSISTANT", robotId=str(robot_id),
                priceCondition={"operator":"LTE","upper":"10.00"}, volumeCondition=None))
            assert result.status == "SAVED"
            return UUID(result.receipt["result"]["ruleId"])
        finally:
            await engine.dispose()
    rule_id = asyncio.run(create()); bars(tmp_path)
    with fixed_fixture_clock(command_database, [NOW + timedelta(hours=6)]):
        for _ in range(5):
            RuleWork(TradingAssistantExecutionPolicyV1(), sessionmaker(command_database), minute_reader=StockRuleMinuteReader(tmp_path)).run_once(executor_id="alert-worker")
    with Session(command_database) as session:
        result = session.scalar(select(RuleResult).where(RuleResult.rule_id == rule_id))
        notices = session.scalars(select(TriggerNotification).where(TriggerNotification.rule_id == rule_id)).all()
        assert result.triggered and len(notices) == 1
        assert notices[0].trigger_id == result.result_id and notices[0].state == "PENDING"
        assert notices[0].robot_id == robot_id and notices[0].latest_attempt_id is None
