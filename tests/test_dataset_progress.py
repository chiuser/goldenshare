from __future__ import annotations

from types import SimpleNamespace

from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.progress import IngestionObserver, ProgressSnapshot
from src.foundation.ingestion.service import DatasetMaintainService


def test_observer_emits_progress_without_run_id() -> None:
    captured: list[tuple[ProgressSnapshot, str]] = []

    def reporter(snapshot: ProgressSnapshot, message: str) -> None:
        captured.append((snapshot, message))

    observer = IngestionObserver(progress_reporter=reporter)
    observer.report_progress(
        run_id=None,
        dataset_key="index_daily",
        unit_total=100,
        unit_done=1,
        unit_failed=0,
        rows_fetched=2000,
        rows_written=2000,
        rows_committed=2000,
        message="index_daily: 1/100 fetched=2000 written=2000 committed=2000",
        current_object={
            "entity": {"kind": "index", "code": "000001.SH"},
            "time": {"point": "2026-04-24"},
            "attributes": {},
        },
    )

    assert len(captured) == 1
    snapshot, message = captured[0]
    assert snapshot.run_id is None
    assert snapshot.rows_committed == 2000
    assert snapshot.current_object["entity"]["code"] == "000001.SH"
    assert message == "index_daily: 1/100 fetched=2000 written=2000 committed=2000"


def test_executor_progress_message_includes_generic_unit_tokens() -> None:
    unit = PlanUnitSnapshot(
        unit_id="u-stk-mins",
        dataset_key="stk_mins",
        source_key="tushare",
        trade_date=None,
        request_params={
            "ts_code": "000001.SZ",
            "freq": "1min",
            "start_date": "2026-04-23 09:00:00",
            "end_date": "2026-04-23 19:00:00",
        },
        progress_context={
            "unit": "stock",
            "ts_code": "000001.SZ",
            "security_name": "平安银行",
            "freq": "1min",
            "start_date": "2026-04-23 09:00:00",
            "end_date": "2026-04-23 19:00:00",
        },
    )

    message = IngestionExecutor._build_progress_message(
        progress_label="stk_mins",
        current=2,
        total=10,
        rows_fetched=16000,
        rows_written=15998,
        rows_committed=15998,
        rows_rejected=2,
        rejected_reason_counts={},
        unit=unit,
        unit_rows_fetched=8000,
        unit_rows_written=7999,
        unit_rows_committed=7999,
        unit_rows_rejected=1,
    )

    assert "stk_mins: 2/10" in message
    assert "unit=stock" in message
    assert "ts_code=000001.SZ" in message
    assert "security_name=平安银行" in message
    assert "freq=1min" in message
    assert "start_date=2026-04-23_09:00:00" in message
    assert "end_date=2026-04-23_19:00:00" in message
    assert "unit_committed=7999" in message
    assert "committed=15998" in message


def test_maintain_progress_reports_only_committed_rows_as_saved() -> None:
    captured: list[dict[str, object]] = []

    class CaptureRunContext:
        def is_cancel_requested(self, *, run_id: int) -> bool:
            return False

        def update_progress(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            captured.append(kwargs)

    service = DatasetMaintainService(object(), dataset_key="daily", run_context=CaptureRunContext())
    snapshot = SimpleNamespace(
        run_id=123,
        unit_done=1,
        unit_failed=0,
        unit_total=5,
        rows_fetched=100,
        rows_written=100,
        rows_committed=0,
        rows_rejected=0,
        current_object={},
    )

    service._progress_reporter(snapshot, "daily: 1/5 fetched=100 written=100 rejected=0")

    assert captured[0]["rows_saved"] == 0
