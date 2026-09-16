"""Single-statement recovery snapshots. Reads never grant execution rights."""
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.biz.models.wealth.trading_assistant.recovery import (
    WriteRequest, WriteAttempt, WriteScope, ValidationCandidate,
)
from src.biz.schemas.wealth.market.trading_assistant.recovered_inputs import RecoveryInputResponse
from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryStatusDto, PendingRecoveryResponse
from src.biz.schemas.wealth.market.trading_assistant.scopes import (
    RuleScope, RuleCreateScope,
)
from src.biz.schemas.wealth.market.trading_assistant.targets import LedgerTarget
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import (
    WriteProtocolConflict, canonical_input, scope_key, parse_scope_key, verify_rule_scope, WriteScopeInput,
)


TITLES = {
    "CALCULATION_RETRY": "重试计算",
    "ACCOUNT_CREATE": "创建账户", "INITIALIZATION_CORRECT": "更正初始持仓", "FEES_UPDATE": "修改费率",
    "TRADE_CREATE": "交易登记", "TRADE_CORRECT": "更正交易", "TRADE_VOID": "作废交易",
    "CASH_FLOW_CREATE": "资金登记", "CASH_FLOW_CORRECT": "更正资金记录", "CASH_FLOW_VOID": "作废资金记录",
    "PLAN_CREATE": "创建交易计划", "ALERT_CREATE": "创建提醒",
    "RULE_CONDITIONS_UPDATE": "修改交易条件", "RULE_CLOSE": "关闭规则",
    "NOTIFICATION_RETRY": "重试通知",
}


def _statement(owner_id: int):
    return select(WriteRequest, WriteAttempt, ValidationCandidate).join(WriteAttempt, and_(
        WriteAttempt.owner_id == WriteRequest.owner_id,
        WriteAttempt.request_id == WriteRequest.request_id,
        WriteAttempt.attempt_id == WriteRequest.current_attempt_id,
    )).outerjoin(ValidationCandidate, and_(
        ValidationCandidate.owner_id == WriteRequest.owner_id,
        ValidationCandidate.request_id == WriteRequest.request_id,
        ValidationCandidate.candidate_id == WriteRequest.candidate_id,
    )).where(WriteRequest.owner_id == owner_id).execution_options(populate_existing=True)


def _scope(key: str):
    return parse_scope_key(key)


def _input(row):
    request, _, candidate = row
    payload = candidate.input_payload if candidate is not None else request.input_payload
    if payload is None:
        raise ValueError("Persisted recovery input is missing")
    target = LedgerTarget.model_validate(request.target) if request.target else None
    _, digest = canonical_input(request.operation_type, request.scope_key, payload, target)
    if digest != request.input_digest or (candidate is not None and candidate.input_digest != digest):
        raise ValueError("Persisted recovery input digest mismatch")
    return TypeAdapter(RecoveryInputResponse).validate_python(dict(
        requestId=str(request.request_id), operationType=request.operation_type,
        inputSchemaVersion=str(request.input_schema_version), target=request.target, input=payload))


def _status(row):
    request, attempt, _ = row
    original = _input(row)
    # Only typed original fields enter display text, never arbitrary payload/exception dumps.
    data = original.input
    lines = []
    for key, label in (("name", "名称"), ("tradeDate", "交易日期"),
                       ("occurredOn", "资金日期"), ("quantity", "数量"), ("amount", "金额"),
                       ("stockCode", "股票代码"), ("deadlineAt", "截止时间")):
        value = getattr(data, key, None)
        if value is not None:
            lines.append(f"{label}：{value}")
    return RecoveryStatusDto(requestId=str(request.request_id), attemptId=str(attempt.attempt_id),
        operationType=request.operation_type, scope=_scope(request.scope_key), target=request.target,
        stateVersion=str(request.state_version), outcome=attempt.status, inputRetained=True,
        summary={"title": TITLES[request.operation_type], "lines": lines}, receipt=attempt.receipt,
        rejection=attempt.rejection, updatedAt=request.updated_at.isoformat())


class WriteRecoveryQueries:
    def __init__(self, policy: TradingAssistantExecutionPolicyV1):
        self.policy = policy

    def status(self, session: Session, *, owner_id: int, request_id: UUID, deadline: Deadline):
        apply_sql_budget(session, deadline, self.policy)
        row = session.execute(_statement(owner_id).where(WriteRequest.request_id == request_id)).one_or_none()
        if row is None:
            raise WriteProtocolConflict("TA_RECOVERY_UNAVAILABLE")
        return _status(row)

    def pending(self, session: Session, *, owner_id: int,
                scope: WriteScopeInput, deadline: Deadline):
        apply_sql_budget(session, deadline, self.policy)
        if isinstance(scope, (RuleScope, RuleCreateScope)):
            verify_rule_scope(session, owner_id, scope)
        row = session.execute(_statement(owner_id).join(WriteScope, and_(
            WriteScope.owner_id == WriteRequest.owner_id, WriteScope.scope_key == WriteRequest.scope_key,
            WriteScope.holder_request_id == WriteRequest.request_id,
        )).where(WriteRequest.scope_key == scope_key(scope))).one_or_none()
        return PendingRecoveryResponse(pendingRequest=_status(row) if row else None)

    def recoverable_input(self, session: Session, *, owner_id: int, request_id: UUID, deadline: Deadline):
        apply_sql_budget(session, deadline, self.policy)
        row = session.execute(_statement(owner_id).where(WriteRequest.request_id == request_id)).one_or_none()
        if row is None:
            raise WriteProtocolConflict("TA_RECOVERY_UNAVAILABLE")
        if row[1].status != "NOT_SAVED":
            raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
        return _input(row)
