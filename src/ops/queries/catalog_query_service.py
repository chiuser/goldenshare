from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.foundation.datasets.models import DatasetDefinition, DatasetInputField
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.specs import list_job_specs, list_workflow_specs
from src.ops.schemas.catalog import (
    JobSpecCatalogItem,
    OpsCatalogResponse,
    ParameterSpecResponse,
    WorkflowSpecCatalogItem,
    WorkflowStepResponse,
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
            job_specs=[
                *[
                    self._build_dataset_action_catalog_item(definition, bindings)
                    for definition in list_dataset_definitions()
                ],
                *[
                    self._build_job_catalog_item(job_spec, bindings)
                    for job_spec in list_job_specs()
                    if job_spec.category == "maintenance"
                ],
            ],
            workflow_specs=[
                WorkflowSpecCatalogItem(
                    key=workflow_spec.key,
                    display_name=workflow_spec.display_name,
                    description=workflow_spec.description,
                    domain_key="workflow",
                    domain_display_name="工作流",
                    parallel_policy=workflow_spec.parallel_policy,
                    default_schedule_policy=workflow_spec.default_schedule_policy,
                    supports_schedule=workflow_spec.supports_schedule,
                    supports_manual_run=workflow_spec.supports_manual_run,
                    schedule_binding_count=bindings.get(("workflow", workflow_spec.key), {}).get("schedule_binding_count", 0),
                    active_schedule_count=bindings.get(("workflow", workflow_spec.key), {}).get("active_schedule_count", 0),
                    supported_params=[
                        ParameterSpecResponse(
                            key=param.key,
                            display_name=param.display_name,
                            param_type=param.param_type,
                            description=param.description,
                            required=param.required,
                            options=list(param.options),
                            multi_value=param.multi_value,
                        )
                        for param in workflow_spec.supported_params
                    ],
                    steps=[
                        WorkflowStepResponse(
                            step_key=step.step_key,
                            job_key=step.job_key,
                            display_name=step.display_name,
                            depends_on=list(step.depends_on),
                            default_params=step.default_params,
                        )
                        for step in workflow_spec.steps
                    ],
                )
                for workflow_spec in list_workflow_specs()
            ],
        )

    def _build_job_catalog_item(self, job_spec, bindings: dict[tuple[str, str], dict[str, int]]) -> JobSpecCatalogItem:
        return JobSpecCatalogItem(
            key=job_spec.key,
            spec_type="job",
            display_name=job_spec.display_name,
            resource_key=None,
            resource_display_name=None,
            domain_key=job_spec.category,
            domain_display_name="维护动作" if job_spec.category == "maintenance" else job_spec.category,
            date_selection_rule=None,
            category=job_spec.category,
            description=job_spec.description,
            strategy_type=job_spec.strategy_type,
            executor_kind=job_spec.executor_kind,
            target_tables=list(job_spec.target_tables),
            supports_manual_run=job_spec.supports_manual_run,
            supports_schedule=job_spec.supports_schedule,
            supports_retry=job_spec.supports_retry,
            schedule_binding_count=bindings.get(("job", job_spec.key), {}).get("schedule_binding_count", 0),
            active_schedule_count=bindings.get(("job", job_spec.key), {}).get("active_schedule_count", 0),
            supported_params=[
                ParameterSpecResponse(
                    key=param.key,
                    display_name=param.display_name,
                    param_type=param.param_type,
                    description=param.description,
                    required=param.required,
                    options=list(param.options),
                    multi_value=param.multi_value,
                )
                for param in job_spec.supported_params
            ],
        )

    def _build_dataset_action_catalog_item(
        self,
        definition: DatasetDefinition,
        bindings: dict[tuple[str, str], dict[str, int]],
    ) -> JobSpecCatalogItem:
        action = definition.capabilities.get_action("maintain")
        action_key = definition.action_key("maintain")
        return JobSpecCatalogItem(
            key=action_key,
            spec_type="dataset_action",
            display_name=definition.action_display_name("maintain"),
            resource_key=definition.dataset_key,
            resource_display_name=definition.display_name,
            domain_key=definition.domain.domain_key,
            domain_display_name=definition.domain.domain_display_name,
            date_selection_rule=definition.date_model.selection_rule(),
            category=definition.domain.domain_key,
            description=definition.identity.description,
            strategy_type="dataset_maintain",
            executor_kind="dataset_action",
            target_tables=[definition.storage.target_table],
            supports_manual_run=bool(action and action.manual_enabled),
            supports_schedule=bool(action and action.schedule_enabled),
            supports_retry=bool(action and action.retry_enabled),
            schedule_binding_count=bindings.get(("dataset_action", action_key), {}).get("schedule_binding_count", 0),
            active_schedule_count=bindings.get(("dataset_action", action_key), {}).get("active_schedule_count", 0),
            supported_params=[
                self._build_dataset_parameter(field)
                for field in (*definition.input_model.time_fields, *definition.input_model.filters)
            ],
        )

    @staticmethod
    def _build_dataset_parameter(field: DatasetInputField) -> ParameterSpecResponse:
        return ParameterSpecResponse(
            key=field.name,
            display_name=field.display_label,
            param_type=field.input_control_type,
            description=field.description,
            required=field.required,
            options=list(field.enum_values),
            multi_value=field.multi_value,
        )
