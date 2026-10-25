"""Internal kernel errors; HTTP error codes belong to the consumer."""


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
