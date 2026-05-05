from __future__ import annotations

from datetime import date, datetime, timezone

from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.ops.dataset_definition_projection import DatasetFreshnessProjection
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.schemas.freshness import DatasetFreshnessItem, FreshnessGroup, OpsFreshnessResponse, OpsFreshnessSummary


def _mark_resource_success(
    *,
    task_run_factory,
    task_run_node_factory,
    resource_key: str,
    ended_at: datetime,
):
    task_run = task_run_factory(
        resource_key=resource_key,
        status="success",
        requested_at=ended_at,
        started_at=ended_at,
        ended_at=ended_at,
    )
    task_run_node_factory(
        task_run_id=task_run.id,
        resource_key=resource_key,
        status="success",
        started_at=ended_at,
        ended_at=ended_at,
    )
    return task_run


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
    equity_block_trade_factory,
    task_run_factory,
    task_run_node_factory,
    task_run_issue_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2025, 12, 31), is_open=True, pretrade_date=date(2025, 12, 30))
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 2, 27), is_open=True, pretrade_date=date(2026, 2, 26))
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 26), is_open=True, pretrade_date=date(2026, 3, 25))
    equity_block_trade_factory(trade_date=date(2020, 1, 1))
    equity_block_trade_factory(trade_date=date(2026, 3, 26), ts_code="000002.SZ", buyer="buyer-2", seller="seller-2", price="11.00", vol="1200.00")
    db_session.add(
        IndexMonthlyServing(
            ts_code="000001.SH",
            period_start_date=date(2025, 12, 1),
            trade_date=date(2025, 12, 31),
            source="api",
        )
    )
    _mark_resource_success(
        task_run_factory=task_run_factory,
        task_run_node_factory=task_run_node_factory,
        resource_key="block_trade",
        ended_at=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
    )
    _mark_resource_success(
        task_run_factory=task_run_factory,
        task_run_node_factory=task_run_node_factory,
        resource_key="index_monthly",
        ended_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
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
    block_trade = grouped["equity_market"]["block_trade"]
    index_monthly = grouped["index_fund"]["index_monthly"]
    assert block_trade["freshness_status"] == "fresh"
    assert block_trade["latest_business_date"] == "2026-03-26"
    assert block_trade["earliest_business_date"] == "2020-01-01"
    assert block_trade["freshness_note"] == "最新业务日当前来自真实目标表观测值。"
    assert block_trade["primary_action_key"] == "block_trade.maintain"
    assert index_monthly["freshness_status"] == "stale"
    assert index_monthly["recent_failure_message"] == "monthly sync timeout"
    assert index_monthly["recent_failure_summary"] == "monthly sync timeout"


def test_ops_freshness_includes_auto_schedule_flags(
    app_client,
    user_factory,
    trade_calendar_factory,
    equity_block_trade_factory,
    task_run_factory,
    task_run_node_factory,
    ops_schedule_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 26), is_open=True, pretrade_date=date(2026, 3, 25))
    equity_block_trade_factory(trade_date=date(2026, 3, 26))
    _mark_resource_success(
        task_run_factory=task_run_factory,
        task_run_node_factory=task_run_node_factory,
        resource_key="block_trade",
        ended_at=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
    )
    ops_schedule_factory(
        target_type="dataset_action",
        target_key="block_trade.maintain",
        status="active",
        schedule_type="cron",
        cron_expr="30 18 * * *",
        next_run_at=datetime(2026, 3, 31, 10, 30, tzinfo=timezone.utc),
    )
    ops_schedule_factory(
        target_type="dataset_action",
        target_key="block_trade.maintain",
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
    item = grouped["equity_market"]["block_trade"]
    assert item["auto_schedule_status"] == "active"
    assert item["auto_schedule_total"] == 2
    assert item["auto_schedule_active"] == 1
    assert item["auto_schedule_next_run_at"] == "2026-03-31T10:30:00"


def test_ops_freshness_marks_dataset_as_automatic_when_covered_by_workflow_schedule(
    app_client,
    user_factory,
    ops_schedule_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    ops_schedule_factory(
        target_type="workflow",
        target_key="reference_data_refresh",
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
    assert grouped["reference_data"]["stock_basic"]["auto_schedule_status"] == "active"
    assert grouped["reference_data"]["stock_basic"]["auto_schedule_total"] == 1
    assert grouped["reference_data"]["trade_cal"]["auto_schedule_status"] == "active"
    assert grouped["reference_data"]["trade_cal"]["auto_schedule_total"] == 1


def test_ops_freshness_exposes_active_task_run_status_for_dataset(
    app_client,
    user_factory,
    trade_calendar_factory,
    equity_block_trade_factory,
    task_run_factory,
    task_run_node_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 4, 16), is_open=True, pretrade_date=date(2026, 4, 15))
    equity_block_trade_factory(trade_date=date(2026, 4, 16))
    _mark_resource_success(
        task_run_factory=task_run_factory,
        task_run_node_factory=task_run_node_factory,
        resource_key="block_trade",
        ended_at=datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc),
    )
    task_run_factory(
        resource_key="block_trade",
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
    block_trade = grouped["equity_market"]["block_trade"]
    assert block_trade["active_task_run_status"] == "running"
    assert block_trade["active_task_run_started_at"] == "2026-04-17T08:01:00"


def test_ops_freshness_hides_historical_failure_when_newer_success_exists(
    app_client,
    db_session,
    user_factory,
    trade_calendar_factory,
    equity_block_trade_factory,
    task_run_factory,
    task_run_node_factory,
    task_run_issue_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 26), is_open=True, pretrade_date=date(2026, 3, 25))
    equity_block_trade_factory(trade_date=date(2026, 3, 26))
    failed = task_run_factory(
        resource_key="block_trade",
        status="failed",
        requested_at=datetime(2026, 3, 25, 8, 18, 18, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 25, 8, 18, 18, tzinfo=timezone.utc),
    )
    issue = task_run_issue_factory(
        task_run_id=failed.id,
        code="task_failed",
        title="任务失败",
        message="historical failure should be hidden",
        occurred_at=datetime(2026, 3, 25, 8, 18, 18, tzinfo=timezone.utc),
    )
    failed.primary_issue_id = issue.id
    _mark_resource_success(
        task_run_factory=task_run_factory,
        task_run_node_factory=task_run_node_factory,
        resource_key="block_trade",
        ended_at=datetime(2026, 3, 25, 9, 11, 31, tzinfo=timezone.utc),
    )
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
    block_trade = grouped["equity_market"]["block_trade"]
    assert block_trade["recent_failure_message"] is None
    assert block_trade["recent_failure_summary"] is None


def test_ops_freshness_marks_unsynced_dataset_as_unknown(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/freshness", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["unknown_datasets"] > 0


def test_build_item_uses_runtime_trace_for_not_applicable_dataset() -> None:
    service = OpsFreshnessQueryService()
    projection = DatasetFreshnessProjection(
        dataset_key="ths_member",
        resource_key="ths_member",
        display_name="同花顺板块成分",
        domain_key="board",
        domain_display_name="板块",
        target_table="core_serving.ths_member",
        cadence="reference",
        raw_table="raw_tushare.ths_member",
        observed_date_column=None,
        primary_action_key="ths_member.maintain",
    )

    item = service._build_item(
        projection=projection,
        latest_success_at=datetime(2026, 4, 1, 9, 30, tzinfo=timezone.utc),
        latest_open_date=date(2026, 4, 1),
        reference_date=date(2026, 4, 1),
        expected_business_date=None,
        recent_failure=None,
        quality_note=None,
        observed_business_range=None,
        observed_sync_date=None,
        observed_at_range=None,
    )

    assert item.latest_business_date is None
    assert item.last_sync_date == date(2026, 4, 1)
    assert item.freshness_status == "unknown"
    assert item.freshness_note == "该数据集当前不按业务日期判断新鲜度，仅展示最近一次任务运行迹象。"


def test_build_item_prefers_runtime_trace_note_for_not_applicable_dataset_with_observed_date() -> None:
    service = OpsFreshnessQueryService()
    projection = DatasetFreshnessProjection(
        dataset_key="namechange",
        resource_key="namechange",
        display_name="股票曾用名",
        domain_key="reference_data",
        domain_display_name="基础主数据",
        target_table="core_serving_light.namechange",
        cadence="daily",
        raw_table="raw_tushare.namechange",
        observed_date_column="ann_date",
        primary_action_key="namechange.maintain",
    )

    item = service._build_item(
        projection=projection,
        latest_success_at=datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc),
        latest_open_date=date(2026, 5, 5),
        reference_date=date(2026, 5, 5),
        expected_business_date=None,
        recent_failure=None,
        quality_note=None,
        observed_business_range=(date(2010, 6, 23), date(2026, 4, 30)),
        observed_sync_date=date(2026, 4, 30),
        observed_at_range=None,
    )

    assert item.last_sync_date == date(2026, 5, 5)
    assert item.latest_business_date == date(2026, 4, 30)
    assert item.freshness_status == "unknown"
    assert item.freshness_note == "该数据集当前不按业务日期判断新鲜度，仅展示最近一次任务运行迹象。"


def test_ops_freshness_expected_date_uses_calendar_week_and_month_anchors() -> None:
    service = OpsFreshnessQueryService()
    weekly_projection = DatasetFreshnessProjection(
        dataset_key="stk_period_bar_week",
        resource_key="stk_period_bar_week",
        display_name="股票周线行情",
        domain_key="equity_market",
        domain_display_name="A股行情",
        target_table="core_serving.stk_period_bar",
        cadence="daily",
        raw_table="raw_tushare.stk_period_bar",
        observed_date_column="trade_date",
        primary_action_key="stk_period_bar_week.maintain",
    )
    monthly_projection = DatasetFreshnessProjection(
        dataset_key="stk_period_bar_month",
        resource_key="stk_period_bar_month",
        display_name="股票月线行情",
        domain_key="equity_market",
        domain_display_name="A股行情",
        target_table="core_serving.stk_period_bar",
        cadence="daily",
        raw_table="raw_tushare.stk_period_bar",
        observed_date_column="trade_date",
        primary_action_key="stk_period_bar_month.maintain",
    )

    assert service._expected_business_date_for_projection(
        weekly_projection,
        reference_date=date(2026, 5, 2),
        latest_open_date=date(2026, 4, 30),
        open_trade_dates=[],
    ) == date(2026, 5, 1)
    assert service._expected_business_date_for_projection(
        monthly_projection,
        reference_date=date(2026, 4, 29),
        latest_open_date=date(2026, 4, 29),
        open_trade_dates=[],
    ) == date(2026, 3, 31)
    assert service._expected_business_date_for_projection(
        monthly_projection,
        reference_date=date(2026, 4, 30),
        latest_open_date=date(2026, 4, 30),
        open_trade_dates=[],
    ) == date(2026, 4, 30)


def test_ops_freshness_does_not_read_legacy_quality_warning_logs(
    app_client,
    user_factory,
    trade_calendar_factory,
    equity_block_trade_factory,
    task_run_factory,
    task_run_node_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 3, 26), is_open=True, pretrade_date=date(2026, 3, 25))
    equity_block_trade_factory(trade_date=date(2026, 3, 26))
    _mark_resource_success(
        task_run_factory=task_run_factory,
        task_run_node_factory=task_run_node_factory,
        resource_key="block_trade",
        ended_at=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
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
    assert "质量提醒" not in (grouped["equity_market"]["block_trade"]["freshness_note"] or "")


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
        target_table="core.equity_daily_bar",
        cadence="daily",
        freshness_status="fresh",
        primary_action_key="daily.maintain",
    )
    live_missing_item = DatasetFreshnessItem(
        dataset_key="ths_hot",
        resource_key="ths_hot",
        display_name="同花顺热榜",
        domain_key="ranking",
        domain_display_name="榜单",
        target_table="core.ths_hot",
        cadence="daily",
        freshness_status="unknown",
        primary_action_key="ths_hot.maintain",
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
        "src.ops.queries.freshness_query_service.list_dataset_freshness_projections",
        lambda: [
            DatasetFreshnessProjection(
                dataset_key="daily",
                resource_key="daily",
                display_name="股票日线",
                domain_key="equity",
                domain_display_name="股票",
                target_table="core_serving.equity_daily_bar",
                cadence="daily",
                raw_table="raw_tushare.daily",
                observed_date_column="trade_date",
                primary_action_key="daily.maintain",
            ),
            DatasetFreshnessProjection(
                dataset_key="ths_hot",
                resource_key="ths_hot",
                display_name="同花顺热榜",
                domain_key="ranking",
                domain_display_name="榜单",
                target_table="core_serving.ths_hot",
                cadence="daily",
                raw_table="raw_tushare.ths_hot",
                observed_date_column="trade_date",
                primary_action_key="ths_hot.maintain",
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
        target_table="core_serving.broker_recommend",
        cadence="reference",
        latest_business_date=date(2026, 4, 1),
        freshness_status="stale",
        primary_action_key="broker_recommend.maintain",
    )
    live_item = DatasetFreshnessItem(
        dataset_key="broker_recommend",
        resource_key="broker_recommend",
        display_name="券商每月荐股",
        domain_key="reference_data",
        domain_display_name="基础主数据",
        target_table="core_serving.broker_recommend",
        cadence="monthly",
        latest_business_date=date(2026, 4, 1),
        freshness_status="fresh",
        primary_action_key="broker_recommend.maintain",
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
        "src.ops.queries.freshness_query_service.list_dataset_freshness_projections",
        lambda: [
            DatasetFreshnessProjection(
                dataset_key="broker_recommend",
                resource_key="broker_recommend",
                display_name="券商每月荐股",
                domain_key="reference_data",
                domain_display_name="基础主数据",
                target_table="core_serving.broker_recommend",
                cadence="monthly",
                raw_table="raw_tushare.broker_recommend",
                observed_date_column="month_key",
                primary_action_key="broker_recommend.maintain",
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "build_live_items",
        lambda _session, *, today=None, resource_keys=None: [live_item] if resource_keys == ["broker_recommend"] else [],
    )

    response = service.build_freshness(db_session)
    item = response.groups[0].items[0]
    assert item.cadence == "monthly"
    assert item.freshness_status == "fresh"
