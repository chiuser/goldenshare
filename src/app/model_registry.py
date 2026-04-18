from __future__ import annotations

from importlib import import_module


MODEL_MODULES: tuple[str, ...] = (
    "src.foundation.models.all_models",
    "src.platform.models.app.app_user",
    "src.platform.models.app.auth_action_token",
    "src.platform.models.app.auth_audit_log",
    "src.platform.models.app.auth_invite_code",
    "src.app.models.auth_permission",
    "src.platform.models.app.auth_refresh_token",
    "src.app.models.auth_role",
    "src.platform.models.app.auth_role_permission",
    "src.platform.models.app.auth_user_role",
    "src.ops.models.ops.config_revision",
    "src.ops.models.ops.dataset_layer_snapshot_current",
    "src.ops.models.ops.dataset_layer_snapshot_history",
    "src.ops.models.ops.dataset_pipeline_mode",
    "src.ops.models.ops.dataset_status_snapshot",
    "src.ops.models.ops.index_series_active",
    "src.ops.models.ops.job_execution",
    "src.ops.models.ops.job_execution_event",
    "src.ops.models.ops.job_execution_step",
    "src.ops.models.ops.job_schedule",
    "src.ops.models.ops.probe_rule",
    "src.ops.models.ops.probe_run_log",
    "src.ops.models.ops.resolution_release",
    "src.ops.models.ops.resolution_release_stage_status",
    "src.ops.models.ops.std_cleansing_rule",
    "src.ops.models.ops.std_mapping_rule",
    "src.ops.models.ops.sync_job_state",
    "src.ops.models.ops.sync_run_log",
)


def register_all_models() -> None:
    """Register all ORM models in the application composition root."""
    for module in MODEL_MODULES:
        import_module(module)
