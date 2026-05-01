from __future__ import annotations

from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
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
        def normalize(self, *, definition, fetch_result):  # type: ignore[no-untyped-def]
            return NormalizedBatch(
                unit_id=fetch_result.unit_id,
                rows_normalized=[{"row_key_hash": "a"}, {"row_key_hash": "b"}],
                rows_rejected=1,
                rejected_reasons={"normalize.required_field_missing:trade_date": 1},
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
    assert captured[0][0].rejected_reason_counts == summary.rejected_reason_counts
