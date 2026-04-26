from __future__ import annotations

from datetime import datetime, timezone

import src.ops.queries.overview_query_service as ops_overview_query_module
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing


def test_ops_overview_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/overview", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_overview_summary_allows_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/overview-summary", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert "freshness_summary" in payload
    assert "total_datasets" in payload["freshness_summary"]


def test_ops_overview_returns_kpis_recent_executions_and_failures(
    app_client,
    db_session,
    user_factory,
    task_run_factory,
    task_run_node_factory,
    task_run_issue_factory,
    trade_calendar_factory,
    equity_block_trade_factory,
    monkeypatch,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    now = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return now.replace(tzinfo=None)
            return now.astimezone(tz)

    monkeypatch.setattr(ops_overview_query_module, "datetime", FixedDateTime)

    trade_calendar_factory(exchange="SSE", trade_date=datetime(2026, 1, 31, tzinfo=timezone.utc).date(), is_open=True)
    trade_calendar_factory(exchange="SSE", trade_date=now.date(), is_open=True)
    equity_block_trade_factory(trade_date=now.date())
    db_session.add(
        IndexMonthlyServing(
            ts_code="000001.SH",
            period_start_date=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
            trade_date=datetime(2026, 1, 31, tzinfo=timezone.utc).date(),
            source="api",
        )
    )
    success_run = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="block_trade",
        status="success",
        requested_at=now,
        started_at=now,
        ended_at=now,
        rows_fetched=100,
        rows_saved=100,
    )
    task_run_node_factory(
        task_run_id=success_run.id,
        resource_key="block_trade",
        status="success",
        started_at=now,
        ended_at=now,
    )
    monthly_run = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="index_monthly",
        status="success",
        requested_at=now,
        started_at=now,
        ended_at=now,
    )
    task_run_node_factory(
        task_run_id=monthly_run.id,
        resource_key="index_monthly",
        status="success",
        started_at=now,
        ended_at=now,
    )
    task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="block_trade",
        status="queued",
        requested_at=now,
    )
    task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="index_monthly",
        status="running",
        requested_at=now,
    )
    failed = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="block_trade",
        status="failed",
        requested_at=now,
    )
    issue = task_run_issue_factory(
        task_run_id=failed.id,
        code="task_failed",
        title="任务失败",
        message="network timeout while fetching daily data",
        occurred_at=now,
    )
    failed.primary_issue_id = issue.id
    db_session.commit()
    task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="maintenance.rebuild_dm",
        status="partial_success",
        requested_at=now,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/overview", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["today_kpis"]["business_date"] == "2026-03-30"
    assert payload["today_kpis"]["total_requests"] == 6
    assert payload["today_kpis"]["completed_requests"] == 4
    assert payload["today_kpis"]["running_requests"] == 1
    assert payload["today_kpis"]["failed_requests"] == 1
    assert payload["today_kpis"]["queued_requests"] == 1
    assert payload["today_kpis"]["attention_dataset_count"] >= 1
    assert payload["kpis"] == {
        "total_executions": 6,
        "queued_executions": 1,
        "running_executions": 1,
        "success_executions": 2,
        "failed_executions": 1,
        "canceled_executions": 0,
        "partial_success_executions": 1,
    }
    assert payload["freshness_summary"]["total_datasets"] >= 2
    assert payload["freshness_summary"]["fresh_datasets"] >= 1
    assert any(item["dataset_key"] == "index_monthly" for item in payload["lagging_datasets"])
    assert len(payload["recent_executions"]) == 6
    assert len(payload["recent_failures"]) == 1
    assert payload["recent_failures"][0]["id"] == failed.id
    assert payload["recent_failures"][0]["primary_issue_title"] == "任务失败"
