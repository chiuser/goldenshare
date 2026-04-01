__all__ = ["DispatchOutcome", "OperationsDispatcher", "OperationsScheduler", "OperationsWorker"]


def __getattr__(name: str):
    if name in {"DispatchOutcome", "OperationsDispatcher"}:
        from src.operations.runtime.dispatcher import DispatchOutcome, OperationsDispatcher

        return {
            "DispatchOutcome": DispatchOutcome,
            "OperationsDispatcher": OperationsDispatcher,
        }[name]
    if name == "OperationsScheduler":
        from src.operations.runtime.scheduler import OperationsScheduler

        return OperationsScheduler
    if name == "OperationsWorker":
        from src.operations.runtime.worker import OperationsWorker

        return OperationsWorker
    raise AttributeError(name)
