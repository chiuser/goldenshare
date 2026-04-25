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
        spec_key = f"{definition.dataset_key}.maintain"
        return JobSpecCatalogItem(
            key=spec_key,
            spec_type="dataset_action",
            display_name=f"维护{definition.display_name}",
            resource_key=definition.dataset_key,
            resource_display_name=definition.display_name,
            category=definition.domain.domain_key,
            description=definition.identity.description,
            strategy_type="dataset_maintain",
            executor_kind="dataset_action",
            target_tables=[definition.storage.target_table],
            supports_manual_run=bool(action and action.manual_enabled),
            supports_schedule=bool(action and action.schedule_enabled),
            supports_retry=bool(action and action.retry_enabled),
            schedule_binding_count=bindings.get(("dataset_action", spec_key), {}).get("schedule_binding_count", 0),
            active_schedule_count=bindings.get(("dataset_action", spec_key), {}).get("active_schedule_count", 0),
            supported_params=[
                self._build_dataset_parameter(field)
                for field in (*definition.input_model.time_fields, *definition.input_model.filters)
            ],
        )

    @staticmethod
    def _build_dataset_parameter(field: DatasetInputField) -> ParameterSpecResponse:
        return ParameterSpecResponse(
            key=field.name,
            display_name=OpsCatalogQueryService._field_display_name(field.name),
            param_type=OpsCatalogQueryService._field_param_type(field),
            description=field.description,
            required=field.required,
            options=list(field.enum_values),
            multi_value=field.multi_value,
        )

    @staticmethod
    def _field_param_type(field: DatasetInputField) -> str:
        if field.name in {"month", "start_month", "end_month"}:
            return "month"
        if field.field_type == "date" or field.name.endswith("_date") or field.name in {"date", "cal_date"}:
            return "date"
        if field.field_type in {"integer", "int"}:
            return "integer"
        if field.field_type in {"boolean", "bool"}:
            return "boolean"
        if field.enum_values:
            return "enum"
        return "string"

    @staticmethod
    def _field_display_name(field_name: str) -> str:
        labels = {
            "trade_date": "处理日期",
            "start_date": "开始日期",
            "end_date": "结束日期",
            "month": "月份",
            "start_month": "开始月份",
            "end_month": "结束月份",
            "ts_code": "证券代码",
            "index_code": "指数代码",
            "con_code": "板块代码",
            "market": "市场",
            "hot_type": "热点类型",
            "is_new": "日终标记",
            "limit_type": "榜单类型",
            "exchange": "交易所",
            "exchange_id": "交易所",
            "content_type": "板块类型",
            "tag": "榜单标签",
            "ann_date": "公告日期",
            "date_field": "日期字段",
        }
        return labels.get(field_name, field_name)
