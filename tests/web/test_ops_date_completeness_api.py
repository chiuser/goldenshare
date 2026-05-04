from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy import text

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.dataset_date_completeness_schedule import DatasetDateCompletenessSchedule
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
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


def test_date_completeness_rules_are_grouped_by_applicability(app_client, user_factory, db_session) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add(
        DatasetStatusSnapshot(
            dataset_key="moneyflow_ind_dc",
            resource_key="moneyflow_ind_dc",
            display_name="板块资金流向(DC)",
            domain_key="moneyflow",
            domain_display_name="资金流向",
            target_table="core_serving.board_moneyflow_dc",
            cadence="daily",
            earliest_business_date=date(2026, 4, 1),
            observed_business_date=date(2026, 4, 24),
            latest_business_date=date(2026, 4, 24),
            freshness_note=None,
            latest_success_at=None,
            last_sync_date=date(2026, 4, 24),
            expected_business_date=date(2026, 4, 24),
            lag_days=0,
            freshness_status="fresh",
            recent_failure_message=None,
            recent_failure_summary=None,
            recent_failure_at=None,
            primary_action_key="moneyflow_ind_dc.maintain",
            snapshot_date=date(2026, 4, 24),
            last_calculated_at=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = app_client.get("/api/v1/ops/review/date-completeness/rules", headers=headers)

    assert response.status_code == 200
    payload = response.json()

    groups = _groups_by_key(payload)
    assert list(groups) == ["supported", "unsupported"]
    assert groups["supported"]["group_label"] == "支持审计"
    assert groups["unsupported"]["group_label"] == "不支持审计"
    assert payload["summary"] == {
        "total": len(groups["supported"]["items"]) + len(groups["unsupported"]["items"]),
        "supported": len(groups["supported"]["items"]),
        "unsupported": len(groups["unsupported"]["items"]),
    }

    supported = _items_by_key(groups["supported"])
    unsupported = _items_by_key(groups["unsupported"])

    assert supported["moneyflow_ind_dc"]["display_name"] == "板块资金流向(DC)"
    assert supported["moneyflow_ind_dc"]["group_key"] == "moneyflow"
    assert supported["moneyflow_ind_dc"]["group_label"] == "资金流向"
    assert supported["moneyflow_ind_dc"]["domain_key"] == "moneyflow"
    assert supported["moneyflow_ind_dc"]["domain_display_name"] == "资金流向"
    assert supported["moneyflow_ind_dc"]["target_table"] == "core_serving.board_moneyflow_dc"
    assert supported["moneyflow_ind_dc"]["date_axis"] == "trade_open_day"
    assert supported["moneyflow_ind_dc"]["bucket_rule"] == "every_open_day"
    assert supported["moneyflow_ind_dc"]["observed_field"] == "trade_date"
    assert supported["moneyflow_ind_dc"]["bucket_window_rule"] is None
    assert supported["moneyflow_ind_dc"]["bucket_applicability_rule"] == "always"
    assert supported["moneyflow_ind_dc"]["rule_label"] == "每个开市交易日"
    assert supported["moneyflow_ind_dc"]["data_range"] == {
        "range_type": "business_date",
        "start_date": "2026-04-01",
        "end_date": "2026-04-24",
        "start_at": None,
        "end_at": None,
        "label": "2026/04/01 至 2026/04/24",
    }
    assert supported["moneyflow_ind_dc"]["audit_applicable"] is True
    assert supported["cctv_news"]["display_name"] == "新闻联播文字稿"
    assert supported["cctv_news"]["group_key"] == "news"
    assert supported["cctv_news"]["group_label"] == "新闻资讯"
    assert supported["cctv_news"]["target_table"] == "core_serving_light.cctv_news"
    assert supported["cctv_news"]["date_axis"] == "natural_day"
    assert supported["cctv_news"]["bucket_rule"] == "every_natural_day"
    assert supported["cctv_news"]["observed_field"] == "date"
    assert supported["cctv_news"]["rule_label"] == "每个自然日"

    assert unsupported["stock_basic"]["audit_applicable"] is False
    assert unsupported["stock_basic"]["not_applicable_reason"] == "snapshot/master dataset"
    assert unsupported["stock_basic"]["data_range"]["label"] == "—"
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

    assert supported["stk_period_bar_week"]["bucket_window_rule"] == "iso_week"
    assert supported["stk_period_bar_week"]["bucket_applicability_rule"] == "requires_open_trade_day_in_bucket"
    assert supported["stk_period_bar_month"]["bucket_window_rule"] == "natural_month"
    assert supported["stk_period_bar_month"]["bucket_applicability_rule"] == "requires_open_trade_day_in_bucket"

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
    assert detail["bucket_window_rule"] == "none"
    assert detail["bucket_applicability_rule"] == "always"
    assert detail["run_mode"] == "manual"
    assert detail["current_stage"] == "queued"
    assert detail["expected_bucket_count"] == 0
    assert detail["missing_bucket_count"] == 0
    assert detail["excluded_bucket_count"] == 0

    list_response = app_client.get("/api/v1/ops/review/date-completeness/runs?dataset_key=moneyflow_ind_dc", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    gaps_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{created['id']}/gaps", headers=headers)
    assert gaps_response.status_code == 200
    assert gaps_response.json() == {"total": 0, "items": []}
    exclusions_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{created['id']}/exclusions", headers=headers)
    assert exclusions_response.status_code == 200
    assert exclusions_response.json() == {"total": 0, "items": []}


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


def test_date_completeness_schedule_crud_and_rejects_unsupported_dataset(app_client, user_factory) -> None:
    headers = _admin_headers(app_client, user_factory)

    create_response = app_client.post(
        "/api/v1/ops/review/date-completeness/schedules",
        headers=headers,
        json={
            "dataset_key": "moneyflow_ind_dc",
            "display_name": "板块资金流向审计",
            "window_mode": "fixed_range",
            "start_date": "2026-04-20",
            "end_date": "2026-04-24",
            "calendar_scope": "default_cn_market",
            "cron_expr": "0 22 * * *",
            "timezone": "Asia/Shanghai",
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["dataset_key"] == "moneyflow_ind_dc"
    assert created["display_name"] == "板块资金流向审计"
    assert created["status"] == "active"
    assert created["next_run_at"] is not None

    list_response = app_client.get("/api/v1/ops/review/date-completeness/schedules?limit=50&offset=0", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    pause_response = app_client.post(
        f"/api/v1/ops/review/date-completeness/schedules/{created['id']}/pause",
        headers=headers,
    )
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"

    resume_response = app_client.post(
        f"/api/v1/ops/review/date-completeness/schedules/{created['id']}/resume",
        headers=headers,
    )
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "active"

    delete_response = app_client.delete(
        f"/api/v1/ops/review/date-completeness/schedules/{created['id']}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"id": created["id"], "status": "deleted"}

    unsupported_response = app_client.post(
        "/api/v1/ops/review/date-completeness/schedules",
        headers=headers,
        json={
            "dataset_key": "stock_basic",
            "window_mode": "fixed_range",
            "start_date": "2026-04-20",
            "end_date": "2026-04-24",
            "calendar_scope": "default_cn_market",
            "cron_expr": "0 22 * * *",
            "timezone": "Asia/Shanghai",
        },
    )
    assert unsupported_response.status_code == 422
    assert unsupported_response.json()["code"] == "audit_not_applicable"


def test_date_completeness_schedule_tick_creates_independent_scheduled_run(app_client, user_factory, db_session) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 22), is_open=True, pretrade_date=date(2026, 4, 21)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 23), is_open=True, pretrade_date=date(2026, 4, 22)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 24), is_open=True, pretrade_date=date(2026, 4, 23)),
        ]
    )
    db_session.commit()

    create_response = app_client.post(
        "/api/v1/ops/review/date-completeness/schedules",
        headers=headers,
        json={
            "dataset_key": "moneyflow_ind_dc",
            "window_mode": "rolling",
            "lookback_count": 3,
            "lookback_unit": "open_day",
            "calendar_scope": "default_cn_market",
            "cron_expr": "0 22 * * *",
            "timezone": "Asia/Shanghai",
        },
    )
    assert create_response.status_code == 200
    schedule_id = create_response.json()["id"]
    schedule = db_session.scalar(
        select(DatasetDateCompletenessSchedule).where(DatasetDateCompletenessSchedule.id == schedule_id)
    )
    assert schedule is not None
    schedule.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    tick_response = app_client.post("/api/v1/ops/review/date-completeness/schedules/tick?limit=10", headers=headers)

    assert tick_response.status_code == 200
    payload = tick_response.json()
    assert payload["scheduled"] == 1
    detail_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{payload['run_ids'][0]}", headers=headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run_mode"] == "scheduled"
    assert detail["schedule_id"] == schedule_id
    assert detail["start_date"] == "2026-04-22"
    assert detail["end_date"] == "2026-04-24"


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


def test_date_completeness_worker_filters_actual_buckets_for_shared_period_table(
    app_client,
    user_factory,
    db_session,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=date(2026, 1, 20), is_open=True, pretrade_date=date(2026, 1, 19)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 1, 27), is_open=True, pretrade_date=date(2026, 1, 26)),
        ]
    )
    db_session.execute(
        text(
            """
            create table core_serving.stk_period_bar (
                trade_date date not null,
                freq text not null,
                ts_code text not null
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            insert into core_serving.stk_period_bar (trade_date, freq, ts_code)
            values
              ('2026-01-23', 'week', '000001.SZ'),
              ('2026-01-30', 'month', '000001.SZ')
            """
        )
    )
    db_session.commit()

    create_response = app_client.post(
        "/api/v1/ops/review/date-completeness/runs",
        headers=headers,
        json={
            "dataset_key": "stk_period_bar_week",
            "start_date": "2026-01-23",
            "end_date": "2026-01-30",
        },
    )
    assert create_response.status_code == 200

    run = DateCompletenessAuditWorker().run_next(db_session)

    assert run is not None
    assert run.dataset_key == "stk_period_bar_week"
    assert run.row_identity_filters_json == {"freq": "week"}
    assert run.expected_bucket_count == 2
    assert run.actual_bucket_count == 1
    assert run.missing_bucket_count == 1
    assert run.excluded_bucket_count == 0
    assert run.result_status == "failed"

    stored_run = db_session.get(DatasetDateCompletenessRun, run.id)
    assert stored_run is not None
    assert stored_run.row_identity_filters_json == {"freq": "week"}

    gaps_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{run.id}/gaps", headers=headers)
    assert gaps_response.status_code == 200
    assert gaps_response.json()["items"][0]["range_start"] == "2026-01-30"


def test_date_completeness_worker_excludes_stk_period_week_without_open_trade_day(
    app_client,
    user_factory,
    db_session,
) -> None:
    headers = _admin_headers(app_client, user_factory)
    db_session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=date(2026, 1, 20), is_open=True, pretrade_date=date(2026, 1, 19)),
            TradeCalendar(exchange="SSE", trade_date=date(2026, 2, 5), is_open=True, pretrade_date=date(2026, 2, 4)),
        ]
    )
    db_session.execute(
        text(
            """
            create table core_serving.stk_period_bar (
                trade_date date not null,
                freq text not null,
                ts_code text not null
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            insert into core_serving.stk_period_bar (trade_date, freq, ts_code)
            values
              ('2026-01-23', 'week', '000001.SZ'),
              ('2026-02-06', 'week', '000001.SZ')
            """
        )
    )
    db_session.commit()

    create_response = app_client.post(
        "/api/v1/ops/review/date-completeness/runs",
        headers=headers,
        json={
            "dataset_key": "stk_period_bar_week",
            "start_date": "2026-01-23",
            "end_date": "2026-02-06",
        },
    )
    assert create_response.status_code == 200

    run = DateCompletenessAuditWorker().run_next(db_session)

    assert run is not None
    assert run.bucket_window_rule == "iso_week"
    assert run.bucket_applicability_rule == "requires_open_trade_day_in_bucket"
    assert run.expected_bucket_count == 2
    assert run.actual_bucket_count == 2
    assert run.missing_bucket_count == 0
    assert run.excluded_bucket_count == 1
    assert run.result_status == "passed"

    gaps_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{run.id}/gaps", headers=headers)
    assert gaps_response.status_code == 200
    assert gaps_response.json() == {"total": 0, "items": []}

    exclusions_response = app_client.get(f"/api/v1/ops/review/date-completeness/runs/{run.id}/exclusions", headers=headers)
    assert exclusions_response.status_code == 200
    payload = exclusions_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["bucket_value"] == "2026-01-30"
    assert payload["items"][0]["window_start"] == "2026-01-26"
    assert payload["items"][0]["window_end"] == "2026-02-01"
    assert payload["items"][0]["reason_code"] == "bucket_has_no_open_trade_day"
