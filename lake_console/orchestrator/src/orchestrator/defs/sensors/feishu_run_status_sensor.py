from collections.abc import Mapping

import dagster as dg

from orchestrator.defs.notifications.feishu import FeishuWebhookResource, truncate_text
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


DAGSTER_PARTITION_TAG = "dagster/partition"
DAGSTER_BACKFILL_TAG = "dagster/backfill"
DAGSTER_FROM_UI_TAG = "dagster/from_ui"
DAGSTER_SCHEDULE_TAG = "dagster/schedule_name"
DAGSTER_SENSOR_TAG = "dagster/sensor_name"
FAILURE_DETAIL_MAX_LENGTH = 1200


def _tag_value(tags: Mapping[str, str], key: str) -> str:
    value = tags.get(key)
    return value if value else "-"


def _trigger_value(tags: Mapping[str, str]) -> str:
    for key in (DAGSTER_SENSOR_TAG, DAGSTER_SCHEDULE_TAG):
        value = tags.get(key)
        if value:
            return value
    if tags.get(DAGSTER_FROM_UI_TAG) == "true":
        return "ui"
    return "-"


def _failure_detail(context: dg.RunFailureSensorContext) -> str:
    details = []
    if context.failure_event.message:
        details.append(context.failure_event.message)

    try:
        step_failure_events = context.get_step_failure_events()
    except Exception as exc:
        details.append(f"Unable to load step failure events: {type(exc).__name__}: {exc}")
    else:
        failed_steps = tuple(
            step_key
            for event in step_failure_events
            if (step_key := getattr(event, "step_key", None))
        )
        if failed_steps:
            details.append(f"Failed steps: {', '.join(failed_steps[:10])}")
            if len(failed_steps) > 10:
                details.append(f"Additional failed step count: {len(failed_steps) - 10}")

        for event in step_failure_events[:1]:
            if event.message and event.message not in details:
                details.append(event.message)

    if not details:
        return "-"
    return truncate_text("\n".join(details), FAILURE_DETAIL_MAX_LENGTH)


def _run_status_alert_text(
    *,
    context: dg.RunStatusSensorContext,
    feishu: FeishuWebhookResource,
    title: str,
    detail_label: str | None = None,
    detail: str | None = None,
) -> str:
    dagster_run = context.dagster_run
    tags = dagster_run.tags
    partition_key = context.partition_key or _tag_value(tags, DAGSTER_PARTITION_TAG)
    run_url = feishu.run_url(dagster_run.run_id)

    lines = [
        title,
        f"Job: {dagster_run.job_name}",
        f"Run ID: {dagster_run.run_id}",
        f"Status: {dagster_run.status.value}",
        f"Partition: {partition_key}",
        f"Backfill: {_tag_value(tags, DAGSTER_BACKFILL_TAG)}",
        f"Trigger: {_trigger_value(tags)}",
    ]
    if detail_label and detail:
        lines.append(f"{detail_label}: {detail}")
    if run_url:
        lines.append(f"Run URL: {run_url}")
    return "\n".join(lines)


def _send_run_status_alert(
    *,
    context: dg.RunStatusSensorContext,
    feishu: FeishuWebhookResource,
    title: str,
    detail_label: str | None = None,
    detail: str | None = None,
) -> None:
    try:
        feishu.send_text(
            _run_status_alert_text(
                context=context,
                feishu=feishu,
                title=title,
                detail_label=detail_label,
                detail=detail,
            )
        )
    except Exception:
        context.log.exception(
            "Failed to send Feishu run status alert for run %s.",
            context.dagster_run.run_id,
        )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.STARTED,
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.PLATFORM_OBSERVABILITY,
        target_layer=SensorTargetLayer.PLATFORM,
        role=SensorRole.RUN_STATUS_NOTIFICATION,
    ),
    description="Dagster run 启动时发送飞书自定义机器人告警。",
)
def feishu_run_started_sensor(
    context: dg.RunStatusSensorContext,
    feishu: FeishuWebhookResource,
) -> None:
    _send_run_status_alert(
        context=context,
        feishu=feishu,
        title="Dagster run started",
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.PLATFORM_OBSERVABILITY,
        target_layer=SensorTargetLayer.PLATFORM,
        role=SensorRole.RUN_STATUS_NOTIFICATION,
    ),
    description="Dagster run 成功时发送飞书自定义机器人告警。",
)
def feishu_run_succeeded_sensor(
    context: dg.RunStatusSensorContext,
    feishu: FeishuWebhookResource,
) -> None:
    _send_run_status_alert(
        context=context,
        feishu=feishu,
        title="Dagster run succeeded",
    )


@dg.run_failure_sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.PLATFORM_OBSERVABILITY,
        target_layer=SensorTargetLayer.PLATFORM,
        role=SensorRole.RUN_STATUS_NOTIFICATION,
    ),
    description="Dagster run 失败时发送飞书自定义机器人告警。",
)
def feishu_run_failed_sensor(
    context: dg.RunFailureSensorContext,
    feishu: FeishuWebhookResource,
) -> None:
    _send_run_status_alert(
        context=context,
        feishu=feishu,
        title="Dagster run failed",
        detail_label="Failure",
        detail=_failure_detail(context),
    )
