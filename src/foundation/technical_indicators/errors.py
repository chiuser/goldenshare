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


class ResourceCleanupError(TechnicalIndicatorError):
    pass
