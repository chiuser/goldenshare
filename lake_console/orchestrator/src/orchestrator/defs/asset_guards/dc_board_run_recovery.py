"""Bounded native run evidence for DC recovery; cursors never own retry quota."""

import math
from dataclasses import dataclass
from datetime import datetime

import dagster as dg
from dagster._core.storage.tags import PARTITION_NAME_TAG, RUN_KEY_TAG, SENSOR_NAME_TAG

from orchestrator.defs.run_contracts.configs import DcBoardRecoveryIdentityConfig
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_AUTO_MAX_ATTEMPTS,
    DC_BOARD_AUTO_RETRY_COOLDOWN_SECONDS,
    DC_BOARD_FAILURE_SAMPLE_LIMIT,
    DC_BOARD_RECOVERY_POLICY_VERSION,
    DC_BOARD_RECOVERY_RUN_RECORD_LIMIT,
)
from orchestrator.defs.run_contracts.run_keys import (
    build_asset_update_run_key,
    build_repair_attempt_run_key,
)

_TERMINAL = {
    dg.DagsterRunStatus.SUCCESS,
    dg.DagsterRunStatus.FAILURE,
    dg.DagsterRunStatus.CANCELED,
}
_ACTIVE = [status for status in dg.DagsterRunStatus if status not in _TERMINAL]
_RETRY_REASONS = {
    "source_response_unclassified",
    "source_transient",
    "source_rate_limit",
}


@dataclass(frozen=True)
class DcBoardRecoveryDecision:
    reason_code: str
    identity: DcBoardRecoveryIdentityConfig | None = None

    @property
    def allowed(self) -> bool:
        return self.identity is not None


def read_dc_run_history(
    instance, *, job_name: str, trade_date: str, exclude_run_id=None
):
    """One job-wide active query and one partition query; no pagination/full scan."""
    active = instance.get_run_records(
        filters=dg.RunsFilter(job_name=job_name, statuses=_ACTIVE),
        limit=2,
    )
    if any(record.dagster_run.run_id != exclude_run_id for record in active):
        return "active_run", ()
    records = instance.get_run_records(
        filters=dg.RunsFilter(job_name=job_name, tags={PARTITION_NAME_TAG: trade_date}),
        limit=DC_BOARD_RECOVERY_RUN_RECORD_LIMIT + 1,
    )
    if len(records) > DC_BOARD_RECOVERY_RUN_RECORD_LIMIT:
        return "run_history_truncated", ()
    return None, tuple(
        record for record in records if record.dagster_run.run_id != exclude_run_id
    )


def _automatic_attempt(run, *, job_name, trade_date):
    """Compare generated native keys; never decode keys into execution parameters."""
    asset = job_name.removesuffix("_update_job")
    config = run.run_config.get("ops", {}).get(asset, {}).get("config", {})
    identity_data = config.get("recovery_identity")
    key = run.tags.get(RUN_KEY_TAG)
    subject = job_name.removesuffix("_job")
    first_key = build_asset_update_run_key(subject=subject, unit_id=trade_date)
    automatic_keys = {first_key: 1}
    automatic_keys.update({
        build_repair_attempt_run_key(subject=subject, repair_scope_id=trade_date, attempt=attempt): attempt
        for attempt in range(2, DC_BOARD_AUTO_MAX_ATTEMPTS + 1)
    })
    if identity_data is None:
        if (
            key == first_key
            and run.tags.get(SENSOR_NAME_TAG) == job_name + "_sensor"
        ):
            if "source_proof" in config or run.parent_run_id or run.root_run_id:
                raise ValueError("automatic identity missing")
            return (
                1,
                None,
            )  # historical first fixed-key run; never authorize from its config
        if key in automatic_keys:
            raise ValueError("automatic key without valid identity")
        return None, None
    identity = DcBoardRecoveryIdentityConfig.model_validate(identity_data)
    if (
        run.job_name != job_name
        or run.tags.get(PARTITION_NAME_TAG) != trade_date
        or run.tags.get(SENSOR_NAME_TAG) != job_name + "_sensor"
        or automatic_keys.get(key) != identity.automatic_attempt
        or run.parent_run_id
        or run.root_run_id
        or run.remote_job_origin is None
        or run.remote_job_origin.job_name != job_name
        or "source_proof" not in config
    ):
        raise ValueError("automatic run provenance mismatch")
    return identity.automatic_attempt, identity


def retryable_dc_failure(instance, record, *, asset_name: str) -> bool:
    """Every failed step must supply complete, correctly typed facts for this asset."""
    connection = instance.get_records_for_run(
        record.dagster_run.run_id,
        of_type=dg.DagsterEventType.STEP_FAILURE,
        limit=DC_BOARD_RECOVERY_RUN_RECORD_LIMIT + 1,
    )
    if (
        not connection.records
        or connection.has_more
        or len(connection.records) > DC_BOARD_RECOVERY_RUN_RECORD_LIMIT
    ):
        return False
    for item in connection.records:
        event = item.event_log_entry.dagster_event
        if event is None or event.step_key != asset_name:
            return False
        failure = event.step_failure_data.user_failure_data
        if failure is None:
            return False
        metadata = {key: value.value for key, value in failure.metadata.items()}
        required = {
            "failure_policy_version",
            "reason_code",
            "request_retryable",
            "partition_retryable",
            "failed_count",
            "unattempted_count",
            "request_count",
            "retry_count",
            "budget_exceeded",
            "budget_reason",
            "failure_samples",
        }
        if not required <= metadata.keys():
            return False
        if (
            metadata["failure_policy_version"] != DC_BOARD_RECOVERY_POLICY_VERSION
            or metadata["reason_code"] not in _RETRY_REASONS
            or metadata["request_retryable"] is not True
            or metadata["partition_retryable"] is not True
            or metadata["budget_exceeded"] is not False
            or metadata["budget_reason"] is not None
        ):
            return False
        if any(
            type(metadata[key]) is not int or metadata[key] < 0
            for key in (
                "failed_count",
                "unattempted_count",
                "request_count",
                "retry_count",
            )
        ):
            return False
        samples = metadata["failure_samples"]
        if (
            metadata["failed_count"] <= 0
            or metadata["unattempted_count"] != 0
            or metadata["request_count"] < metadata["failed_count"]
            or metadata["retry_count"] > metadata["request_count"]
            or not isinstance(samples, list)
            or len(samples) > DC_BOARD_FAILURE_SAMPLE_LIMIT
            or len(samples)
            != min(metadata["failed_count"], DC_BOARD_FAILURE_SAMPLE_LIMIT)
            or any(
                not isinstance(code, str) or not code or len(code) > 128
                for code in samples
            )
        ):
            return False
    return True


def select_dc_recovery(
    records,
    *,
    job_name: str,
    trade_date: str,
    now: datetime,
    allow_recovery=True,
    failure_retryable: bool | None = None,
) -> DcBoardRecoveryDecision:
    """Input is newest-first bounded records; physical readiness already selected a gap."""
    if now.tzinfo is None:
        raise ValueError("recovery time must include timezone")
    if not records:
        return DcBoardRecoveryDecision(
            "request_run",
            DcBoardRecoveryIdentityConfig(
                policy_version=DC_BOARD_RECOVERY_POLICY_VERSION, automatic_attempt=1
            ),
        )
    automatic = {}
    identities = {}
    previous_record = None
    for record in reversed(records):
        run = record.dagster_run
        if run.status not in _TERMINAL:
            return DcBoardRecoveryDecision(
                "active_run" if run.status in _ACTIVE else "unknown_run_status"
            )
        if run.status == dg.DagsterRunStatus.SUCCESS:
            return DcBoardRecoveryDecision("success_file_missing")
        try:
            attempt, identity = _automatic_attempt(
                run, job_name=job_name, trade_date=trade_date
            )
        except (ValueError, TypeError, AttributeError):
            return DcBoardRecoveryDecision("recovery_identity_invalid")
        if attempt is not None:
            if attempt in automatic or attempt != len(automatic) + 1:
                return DcBoardRecoveryDecision("recovery_identity_invalid")
            if identity is not None and attempt > 1:
                previous = automatic[attempt - 1]
                if (
                    identity.source_failure_run_id != previous.dagster_run.run_id
                    or previous is not previous_record
                    or identities[attempt - 1] is None
                    or previous.dagster_run.status != dg.DagsterRunStatus.FAILURE
                ):
                    return DcBoardRecoveryDecision("recovery_identity_invalid")
            automatic[attempt] = record
            identities[attempt] = identity
        previous_record = record
    latest = records[0]
    if latest.dagster_run.status == dg.DagsterRunStatus.CANCELED:
        return DcBoardRecoveryDecision("canceled_requires_review")
    if not allow_recovery:
        return DcBoardRecoveryDecision("failed_requires_review")
    attempt = len(automatic)
    if (
        not attempt
        or automatic[attempt].dagster_run.run_id != latest.dagster_run.run_id
    ):
        return DcBoardRecoveryDecision("manual_failure_requires_review")
    if attempt >= DC_BOARD_AUTO_MAX_ATTEMPTS:
        return DcBoardRecoveryDecision("automatic_attempts_exhausted")
    if identities[attempt] is None:
        return DcBoardRecoveryDecision("legacy_requires_review")
    if failure_retryable is None:
        return DcBoardRecoveryDecision("failure_metadata_required")
    if not failure_retryable:
        return DcBoardRecoveryDecision("failure_requires_review")
    end = latest.end_time
    if type(end) not in (float, int) or not math.isfinite(end) or end > now.timestamp():
        return DcBoardRecoveryDecision("failure_end_time_invalid")
    if now.timestamp() - end < DC_BOARD_AUTO_RETRY_COOLDOWN_SECONDS[attempt - 1]:
        return DcBoardRecoveryDecision("recovery_cooldown")
    return DcBoardRecoveryDecision(
        "request_recovery",
        DcBoardRecoveryIdentityConfig(
            policy_version=DC_BOARD_RECOVERY_POLICY_VERSION,
            automatic_attempt=attempt + 1,
            source_failure_run_id=latest.dagster_run.run_id,
        ),
    )


def dc_recovery_decision(
    instance, *, job_name, trade_date, now, allow_recovery=True, exclude_run_id=None
):
    try:
        reason, records = read_dc_run_history(
            instance,
            job_name=job_name,
            trade_date=trade_date,
            exclude_run_id=exclude_run_id,
        )
        if reason:
            return DcBoardRecoveryDecision(reason)
        decision = select_dc_recovery(
            records,
            job_name=job_name,
            trade_date=trade_date,
            now=now,
            allow_recovery=allow_recovery,
        )
        if decision.reason_code != "failure_metadata_required":
            return decision
        qualified = retryable_dc_failure(
            instance, records[0], asset_name=job_name.removesuffix("_update_job")
        )
        return select_dc_recovery(
            records,
            job_name=job_name,
            trade_date=trade_date,
            now=now,
            allow_recovery=allow_recovery,
            failure_retryable=qualified,
        )
    except Exception:  # noqa: BLE001 -- Missing or unreadable evidence never grants execution.
        return DcBoardRecoveryDecision("run_evidence_unavailable")


def validate_dc_running_identity(context, identity, *, asset_name: str, now: datetime):
    run = context.run
    job = asset_name + "_update_job"
    if identity is None:
        if run.tags.get(SENSOR_NAME_TAG) == job + "_sensor":
            raise ValueError("automatic run requires recovery identity")
        return
    if run.status not in _ACTIVE:
        raise ValueError("current automatic run must be active")
    attempt, stored_identity = _automatic_attempt(
        run, job_name=job, trade_date=context.partition_key
    )
    if attempt != identity.automatic_attempt or stored_identity != identity:
        raise ValueError("current automatic run identity mismatch")
    decision = dc_recovery_decision(
        context.instance,
        job_name=job,
        trade_date=context.partition_key,
        now=now,
        exclude_run_id=run.run_id,
    )
    if not decision.allowed or decision.identity != identity:
        raise ValueError("automatic execution rejected: " + decision.reason_code)
