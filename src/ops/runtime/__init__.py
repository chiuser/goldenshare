__all__ = ["DispatchOutcome", "OperationsDispatcher", "OperationsScheduler", "OperationsWorker"]


def __getattr__(name: str):
    if name in {"DispatchOutcome", "OperationsDispatcher"}:
        from src.ops.runtime.dispatcher import DispatchOutcome, OperationsDispatcher

        return {
            "DispatchOutcome": DispatchOutcome,
            "OperationsDispatcher": OperationsDispatcher,
        }[name]
    if name == "OperationsScheduler":
        from src.ops.runtime.scheduler import OperationsScheduler

        return OperationsScheduler
    if name == "OperationsWorker":
        from src.ops.runtime.worker import OperationsWorker

        return OperationsWorker
    raise AttributeError(name)
