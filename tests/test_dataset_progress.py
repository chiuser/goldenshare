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
        message="指数日线：1/100；累计读取 2000；累计保存 2000",
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
    assert message == "指数日线：1/100；累计读取 2000；累计保存 2000"


def test_executor_progress_message_uses_operator_readable_summary() -> None:
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

    assert "stk_mins：2/10" in message
    assert "单元 stock" in message
    assert "证券 平安银行（000001.SZ）" in message
    assert "频率 1min" in message
    assert "范围 2026-04-23 09:00:00 ~ 2026-04-23 19:00:00" in message
    assert "保存 7999" in message
    assert "累计保存 15998" in message
    assert "unit=" not in message
    assert "committed=" not in message


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

    service._progress_reporter(snapshot, "股票日线：1/5；累计读取 100；累计保存 0")

    assert captured[0]["rows_saved"] == 0
