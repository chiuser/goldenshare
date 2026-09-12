"""Short-transaction request/attempt protocol, design §4.17.

Caller owns the transaction and authenticates the scope before registration.
No method commits, performs a business write, or treats a timeout as NOT_SAVED.
Read methods never acquire execution rights or change stored state.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.biz.models.wealth.trading_assistant.recovery import WriteScope, WriteRequest, WriteAttempt, ValidationCandidate
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.ledger import Ledger
from src.biz.schemas.wealth.market.trading_assistant.targets import LedgerTarget, validate_target, validate_target_receipt
from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryRejection
from src.biz.schemas.wealth.market.trading_assistant.errors import FieldErrorDto
from src.biz.schemas.wealth.market.trading_assistant.receipts import SuccessReceipt
from src.biz.schemas.wealth.market.trading_assistant.scopes import (
    AccountCreateScope, AccountFeesScope, AccountLedgerScope)
from pydantic import TypeAdapter
from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from .market_facts import apply_sql_budget


class WriteProtocolConflict(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def scope_key(scope: AccountCreateScope | AccountFeesScope | AccountLedgerScope) -> str:
    if isinstance(scope, AccountCreateScope):
        return "ACCOUNT_CREATE"
    if isinstance(scope, (AccountFeesScope, AccountLedgerScope)):
        return f"{scope.scopeType}:{scope.accountId}"
    raise ValueError("M2 only accepts accounting scopes")


def canonical_input(operation: str, scope: str, payload: dict,
                    target: LedgerTarget | None = None) -> tuple[dict, bytes]:
    # Serialization is also a defensive deep copy; retained input cannot alias a form dict.
    normalized = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    if any(k in normalized for k in ("requestId", "attemptId", "expectedRequestStateVersion")):
        raise ValueError("Protocol identities must be removed from business input")
    validate_target(operation, target, scope.removeprefix("ACCOUNT_LEDGER:")
                    if scope.startswith("ACCOUNT_LEDGER:") else None)
    document = {"operation":operation, "scope":scope, "input":normalized,
                "target": target.model_dump(mode="json") if target else None}
    digest = sha256(json.dumps(document, ensure_ascii=False, allow_nan=False,
                               sort_keys=True, separators=(",", ":")).encode()).digest()
    return normalized, digest


@dataclass(frozen=True, slots=True)
class AttemptState:
    owner_id: int
    request_id: UUID
    attempt_id: UUID
    scope_key: str
    operation: str
    status: str
    state_version: int
    fence: int
    execute: bool
    receipt: dict | None
    rejection: dict | None
    target: LedgerTarget | None = None
    # Immediate response diagnostics, not a second persisted recovery contract.
    field_errors: tuple[FieldErrorDto, ...] = ()
    accepted_now: bool = False


def snapshot(request: WriteRequest, attempt: WriteAttempt, *, execute=False) -> AttemptState:
    # Copy JSON to avoid leaking mutable ORM state to response construction.
    return AttemptState(request.owner_id, request.request_id, attempt.attempt_id,
        request.scope_key, request.operation_type, attempt.status, request.state_version,
        attempt.fence, execute, json.loads(json.dumps(attempt.receipt)) if attempt.receipt else None,
        json.loads(json.dumps(attempt.rejection)) if attempt.rejection else None,
        LedgerTarget.model_validate(request.target) if request.target is not None else None)


class WriteProtocol:
    def __init__(self, policy: TradingAssistantExecutionPolicyV1):
        self.policy = policy

    def _scope(self, session: Session, owner_id: int, key: str, deadline: Deadline) -> WriteScope | None:
        apply_sql_budget(session, deadline, self.policy)
        return session.scalar(select(WriteScope).where(WriteScope.owner_id == owner_id,
            WriteScope.scope_key == key).with_for_update().execution_options(populate_existing=True))

    def _request(self, session: Session, owner_id: int, request_id: UUID) -> WriteRequest | None:
        return session.scalar(select(WriteRequest).where(WriteRequest.owner_id == owner_id,
            WriteRequest.request_id == request_id).with_for_update().execution_options(populate_existing=True))

    def _attempt(self, session: Session, request: WriteRequest) -> WriteAttempt:
        return session.scalars(select(WriteAttempt).where(WriteAttempt.owner_id == request.owner_id,
            WriteAttempt.request_id == request.request_id, WriteAttempt.attempt_id == request.current_attempt_id)
            .with_for_update().execution_options(populate_existing=True)).one()

    def register(self, session: Session, *, owner_id: int, request_id: UUID, attempt_id: UUID,
                 scope: AccountCreateScope | AccountFeesScope | AccountLedgerScope,
                 operation: str, payload: dict, now: datetime, executor_id: str,
                 deadline: Deadline, expected_state_version: int | None = None,
                 target: LedgerTarget | None = None) -> AttemptState:
        key = scope_key(scope)
        allowed = {"ACCOUNT_CREATE":{"ACCOUNT_CREATE"}, "ACCOUNT_FEES":{"FEES_UPDATE"},
                   "ACCOUNT_LEDGER":{"INITIALIZATION_CORRECT", "TRADE_CREATE", "TRADE_CORRECT", "TRADE_VOID",
                                     "CASH_FLOW_CREATE", "CASH_FLOW_CORRECT", "CASH_FLOW_VOID"}}
        if operation not in allowed[scope.scopeType] or not executor_id or now.tzinfo is None:
            raise ValueError("Invalid trusted operation or clock")
        payload, digest = canonical_input(operation, key, payload, target)
        apply_sql_budget(session, deadline, self.policy)
        if not isinstance(scope, AccountCreateScope) and session.scalar(select(Account.account_id).where(
                Account.owner_id == owner_id, Account.account_id == UUID(scope.accountId))) is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        if target is not None and session.scalar(select(Ledger.ledger_id).where(
                Ledger.account_id == UUID(target.accountId), Ledger.ledger_id == UUID(target.recordId),
                Ledger.kind == target.kind)) is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        session.execute(insert(WriteScope).values(owner_id=owner_id, scope_key=key)
            .on_conflict_do_nothing(index_elements=[WriteScope.owner_id, WriteScope.scope_key]))
        scope_row = self._scope(session, owner_id, key, deadline)
        request = self._request(session, owner_id, request_id)
        if request is not None:
            if request.scope_key != key or request.operation_type != operation or request.input_digest != digest:
                raise WriteProtocolConflict("TA_REQUEST_ID_CONFLICT")
            current = self._attempt(session, request)
            if current.status == "SAVED":
                return snapshot(request, current)
            prior = session.get(WriteAttempt, (owner_id, request_id, attempt_id))
            if prior is not None:
                # A stale original attempt cannot claim a later attempt's execution right.
                return snapshot(request, prior)
            if current.status != "NOT_SAVED" or expected_state_version != request.state_version:
                raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
            if scope_row.holder_request_id is not None:
                raise WriteProtocolConflict("TA_SCOPE_WRITE_PENDING")
            fence = current.fence + 1
            request.current_attempt_id = attempt_id
            request.state_version += 1
            request.updated_at = now
        else:
            if expected_state_version is not None:
                raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
            if scope_row.holder_request_id is not None:
                raise WriteProtocolConflict("TA_SCOPE_WRITE_PENDING")
            candidate_id = None if operation == "FEES_UPDATE" else uuid4()
            request = WriteRequest(owner_id=owner_id, request_id=request_id, scope_key=key,
                operation_type=operation, input_schema_version=1, input_digest=digest,
                target=target.model_dump(mode="json") if target else None,
                input_payload=payload if candidate_id is None else None, candidate_id=candidate_id,
                current_attempt_id=attempt_id, state_version=0,
                created_at=now, updated_at=now)
            session.add(request)
            # Request -> attempt is deferred; attempt -> request is not.
            session.flush()
            if candidate_id is not None:
                session.add(ValidationCandidate(candidate_id=candidate_id, owner_id=owner_id,
                    account_id=None if isinstance(scope, AccountCreateScope) else UUID(scope.accountId),
                    purpose="SAVE", request_id=request_id, input_schema_version=1, input_digest=digest,
                    input_payload=payload, basis={}, created_at=now))
            fence = 1
        attempt = WriteAttempt(owner_id=owner_id, request_id=request_id, attempt_id=attempt_id,
            status="PROCESSING", fence=fence, executor_id=executor_id,
            lease_until=now + timedelta(seconds=self.policy.lease_seconds), basis={}, started_at=now)
        session.add(attempt)
        scope_row.holder_request_id = request_id
        session.flush()
        deadline.remaining_ms()
        return snapshot(request, attempt, execute=True)

    def lock_execution(self, session: Session, state: AttemptState, *, now: datetime,
                       executor_id: str, deadline: Deadline):
        scope = self._scope(session, state.owner_id, state.scope_key, deadline)
        request = self._request(session, state.owner_id, state.request_id)
        if request is None or scope is None or request.scope_key != state.scope_key:
            raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
        attempt = self._attempt(session, request)
        if (scope.holder_request_id != state.request_id or attempt.attempt_id != state.attempt_id
                or attempt.status != "PROCESSING" or attempt.fence != state.fence
                or attempt.executor_id != executor_id or attempt.lease_until <= now):
            raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
        return scope, request, attempt

    def saved(self, session: Session, locked: tuple, receipt: dict, now: datetime):
        scope, request, attempt = locked
        if attempt.status != "PROCESSING" or scope.holder_request_id != request.request_id:
            raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
        checked = TypeAdapter(SuccessReceipt).validate_python(receipt)
        validate_target_receipt(LedgerTarget.model_validate(request.target) if request.target else None, checked)
        if (checked.requestId != str(request.request_id) or checked.attemptId != str(attempt.attempt_id)
                or checked.operationType != request.operation_type):
            raise ValueError("Receipt identity does not match the locked attempt")
        attempt.receipt = checked.model_dump(mode="json")
        attempt.status, attempt.finished_at = "SAVED", now
        scope.holder_request_id = None
        request.state_version += 1
        request.updated_at = now
        session.flush()
        return replace(snapshot(request, attempt), accepted_now=True)

    def stop(self, session: Session, locked: tuple, rejection: RecoveryRejection, now: datetime):
        scope, request, attempt = locked
        if attempt.status != "PROCESSING" or scope.holder_request_id != request.request_id:
            raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
        attempt.fence += 1
        attempt.status, attempt.finished_at = "NOT_SAVED", now
        attempt.rejection = rejection.model_dump(mode="json")
        scope.holder_request_id = None
        request.state_version += 1
        request.updated_at = now
        session.flush()
        return snapshot(request, attempt)

    def expire(self, session: Session, *, owner_id: int, request_id: UUID,
               key: str, now: datetime, deadline: Deadline) -> AttemptState | None:
        """Maintenance only: locks and revokes expired rights, never executes input."""
        scope = self._scope(session, owner_id, key, deadline)
        request = self._request(session, owner_id, request_id)
        if scope is None or request is None or request.scope_key != key:
            return None
        attempt = self._attempt(session, request)
        if (scope.holder_request_id != request_id or attempt.status != "PROCESSING"
                or attempt.lease_until > now):
            return snapshot(request, attempt)
        return self.stop(session, (scope, request, attempt), RecoveryRejection(
            code="TA_WRITE_FAILED", message="本次保存已停止，未写入账务记录", field=None), now)

    def read(self, session: Session, *, owner_id: int, request_id: UUID) -> AttemptState | None:
        request = session.get(WriteRequest, (owner_id, request_id))
        if request is None:
            return None
        attempt = session.get(WriteAttempt, (owner_id, request_id, request.current_attempt_id))
        return snapshot(request, attempt)
