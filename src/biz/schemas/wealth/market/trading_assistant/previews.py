"""Read-only preview payloads; no save identity or acceptance promise."""

from typing import Generic, TypeVar
from pydantic import StrictStr

from .accounts import CashFlowInput, FeeBreakdown, InitializationInput, InitializationPosition, TradeInput
from .common import Contract, ReadState
from .errors import FieldErrorDto
from .value_types import BusinessDate, Money, NonnegativeMoney, Note, PositiveVersion


class TradeCorrectionPreviewInput(TradeInput):
    expectedRevision: PositiveVersion


class CashCorrectionPreviewInput(CashFlowInput):
    expectedRevision: PositiveVersion


class InitializationCorrectionPreviewInput(InitializationInput):
    expectedRevision: PositiveVersion


class TradePreview(FeeBreakdown):
    factVersion: PositiveVersion
    calendarDataStatus: ReadState
    fieldErrors: list[FieldErrorDto]


class ChangedField(Contract):
    field: StrictStr
    clientRowId: StrictStr | None


PreviewT = TypeVar("PreviewT", bound=Contract)


class CorrectionPreview(Contract, Generic[PreviewT]):
    before: PreviewT
    after: PreviewT
    changedFields: list[ChangedField]
    affectedFromDate: BusinessDate
    factVersion: PositiveVersion
    expectedRevision: PositiveVersion
    fieldErrors: list[FieldErrorDto]


class TradePreviewFacts(TradeInput, FeeBreakdown):
    # A projection of proposed facts, not a newly accepted TradeRecord.
    note: Note | None


class CashPreviewFacts(CashFlowInput):
    netCashChange: Money
    note: Note | None


class InitializationPreviewFacts(Contract):
    initialCash: NonnegativeMoney
    initialPositions: list[InitializationPosition | None]


class TradeCorrectionPreview(CorrectionPreview[TradePreviewFacts]):
    pass


class CashCorrectionPreview(CorrectionPreview[CashPreviewFacts]):
    pass


class InitializationCorrectionPreview(CorrectionPreview[InitializationPreviewFacts]):
    pass
