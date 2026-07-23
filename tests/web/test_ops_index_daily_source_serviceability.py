from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.index_daily_reconciliation_policy import (
    INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
    INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
)
from src.ops.services.index_daily_source_serviceability_service import IndexDailySourceServiceabilityService


def _seed_open_days(session: Session, *trade_dates: date) -> None:
    session.add_all(
        [
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_date,
                is_open=True,
                pretrade_date=None,
            )
            for trade_date in trade_dates
        ]
    )


def _seed_active_codes(session: Session, *codes: str) -> None:
    observed_at = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    session.add_all(
        [
            IndexSeriesActive(
                resource="index_daily",
                ts_code=code,
                first_seen_date=date(2026, 7, 1),
                last_seen_date=date(2026, 7, 14),
                last_checked_at=observed_at,
            )
            for code in codes
        ]
    )


def _seed_raw(session: Session, *, ts_code: str, trade_date: date) -> None:
    session.add(
        RawIndexDaily(
            ts_code=ts_code,
            trade_date=trade_date,
            api_name="index_daily",
            fetched_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )
    )


def _seed_terminal_repair(
    session: Session,
    *,
    ts_code: str,
    trade_date: date,
    task_id: int,
    worker_claimed: bool = True,
    status: str = "success",
    repair_slot: str | None = None,
    trigger_source: str = "system",
) -> None:
    occurred_at = datetime(2026, 7, 14, 18, task_id, tzinfo=timezone.utc)
    session.add(
        TaskRun(
            id=task_id,
            task_type="dataset_action",
            resource_key="index_daily",
            action="maintain",
            title="指数日线",
            trigger_source=trigger_source,
            status=status,
            time_input_json={"mode": "point", "trade_date": trade_date.isoformat()},
            filters_json={"ts_code": ts_code},
            request_payload_json={
                "run_scope": INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
                **({"repair_slot": repair_slot} if repair_slot is not None else {}),
            },
            plan_snapshot_json={},
            current_object_json={},
            requested_at=occurred_at,
            started_at=occurred_at if worker_claimed else None,
            ended_at=occurred_at,
        )
    )


def test_index_daily_serviceability_classifies_gaps_from_current_facts(db_session: Session) -> None:
    target_date = date(2026, 7, 14)
    _seed_open_days(db_session, target_date, date(2026, 7, 13), date(2026, 7, 12), date(2026, 7, 11))
    _seed_active_codes(
        db_session,
        "SERVING.GAP",
        "DELAY.GAP",
        "EXHAUST.GAP",
        "STALE.GAP",
        "SKIPPED.GAP",
        "EMPTY.GAP",
        "COMPLETE.GAP",
    )
    _seed_raw(db_session, ts_code="SERVING.GAP", trade_date=target_date)
    _seed_raw(db_session, ts_code="DELAY.GAP", trade_date=date(2026, 7, 13))
    _seed_raw(db_session, ts_code="EXHAUST.GAP", trade_date=date(2026, 7, 13))
    _seed_raw(db_session, ts_code="STALE.GAP", trade_date=date(2026, 7, 10))
    _seed_raw(db_session, ts_code="SKIPPED.GAP", trade_date=date(2026, 7, 15))
    _seed_raw(db_session, ts_code="COMPLETE.GAP", trade_date=target_date)
    db_session.add(IndexDailyServing(ts_code="COMPLETE.GAP", trade_date=target_date, source="api"))
    for task_id, repair_slot in enumerate(
        (
            INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
            INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
            INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
        ),
        start=1,
    ):
        _seed_terminal_repair(
            db_session,
            ts_code="EXHAUST.GAP",
            trade_date=target_date,
            task_id=task_id,
            repair_slot=repair_slot,
        )
    db_session.commit()

    classifications = IndexDailySourceServiceabilityService().classify_active_gaps(
        db_session,
        target_trade_date=target_date,
    )
    by_code = {item.ts_code: item for item in classifications}

    assert set(by_code) == {
        "DELAY.GAP",
        "EMPTY.GAP",
        "EXHAUST.GAP",
        "SERVING.GAP",
        "SKIPPED.GAP",
        "STALE.GAP",
    }
    assert by_code["SERVING.GAP"].internal_status == "serving_projection_gap"
    assert by_code["SERVING.GAP"].public_serviceability_status == "ready"
    assert by_code["SERVING.GAP"].completed_repair_slots == frozenset()
    assert by_code["DELAY.GAP"].internal_status == "source_delayed"
    assert IndexDailySourceServiceabilityService.is_repair_slot_available(
        by_code["DELAY.GAP"],
        repair_slot=INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
    )
    assert by_code["EXHAUST.GAP"].internal_status == "source_retry_exhausted"
    assert by_code["EXHAUST.GAP"].completed_repair_slots == frozenset(
        {
            INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
            INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
            INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
        }
    )
    assert not IndexDailySourceServiceabilityService.is_repair_slot_available(
        by_code["EXHAUST.GAP"],
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
    )
    assert by_code["STALE.GAP"].internal_status == "serviceability_review_required"
    assert by_code["SKIPPED.GAP"].internal_status == "serviceability_review_required"
    assert by_code["EMPTY.GAP"].internal_status == "serviceability_review_required"


def test_index_daily_serviceability_uses_completed_slots_and_ignores_legacy_or_unclaimed_repairs(db_session: Session) -> None:
    target_date = date(2026, 7, 14)
    _seed_open_days(db_session, target_date, date(2026, 7, 13), date(2026, 7, 12))
    _seed_active_codes(db_session, "DELAY.GAP")
    _seed_raw(db_session, ts_code="DELAY.GAP", trade_date=date(2026, 7, 13))
    _seed_terminal_repair(
        db_session,
        ts_code="DELAY.GAP",
        trade_date=target_date,
        task_id=1,
        repair_slot=INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
    )
    _seed_terminal_repair(
        db_session,
        ts_code="DELAY.GAP",
        trade_date=target_date,
        task_id=2,
        worker_claimed=False,
        status="failed",
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
    )
    _seed_terminal_repair(db_session, ts_code="DELAY.GAP", trade_date=target_date, task_id=3)
    _seed_terminal_repair(
        db_session,
        ts_code="DELAY.GAP",
        trade_date=target_date,
        task_id=4,
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
        trigger_source="manual",
    )
    db_session.commit()

    classification = IndexDailySourceServiceabilityService().classify_active_gaps(
        db_session,
        target_trade_date=target_date,
    )[0]

    assert classification.completed_repair_slots == frozenset({INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL})
    assert classification.internal_status == "source_delayed"
    assert IndexDailySourceServiceabilityService.is_repair_slot_available(
        classification,
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
    )


def test_index_daily_activation_requires_three_completed_open_days(db_session: Session) -> None:
    _seed_open_days(db_session, date(2026, 7, 14), date(2026, 7, 13), date(2026, 7, 12))
    for trade_date in (date(2026, 7, 14), date(2026, 7, 13), date(2026, 7, 12)):
        _seed_raw(db_session, ts_code="READY.GAP", trade_date=trade_date)
    _seed_raw(db_session, ts_code="WAIT.GAP", trade_date=date(2026, 7, 14))
    _seed_raw(db_session, ts_code="WAIT.GAP", trade_date=date(2026, 7, 13))
    db_session.commit()

    service = IndexDailySourceServiceabilityService()
    now = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
    ready = service.activation_eligibility(db_session, ts_code="READY.GAP", now=now)
    waiting = service.activation_eligibility(db_session, ts_code="WAIT.GAP", now=now)

    assert ready.reference_trade_date == date(2026, 7, 14)
    assert ready.eligible is True
    assert waiting.reference_trade_date == date(2026, 7, 14)
    assert waiting.eligible is False
    assert "连续 3 个已结束开市日" in waiting.message


def test_index_daily_activation_rejects_when_no_completed_open_day_exists(db_session: Session) -> None:
    result = IndexDailySourceServiceabilityService().activation_eligibility(
        db_session,
        ts_code="EMPTY.GAP",
        now=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
    )

    assert result.reference_trade_date is None
    assert result.eligible is False
