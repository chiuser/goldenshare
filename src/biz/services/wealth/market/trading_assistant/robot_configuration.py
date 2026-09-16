"""Short-transaction configuration operations, design §7.9.

Caller authenticates the owner and owns commit and the request/attempt protocol.
This store neither sends messages nor interprets client data as test evidence.
"""
import json
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from src.biz.models.wealth.trading_assistant.robots import CredentialBlob, RobotCandidate, RobotConfig, RobotTest
from src.biz.schemas.wealth.market.trading_assistant import robot as dto
from .credential_cipher import CredentialEnvelope, CredentialError
from .condition_intervals import require_aware
from .feishu_protocol import validate_webhook
from .market_facts import apply_sql_budget
from .write_protocol import WriteProtocolConflict


class RobotConfigurationStore:
    def __init__(self, cipher, policy):
        self.cipher, self.policy = cipher, policy

    def _lock(self, session, owner_id, deadline, *, create=False):
        apply_sql_budget(session, deadline, self.policy)
        if create:
            session.execute(insert(RobotIdentity).values(robot_id=uuid4(), owner_user_id=owner_id)
                .on_conflict_do_nothing(index_elements=[RobotIdentity.owner_user_id]))
        row = session.scalar(select(RobotIdentity).where(RobotIdentity.owner_user_id == owner_id)
            .with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        return row

    def _secret(self, session, owner, kind, object_id, blob_id):
        if self.cipher is None:
            raise CredentialError()
        row = session.scalar(select(CredentialBlob).where(CredentialBlob.owner_user_id == owner,
            CredentialBlob.object_type == kind, CredentialBlob.object_id == object_id,
            CredentialBlob.blob_id == blob_id))
        if row is None:
            raise CredentialError()
        plain = self.cipher.decrypt(owner, kind, object_id,
            CredentialEnvelope(row.key_id, row.nonce, row.ciphertext, row.algorithm_version))
        try:
            value = json.loads(plain)
            if (not isinstance(value, dict) or set(value) != {"webhook", "signingSecret"}
                    or not isinstance(value["webhook"], str)
                    or (value["signingSecret"] is not None and not isinstance(value["signingSecret"], str))):
                raise ValueError()
            validate_webhook(value["webhook"])
        except (ValueError, UnicodeError):
            raise CredentialError() from None
        return value

    def _encrypt(self, session, owner, kind, object_id, secret, now, deadline):
        if self.cipher is None:
            raise CredentialError()
        plain = json.dumps(secret, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        # A nonce collision has not sent anything. Retry encryption within the
        # existing request deadline; other constraint failures are not swallowed.
        while True:
            deadline.remaining_ms()
            envelope = self.cipher.encrypt(owner, kind, object_id, plain)
            blob_id = uuid4()
            saved = session.scalar(insert(CredentialBlob).values(blob_id=blob_id, owner_user_id=owner,
                object_type=kind, object_id=object_id, key_id=envelope.key_id, nonce=envelope.nonce,
                ciphertext=envelope.ciphertext, algorithm_version=envelope.algorithm_version, created_at=now)
                .on_conflict_do_nothing(constraint="uq_ta_credential_nonce").returning(CredentialBlob.blob_id))
            if saved is not None:
                return saved

    @staticmethod
    def _expected(robot, expected):
        if robot.current_config_id != (UUID(expected) if expected is not None else None):
            raise WriteProtocolConflict("TA_STATE_CONFLICT")

    @staticmethod
    def _display(row, secret):
        # Never return a usable address or a prefix of the secret token.
        return dict(name=row.name, maskedWebhook="https://open.feishu.cn/open-apis/bot/v2/hook/••••",
                    hasSigningSecret=secret["signingSecret"] is not None, keywords=list(row.keywords))

    def create_candidate(self, session, *, owner_id, command, now, deadline):
        require_aware(now)
        if self.cipher is None:
            raise CredentialError()
        robot = self._lock(session, owner_id, deadline, create=True)
        self._expected(robot, command.expectedConfigVersionId)
        previous = None
        if command.webhook.action == "KEEP" or command.signingSecret.action == "KEEP":
            config = session.scalar(select(RobotConfig).where(RobotConfig.owner_user_id == owner_id,
                RobotConfig.robot_id == robot.robot_id, RobotConfig.config_id == robot.current_config_id))
            if config is None:
                raise WriteProtocolConflict("TA_STATE_CONFLICT")
            previous = self._secret(session, owner_id, "CONFIG", config.config_id, config.credential_blob_id)
        webhook = previous["webhook"] if command.webhook.action == "KEEP" else command.webhook.value.get_secret_value()
        signing = (previous["signingSecret"] if command.signingSecret.action == "KEEP" else
                   command.signingSecret.value.get_secret_value() if command.signingSecret.action == "REPLACE" else None)
        validate_webhook(webhook)
        secret = dict(webhook=webhook, signingSecret=signing)
        candidate_id = uuid4()
        blob_id = self._encrypt(session, owner_id, "CANDIDATE", candidate_id, secret, now, deadline)
        digest = sha256(json.dumps(dict(name=command.name, keywords=command.keywords, **secret),
            sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        candidate = RobotCandidate(candidate_id=candidate_id, owner_user_id=owner_id, robot_id=robot.robot_id,
            candidate_version=1, expected_config_id=robot.current_config_id, name=command.name,
            keywords=list(command.keywords), content_digest=digest, credential_blob_id=blob_id, created_at=now)
        session.add(candidate)
        session.flush()
        deadline.remaining_ms()
        return dto.CandidateResult(candidateId=str(candidate_id), candidateVersion="1", **self._display(candidate, secret))

    def confirm(self, session, *, owner_id, candidate_id, command, now, deadline):
        require_aware(now)
        if self.cipher is None:
            raise CredentialError()
        robot = self._lock(session, owner_id, deadline)
        self._expected(robot, command.expectedConfigVersionId)
        candidate = session.scalar(select(RobotCandidate).where(RobotCandidate.owner_user_id == owner_id,
            RobotCandidate.robot_id == robot.robot_id, RobotCandidate.candidate_id == candidate_id))
        if candidate is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        if candidate.expected_config_id != robot.current_config_id:
            raise WriteProtocolConflict("TA_STATE_CONFLICT")
        test = session.scalar(select(RobotTest).where(RobotTest.owner_user_id == owner_id,
            RobotTest.robot_id == robot.robot_id, RobotTest.candidate_id == candidate_id,
            RobotTest.test_id == UUID(command.testId)).with_for_update())
        if not command.receivedConfirmed or test is None or test.state != "SUCCEEDED" or test.completed_at > now:
            raise WriteProtocolConflict("TA_STATE_CONFLICT")
        secret = self._secret(session, owner_id, "CANDIDATE", candidate_id, candidate.credential_blob_id)
        config_id = uuid4()
        blob_id = self._encrypt(session, owner_id, "CONFIG", config_id, secret, now, deadline)
        config = RobotConfig(config_id=config_id, owner_user_id=owner_id, robot_id=robot.robot_id,
            candidate_id=candidate_id, test_id=test.test_id, name=candidate.name, keywords=list(candidate.keywords),
            credential_blob_id=blob_id, confirmed_at=now)
        session.add(config)
        session.flush()
        robot.current_config_id = config_id
        session.flush()
        deadline.remaining_ms()
        return dto.RobotConfig(robotId=str(robot.robot_id), configVersionId=str(config_id), **self._display(config, secret))
