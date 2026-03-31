from __future__ import annotations

from types import SimpleNamespace


def test_ops_runtime_scheduler_tick_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/runtime/scheduler-tick",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 5},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_runtime_scheduler_tick_returns_created_executions(app_client, user_factory, mocker) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    scheduler_tick = mocker.patch("src.web.api.v1.ops.runtime.OpsRuntimeCommandService.scheduler_tick")
    scheduler_tick.return_value = [
        SimpleNamespace(
            id=301,
            schedule_id=21,
            spec_type="workflow",
            spec_key="daily_market_close_sync",
            trigger_source="scheduled",
            status="queued",
            requested_at="2026-03-30T12:00:00+00:00",
            rows_fetched=0,
            rows_written=0,
            summary_message=None,
        )
    ]

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/runtime/scheduler-tick",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scheduled_count"] == 1
    assert payload["items"][0]["id"] == 301
    assert payload["items"][0]["spec_display_name"] == "每日收盘后同步"
    scheduler_tick.assert_called_once()


def test_ops_runtime_worker_run_returns_processed_executions(app_client, user_factory, mocker) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    worker_run = mocker.patch("src.web.api.v1.ops.runtime.OpsRuntimeCommandService.worker_run")
    worker_run.return_value = [
        SimpleNamespace(
            id=401,
            schedule_id=None,
            spec_type="job",
            spec_key="sync_history.stock_basic",
            trigger_source="manual",
            status="success",
            requested_at="2026-03-30T13:00:00+00:00",
            rows_fetched=5814,
            rows_written=5814,
            summary_message="done",
        )
    ]

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/runtime/worker-run",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["items"][0]["id"] == 401
    assert payload["items"][0]["rows_written"] == 5814
    assert payload["items"][0]["summary_message"] == "done"
    worker_run.assert_called_once()
