from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.specs import get_dataset_freshness_spec, list_job_specs, list_workflow_specs
from src.ops.schemas.catalog import (
    JobSpecCatalogItem,
    OpsCatalogResponse,
    ParameterSpecResponse,
    WorkflowSpecCatalogItem,
    WorkflowStepResponse,
)


class OpsCatalogQueryService:
    @staticmethod
    def _resource_meta_for_job_spec_key(spec_key: str) -> tuple[str | None, str | None]:
        if "." not in spec_key:
            return None, None
        _, resource_key = spec_key.split(".", 1)
        if not resource_key:
            return None, None
        freshness_spec = get_dataset_freshness_spec(resource_key)
        if freshness_spec is None:
            return resource_key, None
        return resource_key, freshness_spec.display_name

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
                self._build_job_catalog_item(job_spec, bindings)
                for job_spec in list_job_specs()
            ],
            workflow_specs=[
                WorkflowSpecCatalogItem(
                    key=workflow_spec.key,
                    display_name=workflow_spec.display_name,
                    description=workflow_spec.description,
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
        resource_key, resource_display_name = self._resource_meta_for_job_spec_key(job_spec.key)
        return JobSpecCatalogItem(
            key=job_spec.key,
            display_name=job_spec.display_name,
            resource_key=resource_key,
            resource_display_name=resource_display_name,
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
