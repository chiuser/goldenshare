from __future__ import annotations

from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.asset_guards.major_index_mins_technical import (
    MajorIndexMinsTechnicalReadiness,
    major_index_mins_technical_state_readiness,
    major_index_mins_technical_target_readiness,
)
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_AUTOMATION_CONTRACT_REVISION,
    MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME,
    MAJOR_INDEX_MINS_TECHNICAL_SENSOR_NAME,
)
from orchestrator.defs.sensors.gold_major_index_mins_technical_daily_update_job_sensor import (
    DAGSTER_PARTITION_RANGE_END_TAG,
    DAGSTER_PARTITION_RANGE_START_TAG,
    DAGSTER_PARTITION_TAG,
    _run_request_for_trade_date,
    build_major_index_mins_technical_daily_decision,
    extract_unique_major_index_mins_partition_key,
    gold_major_index_mins_technical_daily_update_job_sensor,
)

TARGET_DATE = "2026-08-04"
PREVIOUS_DATE = "2026-08-03"


def _readiness(
    *,
    ready: bool,
    materialized: int,
    expected: int = 14,
    reason_code: str,
) -> MajorIndexMinsTechnicalReadiness:
    return MajorIndexMinsTechnicalReadiness(
        trade_date=TARGET_DATE,
        ready=ready,
        expected_file_count=expected,
        materialized_file_count=materialized,
        checks_passed=ready,
        reason_code=reason_code,
        reason=reason_code,
    )


def test_sensor_definition_is_stopped_and_targets_daily_job() -> None:
    assert gold_major_index_mins_technical_daily_update_job_sensor.name == (
        MAJOR_INDEX_MINS_TECHNICAL_SENSOR_NAME
    )
    assert gold_major_index_mins_technical_daily_update_job_sensor.default_status is (
        dg.DefaultSensorStatus.STOPPED
    )
    assert gold_major_index_mins_technical_daily_update_job_sensor.job_name == (
        MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME
    )


def test_partition_parser_accepts_one_partition_and_rejects_ambiguity() -> None:
    assert extract_unique_major_index_mins_partition_key(
        partition_key=None,
        tag_values={DAGSTER_PARTITION_TAG: TARGET_DATE},
    ) == TARGET_DATE
    assert extract_unique_major_index_mins_partition_key(
        partition_key=TARGET_DATE,
        tag_values={DAGSTER_PARTITION_TAG: TARGET_DATE},
    ) == TARGET_DATE
    assert extract_unique_major_index_mins_partition_key(
        partition_key=None,
        tag_values={},
    ) is None
    assert extract_unique_major_index_mins_partition_key(
        partition_key="not-a-date",
        tag_values={},
    ) is None
    assert extract_unique_major_index_mins_partition_key(
        partition_key=TARGET_DATE,
        tag_values={DAGSTER_PARTITION_TAG: PREVIOUS_DATE},
    ) is None
    assert extract_unique_major_index_mins_partition_key(
        partition_key=None,
        tag_values={
            DAGSTER_PARTITION_RANGE_START_TAG: TARGET_DATE,
            DAGSTER_PARTITION_RANGE_END_TAG: TARGET_DATE,
        },
    ) == TARGET_DATE
    assert extract_unique_major_index_mins_partition_key(
        partition_key=None,
        tag_values={
            DAGSTER_PARTITION_RANGE_START_TAG: PREVIOUS_DATE,
            DAGSTER_PARTITION_RANGE_END_TAG: TARGET_DATE,
        },
    ) is None
    assert extract_unique_major_index_mins_partition_key(
        partition_key=None,
        tag_values={DAGSTER_PARTITION_RANGE_START_TAG: TARGET_DATE},
    ) is None
    assert extract_unique_major_index_mins_partition_key(
        partition_key=None,
        tag_values={DAGSTER_PARTITION_RANGE_END_TAG: TARGET_DATE},
    ) is None


def test_decision_skips_source_not_ready_before_target_checks() -> None:
    decision = build_major_index_mins_technical_daily_decision(
        target_trade_date=TARGET_DATE,
        previous_trade_date=PREVIOUS_DATE,
        is_historical_baseline=False,
        source_ready=False,
        target_readiness=None,
        previous_state_readiness=None,
    )

    assert decision.selected_trade_date is None
    assert decision.reason_code == "source_not_ready"


def test_decision_skips_ready_target_and_fails_closed_on_existing_target() -> None:
    ready = build_major_index_mins_technical_daily_decision(
        target_trade_date=TARGET_DATE,
        previous_trade_date=PREVIOUS_DATE,
        is_historical_baseline=False,
        source_ready=True,
        target_readiness=_readiness(
            ready=True,
            materialized=14,
            reason_code="ready",
        ),
        previous_state_readiness=None,
    )
    partial = build_major_index_mins_technical_daily_decision(
        target_trade_date=TARGET_DATE,
        previous_trade_date=PREVIOUS_DATE,
        is_historical_baseline=False,
        source_ready=True,
        target_readiness=_readiness(
            ready=False,
            materialized=1,
            reason_code="target_partial",
        ),
        previous_state_readiness=None,
    )
    invalid = build_major_index_mins_technical_daily_decision(
        target_trade_date=TARGET_DATE,
        previous_trade_date=PREVIOUS_DATE,
        is_historical_baseline=False,
        source_ready=True,
        target_readiness=_readiness(
            ready=False,
            materialized=14,
            reason_code="target_invalid",
        ),
        previous_state_readiness=None,
    )

    assert ready.reason_code == "target_ready"
    assert partial.reason_code == "target_partial"
    assert invalid.reason_code == "target_invalid"
    assert ready.selected_trade_date is None
    assert partial.selected_trade_date is None
    assert invalid.selected_trade_date is None


def test_decision_requires_previous_state_except_on_historical_baseline() -> None:
    absent_target = _readiness(
        ready=False,
        materialized=0,
        reason_code="target_absent",
    )
    blocked = build_major_index_mins_technical_daily_decision(
        target_trade_date=TARGET_DATE,
        previous_trade_date=PREVIOUS_DATE,
        is_historical_baseline=False,
        source_ready=True,
        target_readiness=absent_target,
        previous_state_readiness=_readiness(
            ready=False,
            materialized=0,
            expected=7,
            reason_code="state_absent",
        ),
    )
    selected = build_major_index_mins_technical_daily_decision(
        target_trade_date=TARGET_DATE,
        previous_trade_date=PREVIOUS_DATE,
        is_historical_baseline=False,
        source_ready=True,
        target_readiness=absent_target,
        previous_state_readiness=_readiness(
            ready=True,
            materialized=7,
            expected=7,
            reason_code="ready",
        ),
    )
    baseline = build_major_index_mins_technical_daily_decision(
        target_trade_date="2009-01-05",
        previous_trade_date=None,
        is_historical_baseline=True,
        source_ready=True,
        target_readiness=MajorIndexMinsTechnicalReadiness(
            trade_date="2009-01-05",
            ready=False,
            expected_file_count=14,
            materialized_file_count=0,
            checks_passed=False,
            reason_code="target_absent",
            reason="target_absent",
        ),
        previous_state_readiness=None,
    )

    assert blocked.reason_code == "state_absent"
    assert blocked.selected_trade_date is None
    assert selected.reason_code == "request_run"
    assert selected.selected_trade_date == TARGET_DATE
    assert baseline.reason_code == "request_run"
    assert baseline.selected_trade_date == "2009-01-05"


def test_target_readiness_classifies_all_missing_and_partial_without_scanning(
    tmp_path: Path,
) -> None:
    with duckdb.connect(":memory:") as connection:
        absent = major_index_mins_technical_target_readiness(
            connection=connection,
            lake_root=tmp_path,
            trade_date=TARGET_DATE,
            expected_trade_dates=(PREVIOUS_DATE, TARGET_DATE),
        )
        one_path = gold_major_index_mins_technical_path(
            tmp_path,
            1,
            TARGET_DATE,
        )
        one_path.parent.mkdir(parents=True, exist_ok=True)
        one_path.touch()
        partial = major_index_mins_technical_target_readiness(
            connection=connection,
            lake_root=tmp_path,
            trade_date=TARGET_DATE,
            expected_trade_dates=(PREVIOUS_DATE, TARGET_DATE),
        )

    assert absent.all_missing is True
    assert absent.scanned_file_count == 0
    assert partial.partial is True
    assert partial.reason_code == "target_partial"
    assert partial.scanned_file_count == 0
    assert partial.materialized_file_count == 1


def test_previous_state_readiness_classifies_partial_without_scanning(
    tmp_path: Path,
) -> None:
    one_path = gold_major_index_mins_technical_state_path(
        tmp_path,
        1,
        PREVIOUS_DATE,
    )
    one_path.parent.mkdir(parents=True, exist_ok=True)
    one_path.touch()

    with duckdb.connect(":memory:") as connection:
        partial = major_index_mins_technical_state_readiness(
            connection=connection,
            lake_root=tmp_path,
            trade_date=PREVIOUS_DATE,
            expected_trade_dates=(PREVIOUS_DATE, TARGET_DATE),
        )

    assert partial.partial is True
    assert partial.reason_code == "state_partial"
    assert partial.scanned_file_count == 0
    assert partial.materialized_file_count == 1


def test_run_request_is_single_partition_and_revisioned() -> None:
    request = _run_request_for_trade_date(TARGET_DATE)

    assert request.partition_key == TARGET_DATE
    assert request.run_key == (
        f"{MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME}:{TARGET_DATE}:"
        f"{MAJOR_INDEX_MINS_TECHNICAL_AUTOMATION_CONTRACT_REVISION}"
    )
    assert request.tags == {}


def test_run_status_sensor_uses_dagster_cursor_without_custom_cursor() -> None:
    source = Path(
        "src/orchestrator/defs/sensors/"
        "gold_major_index_mins_technical_daily_update_job_sensor.py"
    ).read_text(encoding="utf-8")

    assert "@dg.run_status_sensor" in source
    assert "monitored_jobs=[silver_major_index_mins_update_job]" in source
    assert "build_sensor_cursor" not in source
    assert "SensorResult" not in source
    assert "get_event_records" not in source
