"""Operation-discriminated immutable success receipts, never current details."""

from typing import Annotated, Literal
from pydantic import Field

from . import accounts, robot, rules
from .calculation_status import CalculationStatus
from .common import MutationReceipt


class AccountCreateReceipt(MutationReceipt[accounts.CreateAccountResult]):
    operationType: Literal["ACCOUNT_CREATE"]


class InitializationCorrectReceipt(MutationReceipt[accounts.InitializationCorrectionResult]):
    operationType: Literal["INITIALIZATION_CORRECT"]


class FeesUpdateReceipt(MutationReceipt[accounts.FeeSettingsDto]):
    operationType: Literal["FEES_UPDATE"]


class TradeCreateReceipt(MutationReceipt[accounts.TradeResult]):
    operationType: Literal["TRADE_CREATE"]


class TradeCorrectReceipt(MutationReceipt[accounts.TradeResult]):
    operationType: Literal["TRADE_CORRECT"]


class TradeVoidReceipt(MutationReceipt[accounts.TradeVoidResult]):
    operationType: Literal["TRADE_VOID"]


class CashCreateReceipt(MutationReceipt[accounts.CashFlowResult]):
    operationType: Literal["CASH_FLOW_CREATE"]


class CashCorrectReceipt(MutationReceipt[accounts.CashFlowResult]):
    operationType: Literal["CASH_FLOW_CORRECT"]


class CashVoidReceipt(MutationReceipt[accounts.CashFlowVoidResult]):
    operationType: Literal["CASH_FLOW_VOID"]


class CalculationRetryReceipt(MutationReceipt[CalculationStatus]):
    operationType: Literal["CALCULATION_RETRY"]


class PlanCreateReceipt(MutationReceipt[rules.PlanRow]):
    operationType: Literal["PLAN_CREATE"]


class AlertCreateReceipt(MutationReceipt[rules.AlertRow]):
    operationType: Literal["ALERT_CREATE"]


class ConditionsUpdateReceipt(MutationReceipt[rules.ReviseConditionsResult]):
    operationType: Literal["RULE_CONDITIONS_UPDATE"]


class RuleCloseReceipt(MutationReceipt[rules.CloseRuleResult]):
    operationType: Literal["RULE_CLOSE"]


class CandidateCreateReceipt(MutationReceipt[robot.CandidateResult]):
    operationType: Literal["ROBOT_CANDIDATE_CREATE"]


class RobotTestReceipt(MutationReceipt[robot.TestResult]):
    operationType: Literal["ROBOT_TEST"]


class RobotConfirmReceipt(MutationReceipt[robot.RobotConfig]):
    operationType: Literal["ROBOT_CONFIRM"]


class NotificationRetryReceipt(MutationReceipt[robot.NotificationRetryResult]):
    operationType: Literal["NOTIFICATION_RETRY"]


SuccessReceipt = Annotated[
    AccountCreateReceipt | InitializationCorrectReceipt | FeesUpdateReceipt | TradeCreateReceipt
    | TradeCorrectReceipt | TradeVoidReceipt | CashCreateReceipt | CashCorrectReceipt | CashVoidReceipt
    | CalculationRetryReceipt | PlanCreateReceipt | AlertCreateReceipt | ConditionsUpdateReceipt
    | RuleCloseReceipt | CandidateCreateReceipt | RobotTestReceipt | RobotConfirmReceipt | NotificationRetryReceipt,
    Field(discriminator="operationType"),
]
