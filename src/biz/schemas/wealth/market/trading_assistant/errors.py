"""Registered application error shapes; no exception handler or HTTP policy."""

from pydantic import StrictStr

from .common import Contract
from .error_codes import ErrorCode
from .recovery import RecoveryStatusDto
from .value_types import BusinessDate, EntityId, Version

class FieldErrorDto(Contract):
    field: StrictStr
    clientRowId: StrictStr | None
    message: StrictStr
    affectedOn: BusinessDate | None


class TradingAssistantErrorDto(Contract):
    code: ErrorCode
    message: StrictStr
    requestId: EntityId | None
    attemptId: EntityId | None
    stateVersion: Version | None
    fieldErrors: list[FieldErrorDto]
    recovery: RecoveryStatusDto | None
