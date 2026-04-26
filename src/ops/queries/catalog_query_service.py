from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.foundation.datasets.models import DatasetDefinition, DatasetInputField
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.action_catalog import (
    MaintenanceActionDefinition,
    WorkflowDefinition,
    list_maintenance_actions,
    list_workflow_definitions,
)
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.schemas.catalog import (
    ActionCatalogItem,
    ActionParameterResponse,
    OpsCatalogResponse,
    WorkflowCatalogItem,
    WorkflowStepCatalogItem,
)


class OpsCatalogQueryService:
    def build_catalog(self, session: Session) -> OpsCatalogResponse:
        binding_rows = session.execute(
            select(
                JobSchedule.spec_type,
                JobSchedule.spec_key,
                func.count(JobSchedule.id),
                func.sum(case((JobSchedule.status == "active", 1), else_=0)),
            )
            .group_by(JobSchedule.spec_type, JobSchedule.spec_key)
        ).all()
        bindings = {
            (spec_type, spec_key): {
                "schedule_binding_count": total or 0,
                "active_schedule_count": active or 0,
            }
            for spec_type, spec_key, total, active in binding_rows
        }
        return OpsCatalogResponse(
            actions=[
                *[
                    self._build_dataset_action_catalog_item(definition, bindings)
                    for definition in list_dataset_definitions()
                ],
                *[
                    self._build_maintenance_action_catalog_item(action, bindings)
                    for action in list_maintenance_actions()
                ],
            ],
            workflows=[
                WorkflowCatalogItem(
                    key=workflow.key,
                    display_name=workflow.display_name,
                    description=workflow.description,
                    domain_key="workflow",
                    domain_display_name="工作流",
                    parallel_policy=workflow.parallel_policy,
                    default_schedule_policy=workflow.default_schedule_policy,
                    schedule_enabled=workflow.schedule_enabled,
                    manual_enabled=workflow.manual_enabled,
                    schedule_binding_count=bindings.get(("workflow", workflow.key), {}).get("schedule_binding_count", 0),
                    active_schedule_count=bindings.get(("workflow", workflow.key), {}).get("active_schedule_count", 0),
                    parameters=[
                        ActionParameterResponse(
                            key=param.key,
                            display_name=param.display_name,
                            param_type=param.param_type,
                            description=param.description,
                            required=param.required,
                            options=list(param.options),
                            multi_value=param.multi_value,
                        )
                        for param in workflow.parameters
                    ],
                    steps=[
                        WorkflowStepCatalogItem(
                            step_key=step.step_key,
                            action_key=step.action_key,
                            display_name=step.display_name,
                            dataset_key=step.dataset_key,
                            depends_on=list(step.depends_on),
                            default_params=step.default_params,
                        )
                        for step in workflow.steps
                    ],
                )
                for workflow in list_workflow_definitions()
            ],
        )

    def _build_maintenance_action_catalog_item(
        self,
        action: MaintenanceActionDefinition,
        bindings: dict[tuple[str, str], dict[str, int]],
    ) -> ActionCatalogItem:
        return ActionCatalogItem(
            key=action.key,
            action_type="maintenance_action",
            display_name=action.display_name,
            target_key=action.key,
            target_display_name=action.display_name,
            domain_key=action.domain_key,
            domain_display_name=action.domain_display_name,
            date_selection_rule=None,
            description=action.description,
            target_tables=list(action.target_tables),
            manual_enabled=action.manual_enabled,
            schedule_enabled=action.schedule_enabled,
            retry_enabled=action.retry_enabled,
            schedule_binding_count=bindings.get(("job", action.key), {}).get("schedule_binding_count", 0),
            active_schedule_count=bindings.get(("job", action.key), {}).get("active_schedule_count", 0),
            parameters=[
                ActionParameterResponse(
                    key=param.key,
                    display_name=param.display_name,
                    param_type=param.param_type,
                    description=param.description,
                    required=param.required,
                    options=list(param.options),
                    multi_value=param.multi_value,
                )
                for param in action.parameters
            ],
        )

    def _build_dataset_action_catalog_item(
        self,
        definition: DatasetDefinition,
        bindings: dict[tuple[str, str], dict[str, int]],
    ) -> ActionCatalogItem:
        action = definition.capabilities.get_action("maintain")
        action_key = definition.action_key("maintain")
        return ActionCatalogItem(
            key=action_key,
            action_type="dataset_action",
            display_name=definition.action_display_name("maintain"),
            target_key=definition.dataset_key,
            target_display_name=definition.display_name,
            domain_key=definition.domain.domain_key,
            domain_display_name=definition.domain.domain_display_name,
            date_selection_rule=definition.date_model.selection_rule(),
            description=definition.identity.description,
            target_tables=[definition.storage.target_table],
            manual_enabled=bool(action and action.manual_enabled),
            schedule_enabled=bool(action and action.schedule_enabled),
            retry_enabled=bool(action and action.retry_enabled),
            schedule_binding_count=bindings.get(("dataset_action", action_key), {}).get("schedule_binding_count", 0),
            active_schedule_count=bindings.get(("dataset_action", action_key), {}).get("active_schedule_count", 0),
            parameters=[
                self._build_dataset_parameter(field)
                for field in (*definition.input_model.time_fields, *definition.input_model.filters)
            ],
        )

    @staticmethod
    def _build_dataset_parameter(field: DatasetInputField) -> ActionParameterResponse:
        return ActionParameterResponse(
            key=field.name,
            display_name=field.display_label,
            param_type=field.input_control_type,
            description=field.description,
            required=field.required,
            options=list(field.enum_values),
            multi_value=field.multi_value,
        )
