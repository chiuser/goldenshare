__all__ = ["OperationsScheduler", "OperationsWorker", "TaskRunDispatchOutcome", "TaskRunDispatcher"]


def __getattr__(name: str):
    if name in {"TaskRunDispatchOutcome", "TaskRunDispatcher"}:
        from src.ops.runtime.task_run_dispatcher import TaskRunDispatchOutcome, TaskRunDispatcher

        return {
            "TaskRunDispatchOutcome": TaskRunDispatchOutcome,
            "TaskRunDispatcher": TaskRunDispatcher,
        }[name]
    if name == "OperationsScheduler":
        from src.ops.runtime.scheduler import OperationsScheduler

        return OperationsScheduler
    if name == "OperationsWorker":
        from src.ops.runtime.worker import OperationsWorker

        return OperationsWorker
    raise AttributeError(name)
