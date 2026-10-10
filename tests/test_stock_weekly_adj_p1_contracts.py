from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.datasets.stock_weekly_adj_contracts import (
    SOURCE_FIELDS,
    WeeklyAdjContractError,
    WeeklyAdjExecutionPolicy,
    canonical_source_rows,
    digest,
    latest_completed_calendar_week,
    validate_weekly_response,
    weekly_definition_issues,
)
from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion.execution_scope import execution_observation_timeout
from src.foundation.ingestion.stock_weekly_adj_scope import freeze_weekly_adj_execution
from src.foundation.dao.stock_weekly_adj_delivery_dao import StockWeeklyAdjDeliveryDAO
from src.foundation.models.core.stock_weekly_adj_delivery import StockWeeklyAdjDelivery


def weekly_definition():
    definition = get_dataset_definition("stk_period_bar_adj_week")
    return replace(
        definition,
        storage=replace(
            definition.storage,
            write_path="raw_core_upsert_with_delivery",
            delivery_dao_name="stock_weekly_adj_delivery",
            delivery_table="core.stock_weekly_adj_delivery",
            raw_conflict_columns=("ts_code", "trade_date", "freq"),
            conflict_columns=("ts_code", "trade_date", "freq"),
        ),
        planning=replace(
            definition.planning,
            weekly_adj_policy=WeeklyAdjExecutionPolicy(),
            unit_builder_key="stock_weekly_adj_refresh",
            max_source_rows_per_unit=12000,
            max_units_per_execution=1000,
            fetch_concurrency=1,
        ),
        quality=replace(definition.quality, reject_policy="fail_unit_on_any_rejection"),
        transaction=replace(definition.transaction, idempotent_write_required=True),
    )


def source_row(code="000001.SZ"):
    return {
        **dict.fromkeys(SOURCE_FIELDS, Decimal("1.2500")),
        "ts_code": code,
        "trade_date": date(2026, 6, 5),
        "end_date": date(2026, 10, 9),
        "freq": "week",
    }


def test_source_values_precision_null_and_raw_identity():
    raw = source_row("T600018.SH")
    raw["vol"] = None
    result = canonical_source_rows([raw, dict(raw)], WeeklyAdjExecutionPolicy())
    assert len(result) == 1 and result[0]["ts_code"] == "T600018.SH"
    assert result[0]["close_qfq"] == "1.2500" and result[0]["vol"] is None
    assert result[0]["trade_date"] == "20260605"
    assert raw["close_qfq"] == Decimal("1.2500")


@pytest.mark.parametrize(
    "budget",
    [{"max_units": 1001}, {"max_plan_bytes": 1048577}, {"max_payload_bytes": 8388609}],
)
def test_policy_cannot_exceed_persisted_v1_limits(budget):
    with pytest.raises(WeeklyAdjContractError, match="持久化合同上限"):
        WeeklyAdjExecutionPolicy(**budget)


@pytest.mark.parametrize(
    "field,value",
    [
        ("close", float("nan")),
        ("close", 1.25),
        ("close", Decimal("1.23456")),
        ("pct_chg", Decimal("1000000")),
        ("freq", "month"),
    ],
)
def test_source_values_reject_invalid(field, value):
    raw = source_row()
    raw[field] = value
    with pytest.raises(WeeklyAdjContractError):
        canonical_source_rows([raw], WeeklyAdjExecutionPolicy())


def test_conflict_and_row_and_payload_budget():
    raw = source_row()
    other = {**raw, "close_qfq": Decimal("2")}
    with pytest.raises(WeeklyAdjContractError, match="同键"):
        canonical_source_rows([raw, other], WeeklyAdjExecutionPolicy())
    with pytest.raises(WeeklyAdjContractError):
        canonical_source_rows([raw, raw], WeeklyAdjExecutionPolicy(max_rows_per_unit=1))
    with pytest.raises(WeeklyAdjContractError):
        canonical_source_rows([raw], WeeklyAdjExecutionPolicy(max_payload_bytes=10))


def test_normal_empty_response_requires_full_fields():
    good = {"code": 0, "data": {"fields": list(SOURCE_FIELDS), "items": []}}
    assert validate_weekly_response(good) == []
    for bad in [
        {"code": 0, "data": None},
        {"code": 0, "data": {"fields": [], "items": []}},
        {"code": 0, "data": {"fields": list(SOURCE_FIELDS), "items": [[1]]}},
        {"code": 0, "data": {"fields": [SOURCE_FIELDS[0]] * 21, "items": []}},
    ]:
        with pytest.raises(WeeklyAdjContractError) as exc:
            validate_weekly_response(bad)
        assert exc.value.code == "weekly_adj.source_payload_invalid"


@pytest.mark.parametrize(
    "day,hour,minute,expected",
    [(9, 19, 29, 2), (9, 19, 30, 9), (10, 0, 0, 9), (12, 19, 30, 9)],
)
def test_last_completed_week_at_shanghai_window(day, hour, minute, expected):
    dt = datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert latest_completed_calendar_week(dt) == date(2026, 10, expected)
    assert latest_completed_calendar_week(dt.astimezone(ZoneInfo("UTC"))) == date(
        2026, 10, expected
    )
    with pytest.raises(WeeklyAdjContractError):
        latest_completed_calendar_week(dt.replace(tzinfo=None))


def test_binding_closed_and_range_units_use_their_own_params(mocker):
    definition = weekly_definition()
    assert weekly_definition_issues(definition) == []
    mocker.patch(
        "src.foundation.ingestion.resolver.get_dataset_definition",
        return_value=definition,
    )
    session = mocker.Mock()
    request = DatasetActionRequest(
        definition.dataset_key,
        "maintain",
        DatasetTimeInput(
            "range", start_date=date(2010, 1, 1), end_date=date(2026, 10, 9)
        ),
        filters={"ts_code": "000001.SZ"},
    )
    plan = DatasetActionResolver(session).build_plan(request)
    assert len(plan.units) == 1
    assert plan.units[0].request_params == {
        "freq": "week",
        "ts_code": "000001.SZ",
        "start_date": "20100101",
        "end_date": "20261009",
    }
    assert plan.writing.delivery_table == "core.stock_weekly_adj_delivery"
    session.execute.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()
    retry = DatasetActionResolver(session).build_plan(
        replace(
            request, trigger_source="retry", execution_context=plan.execution_context
        )
    )
    assert (
        retry.units[0].unit_id == plan.units[0].unit_id
        and retry.execution_context == plan.execution_context
    )
    assert plan.trigger_source == "manual" and retry.trigger_source == "retry"
    market = DatasetActionResolver(session).build_plan(
        replace(
            request,
            filters={},
            time_input=DatasetTimeInput(
                "range", start_date=date(2026, 9, 25), end_date=date(2026, 10, 9)
            ),
        )
    )
    assert [u.request_params["trade_date"] for u in market.units] == [
        "20260925",
        "20261002",
        "20261009",
    ]
    assert all("start_date" not in u.request_params for u in market.units)


def test_binding_rejects_orphans_and_month_and_concurrent():
    d = weekly_definition()
    assert weekly_definition_issues(
        replace(d, identity=replace(d.identity, dataset_key="stk_period_bar_adj_month"))
    )
    assert weekly_definition_issues(
        replace(d, planning=replace(d.planning, fetch_concurrency=2))
    )
    assert weekly_definition_issues(
        replace(d, planning=replace(d.planning, weekly_adj_policy=None))
    )
    assert (
        get_dataset_definition("stk_period_bar_adj_week").planning.weekly_adj_policy
        is None
    )
    assert (
        get_dataset_definition("stk_period_bar_adj_month").storage.delivery_table
        is None
    )


def test_freeze_resume_budget_and_original_intent():
    d = weekly_definition()
    assert weekly_definition_issues(
        replace(d, storage=replace(d.storage, core_dao_name="fund_daily"))
    )
    assert weekly_definition_issues(
        replace(d, storage=replace(d.storage, stage_table="other_stage"))
    )
    assert weekly_definition_issues(
        replace(d, source=replace(d.source, base_params={"freq": "month"}))
    )
    scope = {"mode": "point", "start": "2026-10-09", "end": "2026-10-09"}
    frozen = freeze_weekly_adj_execution(
        d, scope=scope, filters={}, trigger_source="schedule"
    )
    assert frozen["intent"] == "scheduled_week"
    resumed = freeze_weekly_adj_execution(
        d, scope=scope, filters={}, trigger_source="retry", previous=frozen
    )
    assert resumed == frozen
    with pytest.raises(WeeklyAdjContractError):
        freeze_weekly_adj_execution(
            d,
            scope=scope,
            filters={"ts_code": "000001.SZ"},
            trigger_source="manual",
            previous=frozen,
        )
    changed = replace(
        d,
        planning=replace(
            d.planning,
            weekly_adj_policy=WeeklyAdjExecutionPolicy(source_timeout_seconds=25),
        ),
    )
    with pytest.raises(WeeklyAdjContractError):
        freeze_weekly_adj_execution(
            changed, scope=scope, filters={}, trigger_source="retry", previous=frozen
        )
    assert execution_observation_timeout(frozen) == 2
    assert execution_observation_timeout(None) is None
    assert (
        execution_observation_timeout(
            {"policy_snapshot": {"storage": {"insert_lock_timeout_seconds": 3}}}
        )
        == 3
    )
    bad = deepcopy(frozen)
    bad["policy_snapshot"]["policy"]["observation_timeout_seconds"] = None
    with pytest.raises(WeeklyAdjContractError):
        execution_observation_timeout(bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent", "manual_revision"),
        ("trigger_source", "manual"),
        ("execution_token", str(uuid4())),
    ],
)
def test_restore_rejects_changed_identity(field, value):
    d = weekly_definition()
    scope = {"mode": "point", "start": "2026-10-09", "end": "2026-10-09"}
    frozen = freeze_weekly_adj_execution(
        d, scope=scope, filters={}, trigger_source="schedule"
    )
    frozen[field] = value
    with pytest.raises(WeeklyAdjContractError):
        freeze_weekly_adj_execution(
            d, scope=scope, filters={}, trigger_source="retry", previous=frozen
        )


def test_builder_converts_policy_and_linter_rejects_mixed_binding(mocker):
    from src.foundation.datasets.definitions import ALL_DATASET_ROWS
    from src.foundation.datasets.definitions._builder import build_definition
    from src.foundation.datasets.models import DatasetScheduleTimePolicy

    d = weekly_definition()
    row = deepcopy(
        next(
            r for r in ALL_DATASET_ROWS if r["identity"]["dataset_key"] == d.dataset_key
        )
    )
    for part in ("storage", "planning", "transaction", "quality"):
        row[part] = asdict(getattr(d, part))
    row["capabilities"]["actions"][0]["schedule_time_policy"] = asdict(
        DatasetScheduleTimePolicy(
            policy="latest_completed_calendar_week",
            schedule_types=("cron",),
            cron_repeat_modes=("daily",),
            explicit_time_input="forbidden",
            generated_time_mode="point",
        )
    )
    built = build_definition(row)
    assert isinstance(built.planning.weekly_adj_policy, WeeklyAdjExecutionPolicy)
    assert (
        built.capabilities.actions[0].schedule_time_policy.policy
        == "latest_completed_calendar_week"
    )
    row["storage"]["row_identity_filters"] = {"freq": "month"}
    with pytest.raises(ValueError, match="预算必须一致"):
        build_definition(row)


def test_requested_plan_budget_rejected_before_dml_or_source(mocker):
    from src.foundation.ingestion.errors import IngestionPlanningError

    d = weekly_definition()
    d = replace(
        d,
        planning=replace(
            d.planning,
            max_units_per_execution=2,
            weekly_adj_policy=WeeklyAdjExecutionPolicy(max_units=2),
        ),
    )
    mocker.patch(
        "src.foundation.ingestion.resolver.get_dataset_definition", return_value=d
    )
    session = mocker.Mock()
    request = DatasetActionRequest(
        d.dataset_key,
        "maintain",
        DatasetTimeInput(
            "range", start_date=date(2026, 9, 25), end_date=date(2026, 10, 9)
        ),
    )
    with pytest.raises(IngestionPlanningError):
        DatasetActionResolver(session).build_plan(request)
    session.execute.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()
    tiny = replace(
        d,
        planning=replace(
            d.planning,
            weekly_adj_policy=WeeklyAdjExecutionPolicy(max_units=2, max_plan_bytes=10),
        ),
    )
    with pytest.raises(WeeklyAdjContractError, match="字节预算"):
        freeze_weekly_adj_execution(
            tiny, scope={"mode": "point"}, filters={}, trigger_source="manual"
        )


@pytest.fixture
def delivery_session():
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS core"))
        StockWeeklyAdjDelivery.__table__.create(connection)
        connection.commit()
        with Session(connection) as session:
            yield session
    engine.dispose()


def record(batch_id, kind="unit", unit_id="unit-1", payload=None):
    payload = payload or {
        "rows": canonical_source_rows([source_row()], WeeklyAdjExecutionPolicy())
    }
    return dict(
        contract_version=1,
        batch_id=batch_id,
        unit_id=unit_id,
        record_kind=kind,
        intent={"mode": "manual_revision"},
        unit_kind="point_week",
        cutoff_week=date(2026, 10, 9),
        start_date=None,
        end_date=None,
        ts_code=None,
        factor_scan_start=None,
        factor_scan_end=None,
        factor_target=None,
        outcome="published",
        payload=payload,
        rows_received=1,
        rows_unique=1,
        rows_written=1,
        rows_preserved=0,
        basis_date=date(2026, 10, 9),
        payload_digest=digest(payload),
        scope_digest="a" * 64,
        reason_summary={},
    )


def test_append_idempotent_conflict_and_transaction_ownership(delivery_session):
    session = delivery_session
    dao = StockWeeklyAdjDeliveryDAO(session)
    values = record(uuid4())
    policy = WeeklyAdjExecutionPolicy()
    first = dao.append(values, policy)
    second = dao.append(values, policy)
    assert first.revision == second.revision
    changed = deepcopy(values)
    changed["rows_preserved"] = 1
    with pytest.raises(WeeklyAdjContractError):
        dao.append(changed, policy)
    session.rollback()
    assert (
        dao.get_record(
            batch_id=values["batch_id"], record_kind="unit", unit_id="unit-1"
        )
        is None
    )
    dao.append(values, policy)
    session.commit()
    assert len(list(dao.iter_units(batch_id=values["batch_id"]))) == 1


def test_control_projection_order_and_budget(delivery_session):
    dao = StockWeeklyAdjDeliveryDAO(delivery_session)
    policy = WeeklyAdjExecutionPolicy()
    batch = uuid4()
    unit = dao.append(record(batch), policy)
    payload = {
        "unit_ids": ["unit-1"],
        "header": {
            "unit_count": 1,
            "total_payload_bytes": 1024,
            "anchor_week": "20261009",
        },
    }
    a = dao.append(record(batch, "batch_closed", "closed", payload), policy)
    b = dao.append(record(uuid4(), "batch_closed", "closed", payload), policy)
    assert dao.next_closed_header(after_revision=0)["revision"] == a.revision
    assert dao.next_closed_header(after_revision=a.revision)["revision"] == b.revision
    assert "payload" not in dao.next_closed_header(after_revision=0)
    bad = record(uuid4(), "plan", "plan", {"units": [{}] * 1001})
    with pytest.raises(WeeklyAdjContractError):
        dao.append(bad, policy)
    with pytest.raises(WeeklyAdjContractError):
        list(dao.iter_units(batch_id=batch, limit=1001))
    assert unit.revision < a.revision


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_id", ""),
        ("scope_digest", "x"),
        ("intent", {}),
        ("reason_summary", {"samples": None}),
        ("cutoff_week", date(2026, 10, 8)),
    ],
)
def test_delivery_bad_metadata_rejected_without_insert(delivery_session, field, value):
    values = record(uuid4())
    values[field] = value
    with pytest.raises(WeeklyAdjContractError):
        StockWeeklyAdjDeliveryDAO(delivery_session).append(
            values, WeeklyAdjExecutionPolicy()
        )
    assert (
        delivery_session.scalar(
            text("SELECT count(*) FROM core.stock_weekly_adj_delivery")
        )
        == 0
    )


def test_ops_schedule_uses_declared_policy_and_rejects_fixed_dates():
    from src.foundation.datasets.models import DatasetScheduleTimePolicy
    from src.ops.services.dataset_schedule_time_policy_resolver import (
        DatasetScheduleTimePolicyResolver,
    )
    from src.ops.services.task_run_service import TaskRunCommandService
    from src.app.exceptions import WebAppError

    d = weekly_definition()
    action = d.capabilities.get_action("maintain")
    action = replace(
        action,
        schedule_time_policy=DatasetScheduleTimePolicy(
            policy="latest_completed_calendar_week",
            schedule_types=("cron",),
            cron_repeat_modes=("daily",),
            explicit_time_input="forbidden",
            generated_time_mode="point",
        ),
    )
    d = replace(d, capabilities=replace(d.capabilities, actions=(action,)))
    assert (
        DatasetScheduleTimePolicyResolver()
        .resolve(definition=d, action="maintain")[0]
        .policy
        == "latest_completed_calendar_week"
    )
    kwargs = dict(
        session=None,
        definition=d,
        target_key="stk_period_bar_adj_week.maintain",
        params_json={},
        calendar_policy="latest_completed_calendar_week",
        scheduled_at=datetime(2026, 10, 9, 19, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone_name="Asia/Shanghai",
    )
    assert TaskRunCommandService()._resolve_dataset_action_schedule_time_input(
        **kwargs
    ) == {"mode": "point", "trade_date": "2026-10-09"}
    with pytest.raises(WebAppError):
        TaskRunCommandService()._resolve_dataset_action_schedule_time_input(
            **{**kwargs, "params_json": {"trade_date": "2026-10-09"}}
        )
    with pytest.raises(WebAppError):
        TaskRunCommandService()._resolve_dataset_action_schedule_time_input(
            **{
                **kwargs,
                "definition": get_dataset_definition("stk_period_bar_adj_month"),
            }
        )


def test_announcement_snapshot_does_not_include_weekly_defaults():
    from src.foundation.ingestion.announcement_scope import freeze_execution

    d = get_dataset_definition("anns_d")
    frozen = freeze_execution(
        d,
        scope={"mode": "range", "start": "2026-10-01", "end": "2026-10-01"},
        filters={},
    )
    snapshot = frozen["policy_snapshot"]
    assert "weekly_adj_policy" not in snapshot["planning"]
    assert (
        "delivery_table" not in snapshot["storage"]
        and "delivery_dao_name" not in snapshot["storage"]
    )
    assert (
        freeze_execution(
            d,
            scope={"mode": "range", "start": "2026-10-01", "end": "2026-10-01"},
            filters={},
            previous=frozen,
        )
        == frozen
    )


def test_weekly_taskrun_freeze_and_explicit_resume_use_no_business_dml(mocker):
    from src.ops.services.task_run_service import (
        TaskRunCommandService,
        TaskRunCreateContext,
    )
    from src.app.exceptions import WebAppError

    d = weekly_definition()
    mocker.patch(
        "src.foundation.ingestion.resolver.get_dataset_definition", return_value=d
    )
    mocker.patch(
        "src.ops.services.task_run_service.get_dataset_definition", return_value=d
    )
    session = mocker.Mock()
    service = TaskRunCommandService()
    context = TaskRunCreateContext(
        task_type="dataset_action",
        resource_key=d.dataset_key,
        action="maintain",
        time_input={"mode": "point", "trade_date": "2026-10-09"},
        filters={},
        trigger_source="schedule",
        request_payload={},
        requested_by_user_id=None,
    )
    payload = service._freeze_dataset_execution_payload(session, context, {})
    session.execute.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()
    source = SimpleNamespace(
        task_type="dataset_action",
        resource_key=d.dataset_key,
        action="maintain",
        status="failed",
        request_payload_json=payload,
    )
    session.get.return_value = source
    resumed = service._freeze_dataset_execution_payload(
        session,
        replace(
            context,
            trigger_source="manual",
            requested_by_user_id=1,
            resume_from_task_run_id=10,
        ),
        {},
    )
    assert resumed["execution_context"] == payload["execution_context"]
    assert resumed["execution_context"]["intent"] == "scheduled_week"
    source.resource_key = "stk_period_bar_adj_month"
    with pytest.raises(WebAppError):
        service._freeze_dataset_execution_payload(
            session,
            replace(
                context,
                trigger_source="manual",
                requested_by_user_id=1,
                resume_from_task_run_id=10,
            ),
            {},
        )


def test_model_registered_and_pg_migration_sql_is_frozen(mocker):
    import importlib.util
    from pathlib import Path
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from io import StringIO
    from src.foundation.models.table_model_registry import get_model_by_table_name

    assert (
        get_model_by_table_name("core.stock_weekly_adj_delivery")
        is StockWeeklyAdjDelivery
    )
    ddl = str(
        CreateTable(StockWeeklyAdjDelivery.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert (
        "GENERATED BY DEFAULT AS IDENTITY" in ddl
        and "JSONB" in ddl
        and "octet_length" in ddl
    )
    output = StringIO()
    ctx = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    chain = [
        ("20261010_000185_stock_weekly_adj_delivery.py", "20261008_000184"),
        ("20261010_000186_stock_weekly_adj_date_index.py", "20261010_000185"),
    ]
    for filename, parent in chain:
        spec = importlib.util.spec_from_file_location(
            "migration_" + filename[:15], Path("alembic/versions") / filename
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.down_revision == parent
        module.op = Operations(ctx)
        module.upgrade()
        with pytest.raises(RuntimeError):
            module.downgrade()
    sql = output.getvalue()
    assert "BEFORE UPDATE OR DELETE ON core.stock_weekly_adj_delivery" in sql
    assert "WHERE freq = 'week'" in sql and "CREATE INDEX CONCURRENTLY" in sql
    assert "indisvalid" in sql and "indisready" in sql
    assert (
        "DROP TABLE" not in sql and "TRUNCATE" not in sql and "DELETE FROM" not in sql
    )
