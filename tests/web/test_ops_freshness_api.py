from __future__ import annotations

from datetime import date, datetime, timezone

from src.operations.specs.dataset_freshness_spec import DatasetFreshnessSpec
from src.web.queries.ops.freshness_query_service import OpsFreshnessQueryService


def test_ops_freshness_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/freshness", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_freshness_returns_grouped_dataset_statuses(
    app_client,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    sync_run_log_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 30), is_open=True, pretrade_date=date(2026, 3, 27))
    sync_job_state_factory(
        job_name="sync_equity_daily",
        target_table="core.equity_daily_bar",
        last_success_date=date(2026, 3, 30),
        last_success_at=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )
    sync_job_state_factory(
        job_name="sync_index_monthly",
        target_table="core.index_monthly_bar",
        last_success_date=date(2025, 12, 31),
        last_success_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    sync_run_log_factory(
        job_name="sync_index_monthly",
        run_type="FULL",
        status="FAILED",
        ended_at=datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
        message="monthly sync timeout",
    )

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/freshness", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_datasets"] >= 2
    assert payload["summary"]["fresh_datasets"] >= 1
    assert payload["summary"]["stale_datasets"] >= 1

    grouped = {
        group["domain_key"]: {item["dataset_key"]: item for item in group["items"]}
        for group in payload["groups"]
    }
    assert grouped["equity"]["daily"]["freshness_status"] == "fresh"
    assert grouped["equity"]["daily"]["business_date_source"] == "state"
    assert grouped["equity"]["daily"]["primary_execution_spec_key"] == "sync_daily.daily"
    assert grouped["index"]["index_monthly"]["freshness_status"] == "stale"
    assert grouped["index"]["index_monthly"]["recent_failure_message"] == "monthly sync timeout"
    assert grouped["index"]["index_monthly"]["recent_failure_summary"] == "monthly sync timeout"


def test_ops_freshness_hides_historical_failure_when_newer_success_exists(
    app_client,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    sync_run_log_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 30), is_open=True, pretrade_date=date(2026, 3, 27))
    sync_job_state_factory(
        job_name="sync_dividend",
        target_table="core.equity_dividend",
        last_success_date=date(2026, 3, 25),
        last_success_at=datetime(2026, 3, 25, 9, 11, 31, tzinfo=timezone.utc),
        full_sync_done=True,
    )
    sync_run_log_factory(
        job_name="sync_dividend",
        run_type="FULL",
        status="FAILED",
        ended_at=datetime(2026, 3, 25, 8, 18, 18, tzinfo=timezone.utc),
        message='(psycopg.errors.UndefinedColumn) column "row_key_hash" of relation "dividend" does not exist',
    )

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/freshness", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    grouped = {
        group["domain_key"]: {item["dataset_key"]: item for item in group["items"]}
        for group in payload["groups"]
    }
    assert grouped["event"]["dividend"]["recent_failure_message"] is None
    assert grouped["event"]["dividend"]["recent_failure_summary"] is None


def test_ops_freshness_uses_observed_table_date_when_newer_than_job_state(
    app_client,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    equity_block_trade_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 30), is_open=True, pretrade_date=date(2026, 3, 27))
    sync_job_state_factory(
        job_name="sync_block_trade",
        target_table="core.equity_block_trade",
        last_success_date=date(2025, 12, 31),
        last_success_at=datetime(2026, 3, 29, 7, 14, 12, tzinfo=timezone.utc),
    )
    equity_block_trade_factory(trade_date=date(2020, 1, 1))
    equity_block_trade_factory(trade_date=date(2026, 3, 26), ts_code="000002.SZ", buyer="buyer-2", seller="seller-2", price="11.00", vol="1200.00")

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/freshness", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    grouped = {
        group["domain_key"]: {item["dataset_key"]: item for item in group["items"]}
        for group in payload["groups"]
    }
    assert grouped["equity"]["block_trade"]["latest_business_date"] == "2026-03-26"
    assert grouped["equity"]["block_trade"]["earliest_business_date"] == "2020-01-01"
    assert grouped["equity"]["block_trade"]["business_date_source"] == "observed"
    assert grouped["equity"]["block_trade"]["freshness_note"] == "已按真实目标表的业务日期修正，状态表记录偏旧。"
    assert grouped["equity"]["block_trade"]["state_business_date"] == "2025-12-31"
    assert grouped["equity"]["block_trade"]["observed_business_date"] == "2026-03-26"


def test_ops_freshness_marks_unsynced_dataset_as_unknown(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/freshness", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["unknown_datasets"] > 0


def test_build_item_prefers_observed_sync_date_for_dataset_without_business_date() -> None:
    service = OpsFreshnessQueryService()
    spec = DatasetFreshnessSpec(
        dataset_key="ths_member",
        resource_key="ths_member",
        job_name="sync_ths_member",
        display_name="同花顺板块成分",
        domain_key="board",
        domain_display_name="板块",
        target_table="core.ths_member",
        cadence="reference",
        observed_date_column=None,
        primary_execution_spec_key="sync_history.ths_member",
    )

    item = service._build_item(
        spec=spec,
        state=None,
        latest_open_date=date(2026, 4, 1),
        reference_date=date(2026, 4, 1),
        recent_failure=None,
        observed_business_range=None,
        observed_sync_date=date(2026, 4, 1),
    )

    assert item.last_sync_date == date(2026, 4, 1)
