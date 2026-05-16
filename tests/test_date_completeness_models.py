from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.models.ops.dataset_date_completeness_exclusion import DatasetDateCompletenessExclusion
from src.ops.models.ops.dataset_date_completeness_gap import DatasetDateCompletenessGap
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.dataset_date_completeness_schedule import DatasetDateCompletenessSchedule
from src.ops.models.ops.dataset_subject_completeness_gap import DatasetSubjectCompletenessGap
from src.ops.models.ops.dataset_subject_completeness_gap_detail import DatasetSubjectCompletenessGapDetail


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
        DatasetDateCompletenessExclusion.__table__.create(connection)
        DatasetSubjectCompletenessGap.__table__.create(connection)
        DatasetSubjectCompletenessGapDetail.__table__.create(connection)
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
            bucket_window_rule="none",
            bucket_applicability_rule="always",
            row_identity_filters_json={"content_type": "行业板块"},
            expected_bucket_count=17,
            actual_bucket_count=16,
            missing_bucket_count=1,
            excluded_bucket_count=1,
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
            DatasetDateCompletenessExclusion(
                run_id=run.id,
                dataset_key=run.dataset_key,
                bucket_kind="natural_date",
                bucket_value=date(2026, 4, 10),
                window_start=date(2026, 4, 6),
                window_end=date(2026, 4, 12),
                reason_code="bucket_has_no_open_trade_day",
                reason_message="该自然周内没有开市交易日，不应产出周线数据。",
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
        stored_exclusion = session.scalar(select(DatasetDateCompletenessExclusion).where(DatasetDateCompletenessExclusion.run_id == run.id))
        stored_schedule = session.scalar(select(DatasetDateCompletenessSchedule).where(DatasetDateCompletenessSchedule.dataset_key == "moneyflow_ind_dc"))

        assert stored_run is not None
        assert stored_run.result_status == "failed"
        assert stored_run.row_identity_filters_json == {"content_type": "行业板块"}
        assert stored_run.excluded_bucket_count == 1
        assert stored_gap is not None
        assert stored_gap.sample_values_json == ["2026-04-17"]
        assert stored_exclusion is not None
        assert stored_exclusion.reason_code == "bucket_has_no_open_trade_day"
        assert stored_schedule is not None
        assert stored_schedule.calendar_scope == "default_cn_market"
        assert stored_schedule.timezone == "Asia/Shanghai"
    finally:
        session.close()
        engine.dispose()


def test_subject_completeness_models_can_persist_matrix_run_gap_and_detail() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        DatasetDateCompletenessRun.__table__.create(connection)
        DatasetSubjectCompletenessGap.__table__.create(connection)
        DatasetSubjectCompletenessGapDetail.__table__.create(connection)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    try:
        run = DatasetDateCompletenessRun(
            dataset_key="adj_factor",
            display_name="复权因子",
            target_table="core_serving.adj_factor",
            run_mode="manual",
            run_status="succeeded",
            result_status="failed",
            start_date=date(2026, 3, 30),
            end_date=date(2026, 3, 31),
            date_axis="trade_open_day",
            bucket_rule="every_open_day",
            window_mode="point_or_range",
            input_shape="trade_date_or_start_end",
            observed_field="trade_date",
            bucket_window_rule="none",
            bucket_applicability_rule="always",
            row_identity_filters_json={},
            audit_scope="date_subject_matrix",
            subject_kind="stock",
            expected_bucket_count=2,
            actual_bucket_count=2,
            missing_bucket_count=0,
            excluded_bucket_count=0,
            gap_range_count=0,
            expected_cell_count=10,
            actual_cell_count=8,
            missing_cell_count=2,
            affected_bucket_count=2,
            affected_subject_count=1,
            detail_truncated=False,
            requested_at=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc),
        )
        session.add(run)
        session.flush()

        gap = DatasetSubjectCompletenessGap(
            run_id=run.id,
            dataset_key=run.dataset_key,
            bucket_kind="trade_date",
            bucket_value=date(2026, 3, 30),
            subject_kind="stock",
            subject_key_fields_json=["ts_code"],
            actual_key_fields_json=["ts_code", "trade_date"],
            missing_cell_count=1,
            affected_subject_count=1,
            sample_subjects_json=[{"ts_code": "001257.SZ", "name": "立新能源"}],
        )
        session.add(gap)
        session.flush()
        session.add(
            DatasetSubjectCompletenessGapDetail(
                run_id=run.id,
                gap_id=gap.id,
                dataset_key=run.dataset_key,
                bucket_kind=gap.bucket_kind,
                bucket_value=gap.bucket_value,
                subject_kind="stock",
                subject_key="001257.SZ",
                subject_name="立新能源",
                subject_key_json={"ts_code": "001257.SZ"},
                actual_key_json={"ts_code": "001257.SZ", "trade_date": "2026-03-30"},
                lifecycle_start=date(2022, 7, 27),
                lifecycle_end=None,
                reason_code="missing_subject_bucket",
                reason_message="该股票在该交易日处于上市生命周期内，但目标表缺少对应行。",
                target_table=run.target_table,
            )
        )
        session.commit()

        stored_run = session.scalar(select(DatasetDateCompletenessRun).where(DatasetDateCompletenessRun.dataset_key == "adj_factor"))
        stored_gap = session.scalar(select(DatasetSubjectCompletenessGap).where(DatasetSubjectCompletenessGap.run_id == run.id))
        stored_detail = session.scalar(select(DatasetSubjectCompletenessGapDetail).where(DatasetSubjectCompletenessGapDetail.run_id == run.id))

        assert stored_run is not None
        assert stored_run.audit_scope == "date_subject_matrix"
        assert stored_run.missing_bucket_count == 0
        assert stored_run.missing_cell_count == 2
        assert stored_run.affected_bucket_count == 2
        assert stored_run.affected_subject_count == 1
        assert stored_gap is not None
        assert stored_gap.sample_subjects_json == [{"ts_code": "001257.SZ", "name": "立新能源"}]
        assert stored_detail is not None
        assert stored_detail.subject_key == "001257.SZ"
        assert stored_detail.reason_code == "missing_subject_bucket"
    finally:
        session.close()
        engine.dispose()
