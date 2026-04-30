from __future__ import annotations

from datetime import date

from sqlalchemy import text

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.services.date_completeness_audit_service import DateCompletenessAuditWorker


def _admin_headers(app_client, user_factory) -> dict[str, str]:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _groups_by_key(payload: dict) -> dict[str, dict]:
    return {group["group_key"]: group for group in payload["groups"]}


def _items_by_key(group: dict) -> dict[str, dict]:
    return {item["dataset_key"]: item for item in group["items"]}


def test_date_completeness_rules_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})

    response = app_client.get(
        "/api/v1/ops/review/date-completeness/rules",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_date_completeness_rules_are_grouped_by_applicability(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.get("/api/v1/ops/review/date-completeness/rules", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {"total": 57, "supported": 48, "unsupported": 9}

    groups = _groups_by_key(payload)
    assert list(groups) == ["supported", "unsupported"]
    assert groups["supported"]["group_label"] == "支持审计"
    assert groups["unsupported"]["group_label"] == "不支持审计"

    supported = _items_by_key(groups["supported"])
    unsupported = _items_by_key(groups["unsupported"])

    assert supported["moneyflow_ind_dc"]["display_name"] == "板块资金流向(DC)"
    assert supported["moneyflow_ind_dc"]["target_table"] == "core_serving.board_moneyflow_dc"
    assert supported["moneyflow_ind_dc"]["date_axis"] == "trade_open_day"
    assert supported["moneyflow_ind_dc"]["bucket_rule"] == "every_open_day"
    assert supported["moneyflow_ind_dc"]["observed_field"] == "trade_date"
    assert supported["moneyflow_ind_dc"]["rule_label"] == "每个开市交易日"
    assert supported["moneyflow_ind_dc"]["audit_applicable"] is True

    assert unsupported["stock_basic"]["audit_applicable"] is False
    assert unsupported["stock_basic"]["not_applicable_reason"] == "snapshot/master dataset"
    assert "stock_basic" not in supported


def test_date_completeness_rules_cover_special_date_models(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.get("/api/v1/ops/review/date-completeness/rules", headers=headers)

    assert response.status_code == 200
    groups = _groups_by_key(response.json())
    supported = _items_by_key(groups["supported"])
    unsupported = _items_by_key(groups["unsupported"])

    assert supported["broker_recommend"]["date_axis"] == "month_key"
    assert supported["broker_recommend"]["bucket_rule"] == "every_natural_month"
    assert supported["broker_recommend"]["observed_field"] == "month"
    assert supported["broker_recommend"]["rule_label"] == "每个自然月"

    assert supported["index_weight"]["date_axis"] == "month_window"
    assert supported["index_weight"]["bucket_rule"] == "month_window_has_data"
    assert supported["index_weight"]["rule_label"] == "每个自然月窗口至少有数据"

    assert unsupported["stk_mins"]["observed_field"] == "trade_time"
    assert unsupported["stk_mins"]["not_applicable_reason"] == "minute completeness audit requires trading-session calendar"


def test_create_date_completeness_run_persists_independent_audit_record(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/review/date-completeness/runs",
        headers=headers,
        json={
            "dataset_key": "moneyflow_ind_dc",
            "start_date": "2026-04-20",
            "end_date": "2026-04-24",
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["run_status"] == "queued"
    assert created["dataset_key"] == "moneyflow_ind_dc"
    assert created["display_name"] == "板块资金流向(DC)"

    detail_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{created['id']}", headers=headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["target_table"] == "core_serving.board_moneyflow_dc"
    assert detail["date_axis"] == "trade_open_day"
    assert detail["bucket_rule"] == "every_open_day"
    assert detail["observed_field"] == "trade_date"
    assert detail["run_mode"] == "manual"
    assert detail["current_stage"] == "queued"
    assert detail["expected_bucket_count"] == 0
    assert detail["missing_bucket_count"] == 0

    list_response = app_client.get("/api/v1/ops/review/date-completeness/runs?dataset_key=moneyflow_ind_dc", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    gaps_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{created['id']}/gaps", headers=headers)
    assert gaps_response.status_code == 200
    assert gaps_response.json() == {"total": 0, "items": []}


def test_create_date_completeness_run_rejects_unsupported_dataset(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/review/date-completeness/runs",
        headers=headers,
        json={
            "dataset_key": "stock_basic",
            "start_date": "2026-04-20",
            "end_date": "2026-04-24",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "audit_not_applicable"


def test_create_date_completeness_run_rejects_invalid_range(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    response = app_client.post(
        "/api/v1/ops/review/date-completeness/runs",
        headers=headers,
        json={
            "dataset_key": "moneyflow_ind_dc",
            "start_date": "2026-04-24",
            "end_date": "2026-04-20",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_date_completeness_worker_executes_queued_run_and_records_gaps(app_client, user_factory, db_session) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 20), is_open=True, pretrade_date=date(2026, 4, 17)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 21), is_open=True, pretrade_date=date(2026, 4, 20)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 22), is_open=True, pretrade_date=date(2026, 4, 21)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 23), is_open=True, pretrade_date=date(2026, 4, 22)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 24), is_open=True, pretrade_date=date(2026, 4, 23)),
        ]
    )
    db_session.execute(text("create table core_serving.board_moneyflow_dc (trade_date date not null, board_code text not null)"))
    db_session.execute(
        text(
            """
            insert into core_serving.board_moneyflow_dc (trade_date, board_code)
            values
              ('2026-04-20', 'BK001'),
              ('2026-04-21', 'BK001'),
              ('2026-04-22', 'BK001'),
              ('2026-04-24', 'BK001')
            """
        )
    )
    db_session.commit()

    create_response = app_client.post(
        "/api/v1/ops/review/date-completeness/runs",
        headers=headers,
        json={
            "dataset_key": "moneyflow_ind_dc",
            "start_date": "2026-04-20",
            "end_date": "2026-04-24",
        },
    )
    assert create_response.status_code == 200

    run = DateCompletenessAuditWorker().run_next(db_session)

    assert run is not None
    assert run.run_status == "succeeded"
    assert run.result_status == "failed"
    assert run.expected_bucket_count == 5
    assert run.actual_bucket_count == 4
    assert run.missing_bucket_count == 1
    assert run.gap_range_count == 1

    gaps_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{run.id}/gaps", headers=headers)
    assert gaps_response.status_code == 200
    assert gaps_response.json()["items"] == [
        {
            "id": 1,
            "run_id": run.id,
            "dataset_key": "moneyflow_ind_dc",
            "bucket_kind": "trade_date",
            "range_start": "2026-04-23",
            "range_end": "2026-04-23",
            "missing_count": 1,
            "sample_values": ["2026-04-23"],
            "created_at": gaps_response.json()["items"][0]["created_at"],
        }
    ]
