from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.foundation.dao.etf_basic_dao import (
    EtfRequestTarget,
    EtfRequestabilitySnapshot,
)
from src.ops.services.etf_minute_history_alignment_plan_service import (
    EtfMinuteHistoryAlignmentPlanService,
    canonical_etf_minute_alignment_hash,
    etf_minute_request_target_hash,
)
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.etf_minute_history_alignment_submit_service import (
    ETF_MINUTE_ALIGNMENT_SUBMIT_ADVISORY_LOCK_KEY,
    EtfMinuteHistoryAlignmentSubmitError,
    EtfMinuteHistoryAlignmentSubmitService,
)


NOW = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
START_DATE = date(2026, 1, 1)
END_DATE = date(2026, 8, 28)


def _target(ts_code: str, *, list_date: date, exchange: str) -> EtfRequestTarget:
    return EtfRequestTarget(  # type: ignore[arg-type]
        ts_code=ts_code,
        list_date=list_date,
        exchange=exchange,
    )


def _snapshot(*targets: EtfRequestTarget) -> EtfRequestabilitySnapshot:
    return EtfRequestabilitySnapshot(
        as_of_date=date(2026, 8, 29),
        exchange=None,
        targets=tuple(targets),
        serving_row_count=len(targets),
        requestable_count=len(targets),
        excluded_reason_counts={},
    )


def _preview_plan(*targets: EtfRequestTarget):
    return EtfMinuteHistoryAlignmentPlanService(
        uuid_factory=lambda: UUID("00000000-0000-0000-0000-000000000001")
    ).build_plan_from_coverage(
        snapshot=_snapshot(*targets),
        alignment_start_date=START_DATE,
        alignment_end_date=END_DATE,
        generated_at=NOW,
        alignment_open_dates=(date(2026, 1, 5), END_DATE),
        raw_monthly_coverages=(),
        successful_task_coverages=(),
    )


@pytest.fixture
def targets() -> tuple[EtfRequestTarget, ...]:
    return (
        _target("510300.SH", list_date=date(2012, 5, 28), exchange="SH"),
        _target("510500.SH", list_date=date(2013, 3, 15), exchange="SH"),
        _target("159915.SZ", list_date=date(2011, 12, 5), exchange="SZ"),
    )


def _confirmed(plan):  # type: ignore[no-untyped-def]
    return EtfMinuteHistoryAlignmentSubmitService.validate_plan_payload(
        plan.to_payload(),
        confirmed_plan_hash=plan.plan_content_hash,
    )


def _session(mocker, *, scalar_values: tuple[object, ...] = (None, None)):
    session = mocker.MagicMock()
    session.get_bind.return_value.dialect.name = "sqlite"
    session.scalar.side_effect = scalar_values
    return session


def _patch_snapshot_dao(mocker, snapshot: EtfRequestabilitySnapshot):
    dao = mocker.Mock()
    dao.load_requestability_snapshot.return_value = snapshot
    dao_cls = mocker.patch(
        "src.ops.services.etf_minute_history_alignment_submit_service.EtfBasicDAO",
        return_value=dao,
    )
    return dao, dao_cls


def test_plan_payload_requires_matching_confirmation_and_untampered_content(targets) -> None:
    plan = _preview_plan(*targets)

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as confirmation_error:
        EtfMinuteHistoryAlignmentSubmitService.validate_plan_payload(
            plan.to_payload(),
            confirmed_plan_hash="0" * 64,
        )
    assert confirmation_error.value.code == "plan_confirmation_mismatch"

    tampered = plan.to_payload()
    tampered["actions"][0]["end_date"] = "2026-08-27"
    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as content_error:
        EtfMinuteHistoryAlignmentSubmitService.validate_plan_payload(
            tampered,
            confirmed_plan_hash=plan.plan_content_hash,
        )
    assert content_error.value.code == "plan_content_hash_mismatch"


def test_plan_payload_rejects_noncanonical_action_even_with_recomputed_hash(targets) -> None:
    plan = _preview_plan(*targets)
    payload = plan.to_payload()
    payload["actions"][0]["frequencies"] = ["5min", "1min"]
    base = dict(payload)
    base.pop("plan_content_hash")
    payload["plan_content_hash"] = canonical_etf_minute_alignment_hash(base)

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as error:
        EtfMinuteHistoryAlignmentSubmitService.validate_plan_payload(
            payload,
            confirmed_plan_hash=payload["plan_content_hash"],
        )

    assert error.value.code == "plan_schema_invalid"


def test_submit_stages_only_first_batch_and_commits_once(mocker, targets) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    session = _session(mocker)
    snapshot = _snapshot(*targets)
    dao, dao_cls = _patch_snapshot_dao(mocker, snapshot)
    current_plan_service = mocker.Mock()
    current_plan_service.build_plan_for_snapshot.return_value = preview
    task_run_service = mocker.Mock()
    task_run_service.stage_task_run.side_effect = [
        SimpleNamespace(id=101),
        SimpleNamespace(id=102),
    ]
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    result = service.submit(session, plan=confirmed, batch_size=2)

    assert result.created_task_run_ids == (101, 102)
    assert result.skipped_covered_action_count == 0
    assert result.remaining_action_count == 1
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    assert session.scalar.call_count == 2
    dao_cls.assert_called_once_with(session)
    dao.load_requestability_snapshot.assert_called_once_with(
        as_of_date=date(2026, 8, 29)
    )
    current_plan_service.build_plan_for_snapshot.assert_called_once_with(
        session,
        snapshot=snapshot,
        generated_at=NOW,
        alignment_start_date=START_DATE,
        alignment_end_date=END_DATE,
    )
    assert task_run_service.stage_task_run.call_count == 2
    first_call = task_run_service.stage_task_run.call_args_list[0]
    first_context = first_call.kwargs["context"]
    assert first_context.task_type == "dataset_action"
    assert first_context.resource_key == "etf_mins"
    assert first_context.action == "maintain"
    assert first_context.trigger_source == "manual"
    assert first_context.requested_by_user_id is None
    assert first_context.time_input == {
        "mode": "range",
        "start_date": "2026-01-05",
        "end_date": "2026-08-28",
    }
    assert first_context.filters == {
        "ts_code": preview.actions[0].ts_code,
        "freq": ["1min", "5min", "15min", "30min", "60min"],
    }
    assert first_context.request_payload == {
        "alignment_plan_id": preview.plan_id,
        "alignment_plan_content_hash": preview.plan_content_hash,
        "alignment_action_number": 1,
    }
    assert first_call.kwargs["task_frozen_at"] == NOW


def test_submit_persists_existing_etf_mins_task_run_contract(
    mocker,
    targets,
) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    _patch_snapshot_dao(mocker, _snapshot(*targets))
    current_plan_service = mocker.Mock()
    current_plan_service.build_plan_for_snapshot.return_value = preview
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        clock=lambda: NOW,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    connection = engine.connect().execution_options(schema_translate_map={"ops": None})
    TaskRun.__table__.create(connection)
    with Session(connection) as session:
        result = service.submit(session, plan=confirmed, batch_size=1)

        task_run = session.get(TaskRun, result.created_task_run_ids[0])
        assert task_run is not None
        assert task_run.task_type == "dataset_action"
        assert task_run.resource_key == "etf_mins"
        assert task_run.action == "maintain"
        assert task_run.status == "queued"
        assert task_run.trigger_source == "manual"
        assert task_run.time_input_json == {
            "mode": "range",
            "start_date": "2026-01-05",
            "end_date": "2026-08-28",
        }
        assert task_run.filters_json == {
            "ts_code": preview.actions[0].ts_code,
            "freq": ["1min", "5min", "15min", "30min", "60min"],
        }
        assert task_run.request_payload_json["alignment_plan_id"] == preview.plan_id
        assert task_run.request_payload_json["alignment_plan_content_hash"] == (
            preview.plan_content_hash
        )
        assert task_run.request_payload_json["alignment_action_number"] == 1
    connection.close()
    engine.dispose()


def test_submit_skips_fully_covered_actions_and_keeps_plan_order(mocker, targets) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    current = SimpleNamespace(actions=preview.actions[1:])
    session = _session(mocker)
    _patch_snapshot_dao(mocker, _snapshot(*targets))
    current_plan_service = mocker.Mock()
    current_plan_service.build_plan_for_snapshot.return_value = current
    task_run_service = mocker.Mock()
    task_run_service.stage_task_run.return_value = SimpleNamespace(id=201)
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    result = service.submit(session, plan=confirmed, batch_size=1)

    assert result.created_task_run_ids == (201,)
    assert result.skipped_covered_action_count == 1
    assert result.remaining_action_count == 1
    context = task_run_service.stage_task_run.call_args.kwargs["context"]
    assert context.filters["ts_code"] == preview.actions[1].ts_code


def test_submit_all_covered_is_idempotent_noop(mocker, targets) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    session = _session(mocker)
    _patch_snapshot_dao(mocker, _snapshot(*targets))
    current_plan_service = mocker.Mock()
    current_plan_service.build_plan_for_snapshot.return_value = SimpleNamespace(actions=())
    task_run_service = mocker.Mock()
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    result = service.submit(session, plan=confirmed, batch_size=10)

    assert result.created_task_run_ids == ()
    assert result.skipped_covered_action_count == 3
    assert result.remaining_action_count == 0
    task_run_service.stage_task_run.assert_not_called()
    session.commit.assert_called_once_with()


def test_submit_rejects_changed_target_hash_before_coverage_query(mocker, targets) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    session = _session(mocker, scalar_values=(None,))
    _patch_snapshot_dao(mocker, _snapshot(*targets[:-1]))
    current_plan_service = mocker.Mock()
    task_run_service = mocker.Mock()
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as error:
        service.submit(session, plan=confirmed, batch_size=10)

    assert error.value.code == "request_target_hash_changed"
    current_plan_service.build_plan_for_snapshot.assert_not_called()
    task_run_service.stage_task_run.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_submit_rejects_action_before_current_list_date(mocker) -> None:
    old_target = _target("510300.SH", list_date=date(2020, 1, 1), exchange="SH")
    current_target = _target(
        "510300.SH",
        list_date=date(2026, 7, 1),
        exchange="SH",
    )
    preview = _preview_plan(old_target)
    payload = preview.to_payload()
    payload["request_target_hash"] = etf_minute_request_target_hash((current_target,))
    base = dict(payload)
    base.pop("plan_content_hash")
    payload["plan_content_hash"] = canonical_etf_minute_alignment_hash(base)
    confirmed = EtfMinuteHistoryAlignmentSubmitService.validate_plan_payload(
        payload,
        confirmed_plan_hash=payload["plan_content_hash"],
    )
    session = _session(mocker, scalar_values=(None,))
    _patch_snapshot_dao(mocker, _snapshot(current_target))
    current_plan_service = mocker.Mock()
    task_run_service = mocker.Mock()
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as error:
        service.submit(session, plan=confirmed, batch_size=10)

    assert error.value.code == "plan_before_list_date"
    current_plan_service.build_plan_for_snapshot.assert_not_called()
    task_run_service.stage_task_run.assert_not_called()
    session.rollback.assert_called_once_with()


def test_submit_rejects_open_task_before_basic_or_coverage_queries(mocker, targets) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    session = _session(mocker, scalar_values=(9001,))
    dao, _ = _patch_snapshot_dao(mocker, _snapshot(*targets))
    current_plan_service = mocker.Mock()
    task_run_service = mocker.Mock()
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as error:
        service.submit(session, plan=confirmed, batch_size=10)

    assert error.value.code == "open_etf_mins_task_exists"
    assert error.value.details["task_run_id"] == 9001
    dao.load_requestability_snapshot.assert_not_called()
    current_plan_service.build_plan_for_snapshot.assert_not_called()
    task_run_service.stage_task_run.assert_not_called()
    session.rollback.assert_called_once_with()


def test_submit_rechecks_open_task_after_coverage_query(mocker, targets) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    session = _session(mocker, scalar_values=(None, 9002))
    _patch_snapshot_dao(mocker, _snapshot(*targets))
    current_plan_service = mocker.Mock()
    current_plan_service.build_plan_for_snapshot.return_value = preview
    task_run_service = mocker.Mock()
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as error:
        service.submit(session, plan=confirmed, batch_size=10)

    assert error.value.code == "open_etf_mins_task_exists"
    task_run_service.stage_task_run.assert_not_called()
    session.rollback.assert_called_once_with()


def test_submit_rejects_partial_coverage_change_instead_of_reusing_old_range(
    mocker,
    targets,
) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    first = preview.actions[0]
    changed_first = type(first)(
        ts_code=first.ts_code,
        frequencies=first.frequencies,
        start_date=date(2026, 2, 1),
        end_date=first.end_date,
        planned_unit_count=first.planned_unit_count,
    )
    session = _session(mocker, scalar_values=(None,))
    _patch_snapshot_dao(mocker, _snapshot(*targets))
    current_plan_service = mocker.Mock()
    current_plan_service.build_plan_for_snapshot.return_value = SimpleNamespace(
        actions=(changed_first, *preview.actions[1:])
    )
    task_run_service = mocker.Mock()
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as error:
        service.submit(session, plan=confirmed, batch_size=10)

    assert error.value.code == "plan_coverage_changed"
    task_run_service.stage_task_run.assert_not_called()
    session.rollback.assert_called_once_with()


def test_submit_stage_failure_rolls_back_whole_batch(mocker, targets) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    session = _session(mocker)
    _patch_snapshot_dao(mocker, _snapshot(*targets))
    current_plan_service = mocker.Mock()
    current_plan_service.build_plan_for_snapshot.return_value = preview
    task_run_service = mocker.Mock()
    task_run_service.stage_task_run.side_effect = [
        SimpleNamespace(id=301),
        RuntimeError("stage failed"),
    ]
    service = EtfMinuteHistoryAlignmentSubmitService(
        plan_service=current_plan_service,
        task_run_service=task_run_service,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="stage failed"):
        service.submit(session, plan=confirmed, batch_size=2)

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_postgresql_submit_uses_dedicated_transaction_advisory_lock(mocker) -> None:
    session = mocker.MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"

    EtfMinuteHistoryAlignmentSubmitService._acquire_submit_lock(session)

    statement = session.execute.call_args.args[0]
    compiled = statement.compile()
    assert "pg_advisory_xact_lock" in str(statement)
    assert ETF_MINUTE_ALIGNMENT_SUBMIT_ADVISORY_LOCK_KEY in compiled.params.values()


@pytest.mark.parametrize("batch_size", (0, -1, True, 1.5))
def test_submit_rejects_invalid_batch_size_before_transaction(mocker, targets, batch_size) -> None:
    preview = _preview_plan(*targets)
    confirmed = _confirmed(preview)
    session = _session(mocker)
    service = EtfMinuteHistoryAlignmentSubmitService()

    with pytest.raises(EtfMinuteHistoryAlignmentSubmitError) as error:
        service.submit(session, plan=confirmed, batch_size=batch_size)

    assert error.value.code == "batch_size_invalid"
    session.execute.assert_not_called()
    session.scalar.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
