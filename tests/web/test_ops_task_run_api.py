from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.ops.models.ops.task_run import TaskRun


def auth_headers(app_client, username: str = "admin", password: str = "secret") -> dict[str, str]:  # type: ignore[no-untyped-def]
    login = app_client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_ops_task_run_list_rejects_non_admin(app_client, user_factory, task_run_factory) -> None:
    user = user_factory(username="user", password="secret", is_admin=False)
    task_run_factory(requested_by_user_id=user.id)

    response = app_client.get("/api/v1/ops/task-runs", headers=auth_headers(app_client, "user"))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_task_run_list_returns_latest_first_and_supports_status_filter(
    app_client,
    user_factory,
    task_run_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    base = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
    older = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="stock_basic",
        title="股票主数据",
        status="success",
        requested_at=base,
    )
    newer = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="index_weekly",
        title="指数周线",
        status="failed",
        requested_at=base + timedelta(minutes=5),
    )
    headers = auth_headers(app_client)

    response = app_client.get("/api/v1/ops/task-runs", headers=headers)
    filtered = app_client.get("/api/v1/ops/task-runs?status=failed", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["id"] for item in payload["items"]] == [newer.id, older.id]
    assert payload["items"][0]["requested_by_username"] == "admin"

    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 1
    assert filtered_payload["items"][0]["id"] == newer.id
    assert filtered_payload["items"][0]["title"] == "指数周线"
    assert filtered_payload["items"][0]["resource_key"] == "index_weekly"


def test_ops_task_run_summary_returns_filtered_status_counts(
    app_client,
    user_factory,
    task_run_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    base = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
    for offset, status in enumerate(["queued", "running", "canceling", "success", "failed", "partial_success", "canceled"]):
        task_run_factory(
            requested_by_user_id=admin.id,
            trigger_source="manual",
            status=status,
            requested_at=base + timedelta(minutes=offset),
        )
    task_run_factory(
        requested_by_user_id=admin.id,
        trigger_source="scheduled",
        status="failed",
        requested_at=base + timedelta(minutes=7),
    )

    response = app_client.get("/api/v1/ops/task-runs/summary?trigger_source=manual", headers=auth_headers(app_client))

    assert response.status_code == 200
    assert response.json() == {
        "total": 7,
        "queued": 1,
        "running": 2,
        "success": 1,
        "failed": 2,
        "canceled": 1,
    }


def test_ops_task_run_create_returns_readable_missing_dataset_message(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)

    response = app_client.post(
        "/api/v1/ops/task-runs",
        headers=auth_headers(app_client),
        json={"task_type": "dataset_action", "action": "maintain", "time_input": {"mode": "none"}, "filters": {}},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "数据集任务缺少维护对象"


def test_ops_task_run_view_returns_single_snapshot_and_nodes(
    app_client,
    db_session,
    user_factory,
    task_run_factory,
    task_run_node_factory,
    task_run_issue_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    task_run = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="daily",
        title="股票日线",
        status="failed",
        time_input_json={"mode": "range", "start_date": "2026-04-20", "end_date": "2026-04-24"},
        unit_total=5,
        unit_done=4,
        unit_failed=1,
        progress_percent=80,
        rows_fetched=100,
        rows_saved=90,
        rows_rejected=10,
        rejected_reason_counts_json={
            "normalize.required_field_missing:trade_date": 7,
            "normalize.invalid_decimal": 3,
        },
        current_object_json={
            "entity": {"kind": "security", "code": "000001.SZ", "name": "平安银行"},
            "time": {"start": "2026-04-20", "end": "2026-04-24"},
            "attributes": {"freq": "1min"},
        },
    )
    node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="daily:range",
        title="维护 股票日线",
        status="failed",
        rows_fetched=100,
        rows_saved=90,
        rows_rejected=10,
        rejected_reason_counts_json={"normalize.required_field_missing:trade_date": 7},
    )
    issue = task_run_issue_factory(
        task_run_id=task_run.id,
        node_id=node.id,
        code="ingestion_failed",
        title="任务处理失败",
        message="唯一键冲突",
        object_json={
            "entity": {"kind": "security", "code": "000001.SZ", "name": "平安银行"},
            "time": {"point": "2026-04-23"},
            "attributes": {"freq": "1min"},
        },
    )
    task_run.primary_issue_id = issue.id
    node.issue_id = issue.id
    task_run.current_node_id = node.id
    task_run.unit_failed = 1
    db_session.commit()

    response = app_client.get(f"/api/v1/ops/task-runs/{task_run.id}/view", headers=auth_headers(app_client))

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["title"] == "股票日线"
    assert payload["run"]["time_scope_label"] == "2026-04-20 ~ 2026-04-24"
    assert payload["progress"]["rows_saved"] == 90
    assert payload["progress"]["rejected_reason_counts"]["normalize.required_field_missing:trade_date"] == 7
    assert payload["progress"]["rejected_reasons"][0]["reason_code"] == "normalize.required_field_missing"
    assert payload["progress"]["rejected_reasons"][0]["field"] == "trade_date"
    assert payload["progress"]["rejected_reasons"][0]["label"] == "必填字段缺失"
    assert payload["progress"]["current_object"] is None
    assert payload["primary_issue"]["title"] == "任务处理失败"
    assert payload["primary_issue"]["object"]["title"] == "问题位置：平安银行（000001.SZ）"
    assert payload["nodes"][0]["title"] == "维护 股票日线"
    assert payload["nodes"][0]["rejected_reasons"][0]["count"] == 7


def test_ops_task_run_view_returns_display_current_object_for_running_task(
    app_client,
    user_factory,
    task_run_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    task_run = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="stk_mins",
        title="股票分钟线",
        status="running",
        unit_total=10,
        unit_done=2,
        progress_percent=20,
        current_object_json={
            "entity": {"kind": "security", "code": "920429.BJ", "name": "康比特"},
            "time": {"kind": "range", "start_date": "2026-01-05", "end_date": "2026-04-24"},
            "attributes": {"freq": "60min"},
        },
    )

    response = app_client.get(f"/api/v1/ops/task-runs/{task_run.id}/view", headers=auth_headers(app_client))

    assert response.status_code == 200
    current_object = response.json()["progress"]["current_object"]
    assert current_object["title"] == "正在处理：康比特（920429.BJ）"
    assert current_object["description"] == "处理范围：2026-01-05 ~ 2026-04-24；频率：60min"
    assert {"label": "证券代码", "value": "920429.BJ"} in current_object["fields"]


def test_ops_task_run_view_resolves_dataset_attribute_title_from_definition(
    app_client,
    user_factory,
    task_run_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    task_run = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="daily",
        title="股票日线",
        status="running",
        current_object_json={
            "attributes": {"dataset_key": "daily"},
        },
    )

    response = app_client.get(f"/api/v1/ops/task-runs/{task_run.id}/view", headers=auth_headers(app_client))

    assert response.status_code == 200
    current_object = response.json()["progress"]["current_object"]
    assert current_object["title"] == "正在处理：股票日线"


def test_ops_task_run_view_does_not_show_unit_id_as_current_object_title(
    app_client,
    user_factory,
    task_run_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    task_run = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="daily",
        title="股票日线",
        status="running",
        current_object_json={
            "attributes": {"unit_id": "daily:2026-04-24:0"},
        },
    )

    response = app_client.get(f"/api/v1/ops/task-runs/{task_run.id}/view", headers=auth_headers(app_client))

    assert response.status_code == 200
    assert response.json()["progress"]["current_object"] is None


def test_ops_task_run_retry_and_cancel_use_task_run_api(app_client, user_factory, task_run_factory) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    failed = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="daily",
        title="股票日线",
        status="failed",
        time_input_json={"mode": "point", "trade_date": "2026-04-24"},
    )
    queued = task_run_factory(
        requested_by_user_id=admin.id,
        resource_key="daily",
        title="股票日线",
        status="queued",
    )
    headers = auth_headers(app_client)

    retry = app_client.post(f"/api/v1/ops/task-runs/{failed.id}/retry", headers=headers)
    cancel = app_client.post(f"/api/v1/ops/task-runs/{queued.id}/cancel", headers=headers)

    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"
    assert retry.json()["id"] != failed.id
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "canceled"


def test_ops_task_run_retry_recovers_scheduled_workflow_target(
    app_client,
    db_session,
    user_factory,
    ops_schedule_factory,
    task_run_factory,
) -> None:
    admin = user_factory(username="admin", password="secret", is_admin=True)
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key="daily_moneyflow_maintenance",
        display_name="每日资金流维护",
        params_json={},
    )
    failed = task_run_factory(
        task_type="workflow",
        resource_key=None,
        action="maintain",
        title="每日资金流维护",
        trigger_source="scheduled",
        status="failed",
        requested_by_user_id=admin.id,
        schedule_id=schedule.id,
        time_input_json={"mode": "point"},
        request_payload_json={},
    )

    retry = app_client.post(f"/api/v1/ops/task-runs/{failed.id}/retry", headers=auth_headers(app_client))

    assert retry.status_code == 200
    body = retry.json()
    assert body["status"] == "queued"
    new_task_run = db_session.get(TaskRun, body["id"])
    assert new_task_run is not None
    assert new_task_run.task_type == "workflow"
    assert new_task_run.trigger_source == "retry"
    assert new_task_run.schedule_id == schedule.id
    assert new_task_run.request_payload_json["target_type"] == "workflow"
    assert new_task_run.request_payload_json["target_key"] == "daily_moneyflow_maintenance"


def test_removed_ops_executions_routes_do_not_exist(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    removed_path = "/api/v1/ops/" + "executions"
    response = app_client.get(removed_path, headers=auth_headers(app_client))

    assert response.status_code == 404
