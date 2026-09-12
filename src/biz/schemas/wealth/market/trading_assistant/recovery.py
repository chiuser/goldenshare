"""Recovery display contract; no lookup, input restoration or write execution."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictStr, model_validator

from .common import Contract, OperationType
from .error_codes import ErrorCode
from .receipts import SuccessReceipt
from .scopes import RecoveryScope
from .targets import LedgerTarget, validate_target, validate_target_receipt
from .value_types import EntityId, Instant, Version


NonemptyText = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class RecoverySummary(Contract):
    """Server-generated original-operation text, never a source of input facts.

    The producer must select safe fields from the original request. This schema
    validates shape only: arbitrary strings cannot prove absence of secrets.
    The UI must render both fields as plain text, not HTML.
    """

    title: NonemptyText
    lines: list[NonemptyText]


class RecoveryRejection(Contract):
    code: ErrorCode
    message: StrictStr
    field: StrictStr | None


class RecoveryStatusDto(Contract):
    requestId: EntityId
    attemptId: EntityId
    operationType: OperationType
    scope: RecoveryScope
    target: LedgerTarget | None
    stateVersion: Version
    outcome: Literal["PROCESSING", "SAVED", "NOT_SAVED", "UNKNOWN"]
    inputRetained: StrictBool
    summary: RecoverySummary
    receipt: SuccessReceipt | None
    rejection: RecoveryRejection | None
    updatedAt: Instant

    @model_validator(mode="after")
    def confirmed_outcome(self):
        validate_target(self.operationType, self.target, getattr(self.scope, "accountId", None))
        scope = self.scope.scopeType
        permitted = {
            "ACCOUNT_CREATE": {"ACCOUNT_CREATE"},
            "ACCOUNT_FEES": {"FEES_UPDATE"},
            "ACCOUNT_LEDGER": {"INITIALIZATION_CORRECT", "TRADE_CREATE", "TRADE_CORRECT", "TRADE_VOID",
                               "CASH_FLOW_CREATE", "CASH_FLOW_CORRECT", "CASH_FLOW_VOID", "CALCULATION_RETRY"},
            "RULE": {"RULE_CONDITIONS_UPDATE", "RULE_CLOSE"},
            "RULE_CREATE": {"PLAN_CREATE", "ALERT_CREATE"},
            "ROBOT": {"ROBOT_CANDIDATE_CREATE", "ROBOT_TEST", "ROBOT_CONFIRM"},
            "NOTIFICATION": {"NOTIFICATION_RETRY"},
        }
        if self.operationType not in permitted[scope]:
            raise ValueError("Recovery operation and scope do not match")
        if scope == "RULE_CREATE" and self.operationType != self.scope.ruleType + "_CREATE":
            raise ValueError("Rule creation type mismatch")
        if (self.outcome == "SAVED") != (self.receipt is not None):
            raise ValueError("Only saved requests have a success receipt")
        if self.receipt is not None and (
            self.receipt.requestId != self.requestId or self.receipt.attemptId != self.attemptId
            or self.receipt.operationType != self.operationType
        ):
            raise ValueError("Receipt does not belong to this operation and attempt")
        if self.rejection is not None and self.outcome != "NOT_SAVED":
            raise ValueError("Only confirmed not-saved requests can have a rejection")
        if self.receipt is not None:
            validate_target_receipt(self.target, self.receipt)
        return self


class PendingRecoveryResponse(Contract):
    pendingRequest: RecoveryStatusDto | None

    @model_validator(mode="after")
    def unresolved_only(self):
        if self.pendingRequest is not None and self.pendingRequest.outcome not in ("PROCESSING", "UNKNOWN"):
            raise ValueError("Terminal requests are not pending")
        return self
