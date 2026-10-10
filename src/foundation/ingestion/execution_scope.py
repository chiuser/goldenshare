"""Dispatch frozen intent contracts by the Definition's named execution policy."""

from src.foundation.ingestion.announcement_scope import (
    freeze_execution as freeze_announcement_execution,
)
from src.foundation.ingestion.stock_weekly_adj_scope import freeze_weekly_adj_execution
from src.foundation.datasets.stock_weekly_adj_contracts import WeeklyAdjContractError
from src.foundation.ingestion.errors import IngestionPlanningError, StructuredError


def freeze_execution(
    definition, *, scope, filters, previous=None, trigger_source="manual"
):
    if definition.planning.weekly_adj_policy is not None:
        if definition.planning.announcement_policy is not None:
            raise WeeklyAdjContractError("周线和公告执行合同不能同时启用")
        try:
            return freeze_weekly_adj_execution(
                definition,
                scope=scope,
                filters=filters,
                trigger_source=trigger_source,
                previous=previous,
            )
        except WeeklyAdjContractError as exc:
            raise IngestionPlanningError(
                StructuredError(
                    error_code=exc.code,
                    error_type="planning",
                    phase="resolver",
                    message=str(exc),
                    retryable=False,
                )
            ) from exc
    return freeze_announcement_execution(
        definition, scope=scope, filters=filters, previous=previous
    )


def execution_observation_timeout(execution_context):
    """Do not interpret every frozen execution as an announcement storage policy."""
    if execution_context is None:
        return None
    try:
        if execution_context.get("contract_kind") == "stock_weekly_adj/v1":
            timeout = execution_context["policy_snapshot"]["policy"][
                "observation_timeout_seconds"
            ]
        elif "contract_kind" not in execution_context:
            timeout = execution_context["policy_snapshot"]["storage"][
                "insert_lock_timeout_seconds"
            ]
        else:
            raise ValueError
        if type(timeout) is not int or timeout < 1:
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError):
        raise WeeklyAdjContractError("冻结执行合同缺少有效观测预算") from None
    return timeout
