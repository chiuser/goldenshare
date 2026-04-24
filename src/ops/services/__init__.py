__all__ = [
    "OpsExecutionCommandService",
    "ManualActionCommandService",
    "OpsProbeCommandService",
    "OpsResolutionReleaseCommandService",
    "OpsRuntimeCommandService",
    "OpsScheduleCommandService",
    "OpsStdRuleCommandService",
]


def __getattr__(name: str):
    if name == "OpsExecutionCommandService":
        from src.ops.services.execution_service import OpsExecutionCommandService

        return OpsExecutionCommandService
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
    raise AttributeError(name)
