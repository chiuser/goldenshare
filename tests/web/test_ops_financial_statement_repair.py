from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.foundation.clients.tushare_client import TushareApiError
from src.foundation.ingestion import source_client as source_client_module
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.raw.raw_balancesheet import RawBalancesheet
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.worker import OperationsWorker
from src.ops.services.operations_task_run_reconciliation_service import OperationsTaskRunReconciliationService
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
from src.ops.services.task_run_service import TaskRunCommandService


@pytest.mark.parametrize("dataset", ("income", "balancesheet", "cashflow"))
def test_automatic_financial_segments_advance_only_after_success(db_session, ops_schedule_factory, task_run_factory, dataset):
    schedule = ops_schedule_factory(target_key=f"{dataset}.maintain", calendar_policy="since_last_success_day_range")
    service = TaskRunCommandService()
    due = datetime(2026, 11, 19, 11, 30, tzinfo=timezone.utc)
    params = {"schedule_policy_params": {"initial_start_date": "2026-11-12"}, "filters": {"report_type": ["1"]}}

    def next_window():
        return service.build_schedule_task_context(
            session=db_session, target_type="dataset_action", target_key=schedule.target_key,
            params_json=params, trigger_source="scheduled", requested_by_user_id=None,
            schedule_id=schedule.id, calendar_policy=schedule.calendar_policy,
            scheduled_at=due, timezone_name="Asia/Shanghai",
        ).time_input

    first = {"mode": "range", "start_date": "2026-11-12", "end_date": "2026-11-13"}
    assert next_window() == first
    prior = task_run_factory(resource_key=dataset, schedule_id=schedule.id, time_input_json=first, status="failed")
    assert next_window() == first
    prior.status = "success"
    db_session.commit()
    assert next_window() == {"mode": "range", "start_date": "2026-11-14", "end_date": "2026-11-15"}
    prior.time_input_json = {"mode": "range", "start_date": "2026-11-16", "end_date": "2026-11-17"}
    db_session.commit()
    assert next_window() == {"mode": "range", "start_date": "2026-11-18", "end_date": "2026-11-18"}


@pytest.mark.parametrize("interruption", ("failed", "page_failure", "canceled", "exit", "exit_before_final_status", "observation_failure"))
def test_financial_retry_uses_durable_prefix_and_keeps_raw_on_observation_failure(
    db_session, task_run_factory, monkeypatch, interruption,
):
    engine = db_session.get_bind()
    with engine.begin() as connection:
        connection.connection.driver_connection.create_function("now", 0, lambda: datetime.now().isoformat())
        RawBalancesheet.__table__.create(connection)

    evidence = Path(__file__).parents[1] / "fixtures/financial_statements/balancesheet_920202_prelisting.json"
    actual_row = json.loads(evidence.read_text())["row"]
    assert (actual_row["ann_date"], actual_row["end_date"], actual_row["report_type"]) == ("20240111", "20230831", "1")
    db_session.add(Security(ts_code="920202.BJ", name="安达股份", list_date=date(2026, 9, 29), list_status="L"))
    db_session.commit()

    original = task_run_factory(
        resource_key="balancesheet",
        time_input_json={"mode": "point", "ann_date": "2024-01-11", "date_field": "ann_date"},
        filters_json={"report_type": ["1"], "report_periods": ["2023-08-31", "2023-09-30"]},
    )
    original_id = original.id
    fail_attempt = True
    requests = []
    progress_done = []
    original_update = TaskRunIngestionContext.update_progress

    def observe(self, **progress):
        if progress["run_id"] == original_id:
            progress_done.append(progress["unit_done"])
            if interruption == "observation_failure" and progress["unit_done"] > 0:
                raise RuntimeError("test observation unavailable")
        return original_update(self, **progress)

    class Connector:
        def call_bounded(self, *, api_name, params, fields, check, **_):
            assert api_name == "balancesheet_vip"
            requests.append((params["period"], params["offset"]))
            assert params["ann_date"] == "20240111"
            assert params["report_type"] == "1"
            if params["period"] == "20230831":
                assert set(fields) == set(actual_row)
                return [actual_row]
            if fail_attempt:
                if interruption == "exit_before_final_status":
                    return []
                if interruption == "page_failure" and params["offset"] == 0:
                    # A full page with a valid regular-quarter shape forces an offset=5000 request.
                    first_page_row = {**actual_row, "end_date": "20230930", "end_type": "3"}
                    return [first_page_row] * 5_000
                if interruption == "exit":
                    raise SystemExit("simulated process exit")
                if interruption == "canceled":
                    original.cancel_requested_at = datetime.now(timezone.utc)
                    db_session.commit()
                    return []
                raise TushareApiError(api_name=api_name, code=50101, message="sample page failure")
            return []

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _: Connector())
    monkeypatch.setattr(TaskRunIngestionContext, "update_progress", observe)
    class InterruptedWorker(OperationsWorker):
        def _finalize_task_run(self, session, task_run_id, outcome):
            raise SystemExit("simulated exit after data and before terminal status")

    worker = InterruptedWorker() if interruption == "exit_before_final_status" else OperationsWorker()
    if interruption in {"exit", "exit_before_final_status"}:
        with pytest.raises(SystemExit):
            worker.run_task_run(db_session, original_id)
        db_session.rollback()
        OperationsTaskRunReconciliationService().reconcile_stale_task_runs(
            db_session, now=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db_session.refresh(original)
    else:
        original = worker.run_task_run(db_session, original_id)
    expected_status = "canceled" if interruption == "canceled" else "failed"
    assert original.status == expected_status
    assert db_session.get(TaskRunNode, original.current_node_id).status == expected_status
    assert requests == [("20230831", 0), ("20230930", 0)] + (
        [("20230930", 5_000)] if interruption == "page_failure" else []
    )
    assert progress_done == sorted(progress_done)
    expected_done = {"observation_failure": 0, "exit_before_final_status": 2}.get(interruption, 1)
    assert original.unit_done == expected_done
    assert db_session.scalar(select(func.count()).select_from(RawBalancesheet)) == 1

    fail_attempt = False
    requests.clear()
    retry = TaskRunCommandService().retry_task_run(db_session, task_run_id=original_id, requested_by_user_id=1)
    retry = OperationsWorker().run_task_run(db_session, retry.id)
    assert retry.status == "success"
    assert db_session.get(TaskRunNode, retry.current_node_id).status == "success"
    assert (retry.unit_done, retry.unit_total, retry.progress_percent) == (2, 2, 100)
    expected_retry_requests = {
        "observation_failure": [("20230831", 0), ("20230930", 0)],
        "exit_before_final_status": [],
    }.get(interruption, [("20230930", 0)])
    assert requests == expected_retry_requests
    assert retry.rows_saved == 1
    assert db_session.scalar(select(RawBalancesheet.end_date)) == date(2023, 8, 31)
    assert db_session.scalar(select(func.count()).select_from(RawBalancesheet)) == 1
