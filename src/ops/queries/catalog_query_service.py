from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.foundation.datasets.models import DatasetDefinition, DatasetInputField
from src.foundation.datasets.registry import list_dataset_definitions
from src.foundation.datasets.source_registry import list_source_selection_definitions
from src.ops.catalog.dataset_catalog_view_resolver import DatasetCatalogViewResolver
from src.ops.action_catalog import (
    MaintenanceActionDefinition,
    WorkflowDefinition,
    dataset_field_default_value,
    list_maintenance_actions,
    list_workflow_definitions,
)
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.schemas.catalog import (
    ActionCatalogItem,
    ActionParameterResponse,
    OpsCatalogResponse,
    SourceCatalogItem,
    WorkflowCatalogItem,
    WorkflowStepCatalogItem,
)


class OpsCatalogQueryService:
    def build_catalog(self, session: Session) -> OpsCatalogResponse:
        binding_rows = session.execute(
            select(
                OpsSchedule.target_type,
                OpsSchedule.target_key,
                func.count(OpsSchedule.id),
                func.sum(case((OpsSchedule.status == "active", 1), else_=0)),
            )
            .group_by(OpsSchedule.target_type, OpsSchedule.target_key)
        ).all()
        bindings = {
            (target_type, target_key): {
                "schedule_binding_count": total or 0,
                "active_schedule_count": active or 0,
            }
            for target_type, target_key, total, active in binding_rows
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
                    group_key=workflow.domain_key,
                    group_label=workflow.domain_display_name,
                    group_order=workflow.group_order,
                    domain_key=workflow.domain_key,
                    domain_display_name=workflow.domain_display_name,
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
                            default_value=param.default_value,
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
            sources=[
                SourceCatalogItem(source_key=source.source_key, display_name=source.display_name)
                for source in list_source_selection_definitions(include_all=True)
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
            group_key=action.domain_key,
            group_label=action.domain_display_name,
            group_order=70,
            item_order=100,
            domain_key=action.domain_key,
            domain_display_name=action.domain_display_name,
            date_selection_rule=None,
            description=action.description,
            target_tables=list(action.target_tables),
            manual_enabled=action.manual_enabled,
            schedule_enabled=action.schedule_enabled,
            retry_enabled=action.retry_enabled,
            schedule_binding_count=bindings.get(("maintenance_action", action.key), {}).get("schedule_binding_count", 0),
            active_schedule_count=bindings.get(("maintenance_action", action.key), {}).get("active_schedule_count", 0),
            parameters=[
                ActionParameterResponse(
                    key=param.key,
                    display_name=param.display_name,
                    param_type=param.param_type,
                    description=param.description,
                    required=param.required,
                    options=list(param.options),
                    multi_value=param.multi_value,
                    default_value=param.default_value,
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
        catalog_item = DatasetCatalogViewResolver().resolve_item(definition.dataset_key)
        return ActionCatalogItem(
            key=action_key,
            action_type="dataset_action",
            display_name=definition.action_display_name("maintain"),
            target_key=definition.dataset_key,
            target_display_name=definition.display_name,
            group_key=catalog_item.group_key,
            group_label=catalog_item.group_label,
            group_order=catalog_item.group_order,
            item_order=catalog_item.item_order,
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
                self._build_dataset_parameter(
                    field,
                    enum_fanout_defaults=definition.planning.enum_fanout_defaults,
                )
                for field in (*definition.input_model.time_fields, *definition.input_model.filters)
            ],
        )

    @staticmethod
    def _build_dataset_parameter(
        field: DatasetInputField,
        *,
        enum_fanout_defaults: dict[str, tuple[str, ...]],
    ) -> ActionParameterResponse:
        return ActionParameterResponse(
            key=field.name,
            display_name=field.display_label,
            param_type=field.input_control_type,
            description=field.description,
            required=field.required,
            options=list(field.enum_values),
            multi_value=field.multi_value,
            default_value=dataset_field_default_value(field, enum_fanout_defaults),
        )
