from __future__ import annotations

from datetime import datetime, timezone

import src.web.queries.ops.overview_query_service as overview_query_module


def test_ops_overview_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/overview", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_overview_returns_kpis_recent_executions_and_failures(
    app_client,
    user_factory,
    job_execution_factory,
    trade_calendar_factory,
    sync_job_state_factory,
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

    monkeypatch.setattr(overview_query_module, "datetime", FixedDateTime)

    trade_calendar_factory(exchange="SSE", trade_date=now.date(), is_open=True)
    sync_job_state_factory(
        job_name="sync_equity_daily",
        target_table="core.equity_daily_bar",
        last_success_date=now.date(),
        last_success_at=now,
    )
    sync_job_state_factory(
        job_name="sync_index_monthly",
        target_table="core.index_monthly_serving",
        last_success_date=datetime(2026, 1, 31, tzinfo=timezone.utc).date(),
        last_success_at=datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc),
    )
    job_execution_factory(
        requested_by_user_id=admin.id,
        spec_key="sync_daily.daily",
        status="queued",
        requested_at=now,
    )
    job_execution_factory(
        requested_by_user_id=admin.id,
        spec_key="sync_daily.moneyflow",
        status="running",
        requested_at=now,
    )
    job_execution_factory(
        requested_by_user_id=admin.id,
        spec_key="backfill_equity_series.daily",
        status="success",
        requested_at=now,
        rows_fetched=100,
        rows_written=100,
    )
    failed = job_execution_factory(
        requested_by_user_id=admin.id,
        spec_key="backfill_index_series.index_monthly",
        status="failed",
        requested_at=now,
        error_code="task_failed",
    )
    job_execution_factory(
        requested_by_user_id=admin.id,
        spec_key="maintenance.rebuild_dm",
        status="partial_success",
        requested_at=now,
    )
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/overview", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["today_kpis"]["business_date"] == "2026-03-30"
    assert payload["today_kpis"]["total_requests"] == 5
    assert payload["today_kpis"]["completed_requests"] == 3
    assert payload["today_kpis"]["running_requests"] == 1
    assert payload["today_kpis"]["failed_requests"] == 1
    assert payload["today_kpis"]["queued_requests"] == 1
    assert payload["today_kpis"]["attention_dataset_count"] >= 1
    assert payload["kpis"] == {
        "total_executions": 5,
        "queued_executions": 1,
        "running_executions": 1,
        "success_executions": 1,
        "failed_executions": 1,
        "canceled_executions": 0,
        "partial_success_executions": 1,
    }
    assert payload["freshness_summary"]["total_datasets"] >= 2
    assert payload["freshness_summary"]["fresh_datasets"] >= 1
    assert any(item["dataset_key"] == "index_monthly" for item in payload["lagging_datasets"])
    assert len(payload["recent_executions"]) == 5
    assert len(payload["recent_failures"]) == 1
    assert payload["recent_failures"][0]["id"] == failed.id
