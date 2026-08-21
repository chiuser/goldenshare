from __future__ import annotations

from dataclasses import replace
import threading
import time
from types import SimpleNamespace

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.progress import IngestionObserver, ProgressSnapshot
from src.foundation.ingestion.service import DatasetMaintainService
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import WriteResult


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


def test_maintain_progress_passes_committed_and_failed_units_separately() -> None:
    captured: list[dict[str, object]] = []

    class CaptureRunContext:
        def is_cancel_requested(self, *, run_id: int) -> bool:
            return False

        def update_progress(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            captured.append(kwargs)

    service = DatasetMaintainService(object(), dataset_key="daily", run_context=CaptureRunContext())
    snapshot = SimpleNamespace(
        run_id=123,
        unit_done=2,
        unit_failed=1,
        unit_total=5,
        rows_fetched=100,
        rows_written=100,
        rows_committed=100,
        rows_rejected=0,
        current_object={},
    )

    service._progress_reporter(snapshot, "股票日线：3/5；累计读取 100；累计保存 100")

    assert captured[0]["unit_done"] == 2
    assert captured[0]["unit_failed"] == 1
    assert "current" not in captured[0]


def test_ops_progress_failure_does_not_rollback_committed_business_rows() -> None:
    class StubSession:
        def __init__(self) -> None:
            self.pending_business_rows = 0
            self.committed_business_rows = 0
            self.rollback_count = 0

        def commit(self) -> None:
            self.committed_business_rows += self.pending_business_rows
            self.pending_business_rows = 0

        def rollback(self) -> None:
            self.pending_business_rows = 0
            self.rollback_count += 1

    class FailingProgressRunContext:
        def __init__(self) -> None:
            self.update_attempts = 0

        def is_cancel_requested(self, *, run_id: int) -> bool:
            return False

        def update_progress(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.update_attempts += 1
            raise RuntimeError("ops state update failed")

    class StubSourceClient:
        def fetch(self, *, definition, unit):  # type: ignore[no-untyped-def]
            return SourceFetchResult(unit_id=unit.unit_id, request_count=1, retry_count=0, latency_ms=0, rows_raw=[{}])

    class StubNormalizer:
        def normalize(self, *, definition, fetch_result, expected_unit_date=None):  # type: ignore[no-untyped-def]
            return NormalizedBatch(
                unit_id=fetch_result.unit_id,
                rows_normalized=[{"trade_date": "2026-04-24", "ts_code": "000001.SZ"}],
                rows_rejected=0,
                rejected_reasons={},
            )

        def raise_if_all_rejected(self, normalized):  # type: ignore[no-untyped-def]
            return None

    class StubWriter:
        def __init__(self, session: StubSession) -> None:
            self.session = session

        def write(self, **kwargs):  # type: ignore[no-untyped-def]
            self.session.pending_business_rows += 1
            return WriteResult(
                unit_id="u-1",
                rows_written=1,
                rows_upserted=1,
                rows_skipped=0,
                target_table="raw_tushare.daily",
                conflict_strategy="upsert",
            )

    session = StubSession()
    run_context = FailingProgressRunContext()
    service = DatasetMaintainService(session, dataset_key="daily", run_context=run_context)
    service.executor.source_client = StubSourceClient()  # type: ignore[assignment]
    service.executor.normalizer = StubNormalizer()  # type: ignore[assignment]
    service.executor.writer = StubWriter(session)  # type: ignore[assignment]
    unit = PlanUnitSnapshot(
        unit_id="u-1",
        dataset_key="daily",
        source_key="tushare",
        trade_date=None,
        request_params={},
        progress_context={},
    )
    request = ValidatedDatasetActionRequest(
        request_id="r-1",
        dataset_key="daily",
        action="maintain",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
        source_key=None,
        trade_date=None,
        start_date=None,
        end_date=None,
        run_id=123,
    )

    summary = service.executor.run(
        request=request,
        definition=get_dataset_definition("daily"),
        units=(unit,),
        progress_reporter=service._progress_reporter,
    )

    assert summary.rows_committed == 1
    assert session.committed_business_rows == 1
    assert session.pending_business_rows == 0
    assert session.rollback_count == 0
    assert run_context.update_attempts == 1


def test_executor_merges_normalizer_and_writer_rejected_reasons() -> None:
    captured: list[tuple[ProgressSnapshot, str]] = []

    class StubSession:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    class StubSourceClient:
        def fetch(self, *, definition, unit):  # type: ignore[no-untyped-def]
            return SourceFetchResult(unit_id=unit.unit_id, request_count=1, retry_count=0, latency_ms=0, rows_raw=[{}, {}, {}])

    class StubNormalizer:
        def normalize(self, *, definition, fetch_result, expected_unit_date=None):  # type: ignore[no-untyped-def]
            return NormalizedBatch(
                unit_id=fetch_result.unit_id,
                rows_normalized=[{"row_key_hash": "a"}, {"row_key_hash": "b"}],
                rows_rejected=1,
                rejected_reasons={"normalize.required_field_missing:trade_date": 1},
                rejected_samples={
                    "normalize.required_field_missing:trade_date": [
                        {"unit_id": "u-1", "field": "trade_date", "value": None, "row": {"row_key_hash": "missing-date"}}
                    ]
                },
            )

        def raise_if_all_rejected(self, normalized):  # type: ignore[no-untyped-def]
            return None

    class StubWriter:
        def write(self, **kwargs):  # type: ignore[no-untyped-def]
            return WriteResult(
                unit_id="u-1",
                rows_written=1,
                rows_upserted=1,
                rows_skipped=0,
                target_table="raw_tushare.test",
                conflict_strategy="upsert",
                rows_rejected=1,
                rejected_reason_counts={"write.duplicate_conflict_key_in_batch:row_key_hash": 1},
                rejected_reason_samples={
                    "write.duplicate_conflict_key_in_batch:row_key_hash": [
                        {
                            "unit_id": "u-1",
                            "field": "row_key_hash",
                            "value": "a",
                            "row": {"row_key_hash": "a", "title": "重复条"},
                        }
                    ]
                },
            )

    executor = IngestionExecutor(StubSession())
    executor.source_client = StubSourceClient()  # type: ignore[assignment]
    executor.normalizer = StubNormalizer()  # type: ignore[assignment]
    executor.writer = StubWriter()  # type: ignore[assignment]
    unit = PlanUnitSnapshot(
        unit_id="u-1",
        dataset_key="major_news",
        source_key="tushare",
        trade_date=None,
        request_params={},
        progress_context={},
    )
    request = ValidatedDatasetActionRequest(
        request_id="r-1",
        dataset_key="major_news",
        action="maintain",
        run_profile="no_time_refresh",
        trigger_source="test",
        params={},
        source_key=None,
        trade_date=None,
        start_date=None,
        end_date=None,
        run_id=123,
    )

    summary = executor.run(
        request=request,
        definition=get_dataset_definition("major_news"),
        units=(unit,),
        progress_reporter=lambda snapshot, message: captured.append((snapshot, message)),
    )

    assert summary.rows_rejected == 2
    assert summary.rejected_reason_counts == {
        "normalize.required_field_missing:trade_date": 1,
        "write.duplicate_conflict_key_in_batch:row_key_hash": 1,
    }
    assert summary.rejected_reason_samples["normalize.required_field_missing:trade_date"][0]["row"]["row_key_hash"] == "missing-date"
    assert summary.rejected_reason_samples["write.duplicate_conflict_key_in_batch:row_key_hash"][0]["value"] == "a"
    assert captured[0][0].rejected_reason_counts == summary.rejected_reason_counts
    assert captured[0][0].rejected_reason_samples == summary.rejected_reason_samples


def test_executor_serial_fetch_failure_does_not_process_missing_source_result() -> None:
    class StubSession:
        def __init__(self) -> None:
            self.rollback_count = 0

        def rollback(self) -> None:
            self.rollback_count += 1

    class FailingSourceClient:
        def fetch(self, *, definition, unit):  # type: ignore[no-untyped-def]
            raise RuntimeError("source boom")

    class GuardNormalizer:
        def normalize(self, **kwargs):  # type: ignore[no-untyped-def]
            pytest.fail("源端请求失败后不得进入 normalizer")

    session = StubSession()
    executor = IngestionExecutor(session)
    executor.source_client = FailingSourceClient()  # type: ignore[assignment]
    executor.normalizer = GuardNormalizer()  # type: ignore[assignment]
    request = ValidatedDatasetActionRequest(
        request_id="r-1",
        dataset_key="major_news",
        action="maintain",
        run_profile="no_time_refresh",
        trigger_source="test",
    )
    unit = PlanUnitSnapshot("u-fail", "major_news", "tushare", None, {}, {})

    with pytest.raises(IngestionError, match="source boom"):
        executor.run(
            request=request,
            definition=get_dataset_definition("major_news"),
            units=(unit,),
        )

    assert session.rollback_count == 1


def test_executor_concurrent_fetch_keeps_write_commit_and_progress_on_main_thread() -> None:
    main_thread = threading.current_thread().name
    captured_messages: list[str] = []

    class StubSession:
        def __init__(self) -> None:
            self.commit_threads: list[str] = []
            self.rollback_count = 0

        def commit(self) -> None:
            self.commit_threads.append(threading.current_thread().name)

        def rollback(self) -> None:
            self.rollback_count += 1

    class ConcurrentSourceClient:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.active = 0
            self.max_active = 0
            self.first_two_started = threading.Barrier(2)

        def fetch(self, *, definition, unit):  # type: ignore[no-untyped-def]
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                if unit.unit_id in {"u-slow", "u-fast"}:
                    self.first_two_started.wait(timeout=2)
                if unit.unit_id == "u-slow":
                    time.sleep(0.05)
                return SourceFetchResult(
                    unit_id=unit.unit_id,
                    request_count=1,
                    retry_count=0,
                    latency_ms=0,
                    rows_raw=[{"unit_id": unit.unit_id}],
                )
            finally:
                with self.lock:
                    self.active -= 1

    class StubNormalizer:
        def __init__(self) -> None:
            self.threads: list[str] = []

        def normalize(self, *, definition, fetch_result, expected_unit_date=None):  # type: ignore[no-untyped-def]
            self.threads.append(threading.current_thread().name)
            return NormalizedBatch(
                unit_id=fetch_result.unit_id,
                rows_normalized=[{"unit_id": fetch_result.unit_id}],
                rows_rejected=0,
                rejected_reasons={},
            )

        def raise_if_all_rejected(self, normalized):  # type: ignore[no-untyped-def]
            return None

    class StubWriter:
        def __init__(self) -> None:
            self.threads: list[str] = []
            self.write_order: list[str] = []

        def write(self, **kwargs):  # type: ignore[no-untyped-def]
            batch = kwargs["batch"]
            self.threads.append(threading.current_thread().name)
            self.write_order.append(batch.unit_id)
            return WriteResult(
                unit_id=batch.unit_id,
                rows_written=1,
                rows_upserted=1,
                rows_skipped=0,
                target_table="raw_tushare.test",
                conflict_strategy="upsert",
            )

    units = (
        PlanUnitSnapshot("u-slow", "major_news", "tushare", None, {}, {}),
        PlanUnitSnapshot("u-fast", "major_news", "tushare", None, {}, {}),
    )
    request = ValidatedDatasetActionRequest(
        request_id="r-1",
        dataset_key="major_news",
        action="maintain",
        run_profile="no_time_refresh",
        trigger_source="test",
        run_id=123,
    )
    definition = get_dataset_definition("major_news")
    definition = replace(definition, planning=replace(definition.planning, fetch_concurrency=2))
    session = StubSession()
    source_client = ConcurrentSourceClient()
    normalizer = StubNormalizer()
    writer = StubWriter()
    executor = IngestionExecutor(session)
    executor.source_client = source_client  # type: ignore[assignment]
    executor.normalizer = normalizer  # type: ignore[assignment]
    executor.writer = writer  # type: ignore[assignment]

    summary = executor.run(
        request=request,
        definition=definition,
        units=units,
        progress_reporter=lambda snapshot, message: captured_messages.append(message),
    )

    assert summary.unit_done == 2
    assert source_client.max_active == 2
    assert writer.write_order == ["u-fast", "u-slow"]
    assert normalizer.threads == [main_thread, main_thread]
    assert writer.threads == [main_thread, main_thread]
    assert session.commit_threads == [main_thread, main_thread]
    assert session.rollback_count == 0
    assert captured_messages[0].startswith("major_news：1/2")
    assert captured_messages[1].startswith("major_news：2/2")


def test_executor_concurrent_fetch_failure_stops_new_submission_and_does_not_write() -> None:
    class StubSession:
        def __init__(self) -> None:
            self.commit_count = 0
            self.rollback_count = 0

        def commit(self) -> None:
            self.commit_count += 1

        def rollback(self) -> None:
            self.rollback_count += 1

    class FailingSourceClient:
        def __init__(self) -> None:
            self.started: list[str] = []

        def fetch(self, *, definition, unit):  # type: ignore[no-untyped-def]
            self.started.append(unit.unit_id)
            if unit.unit_id == "u-fail":
                raise RuntimeError("source boom")
            time.sleep(0.1)
            return SourceFetchResult(unit_id=unit.unit_id, request_count=1, retry_count=0, latency_ms=0, rows_raw=[{}])

    class StubNormalizer:
        def normalize(self, *, definition, fetch_result, expected_unit_date=None):  # type: ignore[no-untyped-def]
            return NormalizedBatch(unit_id=fetch_result.unit_id, rows_normalized=[{}], rows_rejected=0, rejected_reasons={})

        def raise_if_all_rejected(self, normalized):  # type: ignore[no-untyped-def]
            return None

    class StubWriter:
        def __init__(self) -> None:
            self.write_calls = 0

        def write(self, **kwargs):  # type: ignore[no-untyped-def]
            self.write_calls += 1
            return WriteResult(
                unit_id=kwargs["batch"].unit_id,
                rows_written=1,
                rows_upserted=1,
                rows_skipped=0,
                target_table="raw_tushare.test",
                conflict_strategy="upsert",
            )

    request = ValidatedDatasetActionRequest(
        request_id="r-1",
        dataset_key="major_news",
        action="maintain",
        run_profile="no_time_refresh",
        trigger_source="test",
        run_id=123,
    )
    definition = get_dataset_definition("major_news")
    definition = replace(definition, planning=replace(definition.planning, fetch_concurrency=2))
    units = (
        PlanUnitSnapshot("u-fail", "major_news", "tushare", None, {}, {}),
        PlanUnitSnapshot("u-slow", "major_news", "tushare", None, {}, {}),
        PlanUnitSnapshot("u-third", "major_news", "tushare", None, {}, {}),
    )
    session = StubSession()
    source_client = FailingSourceClient()
    writer = StubWriter()
    executor = IngestionExecutor(session)
    executor.source_client = source_client  # type: ignore[assignment]
    executor.normalizer = StubNormalizer()  # type: ignore[assignment]
    executor.writer = writer  # type: ignore[assignment]

    with pytest.raises(IngestionError, match="source boom"):
        executor.run(request=request, definition=definition, units=units)

    assert "u-fail" in source_client.started
    assert set(source_client.started).issubset({"u-fail", "u-slow"})
    assert "u-third" not in source_client.started
    assert writer.write_calls == 0
    assert session.commit_count == 0
    assert session.rollback_count == 1
