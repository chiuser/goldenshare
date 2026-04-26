__all__ = [
    "ManualActionCommandService",
    "OpsProbeCommandService",
    "OpsResolutionReleaseCommandService",
    "OpsRuntimeCommandService",
    "OpsScheduleCommandService",
    "OpsStdRuleCommandService",
    "TaskRunCommandService",
]


def __getattr__(name: str):
    if name == "ManualActionCommandService":
        from src.ops.services.manual_action_service import ManualActionCommandService

        return ManualActionCommandService
    if name == "OpsProbeCommandService":
        from src.ops.services.probe_service import OpsProbeCommandService

        return OpsProbeCommandService
    if name == "OpsResolutionReleaseCommandService":
        from src.ops.services.resolution_release_service import OpsResolutionReleaseCommandService

        return OpsResolutionReleaseCommandService
    if name == "OpsRuntimeCommandService":
        from src.ops.services.runtime_service import OpsRuntimeCommandService

        return OpsRuntimeCommandService
    if name == "OpsScheduleCommandService":
        from src.ops.services.schedule_service import OpsScheduleCommandService

        return OpsScheduleCommandService
    if name == "OpsStdRuleCommandService":
        from src.ops.services.std_rule_service import OpsStdRuleCommandService

        return OpsStdRuleCommandService
    if name == "TaskRunCommandService":
        from src.ops.services.task_run_service import TaskRunCommandService

        return TaskRunCommandService
    raise AttributeError(name)
