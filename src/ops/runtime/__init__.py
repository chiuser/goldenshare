__all__ = [
    "OperationsScheduler",
    "OperationsWorker",
    "TaskRunCompletionWorker",
    "TaskRunDispatchOutcome",
    "TaskRunDispatcher",
    "WorkerLane",
    "MaintenanceExecutionPlan",
    "MaintenanceExecutionRequest",
    "MaintenanceExecutionResult",
    "MaintenanceExecutionUnit",
    "MaintenanceExecutor",
]


def __getattr__(name: str):
    if name in {
        "MaintenanceExecutionPlan",
        "MaintenanceExecutionRequest",
        "MaintenanceExecutionResult",
        "MaintenanceExecutionUnit",
        "MaintenanceExecutor",
    }:
        from src.ops.runtime.maintenance_executor import (
            MaintenanceExecutionPlan,
            MaintenanceExecutionRequest,
            MaintenanceExecutionResult,
            MaintenanceExecutionUnit,
            MaintenanceExecutor,
        )

        return {
            "MaintenanceExecutionPlan": MaintenanceExecutionPlan,
            "MaintenanceExecutionRequest": MaintenanceExecutionRequest,
            "MaintenanceExecutionResult": MaintenanceExecutionResult,
            "MaintenanceExecutionUnit": MaintenanceExecutionUnit,
            "MaintenanceExecutor": MaintenanceExecutor,
        }[name]
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
    if name == "WorkerLane":
        from src.ops.runtime.worker_lane import WorkerLane

        return WorkerLane
    raise AttributeError(name)
