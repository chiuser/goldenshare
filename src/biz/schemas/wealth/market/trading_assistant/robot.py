"""Feishu application contracts only. No external protocol, secrets store or IO."""

from typing import Annotated, Literal
from pydantic import Field, SecretStr, StrictBool, StrictStr, model_validator

from .common import CommandIdentity, Contract, Page
from .rules import NotificationState
from .value_types import EntityId, Instant, PositiveVersion, Quantity, Version

RobotName = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class KeepSecret(Contract):
    action: Literal["KEEP"]


class ClearSecret(Contract):
    action: Literal["CLEAR"]


class ReplaceSecret(Contract):
    action: Literal["REPLACE"]
    value: SecretStr = Field(strict=True, min_length=1)


WebhookUpdate = Annotated[KeepSecret | ReplaceSecret, Field(discriminator="action")]
SigningSecretUpdate = Annotated[KeepSecret | ClearSecret | ReplaceSecret, Field(discriminator="action")]


class CandidateInput(Contract):
    expectedConfigVersionId: EntityId | None
    name: RobotName
    webhook: WebhookUpdate
    signingSecret: SigningSecretUpdate
    keywords: list[StrictStr]

    @model_validator(mode="after")
    def first_configuration(self):
        if self.expectedConfigVersionId is None and (
            self.webhook.action != "REPLACE" or self.signingSecret.action == "KEEP"
        ):
            raise ValueError("First configuration cannot keep nonexistent credentials")
        return self


class CandidateCommand(CandidateInput, CommandIdentity):
    pass


class TestCandidateInput(Contract):
    expectedCandidateVersion: PositiveVersion


class TestCandidateCommand(TestCandidateInput, CommandIdentity):
    pass


class ConfirmCandidateInput(Contract):
    expectedConfigVersionId: EntityId | None
    testId: EntityId
    receivedConfirmed: StrictBool

    @model_validator(mode="after")
    def explicit_confirmation(self):
        if not self.receivedConfirmed:
            raise ValueError("Receipt must be explicitly confirmed by the user")
        return self


class ConfirmCandidateCommand(ConfirmCandidateInput, CommandIdentity):
    pass


class ConfigDisplay(Contract):
    name: RobotName
    maskedWebhook: StrictStr
    hasSigningSecret: StrictBool
    keywords: list[StrictStr]


class RobotConfig(ConfigDisplay):
    robotId: EntityId
    configVersionId: EntityId


class RobotResponse(Contract):
    robot: RobotConfig | None


class CandidateResult(ConfigDisplay):
    candidateId: EntityId
    candidateVersion: PositiveVersion


class TestResult(Contract):
    testId: EntityId
    state: Literal["IN_FLIGHT", "SUCCEEDED", "FAILED", "UNKNOWN"]
    startedAt: Instant
    completedAt: Instant | None
    reason: StrictStr | None


class NotificationRetryInput(Contract):
    expectedStateVersion: PositiveVersion


class NotificationRetryCommand(NotificationRetryInput, CommandIdentity):
    pass


class NotificationRetryResult(Contract):
    notificationId: EntityId
    stateVersion: PositiveVersion
    state: Literal["PENDING"]


class NotificationAttempt(Contract):
    attemptId: EntityId
    attemptNo: Quantity
    robotConfigVersionId: EntityId
    robotName: StrictStr
    startedAt: Instant
    completedAt: Instant | None
    outcome: Literal["IN_FLIGHT", "SUCCEEDED", "FAILED", "UNKNOWN"]
    reason: StrictStr | None


class NotificationDetail(Page[NotificationAttempt]):
    notificationId: EntityId
    triggerId: EntityId
    ruleVersionId: EntityId
    state: NotificationState
    stateVersion: Version
    robotId: EntityId
    robotName: StrictStr
    canRetry: StrictBool
    reason: StrictStr | None
    observedAt: Instant

    @model_validator(mode="after")
    def retry_eligibility(self):
        if self.canRetry and self.state != "FAILED":
            raise ValueError("Only confirmed failures can be retried")
        numbers = [int(item.attemptNo) for item in self.items]
        if numbers != sorted(set(numbers), reverse=True):
            raise ValueError("Attempts must be unique and descending")
        return self
