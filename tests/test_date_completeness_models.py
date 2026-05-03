from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.models.ops.dataset_date_completeness_gap import DatasetDateCompletenessGap
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.dataset_date_completeness_schedule import DatasetDateCompletenessSchedule


def test_date_completeness_models_can_persist_independent_run_gap_and_schedule() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        DatasetDateCompletenessRun.__table__.create(connection)
        DatasetDateCompletenessGap.__table__.create(connection)
        DatasetDateCompletenessSchedule.__table__.create(connection)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    try:
        run = DatasetDateCompletenessRun(
            dataset_key="moneyflow_ind_dc",
            display_name="板块资金流向(DC)",
            target_table="core_serving.board_moneyflow_dc",
            run_mode="manual",
            run_status="succeeded",
            result_status="failed",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 24),
            date_axis="trade_open_day",
            bucket_rule="every_open_day",
            window_mode="point_or_range",
            input_shape="trade_date_or_start_end",
            observed_field="trade_date",
            row_identity_filters_json={"content_type": "行业板块"},
            expected_bucket_count=17,
            actual_bucket_count=16,
            missing_bucket_count=1,
            gap_range_count=1,
            requested_at=datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc),
        )
        session.add(run)
        session.flush()
        session.add(
            DatasetDateCompletenessGap(
                run_id=run.id,
                dataset_key=run.dataset_key,
                bucket_kind="trade_date",
                range_start=date(2026, 4, 17),
                range_end=date(2026, 4, 17),
                missing_count=1,
                sample_values_json=["2026-04-17"],
            )
        )
        session.add(
            DatasetDateCompletenessSchedule(
                dataset_key="moneyflow_ind_dc",
                display_name="每日资金流向日期完整性审计",
                status="active",
                window_mode="rolling",
                lookback_count=10,
                lookback_unit="open_day",
                cron_expr="0 22 * * *",
            )
        )
        session.commit()

        stored_run = session.scalar(select(DatasetDateCompletenessRun).where(DatasetDateCompletenessRun.dataset_key == "moneyflow_ind_dc"))
        stored_gap = session.scalar(select(DatasetDateCompletenessGap).where(DatasetDateCompletenessGap.run_id == run.id))
        stored_schedule = session.scalar(select(DatasetDateCompletenessSchedule).where(DatasetDateCompletenessSchedule.dataset_key == "moneyflow_ind_dc"))

        assert stored_run is not None
        assert stored_run.result_status == "failed"
        assert stored_run.row_identity_filters_json == {"content_type": "行业板块"}
        assert stored_gap is not None
        assert stored_gap.sample_values_json == ["2026-04-17"]
        assert stored_schedule is not None
        assert stored_schedule.calendar_scope == "default_cn_market"
        assert stored_schedule.timezone == "Asia/Shanghai"
    finally:
        session.close()
        engine.dispose()
