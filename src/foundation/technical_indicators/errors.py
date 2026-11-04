"""Internal kernel errors; HTTP error codes belong to the consumer."""

import traceback


def _clear_error_frames(error: BaseException) -> None:
    """Release ended frames while preserving error identity and diagnostics."""
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__traceback__ is not None:
            traceback.clear_frames(current.__traceback__)


class TechnicalIndicatorError(Exception):
    """Base error, retaining the original exception through normal chaining."""


class RequestInvalidError(TechnicalIndicatorError, ValueError):
    pass


class CalculationUnsupportedError(TechnicalIndicatorError):
    pass


class SourceUnsupportedError(TechnicalIndicatorError):
    pass


class SourceContractError(TechnicalIndicatorError):
    pass


class SourceReadError(TechnicalIndicatorError):
    pass


class CalculationExecutionError(TechnicalIndicatorError):
    pass


class ResourceLimitError(TechnicalIndicatorError):
    pass


class CapacityBusyError(TechnicalIndicatorError):
    pass


class WaitExpiredError(TechnicalIndicatorError):
    pass


class CalculationCancelledError(TechnicalIndicatorError):
    pass


class CalculationDeadlineError(TechnicalIndicatorError):
    pass


class OutputEncodingError(TechnicalIndicatorError):
    pass


class OutputReadError(TechnicalIndicatorError):
    """A fixed output query/fetch failed; retain bounded diagnostic context."""

    def __init__(self, message, *, reason, stage, step_name):
        super().__init__(message)
        self.reason, self.stage, self.step_name = reason, stage, step_name


class OutputContractError(TechnicalIndicatorError):
    """An internal result is missing a declared item, field or time position."""

    def __init__(self, message, *, reason, stage, instance_id=None, **diagnostics):
        super().__init__(message)
        self.reason, self.stage, self.instance_id = reason, stage, instance_id
        self.diagnostics = diagnostics


class ResourceCleanupError(TechnicalIndicatorError):
    pass
