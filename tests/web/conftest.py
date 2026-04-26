from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.config.settings import get_settings
from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.app.models.app_user import AppUser
from src.app.models.auth_action_token import AuthActionToken
from src.app.models.auth_audit_log import AuthAuditLog
from src.app.models.auth_invite_code import AuthInviteCode
from src.app.models.auth_permission import AuthPermission
from src.app.models.auth_refresh_token import AuthRefreshToken
from src.app.models.auth_role import AuthRole
from src.app.models.auth_role_permission import AuthRolePermission
from src.app.models.auth_user_role import AuthUserRole
from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.dataset_layer_snapshot_current import DatasetLayerSnapshotCurrent
from src.ops.models.ops.dataset_layer_snapshot_history import DatasetLayerSnapshotHistory
from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.models.ops.resolution_release import ResolutionRelease
from src.ops.models.ops.resolution_release_stage_status import ResolutionReleaseStageStatus
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.models.ops.sync_job_state import SyncJobState
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.app.auth.password_service import PasswordService


@pytest.fixture(autouse=True)
def configured_web_env(monkeypatch) -> Generator[None, None, None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-with-32-bytes-min")
    monkeypatch.setenv("WEB_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PLATFORM_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def web_engine(configured_web_env) -> Generator:

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS app")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving_light")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS foundation")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        AppUser.__table__.create(connection)
        AuthRole.__table__.create(connection)
        AuthPermission.__table__.create(connection)
        AuthUserRole.__table__.create(connection)
        AuthRolePermission.__table__.create(connection)
        AuthRefreshToken.__table__.create(connection)
        AuthActionToken.__table__.create(connection)
        AuthAuditLog.__table__.create(connection)
        AuthInviteCode.__table__.create(connection)
        EquityBlockTrade.__table__.create(connection)
        IndexBasic.__table__.create(connection)
        IndexDailyServing.__table__.create(connection)
        IndexWeeklyServing.__table__.create(connection)
        IndexMonthlyServing.__table__.create(connection)
        ThsIndex.__table__.create(connection)
        ThsMember.__table__.create(connection)
        DcIndex.__table__.create(connection)
        DcMember.__table__.create(connection)
        Security.__table__.create(connection)
        TradeCalendar.__table__.create(connection)
        JobSchedule.__table__.create(connection)
        TaskRun.__table__.create(connection)
        TaskRunNode.__table__.create(connection)
        TaskRunIssue.__table__.create(connection)
        IndexSeriesActive.__table__.create(connection)
        DatasetStatusSnapshot.__table__.create(connection)
        DatasetLayerSnapshotHistory.__table__.create(connection)
        DatasetLayerSnapshotCurrent.__table__.create(connection)
        DatasetPipelineMode.__table__.create(connection)
        ProbeRule.__table__.create(connection)
        ProbeRunLog.__table__.create(connection)
        ResolutionRelease.__table__.create(connection)
        ResolutionReleaseStageStatus.__table__.create(connection)
        StdMappingRule.__table__.create(connection)
        StdCleansingRule.__table__.create(connection)
        ConfigRevision.__table__.create(connection)
        DatasetResolutionPolicy.__table__.create(connection)
        SyncJobState.__table__.create(connection)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(web_engine) -> Generator[Session, None, None]:
    testing_session_local = sessionmaker(bind=web_engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user_factory(db_session: Session) -> Callable[..., AppUser]:
    def build(
        *,
        username: str = "admin",
        password: str = "secret",
        display_name: str | None = "Administrator",
        email: str | None = None,
        account_state: str = "active",
        is_admin: bool = False,
        is_active: bool = True,
    ) -> AppUser:
        user = AppUser(
            username=username,
            password_hash=PasswordService().hash_password(password),
            display_name=display_name,
            email=email,
            account_state=account_state,
            is_admin=is_admin,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return build


@pytest.fixture()
def app_client(db_session: Session) -> Generator[TestClient, None, None]:
    from src.app.web.app import app
    from src.app.dependencies.db import get_db_session

    get_settings.cache_clear()

    def override_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture()
def auth_token(app_client: TestClient, user_factory: Callable[..., AppUser]) -> str:
    user_factory(username="admin", password="secret", is_admin=True)
    response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    assert response.status_code == 200
    return response.json()["token"]


@pytest.fixture()
def task_run_factory(db_session: Session) -> Callable[..., TaskRun]:
    def build(
        *,
        task_type: str = "dataset_action",
        resource_key: str | None = "stock_basic",
        action: str = "maintain",
        title: str = "股票主数据",
        trigger_source: str = "manual",
        status: str = "queued",
        requested_by_user_id: int | None = None,
        requested_at: datetime | None = None,
        time_input_json: dict | None = None,
        filters_json: dict | None = None,
        request_payload_json: dict | None = None,
        rows_fetched: int = 0,
        rows_saved: int = 0,
        rows_rejected: int = 0,
        unit_done: int = 0,
        unit_total: int = 0,
        unit_failed: int = 0,
        progress_percent: int | None = None,
        current_context_json: dict | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        cancel_requested_at: datetime | None = None,
        canceled_at: datetime | None = None,
        primary_issue_id: int | None = None,
        schedule_id: int | None = None,
    ) -> TaskRun:
        next_id = (db_session.scalar(select(func.max(TaskRun.id))) or 0) + 1
        task_run = TaskRun(
            id=next_id,
            task_type=task_type,
            resource_key=resource_key,
            action=action,
            title=title,
            schedule_id=schedule_id,
            trigger_source=trigger_source,
            status=status,
            requested_by_user_id=requested_by_user_id,
            requested_at=requested_at or datetime.now(timezone.utc),
            queued_at=requested_at or datetime.now(timezone.utc),
            time_input_json=time_input_json or {},
            filters_json=filters_json or {},
            request_payload_json=request_payload_json or {},
            plan_snapshot_json={},
            rows_fetched=rows_fetched,
            rows_saved=rows_saved,
            rows_rejected=rows_rejected,
            unit_done=unit_done,
            unit_total=unit_total,
            unit_failed=unit_failed,
            progress_percent=progress_percent,
            current_context_json=current_context_json or {},
            started_at=started_at,
            ended_at=ended_at,
            cancel_requested_at=cancel_requested_at,
            canceled_at=canceled_at,
            primary_issue_id=primary_issue_id,
        )
        db_session.add(task_run)
        db_session.commit()
        db_session.refresh(task_run)
        return task_run

    return build


@pytest.fixture()
def sync_job_state_factory(db_session: Session) -> Callable[..., SyncJobState]:
    def build(
        *,
        job_name: str = "sync_equity_daily",
        target_table: str = "core.equity_daily_bar",
        last_success_date=None,
        last_success_at: datetime | None = None,
        last_cursor: str | None = None,
        full_sync_done: bool = False,
    ) -> SyncJobState:
        row = SyncJobState(
            job_name=job_name,
            target_table=target_table,
            last_success_date=last_success_date,
            last_success_at=last_success_at,
            last_cursor=last_cursor,
            full_sync_done=full_sync_done,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return build


@pytest.fixture()
def trade_calendar_factory(db_session: Session) -> Callable[..., TradeCalendar]:
    def build(
        *,
        exchange: str = "SSE",
        trade_date,
        is_open: bool = True,
        pretrade_date=None,
    ) -> TradeCalendar:
        row = TradeCalendar(
            exchange=exchange,
            trade_date=trade_date,
            is_open=is_open,
            pretrade_date=pretrade_date,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return build


@pytest.fixture()
def equity_block_trade_factory(db_session: Session) -> Callable[..., EquityBlockTrade]:
    def build(
        *,
        ts_code: str = "000001.SZ",
        trade_date,
        buyer: str = "buyer",
        seller: str = "seller",
        price="10.00",
        vol="1000.00",
        amount="10000.00",
    ) -> EquityBlockTrade:
        row = EquityBlockTrade(
            ts_code=ts_code,
            trade_date=trade_date,
            buyer=buyer,
            seller=seller,
            price=price,
            vol=vol,
            amount=amount,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return build


@pytest.fixture()
def job_schedule_factory(db_session: Session) -> Callable[..., JobSchedule]:
    def build(
        *,
        spec_type: str = "dataset_action",
        spec_key: str = "stock_basic.maintain",
        display_name: str = "股票主数据刷新",
        status: str = "active",
        schedule_type: str = "once",
        trigger_mode: str = "schedule",
        cron_expr: str | None = None,
        timezone_name: str = "Asia/Shanghai",
        calendar_policy: str | None = None,
        probe_config_json: dict | None = None,
        params_json: dict | None = None,
        retry_policy_json: dict | None = None,
        concurrency_policy_json: dict | None = None,
        next_run_at: datetime | None = None,
        last_triggered_at: datetime | None = None,
        created_by_user_id: int | None = None,
        updated_by_user_id: int | None = None,
    ) -> JobSchedule:
        next_id = (db_session.scalar(select(func.max(JobSchedule.id))) or 0) + 1
        schedule = JobSchedule(
            id=next_id,
            spec_type=spec_type,
            spec_key=spec_key,
            display_name=display_name,
            status=status,
            schedule_type=schedule_type,
            trigger_mode=trigger_mode,
            cron_expr=cron_expr,
            timezone=timezone_name,
            calendar_policy=calendar_policy,
            probe_config_json=probe_config_json or {},
            params_json=params_json or {},
            retry_policy_json=retry_policy_json or {},
            concurrency_policy_json=concurrency_policy_json or {},
            next_run_at=next_run_at,
            last_triggered_at=last_triggered_at,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )
        db_session.add(schedule)
        db_session.commit()
        db_session.refresh(schedule)
        return schedule

    return build


@pytest.fixture()
def task_run_node_factory(db_session: Session) -> Callable[..., TaskRunNode]:
    def build(
        *,
        task_run_id: int,
        node_key: str = "node_1",
        title: str = "节点 1",
        sequence_no: int = 1,
        status: str = "pending",
        node_type: str = "dataset_plan",
        resource_key: str | None = None,
        time_input_json: dict | None = None,
        context_json: dict | None = None,
        rows_fetched: int = 0,
        rows_saved: int = 0,
        rows_rejected: int = 0,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> TaskRunNode:
        next_id = (db_session.scalar(select(func.max(TaskRunNode.id))) or 0) + 1
        node = TaskRunNode(
            id=next_id,
            task_run_id=task_run_id,
            node_key=node_key,
            node_type=node_type,
            sequence_no=sequence_no,
            title=title,
            resource_key=resource_key,
            status=status,
            time_input_json=time_input_json or {},
            context_json=context_json or {},
            rows_fetched=rows_fetched,
            rows_saved=rows_saved,
            rows_rejected=rows_rejected,
            started_at=started_at,
            ended_at=ended_at,
        )
        db_session.add(node)
        db_session.commit()
        db_session.refresh(node)
        return node

    return build


@pytest.fixture()
def task_run_issue_factory(db_session: Session) -> Callable[..., TaskRunIssue]:
    def build(
        *,
        task_run_id: int,
        node_id: int | None = None,
        severity: str = "error",
        code: str = "test_issue",
        title: str = "测试问题",
        message: str | None = None,
        technical_payload_json: dict | None = None,
        occurred_at: datetime | None = None,
    ) -> TaskRunIssue:
        next_id = (db_session.scalar(select(func.max(TaskRunIssue.id))) or 0) + 1
        issue = TaskRunIssue(
            id=next_id,
            task_run_id=task_run_id,
            node_id=node_id,
            severity=severity,
            code=code,
            title=title,
            operator_message=message,
            suggested_action=None,
            technical_message=message,
            technical_payload_json=technical_payload_json or {},
            source_phase="test",
            fingerprint=f"{task_run_id}:{node_id or 0}:{code}:{next_id}",
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
        db_session.add(issue)
        db_session.commit()
        db_session.refresh(issue)
        return issue

    return build


@pytest.fixture()
def probe_rule_factory(db_session: Session) -> Callable[..., ProbeRule]:
    def build(
        *,
        schedule_id: int | None = None,
        name: str = "收盘探测",
        dataset_key: str = "equity_daily",
        source_key: str | None = "tushare",
        status: str = "active",
        window_start: str | None = "15:30",
        window_end: str | None = "17:30",
        probe_interval_seconds: int = 300,
        probe_condition_json: dict | None = None,
        on_success_action_json: dict | None = None,
        max_triggers_per_day: int = 1,
        timezone_name: str = "Asia/Shanghai",
        created_by_user_id: int | None = None,
        updated_by_user_id: int | None = None,
    ) -> ProbeRule:
        next_id = (db_session.scalar(select(func.max(ProbeRule.id))) or 0) + 1
        rule = ProbeRule(
            id=next_id,
            schedule_id=schedule_id,
            name=name,
            dataset_key=dataset_key,
            source_key=source_key,
            status=status,
            window_start=window_start,
            window_end=window_end,
            probe_interval_seconds=probe_interval_seconds,
            probe_condition_json=probe_condition_json or {},
            on_success_action_json=on_success_action_json or {},
            max_triggers_per_day=max_triggers_per_day,
            timezone_name=timezone_name,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )
        db_session.add(rule)
        db_session.commit()
        db_session.refresh(rule)
        return rule

    return build


@pytest.fixture()
def probe_run_log_factory(db_session: Session) -> Callable[..., ProbeRunLog]:
    def build(
        *,
        probe_rule_id: int,
        status: str = "success",
        condition_matched: bool = True,
        message: str | None = None,
        payload_json: dict | None = None,
        probed_at: datetime | None = None,
        triggered_execution_id: int | None = None,
        duration_ms: int | None = None,
    ) -> ProbeRunLog:
        next_id = (db_session.scalar(select(func.max(ProbeRunLog.id))) or 0) + 1
        log = ProbeRunLog(
            id=next_id,
            probe_rule_id=probe_rule_id,
            status=status,
            condition_matched=condition_matched,
            message=message,
            payload_json=payload_json or {},
            probed_at=probed_at or datetime.now(timezone.utc),
            triggered_execution_id=triggered_execution_id,
            duration_ms=duration_ms,
        )
        db_session.add(log)
        db_session.commit()
        db_session.refresh(log)
        return log

    return build


@pytest.fixture()
def resolution_release_factory(db_session: Session) -> Callable[..., ResolutionRelease]:
    def build(
        *,
        dataset_key: str = "security_master",
        target_policy_version: int = 1,
        status: str = "previewing",
        triggered_by_user_id: int | None = None,
        triggered_at: datetime | None = None,
        finished_at: datetime | None = None,
        rollback_to_release_id: int | None = None,
    ) -> ResolutionRelease:
        next_id = (db_session.scalar(select(func.max(ResolutionRelease.id))) or 0) + 1
        release = ResolutionRelease(
            id=next_id,
            dataset_key=dataset_key,
            target_policy_version=target_policy_version,
            status=status,
            triggered_by_user_id=triggered_by_user_id,
            triggered_at=triggered_at or datetime.now(timezone.utc),
            finished_at=finished_at,
            rollback_to_release_id=rollback_to_release_id,
        )
        db_session.add(release)
        db_session.commit()
        db_session.refresh(release)
        return release

    return build


@pytest.fixture()
def resolution_release_stage_status_factory(db_session: Session) -> Callable[..., ResolutionReleaseStageStatus]:
    def build(
        *,
        release_id: int,
        dataset_key: str = "security_master",
        source_key: str | None = "tushare",
        stage: str = "std",
        status: str = "running",
        rows_in: int | None = None,
        rows_out: int | None = None,
        message: str | None = None,
        updated_at: datetime | None = None,
    ) -> ResolutionReleaseStageStatus:
        next_id = (db_session.scalar(select(func.max(ResolutionReleaseStageStatus.id))) or 0) + 1
        stage_status = ResolutionReleaseStageStatus(
            id=next_id,
            release_id=release_id,
            dataset_key=dataset_key,
            source_key=source_key,
            stage=stage,
            status=status,
            rows_in=rows_in,
            rows_out=rows_out,
            message=message,
            updated_at=updated_at or datetime.now(timezone.utc),
        )
        db_session.add(stage_status)
        db_session.commit()
        db_session.refresh(stage_status)
        return stage_status

    return build


@pytest.fixture()
def dataset_layer_snapshot_history_factory(db_session: Session) -> Callable[..., DatasetLayerSnapshotHistory]:
    def build(
        *,
        snapshot_date,
        dataset_key: str = "equity_daily",
        source_key: str | None = "tushare",
        stage: str = "serving",
        status: str = "healthy",
        rows_in: int | None = None,
        rows_out: int | None = None,
        error_count: int | None = None,
        last_success_at: datetime | None = None,
        last_failure_at: datetime | None = None,
        lag_seconds: int | None = None,
        message: str | None = None,
        calculated_at: datetime | None = None,
    ) -> DatasetLayerSnapshotHistory:
        next_id = (db_session.scalar(select(func.max(DatasetLayerSnapshotHistory.id))) or 0) + 1
        row = DatasetLayerSnapshotHistory(
            id=next_id,
            snapshot_date=snapshot_date,
            dataset_key=dataset_key,
            source_key=source_key,
            stage=stage,
            status=status,
            rows_in=rows_in,
            rows_out=rows_out,
            error_count=error_count,
            last_success_at=last_success_at,
            last_failure_at=last_failure_at,
            lag_seconds=lag_seconds,
            message=message,
            calculated_at=calculated_at or datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return build
