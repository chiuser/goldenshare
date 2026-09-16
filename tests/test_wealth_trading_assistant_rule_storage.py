"""Rule row constraints in a new isolated PostgreSQL, never production."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion, RuleExecution, RobotIdentity
from src.biz.models.wealth.trading_assistant.rule_checks import (
    RuleMarketBasis, RuleCheck, RuleCheckProgress, RuleResult, RuleResultCheck,
)

NOW = datetime(2026, 9, 15, 10, tzinfo=timezone(timedelta(hours=8)))


@pytest.fixture(scope="module")
def rule_database(database):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    with database.begin() as conn:
        previous = "20260912_000172"
        with Operations.context(MigrationContext.configure(conn)):
            for revision in ("20260912_000173", "20260912_000174", "20260912_000175",
                             "20260912_000176", "20260915_000177"):
                migration = scripts.get_revision(revision).module
                assert migration.down_revision == previous
                migration.upgrade()
                previous = revision
    return database


def seed_rule(conn, *, owner=1, kind="PLAN", account=None, version_overrides=None):
    if kind == "PLAN" and account is None:
        account, _, _ = seed_account(conn)
    rule_id, version_id = uuid4(), uuid4()
    conn.execute(insert(Rule).values(rule_id=rule_id, owner_user_id=owner, kind=kind,
        account_id=account, current_version_id=version_id, state="ACTIVE", state_version=1,
        created_at=NOW, last_check_no=0))
    values = dict(rule_version_id=version_id, owner_user_id=owner, rule_id=rule_id,
        version_no=1, effective_at=NOW, deadline_at=NOW + timedelta(hours=5),
        stock_code="000001.SZ", stock_name_at_save="平安银行", source="TRADING_ASSISTANT",
        direction=None if kind == "ALERT" else "BUY", price_operator="LTE", price_upper="10.00",
        notify_enabled=False)
    values.update(version_overrides or {})
    conn.execute(insert(RuleVersion).values(**values))
    return rule_id, version_id


def test_rule_version_cycle_is_atomic_and_subsecond_time_is_exact(rule_database):
    moment = NOW.replace(microsecond=123456)
    with rule_database.begin() as conn:
        rule_id, version_id = seed_rule(conn, version_overrides={"effective_at": moment})
    with rule_database.connect() as conn:
        assert conn.scalar(select(RuleVersion.effective_at).where(
            RuleVersion.rule_version_id == version_id)) == moment
        assert conn.scalar(select(Rule.current_version_id).where(Rule.rule_id == rule_id)) == version_id


@pytest.mark.parametrize("changes", [
    {"price_operator": None}, {"price_operator": "LTE", "price_lower": "9.00"},
    {"price_operator": "GTE"}, {"price_operator": "BETWEEN", "price_lower": "11.00"},
    {"price_upper": None}, {"price_upper": "NaN"}, {"price_upper": "Infinity"},
    {"price_upper": "-1.00"}, {"price_upper": "10.001"},
    {"volume_operator": "GTE"}, {"volume_threshold_lots": "1.00"},
    {"volume_operator": "GT", "volume_threshold_lots": "1.00"},
    {"notify_enabled": True}, {"deadline_at": NOW},
])
def test_incomplete_or_invalid_conditions_are_rejected(rule_database, changes):
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        seed_rule(conn, version_overrides=changes)


def test_plan_cannot_reference_another_users_account(rule_database):
    with rule_database.begin() as conn:
        account, _, _ = seed_account(conn)
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        seed_rule(conn, owner=2, kind="PLAN", account=account)


def test_current_version_cannot_point_to_another_rule(rule_database):
    with rule_database.begin() as conn:
        first, first_version = seed_rule(conn)
        second, second_version = seed_rule(conn)
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        conn.execute(Rule.__table__.update().where(Rule.rule_id == first).values(current_version_id=second_version))


def test_result_is_unique_and_cannot_reference_other_rules_version(rule_database):
    with rule_database.begin() as conn:
        first, version = seed_rule(conn)
        second, other_version = seed_rule(conn)
    values = dict(owner_user_id=1, rule_id=first, triggered=True,
        decided_at=NOW + timedelta(hours=6), trigger_version_id=version,
        first_match_at=NOW + timedelta(minutes=1), actual_price="9.00", price_satisfied=True)
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        conn.execute(insert(RuleResult).values(**(values | {
            "result_id": uuid4(), "trigger_version_id": other_version})))
    with rule_database.begin() as conn:
        conn.execute(insert(RuleResult).values(**values, result_id=uuid4()))
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        conn.execute(insert(RuleResult).values(**values, result_id=uuid4()))


@pytest.mark.parametrize("state", ["ENDED", "CLOSED", "UNKNOWN"])
def test_state_cannot_be_changed_without_its_required_evidence(rule_database, state):
    with rule_database.begin() as conn:
        rule, _ = seed_rule(conn)
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        conn.execute(Rule.__table__.update().where(Rule.rule_id == rule).values(state=state))


def seed_check(conn, rule, version):
    basis, check = uuid4(), uuid4()
    material = [{"at": "2026-09-15T10:01:00+08:00", "price": "9.123456789", "volumeShares": "100"}]
    conn.execute(insert(RuleMarketBasis).values(market_basis_id=basis, owner_user_id=1,
        rule_id=rule, stock_code="000001.SZ", trade_date=NOW.date(), source="isolated-test",
        source_version="test-1", price_basis="QFQ", time_label_version="test-1", volume_unit="SHARE",
        session_evidence={"source": "explicit-test"}, coverage={}, observed_at=NOW,
        material=material))
    conn.execute(insert(RuleCheck).values(check_id=check, owner_user_id=1, rule_id=rule,
        rule_version_id=version, check_no=1, trade_date=NOW.date(), requested_from=NOW,
        requested_through=NOW + timedelta(minutes=1), started_at=NOW, status="CHECKING",
        missing_ranges=[], market_basis_id=basis, evaluator_version="test-1", execution_fence=1))
    return basis, check, material


def test_frozen_material_is_readable_and_progress_cannot_mix_bases(rule_database):
    with rule_database.begin() as conn:
        rule, version = seed_rule(conn)
        basis, check, material = seed_check(conn, rule, version)
        other, other_version = seed_rule(conn)
        other_basis, _, _ = seed_check(conn, other, other_version)
    with rule_database.connect() as conn:
        assert conn.scalar(select(RuleMarketBasis.material).where(
            RuleMarketBasis.market_basis_id == basis)) == material
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        conn.execute(insert(RuleCheckProgress).values(check_id=check, market_basis_id=other_basis,
            cursor={}, cumulative_volume_shares=0, processed_rows=0, updated_at=NOW))


def test_result_evidence_cannot_reference_a_different_rules_check(rule_database):
    with rule_database.begin() as conn:
        rule, version = seed_rule(conn)
        _, check, _ = seed_check(conn, rule, version)
        other, other_version = seed_rule(conn)
        _, other_check, _ = seed_check(conn, other, other_version)
        result = uuid4()
        conn.execute(insert(RuleResult).values(result_id=result, owner_user_id=1, rule_id=rule,
            triggered=False, decided_at=NOW + timedelta(hours=6)))
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        conn.execute(insert(RuleResultCheck).values(result_id=result, check_id=other_check,
            owner_user_id=1, rule_id=rule))


@pytest.mark.parametrize("changes", [
    {"actual_price": "NaN"}, {"actual_price": "Infinity"}, {"actual_price": None},
    {"price_satisfied": False}, {"price_satisfied": None},
    {"volume_satisfied": True}, {"cumulative_volume_shares": "1.5", "volume_satisfied": True},
])
def test_trigger_requires_finite_matching_values(rule_database, changes):
    with rule_database.begin() as conn:
        rule, version = seed_rule(conn)
    values = dict(result_id=uuid4(), owner_user_id=1, rule_id=rule, triggered=True,
        decided_at=NOW + timedelta(hours=6), trigger_version_id=version,
        first_match_at=NOW + timedelta(minutes=1), actual_price="9.00", price_satisfied=True)
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        conn.execute(insert(RuleResult).values(**(values | changes)))


def test_robot_identity_is_owner_bound_but_does_not_grant_qualification(rule_database):
    robot = uuid4()
    with rule_database.begin() as conn:
        conn.execute(insert(RobotIdentity).values(robot_id=robot, owner_user_id=2))
    with pytest.raises(IntegrityError), rule_database.begin() as conn:
        seed_rule(conn, version_overrides={"notify_enabled": True, "robot_id": robot})
    with rule_database.connect() as conn:
        assert conn.scalar(select(RobotIdentity.current_config_id).where(
            RobotIdentity.robot_id == robot)) is None


def test_migration_downgrade_does_not_delete_rule_history():
    module = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260915_000177").module
    assert module.down_revision == "20260912_000176"
    with pytest.raises(RuntimeError, match="must not be dropped"):
        module.downgrade()
