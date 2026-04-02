from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.web.schemas.ops.execution import ExecutionDetailResponse


def test_ops_execution_list_rejects_non_admin(app_client, user_factory, job_execution_factory) -> None:
    user = user_factory(username="user", password="secret", is_admin=False)
    job_execution_factory(requested_by_user_id=user.id)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/executions", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_execution_list_returns_latest_first_and_supports_status_filter(
    app_client,
    user_factory,
    job_execution_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    base = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
    older = job_execution_factory(
        requested_by_user_id=admin.id,
        spec_key="sync_history.stock_basic",
        status="success",
        requested_at=base,
    )
    newer = job_execution_factory(
        requested_by_user_id=admin.id,
        spec_key="backfill_index_series.index_weekly",
        status="failed",
        requested_at=base + timedelta(minutes=5),
        error_code="task_failed",
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/executions", headers={"Authorization": f"Bearer {token}"})
    filtered = app_client.get(
        "/api/v1/ops/executions?status=failed",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["id"] for item in payload["items"]] == [newer.id, older.id]
    assert payload["items"][0]["requested_by_username"] == "admin"

    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 1
    assert filtered_payload["items"][0]["id"] == newer.id
    assert filtered_payload["items"][0]["spec_display_name"] == "指数纵向回补 / index_weekly"


def test_ops_execution_detail_returns_steps_and_events(
    app_client,
    user_factory,
    job_execution_factory,
    job_execution_step_factory,
    job_execution_event_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    execution = job_execution_factory(
        requested_by_user_id=admin.id,
        spec_type="job",
        spec_key="backfill_index_series.index_weight",
        status="running",
        params_json={"start_date": "2020-01-01", "end_date": "2026-03-30"},
        progress_current=651,
        progress_total=5814,
        progress_percent=11,
        progress_message="daily: 651/5814 ts_code=002034.SZ fetched=6 written=6",
        last_progress_at=datetime(2026, 3, 30, 12, 5, tzinfo=timezone.utc),
        summary_message="执行中",
    )
    step = job_execution_step_factory(
        execution_id=execution.id,
        step_key="index_weight",
        display_name="指数权重",
        sequence_no=1,
        status="running",
        unit_kind="index_code",
        unit_value="000300.SH",
        rows_fetched=6000,
        rows_written=6000,
    )
    job_execution_event_factory(
        execution_id=execution.id,
        event_type="started",
        message="execution started",
    )
    job_execution_event_factory(
        execution_id=execution.id,
        step_id=step.id,
        event_type="step_progress",
        message="step progress",
        payload_json={"index_code": "000300.SH"},
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get(f"/api/v1/ops/executions/{execution.id}", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == execution.id
    assert payload["requested_by_username"] == "admin"
    assert payload["spec_display_name"] == "指数纵向回补 / index_weight"
    assert payload["params_json"]["start_date"] == "2020-01-01"
    assert payload["progress_current"] == 651
    assert payload["progress_total"] == 5814
    assert payload["progress_percent"] == 11
    assert payload["progress_message"] == "daily: 651/5814 ts_code=002034.SZ fetched=6 written=6"
    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["step_key"] == "index_weight"
    assert len(payload["events"]) == 2
    assert payload["events"][1]["payload_json"]["index_code"] == "000300.SH"


def test_ops_execution_detail_returns_not_found_for_missing_execution(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/executions/9999", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_ops_execution_create_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/executions",
        headers={"Authorization": f"Bearer {token}"},
        json={"spec_type": "job", "spec_key": "sync_history.stock_basic", "params_json": {}},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_execution_create_creates_queued_execution_for_admin(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/executions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "spec_type": "job",
            "spec_key": "backfill_index_series.index_weekly",
            "params_json": {"start_date": "2020-01-01", "end_date": "2020-01-31", "limit": 10},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_type"] == "job"
    assert payload["spec_key"] == "backfill_index_series.index_weekly"
    assert payload["status"] == "queued"
    assert payload["params_json"]["limit"] == 10
    assert [event["event_type"] for event in payload["events"]] == ["created", "queued"]


def test_ops_execution_create_supports_sync_history_ths_member_without_optional_filters(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/executions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "spec_type": "job",
            "spec_key": "sync_history.ths_member",
            "params_json": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_key"] == "sync_history.ths_member"
    assert payload["status"] == "queued"
    assert payload["params_json"] == {}


def test_ops_execution_retry_creates_new_execution(app_client, user_factory, job_execution_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    existing = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="failed",
        requested_by_user_id=admin.id,
        params_json={"exchange": "SSE"},
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        f"/api/v1/ops/executions/{existing.id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] != existing.id
    assert payload["trigger_source"] == "retry"
    assert payload["params_json"] == {"exchange": "SSE"}


def test_ops_execution_retry_now_keeps_backward_compatible_path_but_only_requeues(app_client, user_factory, job_execution_factory, mocker) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    existing = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="failed",
        requested_by_user_id=admin.id,
    )
    mocker.patch(
        "src.web.api.v1.ops.executions.OpsExecutionCommandService.retry_execution",
        return_value=existing.id + 1,
    )
    mocker.patch(
        "src.web.api.v1.ops.executions.ExecutionQueryService.get_execution_detail",
        return_value=ExecutionDetailResponse(
            id=existing.id + 1,
            schedule_id=None,
            spec_type="job",
            spec_key="sync_history.stock_basic",
            spec_display_name="股票基础信息",
            schedule_display_name=None,
            trigger_source="retry",
            status="queued",
            requested_by_username="admin",
            requested_at=datetime.now(timezone.utc),
            queued_at=datetime.now(timezone.utc),
            started_at=None,
            ended_at=None,
            params_json={},
            summary_message="任务已提交",
            rows_fetched=0,
            rows_written=0,
            progress_current=None,
            progress_total=None,
            progress_percent=None,
            progress_message=None,
            last_progress_at=None,
            cancel_requested_at=None,
            canceled_at=None,
            error_code=None,
            error_message=None,
            steps=[],
            events=[],
        ),
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        f"/api/v1/ops/executions/{existing.id}/retry-now",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] != existing.id
    assert payload["trigger_source"] == "retry"
    assert payload["status"] == "queued"


def test_ops_execution_run_now_returns_current_execution_without_starting_it(app_client, user_factory, job_execution_factory, mocker) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="queued",
        requested_by_user_id=admin.id,
    )
    mocker.patch(
        "src.web.api.v1.ops.executions.ExecutionQueryService.get_execution_detail",
        return_value=ExecutionDetailResponse(
            id=execution.id,
            schedule_id=None,
            spec_type="job",
            spec_key="sync_history.stock_basic",
            spec_display_name="股票基础信息",
            schedule_display_name=None,
            trigger_source="manual",
            status="queued",
            requested_by_username="admin",
            requested_at=datetime.now(timezone.utc),
            queued_at=datetime.now(timezone.utc),
            started_at=None,
            ended_at=None,
            params_json={},
            summary_message="任务已提交",
            rows_fetched=0,
            rows_written=0,
            progress_current=None,
            progress_total=None,
            progress_percent=None,
            progress_message=None,
            last_progress_at=None,
            cancel_requested_at=None,
            canceled_at=None,
            error_code=None,
            error_message=None,
            steps=[],
            events=[],
        ),
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        f"/api/v1/ops/executions/{execution.id}/run-now",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == execution.id
    assert payload["status"] == "queued"


def test_ops_execution_create_run_now_keeps_backward_compatible_path_but_only_creates_queued_execution(app_client, user_factory, mocker) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    mocker.patch(
        "src.web.api.v1.ops.executions.OpsExecutionCommandService.create_manual_execution",
        return_value=88,
    )
    mocker.patch(
        "src.web.api.v1.ops.executions.ExecutionQueryService.get_execution_detail",
        return_value=ExecutionDetailResponse(
            id=88,
            schedule_id=None,
            spec_type="job",
            spec_key="sync_history.stock_basic",
            spec_display_name="股票基础信息",
            schedule_display_name=None,
            trigger_source="manual",
            status="queued",
            requested_by_username="admin",
            requested_at=datetime.now(timezone.utc),
            queued_at=datetime.now(timezone.utc),
            started_at=None,
            ended_at=None,
            params_json={},
            summary_message="任务已提交",
            rows_fetched=0,
            rows_written=0,
            progress_current=None,
            progress_total=None,
            progress_percent=None,
            progress_message=None,
            last_progress_at=None,
            cancel_requested_at=None,
            canceled_at=None,
            error_code=None,
            error_message=None,
            steps=[],
            events=[],
        ),
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/executions/run-now",
        headers={"Authorization": f"Bearer {token}"},
        json={
          "spec_type": "job",
          "spec_key": "sync_history.stock_basic",
          "params_json": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec_key"] == "sync_history.stock_basic"
    assert payload["status"] == "queued"


def test_ops_execution_cancel_marks_queued_execution_as_canceled(app_client, user_factory, job_execution_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="queued",
        requested_by_user_id=admin.id,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        f"/api/v1/ops/executions/{execution.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == execution.id
    assert payload["cancel_requested_at"] is not None
    assert payload["status"] == "canceled"


def test_ops_execution_cancel_marks_running_execution_as_canceling(app_client, user_factory, job_execution_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="running",
        requested_by_user_id=admin.id,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        f"/api/v1/ops/executions/{execution.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == execution.id
    assert payload["cancel_requested_at"] is not None
    assert payload["status"] == "canceling"


def test_ops_execution_steps_and_events_endpoints_return_split_views(
    app_client,
    user_factory,
    job_execution_factory,
    job_execution_step_factory,
    job_execution_event_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="running",
        requested_by_user_id=admin.id,
    )
    step = job_execution_step_factory(
        execution_id=execution.id,
        step_key="sync_history.stock_basic",
        display_name="股票主数据刷新",
        sequence_no=1,
        status="running",
    )
    job_execution_event_factory(
        execution_id=execution.id,
        step_id=step.id,
        event_type="step_progress",
        message="progress",
        payload_json={"rows_written": 100},
    )

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    steps = app_client.get(f"/api/v1/ops/executions/{execution.id}/steps", headers={"Authorization": f"Bearer {token}"})
    events = app_client.get(f"/api/v1/ops/executions/{execution.id}/events", headers={"Authorization": f"Bearer {token}"})

    assert steps.status_code == 200
    assert steps.json()["execution_id"] == execution.id
    assert steps.json()["items"][0]["step_key"] == "sync_history.stock_basic"

    assert events.status_code == 200
    assert events.json()["execution_id"] == execution.id
    assert events.json()["items"][0]["payload_json"]["rows_written"] == 100


def test_ops_execution_logs_endpoint_returns_sync_run_logs(
    app_client,
    user_factory,
    job_execution_factory,
    sync_run_log_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="success",
        requested_by_user_id=admin.id,
    )
    sync_run_log_factory(
        execution_id=execution.id,
        job_name="sync_stock_basic",
        run_type="FULL",
        status="SUCCESS",
        rows_fetched=5814,
        rows_written=5814,
        message="stock_basic refreshed",
    )

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get(f"/api/v1/ops/executions/{execution.id}/logs", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_id"] == execution.id
    assert len(payload["items"]) == 1
    assert payload["items"][0]["job_name"] == "sync_stock_basic"
    assert payload["items"][0]["run_type"] == "FULL"
    assert payload["items"][0]["rows_written"] == 5814
