from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import Mock

from src.ops.specs.dataset_freshness_spec import DatasetFreshnessSpec
from src.ops.schemas.freshness import DatasetFreshnessItem, FreshnessGroup, OpsFreshnessResponse, OpsFreshnessSummary
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService


def test_ops_freshness_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/freshness", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_freshness_returns_grouped_dataset_statuses(
    app_client,
    db_session,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    task_run_factory,
    task_run_issue_factory,
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
        target_table="core.index_monthly_serving",
        last_success_date=date(2025, 12, 31),
        last_success_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    failed = task_run_factory(
        resource_key="index_monthly",
        status="failed",
        requested_at=datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
    )
    issue = task_run_issue_factory(
        task_run_id=failed.id,
        code="task_failed",
        title="任务失败",
        message="monthly sync timeout",
        occurred_at=datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
    )
    failed.primary_issue_id = issue.id
    db_session.commit()

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
    assert grouped["equity"]["daily"]["primary_execution_spec_key"] == "daily.maintain"
    assert grouped["index"]["index_monthly"]["freshness_status"] == "stale"
    assert grouped["index"]["index_monthly"]["recent_failure_message"] == "monthly sync timeout"
    assert grouped["index"]["index_monthly"]["recent_failure_summary"] == "monthly sync timeout"


def test_ops_freshness_includes_auto_schedule_flags(
    app_client,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    job_schedule_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 30), is_open=True, pretrade_date=date(2026, 3, 27))
    sync_job_state_factory(
        job_name="sync_equity_daily",
        target_table="core.equity_daily_bar",
        last_success_date=date(2026, 3, 30),
        last_success_at=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )
    job_schedule_factory(
        spec_type="dataset_action",
        spec_key="daily.maintain",
        status="active",
        schedule_type="cron",
        cron_expr="30 18 * * *",
        next_run_at=datetime(2026, 3, 31, 10, 30, tzinfo=timezone.utc),
    )
    job_schedule_factory(
        spec_type="dataset_action",
        spec_key="daily.maintain",
        status="paused",
        schedule_type="cron",
        cron_expr="45 18 * * *",
        next_run_at=datetime(2026, 3, 31, 10, 45, tzinfo=timezone.utc),
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
    daily_item = grouped["equity"]["daily"]
    assert daily_item["auto_schedule_status"] == "active"
    assert daily_item["auto_schedule_total"] == 2
    assert daily_item["auto_schedule_active"] == 1
    assert daily_item["auto_schedule_next_run_at"] == "2026-03-31T10:30:00"


def test_ops_freshness_marks_dataset_as_automatic_when_covered_by_workflow_schedule(
    app_client,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    job_schedule_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 30), is_open=True, pretrade_date=date(2026, 3, 27))
    sync_job_state_factory(
        job_name="sync_stock_basic",
        target_table="core.security_serving",
        last_success_date=date(2026, 3, 30),
        last_success_at=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )
    sync_job_state_factory(
        job_name="sync_trade_cal",
        target_table="core.trade_calendar",
        last_success_date=date(2026, 3, 30),
        last_success_at=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )
    job_schedule_factory(
        spec_type="workflow",
        spec_key="reference_data_refresh",
        status="active",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        next_run_at=datetime(2026, 3, 31, 11, 0, tzinfo=timezone.utc),
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
    stock_basic_item = grouped["reference_data"]["stock_basic"]
    trade_cal_item = grouped["reference_data"]["trade_cal"]
    assert stock_basic_item["auto_schedule_status"] == "active"
    assert stock_basic_item["auto_schedule_total"] == 1
    assert stock_basic_item["auto_schedule_active"] == 1
    assert trade_cal_item["auto_schedule_status"] == "active"
    assert trade_cal_item["auto_schedule_total"] == 1
    assert trade_cal_item["auto_schedule_active"] == 1


def test_ops_freshness_exposes_active_execution_status_for_dataset(
    app_client,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    task_run_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 4, 16), is_open=True, pretrade_date=date(2026, 4, 15))
    sync_job_state_factory(
        job_name="sync_cyq_perf",
        target_table="core.equity_cyq_perf",
        last_success_date=date(2026, 4, 10),
        last_success_at=datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc),
    )
    task_run_factory(
        resource_key="cyq_perf",
        status="running",
        requested_at=datetime(2026, 4, 17, 8, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 17, 8, 1, tzinfo=timezone.utc),
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
    cyq_item = grouped["equity"]["cyq_perf"]
    assert cyq_item["active_execution_status"] == "running"
    assert cyq_item["active_execution_started_at"] == "2026-04-17T08:01:00"


def test_ops_freshness_hides_historical_failure_when_newer_success_exists(
    app_client,
    db_session,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
    task_run_factory,
    task_run_issue_factory,
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
    failed = task_run_factory(
        resource_key="dividend",
        status="failed",
        requested_at=datetime(2026, 3, 25, 8, 18, 18, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 25, 8, 18, 18, tzinfo=timezone.utc),
    )
    issue = task_run_issue_factory(
        task_run_id=failed.id,
        code="task_failed",
        title="任务失败",
        message='(psycopg.errors.UndefinedColumn) column "row_key_hash" of relation "dividend" does not exist',
        occurred_at=datetime(2026, 3, 25, 8, 18, 18, tzinfo=timezone.utc),
    )
    failed.primary_issue_id = issue.id
    db_session.commit()

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
        primary_execution_spec_key="ths_member.maintain",
    )

    item = service._build_item(
        spec=spec,
        state=None,
        latest_open_date=date(2026, 4, 1),
        reference_date=date(2026, 4, 1),
        recent_failure=None,
        quality_note=None,
        observed_business_range=None,
        observed_sync_date=date(2026, 4, 1),
    )

    assert item.last_sync_date == date(2026, 4, 1)


def test_ops_freshness_does_not_read_legacy_quality_warning_logs(
    app_client,
    user_factory,
    trade_calendar_factory,
    sync_job_state_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 30), is_open=True, pretrade_date=date(2026, 3, 27))
    sync_job_state_factory(
        job_name="sync_dividend",
        target_table="core.equity_dividend",
        last_success_date=date(2026, 3, 30),
        last_success_at=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        full_sync_done=True,
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
    dividend_item = grouped["event"]["dividend"]
    assert "质量提醒" not in (dividend_item["freshness_note"] or "")


def test_build_freshness_merges_missing_datasets_when_snapshot_is_incomplete(
    db_session,
    monkeypatch,
) -> None:
    service = OpsFreshnessQueryService()

    snapshot_item = DatasetFreshnessItem(
        dataset_key="daily",
        resource_key="daily",
        display_name="股票日线",
        domain_key="equity",
        domain_display_name="股票",
        job_name="sync_equity_daily",
        target_table="core.equity_daily_bar",
        cadence="daily",
        freshness_status="fresh",
        primary_execution_spec_key="daily.maintain",
        full_sync_done=False,
    )
    live_missing_item = DatasetFreshnessItem(
        dataset_key="ths_hot",
        resource_key="ths_hot",
        display_name="同花顺热榜",
        domain_key="ranking",
        domain_display_name="榜单",
        job_name="sync_ths_hot",
        target_table="core.ths_hot",
        cadence="daily",
        freshness_status="unknown",
        primary_execution_spec_key="ths_hot.maintain",
        full_sync_done=False,
    )
    snapshot_response = OpsFreshnessResponse(
        summary=OpsFreshnessSummary(
            total_datasets=1,
            fresh_datasets=1,
            lagging_datasets=0,
            stale_datasets=0,
            unknown_datasets=0,
            disabled_datasets=0,
        ),
        groups=[
            FreshnessGroup(
                domain_key="equity",
                domain_display_name="股票",
                items=[snapshot_item],
            )
        ],
    )

    monkeypatch.setattr(service, "_build_from_snapshot", lambda _session: snapshot_response)
    monkeypatch.setattr(
        "src.ops.queries.freshness_query_service.list_dataset_freshness_specs",
        lambda: [
            DatasetFreshnessSpec(
                dataset_key="daily",
                resource_key="daily",
                job_name="sync_equity_daily",
                display_name="股票日线",
                domain_key="equity",
                domain_display_name="股票",
                target_table="core.equity_daily_bar",
                cadence="daily",
                observed_date_column="trade_date",
                primary_execution_spec_key="daily.maintain",
            ),
            DatasetFreshnessSpec(
                dataset_key="ths_hot",
                resource_key="ths_hot",
                job_name="sync_ths_hot",
                display_name="同花顺热榜",
                domain_key="ranking",
                domain_display_name="榜单",
                target_table="core.ths_hot",
                cadence="daily",
                observed_date_column="trade_date",
                primary_execution_spec_key="ths_hot.maintain",
            ),
        ],
    )
    monkeypatch.setattr(
        service,
        "build_live_items",
        lambda _session, *, today=None, resource_keys=None: [live_missing_item] if resource_keys == ["ths_hot"] else [],
    )

    response = service.build_freshness(db_session)
    dataset_keys = {item.dataset_key for group in response.groups for item in group.items}

    assert "daily" in dataset_keys
    assert "ths_hot" in dataset_keys


def test_build_freshness_refreshes_snapshot_when_cadence_changed(
    db_session,
    monkeypatch,
) -> None:
    service = OpsFreshnessQueryService()
    snapshot_item = DatasetFreshnessItem(
        dataset_key="broker_recommend",
        resource_key="broker_recommend",
        display_name="券商每月荐股",
        domain_key="reference_data",
        domain_display_name="基础主数据",
        job_name="sync_broker_recommend",
        target_table="core_serving.broker_recommend",
        cadence="reference",
        latest_business_date=date(2026, 4, 1),
        freshness_status="stale",
        primary_execution_spec_key="broker_recommend.maintain",
        full_sync_done=True,
    )
    live_item = DatasetFreshnessItem(
        dataset_key="broker_recommend",
        resource_key="broker_recommend",
        display_name="券商每月荐股",
        domain_key="reference_data",
        domain_display_name="基础主数据",
        job_name="sync_broker_recommend",
        target_table="core_serving.broker_recommend",
        cadence="monthly",
        latest_business_date=date(2026, 4, 1),
        freshness_status="fresh",
        primary_execution_spec_key="broker_recommend.maintain",
        full_sync_done=True,
    )
    snapshot_response = OpsFreshnessResponse(
        summary=OpsFreshnessSummary(
            total_datasets=1,
            fresh_datasets=0,
            lagging_datasets=0,
            stale_datasets=1,
            unknown_datasets=0,
            disabled_datasets=0,
        ),
        groups=[
            FreshnessGroup(
                domain_key="reference_data",
                domain_display_name="基础主数据",
                items=[snapshot_item],
            )
        ],
    )
    monkeypatch.setattr(service, "_build_from_snapshot", lambda _session: snapshot_response)
    monkeypatch.setattr(
        "src.ops.queries.freshness_query_service.list_dataset_freshness_specs",
        lambda: [
            DatasetFreshnessSpec(
                dataset_key="broker_recommend",
                resource_key="broker_recommend",
                job_name="sync_broker_recommend",
                display_name="券商每月荐股",
                domain_key="reference_data",
                domain_display_name="基础主数据",
                target_table="core_serving.broker_recommend",
                cadence="monthly",
                observed_date_column=None,
                primary_execution_spec_key="broker_recommend.maintain",
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "build_live_items",
        lambda _session, *, today=None, resource_keys=None: [live_item] if resource_keys == ["broker_recommend"] else [],
    )

    response = service.build_freshness(db_session)
    item = next(
        item
        for group in response.groups
        for item in group.items
        if item.dataset_key == "broker_recommend"
    )
    assert item.cadence == "monthly"
    assert item.freshness_status == "fresh"


def test_observed_snapshot_for_stk_period_week_adds_freq_filter(mocker) -> None:
    service = OpsFreshnessQueryService()
    spec = DatasetFreshnessSpec(
        dataset_key="stk_period_bar_week",
        resource_key="stk_period_bar_week",
        job_name="sync_stk_period_bar_week",
        display_name="股票周线",
        domain_key="equity",
        domain_display_name="股票",
        target_table="core_serving.stk_period_bar",
        cadence="weekly",
        observed_date_column="trade_date",
        primary_execution_spec_key="stk_period_bar_week.maintain",
    )
    session = mocker.Mock()
    session.execute.return_value.one.return_value = (date(2020, 1, 1), date(2026, 4, 3))

    observed_ranges, _ = service._observed_dataset_snapshots(session, [spec])

    assert observed_ranges["stk_period_bar_week"] == (date(2020, 1, 1), date(2026, 4, 3))
    query = session.execute.call_args.args[0]
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "freq" in compiled
    assert "week" in compiled


def test_build_freshness_overrides_snapshot_with_live_weekly_item(
    db_session,
    monkeypatch,
) -> None:
    service = OpsFreshnessQueryService()
    snapshot_item = DatasetFreshnessItem(
        dataset_key="stk_period_bar_week",
        resource_key="stk_period_bar_week",
        display_name="股票周线",
        domain_key="equity",
        domain_display_name="股票",
        job_name="sync_stk_period_bar_week",
        target_table="core_serving.stk_period_bar",
        cadence="weekly",
        latest_business_date=date(2026, 3, 27),
        observed_business_date=date(2026, 3, 27),
        freshness_status="fresh",
        primary_execution_spec_key="stk_period_bar_week.maintain",
        full_sync_done=False,
    )
    live_item = DatasetFreshnessItem(
        dataset_key="stk_period_bar_week",
        resource_key="stk_period_bar_week",
        display_name="股票周线",
        domain_key="equity",
        domain_display_name="股票",
        job_name="sync_stk_period_bar_week",
        target_table="core_serving.stk_period_bar",
        cadence="weekly",
        latest_business_date=date(2026, 4, 3),
        observed_business_date=date(2026, 4, 3),
        freshness_status="fresh",
        primary_execution_spec_key="stk_period_bar_week.maintain",
        full_sync_done=False,
    )
    snapshot_response = OpsFreshnessResponse(
        summary=OpsFreshnessSummary(
            total_datasets=1,
            fresh_datasets=1,
            lagging_datasets=0,
            stale_datasets=0,
            unknown_datasets=0,
            disabled_datasets=0,
        ),
        groups=[
            FreshnessGroup(
                domain_key="equity",
                domain_display_name="股票",
                items=[snapshot_item],
            )
        ],
    )

    monkeypatch.setattr(service, "_build_from_snapshot", lambda _session: snapshot_response)
    monkeypatch.setattr(
        "src.ops.queries.freshness_query_service.list_dataset_freshness_specs",
        lambda: [
            DatasetFreshnessSpec(
                dataset_key="stk_period_bar_week",
                resource_key="stk_period_bar_week",
                job_name="sync_stk_period_bar_week",
                display_name="股票周线",
                domain_key="equity",
                domain_display_name="股票",
                target_table="core_serving.stk_period_bar",
                cadence="weekly",
                observed_date_column="trade_date",
                primary_execution_spec_key="stk_period_bar_week.maintain",
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "build_live_items",
        lambda _session, *, today=None, resource_keys=None: [live_item] if resource_keys == ["stk_period_bar_week"] else [],
    )

    response = service.build_freshness(db_session)
    item = next(
        item
        for group in response.groups
        for item in group.items
        if item.dataset_key == "stk_period_bar_week"
    )
    assert item.latest_business_date == date(2026, 4, 3)


def test_build_freshness_refreshes_snapshot_items_missing_business_date_with_live_data(
    db_session,
    monkeypatch,
) -> None:
    service = OpsFreshnessQueryService()
    snapshot_item = DatasetFreshnessItem(
        dataset_key="stk_nineturn",
        resource_key="stk_nineturn",
        display_name="神奇九转指标",
        domain_key="equity",
        domain_display_name="股票",
        job_name="sync_stk_nineturn",
        target_table="core_serving.equity_nineturn",
        cadence="daily",
        last_sync_date=date(2026, 4, 16),
        latest_business_date=None,
        freshness_status="unknown",
        primary_execution_spec_key="stk_nineturn.maintain",
        full_sync_done=False,
    )
    live_item = DatasetFreshnessItem(
        dataset_key="stk_nineturn",
        resource_key="stk_nineturn",
        display_name="神奇九转指标",
        domain_key="equity",
        domain_display_name="股票",
        job_name="sync_stk_nineturn",
        target_table="core_serving.equity_nineturn",
        cadence="daily",
        earliest_business_date=date(2020, 1, 1),
        observed_business_date=date(2026, 4, 16),
        latest_business_date=date(2026, 4, 16),
        freshness_status="fresh",
        primary_execution_spec_key="stk_nineturn.maintain",
        full_sync_done=False,
    )
    snapshot_response = OpsFreshnessResponse(
        summary=OpsFreshnessSummary(
            total_datasets=1,
            fresh_datasets=0,
            lagging_datasets=0,
            stale_datasets=0,
            unknown_datasets=1,
            disabled_datasets=0,
        ),
        groups=[
            FreshnessGroup(
                domain_key="equity",
                domain_display_name="股票",
                items=[snapshot_item],
            )
        ],
    )
    monkeypatch.setattr(service, "_build_from_snapshot", lambda _session: snapshot_response)
    monkeypatch.setattr(
        "src.ops.queries.freshness_query_service.list_dataset_freshness_specs",
        lambda: [
            DatasetFreshnessSpec(
                dataset_key="stk_nineturn",
                resource_key="stk_nineturn",
                job_name="sync_stk_nineturn",
                display_name="神奇九转指标",
                domain_key="equity",
                domain_display_name="股票",
                target_table="core_serving.equity_nineturn",
                cadence="daily",
                observed_date_column="trade_date",
                primary_execution_spec_key="stk_nineturn.maintain",
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "build_live_items",
        lambda _session, *, today=None, resource_keys=None: [live_item] if resource_keys == ["stk_nineturn"] else [],
    )

    response = service.build_freshness(db_session)
    item = next(
        item
        for group in response.groups
        for item in group.items
        if item.dataset_key == "stk_nineturn"
    )
    assert item.latest_business_date == date(2026, 4, 16)


def test_build_freshness_refreshes_snapshot_items_missing_business_range_with_live_data(
    db_session,
    monkeypatch,
) -> None:
    service = OpsFreshnessQueryService()
    snapshot_item = DatasetFreshnessItem(
        dataset_key="stk_nineturn",
        resource_key="stk_nineturn",
        display_name="神奇九转指标",
        domain_key="equity",
        domain_display_name="股票",
        job_name="sync_stk_nineturn",
        target_table="core_serving.equity_nineturn",
        cadence="daily",
        last_sync_date=date(2026, 4, 16),
        earliest_business_date=None,
        latest_business_date=date(2026, 4, 15),
        freshness_status="fresh",
        primary_execution_spec_key="stk_nineturn.maintain",
        full_sync_done=False,
    )
    live_item = DatasetFreshnessItem(
        dataset_key="stk_nineturn",
        resource_key="stk_nineturn",
        display_name="神奇九转指标",
        domain_key="equity",
        domain_display_name="股票",
        job_name="sync_stk_nineturn",
        target_table="core_serving.equity_nineturn",
        cadence="daily",
        earliest_business_date=date(2016, 8, 9),
        observed_business_date=date(2026, 4, 16),
        latest_business_date=date(2026, 4, 16),
        freshness_status="fresh",
        primary_execution_spec_key="stk_nineturn.maintain",
        full_sync_done=False,
    )
    snapshot_response = OpsFreshnessResponse(
        summary=OpsFreshnessSummary(
            total_datasets=1,
            fresh_datasets=1,
            lagging_datasets=0,
            stale_datasets=0,
            unknown_datasets=0,
            disabled_datasets=0,
        ),
        groups=[
            FreshnessGroup(
                domain_key="equity",
                domain_display_name="股票",
                items=[snapshot_item],
            )
        ],
    )
    monkeypatch.setattr(service, "_build_from_snapshot", lambda _session: snapshot_response)
    monkeypatch.setattr(
        "src.ops.queries.freshness_query_service.list_dataset_freshness_specs",
        lambda: [
            DatasetFreshnessSpec(
                dataset_key="stk_nineturn",
                resource_key="stk_nineturn",
                job_name="sync_stk_nineturn",
                display_name="神奇九转指标",
                domain_key="equity",
                domain_display_name="股票",
                target_table="core_serving.equity_nineturn",
                cadence="daily",
                observed_date_column="trade_date",
                primary_execution_spec_key="stk_nineturn.maintain",
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "build_live_items",
        lambda _session, *, today=None, resource_keys=None: [live_item] if resource_keys == ["stk_nineturn"] else [],
    )

    response = service.build_freshness(db_session)
    item = next(
        item
        for group in response.groups
        for item in group.items
        if item.dataset_key == "stk_nineturn"
    )
    assert item.earliest_business_date == date(2016, 8, 9)
    assert item.latest_business_date == date(2026, 4, 16)


def test_stk_period_month_prefers_observed_business_date_over_state_date() -> None:
    service = OpsFreshnessQueryService()
    spec = DatasetFreshnessSpec(
        dataset_key="stk_period_bar_month",
        resource_key="stk_period_bar_month",
        job_name="sync_stk_period_bar_month",
        display_name="股票月线",
        domain_key="equity",
        domain_display_name="股票",
        target_table="core_serving.stk_period_bar",
        cadence="monthly",
        observed_date_column="trade_date",
        primary_execution_spec_key="stk_period_bar_month.maintain",
    )
    state = Mock(
        last_success_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
        last_success_date=date(2026, 3, 20),
        full_sync_done=False,
    )

    item = service._build_item(
        spec=spec,
        state=state,
        latest_open_date=date(2026, 3, 20),
        reference_date=date(2026, 3, 20),
        recent_failure=None,
        quality_note=None,
        observed_business_range=(date(2010, 1, 31), date(2026, 2, 28)),
        observed_sync_date=date(2026, 2, 28),
    )

    assert item.earliest_business_date == date(2010, 1, 31)
    assert item.observed_business_date == date(2026, 2, 28)
    assert item.latest_business_date == date(2026, 2, 28)
    assert item.business_date_source == "observed"


def test_broker_recommend_monthly_dataset_synced_at_month_start_is_fresh() -> None:
    service = OpsFreshnessQueryService()
    spec = DatasetFreshnessSpec(
        dataset_key="broker_recommend",
        resource_key="broker_recommend",
        job_name="sync_broker_recommend",
        display_name="券商每月荐股",
        domain_key="reference_data",
        domain_display_name="基础主数据",
        target_table="core_serving.broker_recommend",
        cadence="monthly",
        observed_date_column=None,
        primary_execution_spec_key="broker_recommend.maintain",
    )
    state = Mock(
        last_success_at=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
        last_success_date=date(2026, 4, 1),
        full_sync_done=True,
    )

    item = service._build_item(
        spec=spec,
        state=state,
        latest_open_date=date(2026, 4, 16),
        reference_date=date(2026, 4, 16),
        recent_failure=None,
        quality_note=None,
        observed_business_range=None,
        observed_sync_date=None,
    )

    assert item.latest_business_date == date(2026, 4, 1)
    assert item.lag_days == 15
    assert item.freshness_status == "fresh"


def test_reference_dataset_uses_last_sync_date_as_business_date_when_no_observed_date() -> None:
    service = OpsFreshnessQueryService()
    spec = DatasetFreshnessSpec(
        dataset_key="stock_basic",
        resource_key="stock_basic",
        job_name="sync_stock_basic",
        display_name="股票主数据",
        domain_key="reference_data",
        domain_display_name="基础主数据",
        target_table="core_serving.security_serving",
        cadence="reference",
        observed_date_column=None,
        primary_execution_spec_key="stock_basic.maintain",
    )
    state = Mock(
        last_success_at=datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
        last_success_date=None,
        full_sync_done=True,
    )

    item = service._build_item(
        spec=spec,
        state=state,
        latest_open_date=date(2026, 4, 15),
        reference_date=date(2026, 4, 15),
        recent_failure=None,
        quality_note=None,
        observed_business_range=(None, None),
        observed_sync_date=None,
    )

    assert item.latest_business_date == date(2026, 4, 15)
    assert item.business_date_source == "sync_date"
    assert item.freshness_note == "该数据集无业务日期字段，已使用最近同步日期作为业务日期。"
