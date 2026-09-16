"""M7 physical evidence in this test's new PostgreSQL cluster only."""
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import insert, select, update, inspect
from sqlalchemy.exc import IntegrityError

from tests.test_wealth_trading_assistant_persistence import database
from tests.test_wealth_trading_assistant_rule_storage import rule_database, NOW
from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from src.biz.models.wealth.trading_assistant.robots import CredentialBlob, RobotCandidate, RobotTest, RobotConfig
from src.biz.services.wealth.market.trading_assistant.credential_cipher import CredentialCipher, CredentialEnvelope, CredentialError

CIPHER = CredentialCipher("test", {"test": bytes(range(32))})
SECRET = b'{"webhook":"https://open.feishu.cn/open-apis/bot/v2/hook/isolated","signingSecret":null}'


@pytest.fixture(scope="module")
def robot_database(rule_database):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    module = scripts.get_revision("20260916_000178").module
    assert module.down_revision == "20260915_000177"
    with rule_database.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        module.upgrade()
        scripts.get_revision("20260916_000179").module.upgrade()
        scripts.get_revision("20260916_000180").module.upgrade()
    return rule_database


def blob(conn, owner, kind, object_id, **patch):
    envelope = CIPHER.encrypt(owner, kind, object_id, SECRET)
    values = dict(blob_id=uuid4(), owner_user_id=owner, object_type=kind, object_id=object_id,
                  key_id=envelope.key_id, nonce=envelope.nonce, ciphertext=envelope.ciphertext,
                  algorithm_version=envelope.algorithm_version, created_at=NOW)
    values.update(patch)
    conn.execute(insert(CredentialBlob).values(**values))
    return values


def candidate(conn, *, owner=1, **patch):
    robot_id = conn.scalar(select(RobotIdentity.robot_id).where(RobotIdentity.owner_user_id == owner))
    if robot_id is None:
        robot_id = uuid4()
        conn.execute(insert(RobotIdentity).values(robot_id=robot_id, owner_user_id=owner))
    candidate_id = uuid4()
    credential = blob(conn, owner, "CANDIDATE", candidate_id)
    values = dict(candidate_id=candidate_id, owner_user_id=owner, robot_id=robot_id,
                  candidate_version=1, expected_config_id=None, name="测试机器人", keywords=[],
                  content_digest="a" * 64, credential_blob_id=credential["blob_id"], created_at=NOW)
    values.update(patch)
    conn.execute(insert(RobotCandidate).values(**values))
    return values


def test_row(conn, c, state="SUCCEEDED", **patch):
    values = dict(test_id=uuid4(), owner_user_id=c["owner_user_id"], robot_id=c["robot_id"],
                  candidate_id=c["candidate_id"], attempt_no=1, state=state, started_at=NOW,
                  completed_at=None if state == "IN_FLIGHT" else NOW + timedelta(seconds=1), reason=None)
    values.update(patch)
    conn.execute(insert(RobotTest).values(**values))
    return values


test_row.__test__ = False


def config(conn, c, t, **patch):
    config_id = uuid4()
    credential = blob(conn, c["owner_user_id"], "CONFIG", config_id)
    values = dict(config_id=config_id, owner_user_id=c["owner_user_id"], robot_id=c["robot_id"],
                  candidate_id=c["candidate_id"], test_id=t["test_id"], name=c["name"],
                  keywords=c["keywords"], credential_blob_id=credential["blob_id"],
                  confirmed_at=NOW + timedelta(seconds=2))
    values.update(patch)
    conn.execute(insert(RobotConfig).values(**values))
    return values


def test_roundtrip_ciphertext_and_atomic_activation(robot_database):
    with robot_database.begin() as conn:
        c = candidate(conn)
        t = test_row(conn, c)
        saved = config(conn, c, t)
        conn.execute(update(RobotIdentity).where(RobotIdentity.robot_id == c["robot_id"]).values(
            current_config_id=saved["config_id"]))
    with robot_database.connect() as conn:
        row = conn.execute(select(CredentialBlob).where(CredentialBlob.blob_id == saved["credential_blob_id"])).mappings().one()
        envelope = CredentialEnvelope(row["key_id"], row["nonce"], row["ciphertext"], row["algorithm_version"])
        assert SECRET not in row["ciphertext"]
        assert CIPHER.decrypt(1, "CONFIG", saved["config_id"], envelope) == SECRET
        with pytest.raises(CredentialError):
            CIPHER.decrypt(1, "CANDIDATE", c["candidate_id"], envelope)


@pytest.mark.parametrize("state", ["IN_FLIGHT", "FAILED", "UNKNOWN"])
def test_only_explicit_success_can_back_config(robot_database, state):
    with robot_database.begin() as conn:
        c = candidate(conn)
        t = test_row(conn, c, state)
    with pytest.raises(IntegrityError), robot_database.begin() as conn:
        config(conn, c, t)


def test_wrong_candidate_and_other_owner_test_cannot_activate(robot_database):
    with robot_database.begin() as conn:
        c = candidate(conn)
        other = candidate(conn)
        foreign = candidate(conn, owner=2)
        tests = [test_row(conn, other), test_row(conn, foreign)]
    for t in tests:
        with pytest.raises(IntegrityError), robot_database.begin() as conn:
            config(conn, c, t)


def test_same_key_nonce_is_unique_across_object_kinds(robot_database):
    with robot_database.begin() as conn:
        first = blob(conn, 1, "CANDIDATE", uuid4())
    with pytest.raises(IntegrityError), robot_database.begin() as conn:
        blob(conn, 2, "CONFIG", uuid4(), nonce=first["nonce"])


@pytest.mark.parametrize("patch", [{"nonce": b"short"}, {"ciphertext": b"short"},
    {"algorithm_version": "PLAIN"}, {"object_type": "OTHER"}])
def test_malformed_envelope_rejected(robot_database, patch):
    with pytest.raises(IntegrityError), robot_database.begin() as conn:
        blob(conn, 1, "CANDIDATE", uuid4(), **patch)


def test_candidate_cannot_borrow_credentials(robot_database):
    with robot_database.begin() as conn:
        foreign = blob(conn, 2, "CANDIDATE", uuid4())
        same_owner_other = blob(conn, 1, "CANDIDATE", uuid4())
    for borrowed in (foreign, same_owner_other):
        with pytest.raises(IntegrityError), robot_database.begin() as conn:
            candidate(conn, credential_blob_id=borrowed["blob_id"])


def test_one_inflight_test_and_unique_attempt_number(robot_database):
    with robot_database.begin() as conn:
        c = candidate(conn)
        test_row(conn, c, "IN_FLIGHT")
    for number, state in [(2, "IN_FLIGHT"), (1, "FAILED")]:
        with pytest.raises(IntegrityError), robot_database.begin() as conn:
            test_row(conn, c, state, attempt_no=number)


@pytest.mark.parametrize("count", [0, 10, 11])
def test_keyword_capacity_is_enforced_in_storage(robot_database, count):
    if count <= 10:
        with robot_database.begin() as conn:
            c = candidate(conn, keywords=[f"词{i}" for i in range(count)])
            config(conn, c, test_row(conn, c))
    else:
        with pytest.raises(IntegrityError), robot_database.begin() as conn:
            candidate(conn, keywords=["词"] * count)


def test_activation_cannot_repeat_or_point_to_foreign_config(robot_database):
    with robot_database.begin() as conn:
        c = candidate(conn, owner=2)
        t = test_row(conn, c)
        saved = config(conn, c, t)
    with pytest.raises(IntegrityError), robot_database.begin() as conn:
        config(conn, c, t)
    with pytest.raises(IntegrityError), robot_database.begin() as conn:
        conn.execute(update(RobotIdentity).where(RobotIdentity.owner_user_id == 1).values(current_config_id=saved["config_id"]))


def test_migration_retains_evidence():
    module = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20260916_000178").module
    with pytest.raises(RuntimeError, match="must not be dropped"):
        module.downgrade()


def test_frozen_migration_matches_models_and_preserves_atomic_pointer(robot_database):
    with robot_database.connect() as conn:
        inspector = inspect(conn)
        for model in (CredentialBlob, RobotCandidate, RobotTest, RobotConfig):
            actual = {c["name"]: c["nullable"] for c in inspector.get_columns(model.__tablename__, schema="app")}
            assert actual == {c.name: c.nullable for c in model.__table__.columns}
        old = conn.scalar(select(RobotIdentity.current_config_id).where(RobotIdentity.owner_user_id == 1))
    with pytest.raises(RuntimeError, match="after pointer"), robot_database.begin() as conn:
        c = candidate(conn)
        saved = config(conn, c, test_row(conn, c))
        conn.execute(update(RobotIdentity).where(RobotIdentity.owner_user_id == 1).values(current_config_id=saved["config_id"]))
        raise RuntimeError("after pointer")
    with robot_database.connect() as conn:
        assert conn.scalar(select(RobotIdentity.current_config_id).where(RobotIdentity.owner_user_id == 1)) == old
        assert conn.scalar(select(RobotConfig.config_id).where(RobotConfig.config_id == saved["config_id"])) is None
