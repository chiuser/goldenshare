"""Private configuration store against real isolated PostgreSQL; no webhook IO."""
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database
from tests.test_wealth_trading_assistant_rule_storage import rule_database, NOW
from tests.test_wealth_trading_assistant_robot_storage import robot_database, CIPHER, test_row
from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from src.biz.models.wealth.trading_assistant.robots import CredentialBlob, RobotCandidate, RobotConfig, RobotTest
from src.biz.schemas.wealth.market.trading_assistant.robot import CandidateInput, ConfirmCandidateInput
from src.biz.services.wealth.market.trading_assistant.credential_cipher import CredentialError
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.robot_configuration import RobotConfigurationStore
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict

POLICY = TradingAssistantExecutionPolicyV1()


@pytest.fixture
def session(robot_database):
    # Every case starts empty; rollback only this test's uncommitted transaction.
    with Session(robot_database) as session:
        yield session


def command(expected=None, **patch):
    data = dict(expectedConfigVersionId=expected, name="我的机器人", keywords=["财势乾坤"],
        webhook=dict(action="REPLACE", value="https://open.feishu.cn/open-apis/bot/v2/hook/private-token"),
        signingSecret=dict(action="REPLACE", value="private-signature"))
    data.update(patch)
    return CandidateInput.model_validate(data)


def create(store, session, *, owner=1, data=None):
    return store.create_candidate(session, owner_id=owner, command=data or command(),
        now=NOW, deadline=Deadline.after_ms(5000))


def evidence(session, candidate, state="SUCCEEDED"):
    c = session.get(RobotCandidate, UUID(candidate.candidateId))
    return test_row(session, dict(owner_user_id=c.owner_user_id, robot_id=c.robot_id,
        candidate_id=c.candidate_id), state)


def confirm(store, session, candidate, test, expected=None, owner=1):
    return store.confirm(session, owner_id=owner, candidate_id=UUID(candidate.candidateId),
        command=ConfirmCandidateInput(expectedConfigVersionId=expected, testId=str(test["test_id"]), receivedConfirmed=True),
        now=NOW + timedelta(seconds=2), deadline=Deadline.after_ms(5000))


def test_candidate_is_not_active_and_activation_reencrypts(session):
    store = RobotConfigurationStore(CIPHER, POLICY)
    candidate = create(store, session)
    assert session.scalar(select(RobotIdentity.current_config_id)) is None
    assert session.scalar(select(func.count()).select_from(RobotTest)) == 0
    activated = confirm(store, session, candidate, evidence(session, candidate))
    assert session.scalar(select(RobotIdentity.current_config_id)) == UUID(activated.configVersionId)
    blobs = list(session.scalars(select(CredentialBlob)))
    assert len(blobs) == 2 and blobs[0].nonce != blobs[1].nonce and blobs[0].ciphertext != blobs[1].ciphertext
    for result in (candidate, activated):
        assert "private-token" not in result.model_dump_json()
        assert "private-signature" not in result.model_dump_json()
        assert result.hasSigningSecret is True


def test_keep_and_clear_use_exact_current_configuration(session):
    store = RobotConfigurationStore(CIPHER, POLICY)
    first = create(store, session)
    active = confirm(store, session, first, evidence(session, first))
    second = create(store, session, data=command(active.configVersionId,
        webhook=dict(action="KEEP"), signingSecret=dict(action="CLEAR")))
    assert not second.hasSigningSecret
    assert session.scalar(select(RobotIdentity.current_config_id)) == UUID(active.configVersionId)
    new_active = confirm(store, session, second, evidence(session, second), active.configVersionId)
    row = session.get(RobotConfig, UUID(new_active.configVersionId))
    secret = store._secret(session, 1, "CONFIG", row.config_id, row.credential_blob_id)
    assert secret["webhook"].endswith("private-token") and secret["signingSecret"] is None
    old = session.get(RobotConfig, UUID(active.configVersionId))
    assert store._secret(session, 1, "CONFIG", old.config_id, old.credential_blob_id)["signingSecret"] == "private-signature"


@pytest.mark.parametrize("state", ["FAILED", "UNKNOWN", "IN_FLIGHT"])
def test_unsuccessful_test_cannot_activate(session, state):
    store = RobotConfigurationStore(CIPHER, POLICY)
    candidate = create(store, session)
    with pytest.raises(WriteProtocolConflict):
        confirm(store, session, candidate, evidence(session, candidate, state))
    assert session.scalar(select(func.count()).select_from(RobotConfig)) == 0


def test_old_candidate_cannot_overwrite_new_active_configuration(session):
    store = RobotConfigurationStore(CIPHER, POLICY)
    first, second = create(store, session), create(store, session)
    old_test, new_test = evidence(session, first), evidence(session, second)
    active = confirm(store, session, second, new_test)
    with pytest.raises(WriteProtocolConflict):
        confirm(store, session, first, old_test, active.configVersionId)
    assert session.scalar(select(RobotIdentity.current_config_id)) == UUID(active.configVersionId)


def test_other_users_candidate_and_test_are_rejected(session):
    store = RobotConfigurationStore(CIPHER, POLICY)
    own, foreign = create(store, session), create(store, session, owner=2)
    foreign_test = evidence(session, foreign)
    for candidate in (own, foreign):
        with pytest.raises(WriteProtocolConflict):
            confirm(store, session, candidate, foreign_test)
    assert session.scalar(select(func.count()).select_from(RobotConfig)) == 0


def test_missing_cipher_never_writes_plaintext_or_identity(session):
    with pytest.raises(CredentialError):
        create(RobotConfigurationStore(None, POLICY), session)
    assert session.scalar(select(func.count()).select_from(RobotIdentity)) == 0
    assert session.scalar(select(func.count()).select_from(CredentialBlob)) == 0


def test_tampering_cannot_activate_and_preserves_existing_config(session):
    store = RobotConfigurationStore(CIPHER, POLICY)
    first = create(store, session)
    active = confirm(store, session, first, evidence(session, first))
    second = create(store, session, data=command(active.configVersionId))
    test = evidence(session, second)
    row = session.get(RobotCandidate, UUID(second.candidateId))
    session.execute(update(CredentialBlob).where(CredentialBlob.blob_id == row.credential_blob_id).values(ciphertext=b"x" * 32))
    with pytest.raises(CredentialError):
        confirm(store, session, second, test, active.configVersionId)
    assert session.scalar(select(RobotIdentity.current_config_id)) == UUID(active.configVersionId)


def test_nonce_collision_reencrypts_without_duplicate_candidate(session):
    first_store = RobotConfigurationStore(CIPHER, POLICY)
    create(first_store, session)
    original = session.scalar(select(CredentialBlob))
    from src.biz.services.wealth.market.trading_assistant.credential_cipher import CredentialEnvelope

    class OnceCollision:
        calls = 0

        def encrypt(self, *args):
            self.calls += 1
            if self.calls == 1:
                return CredentialEnvelope(original.key_id, original.nonce, original.ciphertext)
            return CIPHER.encrypt(*args)

    cipher = OnceCollision()
    create(RobotConfigurationStore(cipher, POLICY), session)
    assert cipher.calls == 2
    assert session.scalar(select(func.count()).select_from(CredentialBlob)) == 2
    assert session.scalar(select(func.count()).select_from(RobotCandidate)) == 2
