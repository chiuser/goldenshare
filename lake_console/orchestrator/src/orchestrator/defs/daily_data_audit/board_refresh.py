"""Find status refreshes for Eastmoney standards and their later Checks."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

import dagster as dg
import sqlalchemy as sa
from dagster._core.storage.event_log.schema import (
    AssetCheckExecutionsTable as Checks,
)
from dagster._core.storage.event_log.schema import (
    SqlEventLogStorageTable as Events,
)

from orchestrator.defs.daily_data_audit.board_summary import (
    BOARD_CHECKS,
    RAW_CLASSIFICATION,
    RAW_MONEYFLOW,
)
from orchestrator.defs.daily_data_audit.dc_index_review import (
    BOARD_CONFIRM_JOB,
    BOARD_RECHECK_JOB,
    REVIEW_VERSION_TAG,
    read_dc_index_recheck,
    read_dc_index_standard,
)
from orchestrator.defs.daily_data_audit.evidence import (
    BUSINESS_DATE_TAG,
    load_evidence,
    metadata,
    read_summary,
)
from orchestrator.defs.daily_data_audit.registry import targets_for_day


@dataclass(frozen=True)
class BoardRefresh:
    day: date
    standard_version: str | None
    assets: tuple[str, ...]
    unit_id: str
    recheck_run_id: str | None = None


def _next_completed(instance, job_name, after):
    filters = dg.RunsFilter(
        job_name=job_name,
        statuses=[dg.DagsterRunStatus.SUCCESS],
        updated_after=datetime.fromisoformat(after) if after else None,
    )
    return next(
        iter(
            instance.get_run_records(
                filters=filters,
                order_by="update_timestamp",
                ascending=True,
                limit=1,
            )
        ),
        None,
    )


def _next_check(instance, after, previous_event_id):
    completed = Checks.c.evaluation_event_timestamp
    event_id = Checks.c.evaluation_event_storage_id
    check_names = tuple(BOARD_CHECKS.values())
    query = (
        sa.select(
            Events.c.partition,
            Checks.c.check_name,
            Checks.c.run_id,
            completed,
            event_id,
        )
        .select_from(
            Checks.join(
                Events, Checks.c.materialization_event_storage_id == Events.c.id
            )
        )
        .where(
            Checks.c.check_name.in_(check_names),
            Checks.c.asset_key.in_(
                tuple(dg.AssetKey(key).to_string() for key in BOARD_CHECKS)
            ),
            Checks.c.execution_status.in_(("SUCCEEDED", "FAILED")),
            Events.c.partition.is_not(None),
            sa.or_(
                completed > after,
                sa.and_(completed == after, event_id > previous_event_id),
            ),
        )
        .order_by(completed, event_id)
        .limit(1)
    )
    with instance.event_log_storage.index_connection() as connection:
        return connection.execute(query).first()


def _check_delivery(instance, day, observed_at, asset):
    targets = tuple(
        target
        for target in targets_for_day(day, {day: True})
        if target.asset_key == asset
    )
    return load_evidence(instance, targets, day, observed_at).get(asset)


def _check_matches_standard(asset, delivery, check, standard):
    # A failed Check can lack comparison metadata. Its native target has already been matched.
    if not check.evaluation.passed:
        return True
    fields = metadata(check.evaluation)
    if asset == RAW_CLASSIFICATION:
        return delivery.materialization.run_id == standard["raw_run_id"]
    if asset == RAW_MONEYFLOW:
        comparison = fields.get("board_coverage") or {}
        return (
            comparison.get("standard_version") == standard["version"]
            and comparison.get("raw_run_id") == delivery.materialization.run_id
        )
    parity = fields.get("board_parity") or {}
    return parity.get("raw_run_id") == standard["raw_run_id"]


def next_board_refresh(instance, cursor, observed_at):
    state = (
        json.loads(cursor)
        if cursor
        else {
            "confirmation_after": None,
            "recheck_after": None,
            "check_after": observed_at.astimezone(UTC).replace(tzinfo=None).isoformat(),
            "check_event": 0,
        }
    )
    confirmation = _next_completed(
        instance, BOARD_CONFIRM_JOB, state["confirmation_after"]
    )
    if confirmation:
        run = confirmation.dagster_run
        state["confirmation_after"] = confirmation.update_timestamp.isoformat()
        if not cursor:
            state["check_after"] = (
                confirmation.update_timestamp.astimezone(UTC)
                .replace(tzinfo=None)
                .isoformat()
            )
        day = date.fromisoformat(run.tags[BUSINESS_DATE_TAG])
        standard = read_dc_index_standard(instance, day)
        summary = read_summary(instance, day)
        if (
            standard
            and standard["version"] == run.run_id
            and summary
            and summary.get("board_standard_version") != run.run_id
        ):
            return BoardRefresh(
                day,
                run.run_id,
                tuple(BOARD_CHECKS),
                f"board-confirm:{day}:{run.run_id}",
            ), json.dumps(state)

    recheck = _next_completed(instance, BOARD_RECHECK_JOB, state.get("recheck_after"))
    if recheck:
        state["recheck_after"] = recheck.update_timestamp.isoformat()
        request = _recheck_refresh(instance, recheck.dagster_run)
        if request:
            return request, json.dumps(state)

    check = _next_check(
        instance, datetime.fromisoformat(state["check_after"]), state["check_event"]
    )
    if not check:
        return None, json.dumps(state)
    partition, check_name, run_id, completed, event_id = check
    state.update(check_after=completed.isoformat(), check_event=event_id)
    day = date.fromisoformat(partition)
    asset = next(key for key, name in BOARD_CHECKS.items() if check_name == name)
    standard = read_dc_index_standard(instance, day)
    summary = (
        read_summary(instance, day) if standard or asset == RAW_CLASSIFICATION else None
    )
    if not summary:
        return None, json.dumps(state)
    row = next(
        (row for row in summary["rows"] if row["scope"]["asset_key"] == asset), None
    )
    if not row:
        return None, json.dumps(state)
    delivery = _check_delivery(instance, day, observed_at, asset)
    current_check = delivery.checks.get(check_name) if delivery else None
    if not current_check or current_check.run_id != run_id:
        return None, json.dumps(state)
    if asset == RAW_CLASSIFICATION and (
        not standard or standard["raw_run_id"] != delivery.materialization.run_id
    ):
        if (
            current_check.event.timestamp
            <= datetime.fromisoformat(row["observed_at"]).timestamp()
        ):
            return None, json.dumps(state)
        raw_run_id = delivery.materialization.run_id
        return BoardRefresh(
            day, None, (asset,), f"board-raw:{day}:{raw_run_id}:{run_id}"
        ), json.dumps(state)
    version = standard["version"]
    if (
        summary.get("board_standard_version") == version
        and any(
            item.get("check_name") == check_name and item["run_id"] == run_id
            for item in row["completeness"]["evidence"]
        )
    ) or not _check_matches_standard(asset, delivery, current_check, standard):
        return None, json.dumps(state)
    standard_was_usable = summary.get("board_standard_version") == version
    raw_changes_readiness = asset == RAW_CLASSIFICATION and (
        current_check.evaluation.passed != standard_was_usable
    )
    assets = tuple(BOARD_CHECKS) if raw_changes_readiness else (asset,)
    return BoardRefresh(
        day, version, assets, f"board-check:{day}:{version}:{run_id}:{check_name}"
    ), json.dumps(state)


def _recheck_refresh(instance, run):
    day = date.fromisoformat(run.tags[BUSINESS_DATE_TAG])
    version = run.tags[REVIEW_VERSION_TAG]
    summary = read_summary(instance, day)
    if not summary:
        return None
    raw = next(
        (
            row
            for row in summary["rows"]
            if row["scope"]["asset_key"] == RAW_CLASSIFICATION
        ),
        None,
    )
    previous = (raw or {}).get("board_review") or {}
    if previous.get("review_version") != version or previous.get("standard"):
        return None
    current = read_dc_index_recheck(instance, day, version)
    prior_result = previous.get("recheck") or {}
    if (
        not current
        or current["run_id"] != run.run_id
        or prior_result.get("run_id") == run.run_id
    ):
        return None
    if not (current["has_confirmed_gap"] or prior_result.get("has_confirmed_gap")):
        return None
    return BoardRefresh(
        day,
        None,
        (RAW_CLASSIFICATION,),
        f"board-recheck:{day}:{version}:{run.run_id}",
        run.run_id,
    )
