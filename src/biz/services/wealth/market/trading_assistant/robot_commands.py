"""Atomic robot commands, without retained-input recovery or automatic sends."""
import hashlib
import json
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.robots import RobotCandidate, RobotConfig, RobotTest
from src.biz.schemas.wealth.market.trading_assistant import receipts
from .execution_policy import Deadline
from .robot_configuration import RobotConfigurationStore
from .write_protocol import WriteProtocolConflict
from .condition_intervals import require_aware
from .credential_cipher import CredentialError


def command_object_id(owner_id, operation, request_id):
    return uuid5(NAMESPACE_URL, f"wealth-ta:{owner_id}:{operation}:{request_id}")


def candidate_digest(command):
    values = command.model_dump(mode="json", exclude={"requestId", "attemptId"})
    for key in ("webhook", "signingSecret"):
        intent = getattr(command, key)
        if intent.action == "REPLACE":
            values[key]["value"] = intent.value.get_secret_value()
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()


class RobotCommandService:
    def __init__(self, transactions, policy, now, cipher):
        self.transactions, self.policy, self.now = transactions, policy, now
        self.store = RobotConfigurationStore(cipher, policy)

    async def create(self, *, owner_id, command):
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        def save(session):
            now = self.now()
            result = self.store.create_candidate(session, owner_id=owner_id, command=command, now=now,
                deadline=deadline, candidate_id=command_object_id(owner_id, "CANDIDATE", command.requestId),
                request_digest=candidate_digest(command))
            row = session.get(RobotCandidate, UUID(result.candidateId))
            return receipts.CandidateCreateReceipt(requestId=command.requestId, attemptId=command.attemptId,
                operationType="ROBOT_CANDIDATE_CREATE", acceptedAt=row.created_at.isoformat(), result=result)
        return await self.transactions.run(save, deadline=deadline, write=True)

    async def confirm(self, *, owner_id, candidate_id, command):
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        def save(session):
            result = self.store.confirm(session, owner_id=owner_id, candidate_id=candidate_id,
                command=command, now=self.now(), deadline=deadline)
            row = session.get(RobotConfig, UUID(result.configVersionId))
            return receipts.RobotConfirmReceipt(requestId=command.requestId, attemptId=command.attemptId,
                operationType="ROBOT_CONFIRM", acceptedAt=row.confirmed_at.isoformat(), result=result)
        return await self.transactions.run(save, deadline=deadline, write=True)

    async def test(self, *, owner_id, candidate_id, command):
        if self.store.cipher is None:
            raise CredentialError()
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        def save(session):
            now = self.now()
            require_aware(now)
            robot = self.store._lock(session, owner_id, deadline)
            candidate = session.scalar(select(RobotCandidate).where(RobotCandidate.owner_user_id == owner_id,
                RobotCandidate.robot_id == robot.robot_id, RobotCandidate.candidate_id == candidate_id))
            if candidate is None:
                raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
            if candidate.candidate_version != int(command.expectedCandidateVersion):
                raise WriteProtocolConflict("TA_STATE_CONFLICT")
            test_id = command_object_id(owner_id, "TEST", command.requestId)
            row = session.get(RobotTest, test_id)
            if row is not None:
                if row.owner_user_id != owner_id or row.candidate_id != candidate_id:
                    raise WriteProtocolConflict("TA_REQUEST_ID_CONFLICT")
            else:
                self.store._expected(robot, str(candidate.expected_config_id) if candidate.expected_config_id else None)
                latest = session.scalar(select(RobotTest).where(RobotTest.candidate_id == candidate_id)
                    .order_by(RobotTest.attempt_no.desc()).limit(1))
                # Unknown is not a failed delivery. Never turn it into another send.
                if latest is not None and latest.state != "FAILED":
                    raise WriteProtocolConflict("TA_STATE_CONFLICT")
                row = RobotTest(test_id=test_id, owner_user_id=owner_id, robot_id=robot.robot_id,
                    candidate_id=candidate_id, attempt_no=1 if latest is None else latest.attempt_no + 1,
                    state="IN_FLIGHT", started_at=now)
                session.add(row)
                session.flush()
            # Receipt describes acceptance, current outcome is read via test GET.
            return receipts.RobotTestReceipt(requestId=command.requestId, attemptId=command.attemptId,
                operationType="ROBOT_TEST", acceptedAt=row.started_at.isoformat(), result=dict(
                    testId=str(row.test_id), state="IN_FLIGHT", startedAt=row.started_at.isoformat(),
                    completedAt=None, reason=None))
        return await self.transactions.run(save, deadline=deadline, write=True)
