from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_qfq_nineturn_daily import EquityQfqNineTurnDaily
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import WealthSectorAnalysisPublishBatch
from src.ops.catalog.biz_dataset_definitions import get_biz_dataset_definition
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.queries.biz_table_card_query_service import (
    BizDatasetObservation,
    BizTableCardQueryService,
)


def _admin_token(app_client, user_factory) -> str:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    return str(login.json()["token"])


def _card_map(payload: dict) -> dict[str, dict]:
    return {
        item["card_key"]: item
        for group in payload["groups"]
        for item in group["items"]
    }


def _stable_observation() -> BizDatasetObservation:
    now = datetime.now(timezone.utc)
    return BizDatasetObservation(
        earliest_business_date=date.today() - timedelta(days=1),
        latest_business_date=date.today(),
        latest_success_at=now,
        latest_observed_at=now,
    )


def test_ops_biz_table_cards_project_all_definitions_and_actions(
    app_client,
    user_factory,
    db_session,
    monkeypatch,
) -> None:
    token = _admin_token(app_client, user_factory)
    monkeypatch.setattr(
        BizTableCardQueryService,
        "_load_business_observation",
        lambda self, session, definition: _stable_observation(),
    )
    today = date.today()
    db_session.merge(
        TradeCalendar(
            exchange="SSE",
            trade_date=today,
            is_open=True,
            pretrade_date=today - timedelta(days=1),
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=biz_tableset",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 15
    assert [(group["group_key"], group["group_label"]) for group in payload["groups"]] == [
        ("data_mart", "数据集市"),
        ("sector_analysis", "板块分析"),
        ("content_relation", "内容关联"),
        ("technical_indicators", "技术指标"),
    ]
    assert [item["card_key"] for item in payload["groups"][0]["items"]] == [
        "wealth_market_turnover_snapshot",
        "equity_daily_snapshot",
    ]

    cards = _card_map(payload)
    maintenance_cards = [item for item in cards.values() if item["primary_action_type"]]
    assert len(maintenance_cards) == 11
    assert {item["primary_action_type"] for item in maintenance_cards} == {"maintenance_action"}
    assert cards["equity_daily_snapshot"]["primary_action_key"] == "maintenance.rebuild_dm"
    assert cards["wealth_sector_heat_daily"]["primary_action_key"] == (
        "maintenance.materialize_wealth_sector_heat_daily"
    )
    assert cards["news_stock_link"]["primary_action_key"] == "maintenance.materialize_news_stock_links"

    for key in (
        "wealth_market_turnover_snapshot",
        "wealth_sector_hierarchy",
        "equity_qfq_nineturn_daily",
        "index_nineturn_daily",
    ):
        assert cards[key]["primary_action_type"] is None
        assert cards[key]["primary_action_key"] is None
        assert cards[key]["auto_schedule_status"] == "none"
        assert cards[key]["probe_total"] == 0


def test_ops_biz_table_cards_project_task_trace_active_run_and_direct_schedules(
    app_client,
    user_factory,
    db_session,
    task_run_factory,
    monkeypatch,
) -> None:
    token = _admin_token(app_client, user_factory)
    monkeypatch.setattr(
        BizTableCardQueryService,
        "_load_business_observation",
        lambda self, session, definition: _stable_observation(),
    )
    now = datetime.now(timezone.utc)
    task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="刷新数据集市快照",
        status="success",
        requested_at=now - timedelta(hours=3),
        ended_at=now - timedelta(hours=2),
        request_payload_json={"target_key": "maintenance.rebuild_dm"},
    )
    task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="刷新数据集市快照",
        status="failed",
        requested_at=now - timedelta(hours=1),
        ended_at=now - timedelta(minutes=30),
        request_payload_json={"target_key": "maintenance.rebuild_dm"},
    )
    task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="生成单日板块热度",
        status="running",
        requested_at=now - timedelta(minutes=10),
        started_at=now - timedelta(minutes=9),
        request_payload_json={"target_key": "maintenance.materialize_wealth_sector_heat_daily"},
    )
    db_session.add_all(
        [
            OpsSchedule(
                target_type="maintenance_action",
                target_key="maintenance.materialize_wealth_sector_heat_daily",
                display_name="板块热度自动任务",
                status="active",
                schedule_type="cron",
                trigger_mode="schedule",
                cron_expr="0 22 * * *",
                next_run_at=now + timedelta(hours=1),
            ),
            OpsSchedule(
                target_type="maintenance_action",
                target_key="maintenance.materialize_wealth_sector_heat_daily",
                display_name="板块热度已暂停任务",
                status="paused",
                schedule_type="cron",
                trigger_mode="schedule",
                cron_expr="0 23 * * *",
            ),
            OpsSchedule(
                target_type="maintenance_action",
                target_key="maintenance.materialize_news_stock_links",
                display_name="新闻关联已暂停任务",
                status="paused",
                schedule_type="cron",
                trigger_mode="schedule",
                cron_expr="*/5 * * * *",
            ),
            OpsSchedule(
                target_type="workflow",
                target_key="daily_market_close_maintenance",
                display_name="工作流任务",
                status="active",
                schedule_type="cron",
                trigger_mode="schedule",
                cron_expr="0 20 * * *",
            ),
        ]
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/ops/dataset-cards?source_key=biz_tableset",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    cards = _card_map(response.json())
    assert cards["equity_daily_snapshot"]["status"] == "failed"
    assert cards["equity_daily_snapshot"]["freshness_note"] == "最近一次构建失败。"
    heat = cards["wealth_sector_heat_daily"]
    assert heat["status"] == "running"
    assert heat["active_task_run_status"] == "running"
    assert heat["auto_schedule_status"] == "active"
    assert heat["auto_schedule_total"] == 2
    assert heat["auto_schedule_active"] == 1
    assert heat["auto_schedule_next_run_at"] is not None
    assert cards["news_stock_link"]["auto_schedule_status"] == "paused"
    assert cards["news_stock_link"]["auto_schedule_total"] == 1


def test_biz_direct_observation_uses_observed_time_from_latest_business_date(db_session) -> None:
    EquityQfqNineTurnDaily.__table__.create(db_session.connection(), checkfirst=True)
    older_date = date(2026, 8, 20)
    latest_date = date(2026, 8, 21)
    db_session.add_all(
        [
            EquityQfqNineTurnDaily(
                ts_code="000001.SZ",
                trade_date=older_date,
                up_count=1,
                down_count=0,
                formula_version=1,
                published_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
            ),
            EquityQfqNineTurnDaily(
                ts_code="000001.SZ",
                trade_date=latest_date,
                up_count=2,
                down_count=0,
                formula_version=1,
                published_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    observation = BizTableCardQueryService._load_direct_trade_date_observation(
        db_session,
        get_biz_dataset_definition("equity_qfq_nineturn_daily"),
    )

    assert observation.earliest_business_date == older_date
    assert observation.latest_business_date == latest_date
    assert observation.latest_observed_at == datetime(2026, 8, 21, 12)


def test_biz_sector_analysis_observation_only_accepts_published_batch(db_session) -> None:
    WealthSectorAnalysisPublishBatch.__table__.create(db_session.connection(), checkfirst=True)
    hash_value = "a" * 64
    common = {
        "hierarchy_version": "v1",
        "formula_bundle_version": "v1",
        "template_version": "v1",
        "source_hash": hash_value,
        "plan_hash": hash_value,
        "content_hash": hash_value,
        "source_dates_json": {},
        "source_row_counts_json": {},
        "expected_fact_counts_json": {},
        "actual_fact_counts_json": {},
    }
    db_session.add_all(
        [
            WealthSectorAnalysisPublishBatch(
                batch_id=uuid4(),
                trade_date=date(2026, 8, 20),
                status="PUBLISHED",
                started_at=datetime(2026, 8, 20, 11, tzinfo=timezone.utc),
                published_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
                **common,
            ),
            WealthSectorAnalysisPublishBatch(
                batch_id=uuid4(),
                trade_date=date(2026, 8, 21),
                status="FAILED",
                started_at=datetime(2026, 8, 21, 11, tzinfo=timezone.utc),
                failed_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
                failure_reason_code="test",
                **common,
            ),
        ]
    )
    db_session.commit()

    observation = BizTableCardQueryService._load_sector_analysis_observation(db_session)

    assert observation.latest_business_date == date(2026, 8, 20)
    assert observation.latest_success_at == datetime(2026, 8, 20, 12)


def test_biz_observation_query_failure_isolated_to_related_cards(db_session, monkeypatch) -> None:
    service = BizTableCardQueryService()
    today = date.today()
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=today,
            is_open=True,
            pretrade_date=today - timedelta(days=1),
        )
    )
    db_session.commit()

    def load_observation(self, session, definition):
        if definition.dataset_key == "wealth_sector_heat_daily":
            raise RuntimeError("test failure")
        return _stable_observation()

    monkeypatch.setattr(BizTableCardQueryService, "_load_business_observation", load_observation)

    response = service.list_cards(db_session)
    cards = {
        item.card_key: item
        for group in response.groups
        for item in group.items
    }

    assert cards["wealth_sector_heat_daily"].status == "unknown"
    assert cards["wealth_sector_heat_daily"].freshness_note == "状态读取失败"
    assert cards["equity_qfq_nineturn_daily"].status != "unknown"


def test_turnover_observation_query_does_not_count_all_rows(db_session) -> None:
    WealthMarketTurnoverSnapshot.__table__.create(db_session.connection(), checkfirst=True)
    statements: list[str] = []
    connection = db_session.connection()
    from sqlalchemy import event

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(connection, "before_cursor_execute", record_statement)
    try:
        BizTableCardQueryService._load_turnover_observation(db_session)
    finally:
        event.remove(connection, "before_cursor_execute", record_statement)

    assert statements
    assert all("count(" not in statement for statement in statements)
