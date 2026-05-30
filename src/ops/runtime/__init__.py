__all__ = [
    "OperationsScheduler",
    "OperationsWorker",
    "TaskRunCompletionWorker",
    "TaskRunDispatchOutcome",
    "TaskRunDispatcher",
]


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
    if name == "TaskRunCompletionWorker":
        from src.ops.runtime.task_completion_worker import TaskRunCompletionWorker

        return TaskRunCompletionWorker
    raise AttributeError(name)
