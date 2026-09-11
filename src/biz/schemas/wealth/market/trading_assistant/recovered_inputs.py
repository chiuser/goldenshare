"""Recoverable original inputs. They are not executable commands or new attempts."""

from typing import Annotated, Generic, Literal, TypeVar
from pydantic import Field

from . import accounts, robot, rules
from .calculation_status import CalculationRetryInput
from .common import Contract
from .value_types import EntityId, PositiveVersion


class InitializationCorrectionInput(accounts.InitializationInput):
    expectedRevision: PositiveVersion


class TradeCorrectionInput(accounts.TradeInput):
    expectedRevision: PositiveVersion


class CashCorrectionInput(accounts.CashFlowInput):
    expectedRevision: PositiveVersion


class VoidInput(Contract):
    expectedRevision: PositiveVersion


class FeesUpdateInput(accounts.FeeInputs):
    expectedFeeVersionId: EntityId


class ConditionsUpdateInput(rules.Conditions):
    expectedStateVersion: PositiveVersion


class CloseRuleInput(Contract):
    expectedStateVersion: PositiveVersion


class SafeCandidateInput(robot.ConfigDisplay):
    # Outer requestId locates the retained credential reference on the server.
    # A failed create need not have produced any candidate entity.
    expectedConfigVersionId: EntityId | None


InputT = TypeVar("InputT", bound=Contract)


class RecoveredInput(Contract, Generic[InputT]):
    requestId: EntityId
    inputSchemaVersion: PositiveVersion
    input: InputT


class AccountCreateInput(RecoveredInput[accounts.CreateAccountInput]):
    operationType: Literal["ACCOUNT_CREATE"]


class InitializationInput(RecoveredInput[InitializationCorrectionInput]):
    operationType: Literal["INITIALIZATION_CORRECT"]


class FeeInput(RecoveredInput[FeesUpdateInput]):
    operationType: Literal["FEES_UPDATE"]


class TradeCreateInput(RecoveredInput[accounts.TradeInput]):
    operationType: Literal["TRADE_CREATE"]


class TradeCorrectInput(RecoveredInput[TradeCorrectionInput]):
    operationType: Literal["TRADE_CORRECT"]


class TradeVoidInput(RecoveredInput[VoidInput]):
    operationType: Literal["TRADE_VOID"]


class CashCreateInput(RecoveredInput[accounts.CashFlowInput]):
    operationType: Literal["CASH_FLOW_CREATE"]


class CashCorrectInput(RecoveredInput[CashCorrectionInput]):
    operationType: Literal["CASH_FLOW_CORRECT"]


class CashVoidInput(RecoveredInput[VoidInput]):
    operationType: Literal["CASH_FLOW_VOID"]


class CalculationInput(RecoveredInput[CalculationRetryInput]):
    operationType: Literal["CALCULATION_RETRY"]


class PlanCreateInput(RecoveredInput[rules.CreatePlanInput]):
    operationType: Literal["PLAN_CREATE"]


class AlertCreateInput(RecoveredInput[rules.CreateAlertInput]):
    operationType: Literal["ALERT_CREATE"]


class RuleConditionsInput(RecoveredInput[ConditionsUpdateInput]):
    operationType: Literal["RULE_CONDITIONS_UPDATE"]


class RuleCloseInput(RecoveredInput[CloseRuleInput]):
    operationType: Literal["RULE_CLOSE"]


class CandidateInput(RecoveredInput[SafeCandidateInput]):
    operationType: Literal["ROBOT_CANDIDATE_CREATE"]


class TestInput(RecoveredInput[robot.TestCandidateInput]):
    operationType: Literal["ROBOT_TEST"]


class ConfirmInput(RecoveredInput[robot.ConfirmCandidateInput]):
    operationType: Literal["ROBOT_CONFIRM"]


class NotificationInput(RecoveredInput[robot.NotificationRetryInput]):
    operationType: Literal["NOTIFICATION_RETRY"]


RecoveryInputResponse = Annotated[
    AccountCreateInput | InitializationInput | FeeInput | TradeCreateInput | TradeCorrectInput | TradeVoidInput
    | CashCreateInput | CashCorrectInput | CashVoidInput | CalculationInput | PlanCreateInput | AlertCreateInput
    | RuleConditionsInput | RuleCloseInput | CandidateInput | TestInput | ConfirmInput | NotificationInput,
    Field(discriminator="operationType"),
]
