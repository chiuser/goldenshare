from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.error_mapper import IngestionErrorMapper
from src.foundation.ingestion.errors import IngestionError, IngestionWriteError, StructuredError
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.progress import IngestionObserver
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
from src.foundation.ingestion.staged_stream import StagedStreamPublisher
from src.foundation.ingestion.writer import DatasetWriter, WriteResult


@dataclass(slots=True)
class _RunState:
    rows_fetched: int = 0
    rows_written: int = 0
    rows_committed: int = 0
    rows_rejected: int = 0
    rows_deduplicated: int = 0
    rows_normalized_before_dedupe: int = 0
    rows_inserted: int = 0
    rows_matched: int = 0
    scope_existing_count: int = 0
    scope_source_unique_count: int = 0
    final_scope_count: int = 0
    pagination_unit_count: int = 0
    pagination_total_page_count: int = 0
    pagination_total_retry_count: int = 0
    pagination_total_rows_merged: int = 0
    pagination_multi_page_unit_count: int = 0
    pagination_max_pages_per_unit: int = 0
    pagination_short_page_unit_count: int = 0
    pagination_units: list[dict[str, Any]] = field(default_factory=list)
    pagination_units_truncated: bool = False
    paged_unit_active: dict[str, Any] | None = None
    paged_unit_completed: list[dict[str, Any]] = field(default_factory=list)
    paged_unit_completed_truncated: bool = False
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)
    rejected_reason_samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    persistence_diagnostics: dict[str, Any] = field(default_factory=dict)
    unit_done: int = 0
    unit_failed: int = 0
    error_counts: dict[str, int] = field(default_factory=dict)


class IngestionRunSummary:
    def __init__(
        self,
        *,
        dataset_key: str,
        run_profile: str,
        unit_total: int,
        unit_done: int,
        unit_failed: int,
        rows_fetched: int,
        rows_written: int,
        rows_committed: int,
        rows_rejected: int,
        rows_deduplicated: int,
        ingestion_diagnostics: dict[str, Any],
        rejected_reason_counts: dict[str, int],
        rejected_reason_samples: dict[str, list[dict[str, Any]]],
        result_date: date | None,
        message: str | None,
        error_counts: dict[str, int],
    ) -> None:
        self.dataset_key = dataset_key
        self.run_profile = run_profile
        self.unit_total = unit_total
        self.unit_done = unit_done
        self.unit_failed = unit_failed
        self.rows_fetched = rows_fetched
        self.rows_written = rows_written
        self.rows_committed = rows_committed
        self.rows_rejected = rows_rejected
        self.rows_deduplicated = rows_deduplicated
        self.ingestion_diagnostics = ingestion_diagnostics
        self.rejected_reason_counts = rejected_reason_counts
        self.rejected_reason_samples = rejected_reason_samples
        self.result_date = result_date
        self.message = message
        self.error_counts = error_counts


class IngestionExecutor:
    MAX_REASON_BUCKETS = 3
    MAX_PAGED_UNIT_RESULTS = 16

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.source_client = DatasetSourceClient()
        self.normalizer = DatasetNormalizer()
        self.writer = DatasetWriter(session)
        self.error_mapper = IngestionErrorMapper()

    def run(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        units: tuple[PlanUnitSnapshot, ...],
        cancel_checker=None,  # type: ignore[no-untyped-def]
        progress_reporter=None,  # type: ignore[no-untyped-def]
    ) -> IngestionRunSummary:
        observer = IngestionObserver(progress_reporter=progress_reporter)
        state = _RunState()
        eligibility_as_of = (
            self._current_china_date()
            if definition.transaction.commit_policy == "raw_then_serving"
            else None
        )

        total_units = len(units)
        fetch_concurrency = definition.planning.fetch_concurrency
        if definition.planning.page_processing_mode == "staged_stream":
            self._run_staged_units_serially(
                request=request,
                definition=definition,
                units=units,
                observer=observer,
                state=state,
                cancel_checker=cancel_checker,
            )
        elif fetch_concurrency <= 1 or total_units <= 1:
            self._run_units_serially(
                request=request,
                definition=definition,
                units=units,
                observer=observer,
                state=state,
                cancel_checker=cancel_checker,
                eligibility_as_of=eligibility_as_of,
            )
        else:
            self._run_units_with_concurrent_fetch(
                request=request,
                definition=definition,
                units=units,
                observer=observer,
                state=state,
                cancel_checker=cancel_checker,
                fetch_concurrency=fetch_concurrency,
                eligibility_as_of=eligibility_as_of,
            )

        return IngestionRunSummary(
            dataset_key=request.dataset_key,
            run_profile=request.run_profile,
            unit_total=total_units,
            unit_done=state.unit_done,
            unit_failed=state.unit_failed,
            rows_fetched=state.rows_fetched,
            rows_written=state.rows_written,
            rows_committed=state.rows_committed,
            rows_rejected=state.rows_rejected,
            rows_deduplicated=state.rows_deduplicated,
            ingestion_diagnostics=self._build_ingestion_diagnostics(state),
            rejected_reason_counts=state.rejected_reason_counts,
            rejected_reason_samples=state.rejected_reason_samples,
            result_date=self._resolve_result_date(request),
            message=f"共 {total_units} 个单元，成功 {state.unit_done} 个，失败 {state.unit_failed} 个",
            error_counts=state.error_counts,
        )

    def _run_staged_units_serially(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        units: tuple[PlanUnitSnapshot, ...],
        observer: IngestionObserver,
        state: _RunState,
        cancel_checker,
    ) -> None:  # type: ignore[no-untyped-def]
        total_units = len(units)
        with StagedStreamPublisher(
            outer_session=self.session, definition=definition
        ) as publisher:
            for unit_index, unit in enumerate(units, start=1):
                unit_rows_fetched = 0
                unit_rows_written = 0
                unit_rows_rejected = 0
                unit_rows_deduplicated = 0
                unit_rows_normalized_before_dedupe = 0
                unit_rows_staged_unique = 0
                page_count = 0
                completed_page_count = 0
                retry_count = 0
                terminal_offset = None
                terminal_page_rows = 0
                observed_short_page = False
                stage_run_id = publisher.begin_unit()
                try:
                    if unit.trade_date is None:
                        raise IngestionError(
                            StructuredError(
                                error_code="quarter_end_required",
                                error_type="planning",
                                phase="executor",
                                message="staged-stream unit 缺少报告期",
                                retryable=False,
                                unit_id=unit.unit_id,
                            )
                        )
                    self._set_paged_unit_active(
                        state=state,
                        unit=unit,
                        unit_index=unit_index,
                        unit_total=total_units,
                        phase="processing_page",
                        current_page_number=1,
                        completed_page_count=0,
                        unit_rows_fetched=0,
                        unit_rows_normalized_before_dedupe=0,
                        unit_rows_staged_unique=0,
                        unit_rows_deduplicated=0,
                        unit_rows_rejected=0,
                        retry_count=0,
                        observed_short_page=False,
                        terminal_page_rows=None,
                    )
                    self._report_paged_unit_progress(
                        request=request,
                        definition=definition,
                        observer=observer,
                        state=state,
                        unit=unit,
                        total_units=total_units,
                        unit_rows_fetched=0,
                        unit_rows_rejected=0,
                        unit_rows_deduplicated=0,
                    )
                    self._ensure_not_canceled(
                        cancel_checker=cancel_checker, run_id=request.run_id
                    )
                    repair_value = unit.request_params.get("ts_code")
                    repair_ts_code = (
                        str(repair_value).strip().upper()
                        if repair_value not in (None, "")
                        else None
                    )
                    page_iterator = iter(
                        self.source_client.iter_pages(definition=definition, unit=unit)
                    )
                    while True:
                        self._ensure_not_canceled(
                            cancel_checker=cancel_checker, run_id=request.run_id
                        )
                        try:
                            page = next(page_iterator)
                        except StopIteration:
                            break
                        page_count += 1
                        retry_count += int(page.retry_count or 0)
                        terminal_offset = page.offset
                        terminal_page_rows = len(page.rows_raw)
                        observed_short_page = page.is_short_page
                        unit_rows_fetched += len(page.rows_raw)
                        normalized = self.normalizer.normalize(
                            definition=definition,
                            fetch_result=SourceFetchResult(
                                unit_id=unit.unit_id,
                                request_count=1,
                                retry_count=page.retry_count,
                                latency_ms=page.latency_ms,
                                rows_raw=page.rows_raw,
                            ),
                            expected_unit_date=unit.trade_date,
                        )
                        unit_rows_normalized_before_dedupe += len(normalized.rows_normalized)
                        unit_rows_normalized_before_dedupe += int(normalized.rows_deduplicated or 0)
                        self.normalizer.raise_if_all_rejected(normalized)
                        if normalized.rows_rejected:
                            unit_rows_rejected += normalized.rows_rejected
                            for reason_code, count in normalized.rejected_reasons.items():
                                state.rejected_reason_counts[reason_code] = state.rejected_reason_counts.get(reason_code, 0) + int(count or 0)
                            self._merge_reason_samples(state.rejected_reason_samples, normalized.rejected_samples)
                            raise IngestionError(
                                StructuredError(
                                    error_code="staged_scope_rows_rejected",
                                    error_type="normalize",
                                    phase="executor",
                                    message="staged-stream scope 存在归一化拒绝行，拒绝部分发布",
                                    retryable=False,
                                    unit_id=unit.unit_id,
                                    details={"rows_rejected": normalized.rows_rejected},
                                )
                            )
                        if normalized.rows_normalized:
                            stage_result = publisher.stage_page(
                                stage_run_id=stage_run_id,
                                period=unit.trade_date,
                                repair_ts_code=repair_ts_code,
                                rows=normalized.rows_normalized,
                                page_number=page.page_number,
                                offset=page.offset,
                            )
                            unit_rows_staged_unique += int(
                                stage_result.rows_staged or 0
                            )
                            unit_rows_deduplicated += int(
                                stage_result.rows_deduplicated or 0
                            )
                        unit_rows_deduplicated += int(normalized.rows_deduplicated or 0)
                        completed_page_count += 1
                        if observed_short_page:
                            self._set_paged_unit_active(
                                state=state,
                                unit=unit,
                                unit_index=unit_index,
                                unit_total=total_units,
                                phase="reconciling",
                                current_page_number=page.page_number,
                                completed_page_count=completed_page_count,
                                unit_rows_fetched=unit_rows_fetched,
                                unit_rows_normalized_before_dedupe=unit_rows_normalized_before_dedupe,
                                unit_rows_staged_unique=unit_rows_staged_unique,
                                unit_rows_deduplicated=unit_rows_deduplicated,
                                unit_rows_rejected=unit_rows_rejected,
                                retry_count=retry_count,
                                observed_short_page=True,
                                terminal_page_rows=terminal_page_rows,
                            )
                        else:
                            self._set_paged_unit_active(
                                state=state,
                                unit=unit,
                                unit_index=unit_index,
                                unit_total=total_units,
                                phase="processing_page",
                                current_page_number=page.page_number + 1,
                                completed_page_count=completed_page_count,
                                unit_rows_fetched=unit_rows_fetched,
                                unit_rows_normalized_before_dedupe=unit_rows_normalized_before_dedupe,
                                unit_rows_staged_unique=unit_rows_staged_unique,
                                unit_rows_deduplicated=unit_rows_deduplicated,
                                unit_rows_rejected=unit_rows_rejected,
                                retry_count=retry_count,
                                observed_short_page=False,
                                terminal_page_rows=None,
                            )
                        self._report_paged_unit_progress(
                            request=request,
                            definition=definition,
                            observer=observer,
                            state=state,
                            unit=unit,
                            total_units=total_units,
                            unit_rows_fetched=unit_rows_fetched,
                            unit_rows_rejected=unit_rows_rejected,
                            unit_rows_deduplicated=unit_rows_deduplicated,
                        )
                        if observed_short_page:
                            break
                    if not observed_short_page:
                        raise IngestionError(
                            StructuredError(
                                error_code="pagination_short_page_missing",
                                error_type="source",
                                phase="executor",
                                message="staged-stream 分页未观察到终止短页",
                                retryable=False,
                                unit_id=unit.unit_id,
                            )
                        )
                    self._set_paged_unit_active(
                        state=state,
                        unit=unit,
                        unit_index=unit_index,
                        unit_total=total_units,
                        phase="publishing",
                        current_page_number=page_count,
                        completed_page_count=completed_page_count,
                        unit_rows_fetched=unit_rows_fetched,
                        unit_rows_normalized_before_dedupe=unit_rows_normalized_before_dedupe,
                        unit_rows_staged_unique=unit_rows_staged_unique,
                        unit_rows_deduplicated=unit_rows_deduplicated,
                        unit_rows_rejected=unit_rows_rejected,
                        retry_count=retry_count,
                        observed_short_page=True,
                        terminal_page_rows=terminal_page_rows,
                    )
                    self._report_paged_unit_progress(
                        request=request,
                        definition=definition,
                        observer=observer,
                        state=state,
                        unit=unit,
                        total_units=total_units,
                        unit_rows_fetched=unit_rows_fetched,
                        unit_rows_rejected=unit_rows_rejected,
                        unit_rows_deduplicated=unit_rows_deduplicated,
                    )
                    finalized = publisher.finalize_unit(
                        stage_run_id=stage_run_id,
                        period=unit.trade_date,
                        repair_ts_code=repair_ts_code,
                    )
                    unit_rows_written = int(finalized.rows_source_unique or 0)
                    unit_rows_inserted = int(finalized.rows_inserted or 0)
                    unit_rows_matched = int(finalized.rows_matched or 0)
                    unit_final_scope_count = int(finalized.final_scope_count or 0)
                    state.rows_fetched += unit_rows_fetched
                    state.rows_written += unit_rows_written
                    state.rows_committed += unit_rows_written
                    state.rows_rejected += unit_rows_rejected
                    state.rows_deduplicated += unit_rows_deduplicated
                    state.rows_normalized_before_dedupe += (
                        unit_rows_normalized_before_dedupe
                    )
                    state.rows_inserted += unit_rows_inserted
                    state.rows_matched += unit_rows_matched
                    state.scope_existing_count += unit_rows_matched
                    state.scope_source_unique_count += unit_rows_written
                    state.final_scope_count += unit_final_scope_count
                    state.pagination_unit_count += 1
                    state.pagination_total_page_count += page_count
                    state.pagination_total_retry_count += retry_count
                    state.pagination_total_rows_merged += unit_rows_fetched
                    state.pagination_multi_page_unit_count += int(page_count > 1)
                    state.pagination_max_pages_per_unit = max(state.pagination_max_pages_per_unit, page_count)
                    state.pagination_short_page_unit_count += 1
                    if len(state.pagination_units) < 3:
                        state.pagination_units.append(
                            {
                                "unit_id": unit.unit_id,
                                "page_count": page_count,
                                "retry_count": retry_count,
                                "terminal_offset": terminal_offset,
                                "terminal_page_rows": terminal_page_rows,
                            }
                        )
                    else:
                        state.pagination_units_truncated = True
                    self._complete_paged_unit(
                        state=state,
                        unit=unit,
                        unit_index=unit_index,
                        page_count=page_count,
                        retry_count=retry_count,
                        terminal_page_rows=terminal_page_rows,
                        unit_rows_fetched=unit_rows_fetched,
                        unit_rows_normalized_before_dedupe=unit_rows_normalized_before_dedupe,
                        unit_rows_staged_unique=unit_rows_staged_unique,
                        unit_rows_deduplicated=unit_rows_deduplicated,
                        unit_rows_rejected=unit_rows_rejected,
                        unit_rows_inserted=unit_rows_inserted,
                        unit_rows_matched=unit_rows_matched,
                        unit_rows_committed=unit_rows_written,
                        unit_final_scope_count=unit_final_scope_count,
                    )
                    state.unit_done += 1
                except Exception as exc:
                    self._fail_paged_unit(
                        state=state,
                        exc=exc,
                        current_page_number=(
                            int(state.paged_unit_active.get("current_page_number") or 0)
                            if isinstance(state.paged_unit_active, dict)
                            else None
                        ),
                        completed_page_count=completed_page_count,
                        unit_rows_fetched=unit_rows_fetched,
                        unit_rows_normalized_before_dedupe=unit_rows_normalized_before_dedupe,
                        unit_rows_staged_unique=unit_rows_staged_unique,
                        unit_rows_deduplicated=unit_rows_deduplicated,
                        unit_rows_rejected=unit_rows_rejected,
                        retry_count=retry_count,
                        observed_short_page=observed_short_page,
                        terminal_page_rows=terminal_page_rows
                        if observed_short_page
                        else None,
                    )
                    state.rows_fetched += unit_rows_fetched
                    state.rows_rejected += unit_rows_rejected
                    state.rows_deduplicated += unit_rows_deduplicated
                    state.rows_normalized_before_dedupe += unit_rows_normalized_before_dedupe
                    state.pagination_unit_count += int(page_count > 0)
                    state.pagination_total_page_count += page_count
                    state.pagination_total_retry_count += retry_count
                    state.pagination_total_rows_merged += unit_rows_fetched
                    state.pagination_multi_page_unit_count += int(page_count > 1)
                    state.pagination_max_pages_per_unit = max(state.pagination_max_pages_per_unit, page_count)
                    state.pagination_short_page_unit_count += int(observed_short_page)
                    if page_count > 0 and len(state.pagination_units) < 3:
                        state.pagination_units.append(
                            {
                                "unit_id": unit.unit_id,
                                "page_count": page_count,
                                "retry_count": retry_count,
                                "terminal_offset": terminal_offset,
                                "terminal_page_rows": terminal_page_rows,
                            }
                        )
                    elif page_count > 0:
                        state.pagination_units_truncated = True
                    self._record_unit_exception(state=state, unit=unit, exc=exc)
                finally:
                    self._report_unit_progress(
                        request=request,
                        definition=definition,
                        observer=observer,
                        state=state,
                        unit=unit,
                        total_units=total_units,
                        unit_rows_fetched=unit_rows_fetched,
                        unit_rows_written=unit_rows_written,
                        unit_rows_rejected=unit_rows_rejected,
                        unit_rows_deduplicated=unit_rows_deduplicated,
                    )

    def _run_units_serially(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        units: tuple[PlanUnitSnapshot, ...],
        observer: IngestionObserver,
        state: _RunState,
        cancel_checker,
        eligibility_as_of: date | None,
    ) -> None:  # type: ignore[no-untyped-def]
        total_units = len(units)
        for unit in units:
            self._ensure_not_canceled(cancel_checker=cancel_checker, run_id=request.run_id)
            try:
                source_result = self.source_client.fetch(definition=definition, unit=unit)
            except Exception as exc:
                self._handle_unit_exception(
                    request=request,
                    definition=definition,
                    observer=observer,
                    state=state,
                    unit=unit,
                    total_units=total_units,
                    exc=exc,
                )
                continue
            self._process_fetched_unit(
                request=request,
                definition=definition,
                observer=observer,
                state=state,
                unit=unit,
                total_units=total_units,
                source_result=source_result,
                eligibility_as_of=eligibility_as_of,
            )

    def _run_units_with_concurrent_fetch(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        units: tuple[PlanUnitSnapshot, ...],
        observer: IngestionObserver,
        state: _RunState,
        cancel_checker,
        fetch_concurrency: int,
        eligibility_as_of: date | None,
    ) -> None:  # type: ignore[no-untyped-def]
        total_units = len(units)
        unit_iter = iter(units)
        in_flight: dict[Future, PlanUnitSnapshot] = {}

        def submit_next(executor: ThreadPoolExecutor) -> bool:
            try:
                unit = next(unit_iter)
            except StopIteration:
                return False
            self._ensure_not_canceled(cancel_checker=cancel_checker, run_id=request.run_id)
            future = executor.submit(self.source_client.fetch, definition=definition, unit=unit)
            in_flight[future] = unit
            return True

        with ThreadPoolExecutor(max_workers=fetch_concurrency) as executor:
            for _ in range(min(fetch_concurrency, total_units)):
                submit_next(executor)
            try:
                while in_flight:
                    done, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
                    failed_future = next((future for future in done if future.exception() is not None), None)
                    if failed_future is not None:
                        unit = in_flight.pop(failed_future)
                        for pending_future in in_flight:
                            pending_future.cancel()
                        self._handle_unit_exception(
                            request=request,
                            definition=definition,
                            observer=observer,
                            state=state,
                            unit=unit,
                            total_units=total_units,
                            exc=failed_future.exception(),
                        )
                    for future in done:
                        unit = in_flight.pop(future, None)
                        if unit is None:
                            continue
                        self._process_fetched_unit(
                            request=request,
                            definition=definition,
                            observer=observer,
                            state=state,
                            unit=unit,
                            total_units=total_units,
                            source_result=future.result(),
                            eligibility_as_of=eligibility_as_of,
                        )
                        submit_next(executor)
            except Exception:
                for pending_future in in_flight:
                    pending_future.cancel()
                raise

    def _process_fetched_unit(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        observer: IngestionObserver,
        state: _RunState,
        unit: PlanUnitSnapshot,
        total_units: int,
        source_result,
        eligibility_as_of: date | None,
    ) -> None:  # type: ignore[no-untyped-def]
        unit_rows_fetched = 0
        unit_rows_written = 0
        unit_rows_rejected = 0
        unit_rows_deduplicated = 0
        try:
            self._record_pagination_diagnostics(state, unit=unit, source_result=source_result)
            normalized = self.normalizer.normalize(
                definition=definition,
                fetch_result=source_result,
                expected_unit_date=unit.trade_date,
            )
            self.normalizer.raise_if_all_rejected(normalized)
            if definition.transaction.commit_policy == "raw_then_serving":
                if eligibility_as_of is None:
                    raise RuntimeError("raw_then_serving 缺少固定 eligibility_as_of")
                unit_rows_fetched = len(source_result.rows_raw)
                unit_rows_rejected = normalized.rows_rejected
                unit_rows_deduplicated = int(normalized.rows_deduplicated or 0)
                written = self._write_raw_then_serving(
                    definition=definition,
                    batch=normalized,
                    state=state,
                    eligibility_as_of=eligibility_as_of,
                )
            else:
                written = self.writer.write(
                    definition=definition,
                    batch=normalized,
                    plan_unit=unit,
                    run_profile=request.run_profile,
                )
            unit_rows_fetched = len(source_result.rows_raw)
            unit_rows_written = written.rows_written
            unit_rows_rejected = normalized.rows_rejected + int(written.rows_rejected or 0)
            unit_rows_deduplicated = int(normalized.rows_deduplicated or 0)
            state.rows_fetched += unit_rows_fetched
            state.rows_written += unit_rows_written
            state.rows_rejected += unit_rows_rejected
            state.rows_deduplicated += unit_rows_deduplicated
            state.rows_normalized_before_dedupe += len(normalized.rows_normalized) + unit_rows_deduplicated
            state.rows_inserted += int(written.rows_inserted or 0)
            state.rows_matched += int(written.rows_matched or 0)
            state.scope_existing_count += int(written.scope_existing_count or 0)
            state.scope_source_unique_count += int(written.scope_source_unique_count or 0)
            self._merge_persistence_diagnostics(
                state,
                persistence_diagnostics=written.persistence_diagnostics,
                pagination_diagnostics=getattr(source_result, "pagination_diagnostics", None),
            )
            for reason_code, count in normalized.rejected_reasons.items():
                state.rejected_reason_counts[reason_code] = state.rejected_reason_counts.get(reason_code, 0) + int(count or 0)
            self._merge_reason_samples(state.rejected_reason_samples, normalized.rejected_samples)
            for reason_code, count in written.rejected_reason_counts.items():
                state.rejected_reason_counts[reason_code] = state.rejected_reason_counts.get(reason_code, 0) + int(count or 0)
            self._merge_reason_samples(state.rejected_reason_samples, written.rejected_reason_samples)
            if definition.transaction.commit_policy != "raw_then_serving":
                self.session.commit()
            state.rows_committed += unit_rows_written
            state.unit_done += 1
        except Exception as exc:
            self._record_unit_exception(state=state, unit=unit, exc=exc)
        finally:
            self._report_unit_progress(
                request=request,
                definition=definition,
                observer=observer,
                state=state,
                unit=unit,
                total_units=total_units,
                unit_rows_fetched=unit_rows_fetched,
                unit_rows_written=unit_rows_written,
                unit_rows_rejected=unit_rows_rejected,
                unit_rows_deduplicated=unit_rows_deduplicated,
            )

    def _write_raw_then_serving(
        self,
        *,
        definition: DatasetDefinition,
        batch,
        state: _RunState,
        eligibility_as_of: date,
    ) -> WriteResult:  # type: ignore[no-untyped-def]
        previous_raw = dict(state.persistence_diagnostics.get("raw") or {})
        previous_serving = dict(state.persistence_diagnostics.get("serving") or {})
        previous_excluded = dict(
            state.persistence_diagnostics.get("excluded_reason_counts") or {}
        )
        raw_result = self.writer.write_raw_phase(
            definition=definition,
            batch=batch,
        )
        persistence_diagnostics = {
            "raw": {
                "rows_upserted": int(previous_raw.get("rows_upserted") or 0)
                + raw_result.rows_upserted,
                "committed": False,
            },
            "serving": {
                "eligible_rows": int(previous_serving.get("eligible_rows") or 0),
                "rows_upserted": int(previous_serving.get("rows_upserted") or 0),
                "committed": False,
            },
            "eligibility_as_of": eligibility_as_of.isoformat(),
            "excluded_reason_counts": previous_excluded,
        }
        self._merge_persistence_diagnostics(
            state,
            persistence_diagnostics=persistence_diagnostics,
            pagination_diagnostics=None,
        )
        self.session.commit()
        persistence_diagnostics["raw"]["committed"] = True
        self._merge_persistence_diagnostics(
            state,
            persistence_diagnostics=persistence_diagnostics,
            pagination_diagnostics=None,
        )

        try:
            serving_result = self.writer.write_serving_phase(
                definition=definition,
                batch=batch,
                eligibility_as_of=eligibility_as_of,
            )
        except Exception as exc:
            raise self._fund_daily_serving_publish_error(
                exc=exc,
                batch_unit_id=batch.unit_id,
                persistence_diagnostics=persistence_diagnostics,
            ) from exc

        current_serving = dict(
            serving_result.persistence_diagnostics.get("serving") or {}
        )
        persistence_diagnostics["serving"] = {
            "eligible_rows": int(previous_serving.get("eligible_rows") or 0)
            + int(current_serving.get("eligible_rows") or 0),
            "rows_upserted": int(previous_serving.get("rows_upserted") or 0)
            + int(current_serving.get("rows_upserted") or 0),
            "committed": False,
        }
        current_excluded = dict(
            serving_result.persistence_diagnostics.get("excluded_reason_counts") or {}
        )
        for reason_code, count in current_excluded.items():
            persistence_diagnostics["excluded_reason_counts"][reason_code] = int(
                persistence_diagnostics["excluded_reason_counts"].get(reason_code) or 0
            ) + int(count or 0)
        self._merge_persistence_diagnostics(
            state,
            persistence_diagnostics=persistence_diagnostics,
            pagination_diagnostics=None,
        )
        try:
            self.session.commit()
        except Exception as exc:
            raise self._fund_daily_serving_publish_error(
                exc=exc,
                batch_unit_id=batch.unit_id,
                persistence_diagnostics=persistence_diagnostics,
                failure_phase="serving_commit",
            ) from exc

        persistence_diagnostics["serving"]["committed"] = True
        self._merge_persistence_diagnostics(
            state,
            persistence_diagnostics=persistence_diagnostics,
            pagination_diagnostics=None,
        )
        return replace(
            serving_result,
            persistence_diagnostics=persistence_diagnostics,
        )

    @staticmethod
    def _fund_daily_serving_publish_error(
        *,
        exc: BaseException,
        batch_unit_id: str,
        persistence_diagnostics: dict[str, Any],
        failure_phase: str | None = None,
    ) -> IngestionWriteError:
        source_details: dict[str, Any] = {}
        source_phase = "writer"
        if isinstance(exc, IngestionError):
            source_details = dict(exc.structured_error.details or {})
            source_phase = exc.structured_error.phase
        resolved_failure_phase = str(
            failure_phase or source_details.get("failure_phase") or "serving_publish"
        )
        raw_diagnostics = dict(persistence_diagnostics.get("raw") or {})
        serving_diagnostics = dict(persistence_diagnostics.get("serving") or {})
        details = {
            **source_details,
            "failure_phase": resolved_failure_phase,
            "raw_committed": bool(raw_diagnostics.get("committed")),
            "raw_rows_committed": int(raw_diagnostics.get("rows_upserted") or 0),
            "serving_eligible_rows": int(serving_diagnostics.get("eligible_rows") or 0),
            "serving_rows_upserted": int(serving_diagnostics.get("rows_upserted") or 0),
            "serving_committed": bool(serving_diagnostics.get("committed")),
            "eligibility_as_of": persistence_diagnostics.get("eligibility_as_of"),
            "excluded_reason_counts": dict(
                persistence_diagnostics.get("excluded_reason_counts") or {}
            ),
        }
        return IngestionWriteError(
            StructuredError(
                error_code="fund_daily_serving_publish_failed",
                error_type="write",
                phase=source_phase if failure_phase is None else "executor",
                message=str(exc),
                retryable=False,
                unit_id=batch_unit_id,
                details=details,
            )
        )

    @staticmethod
    def _current_china_date() -> date:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()

    def _handle_unit_exception(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        observer: IngestionObserver,
        state: _RunState,
        unit: PlanUnitSnapshot,
        total_units: int,
        exc: BaseException | None,
    ) -> None:
        error = exc or RuntimeError("unknown ingestion unit failure")
        try:
            self._record_unit_exception(state=state, unit=unit, exc=error)
        finally:
            self._report_unit_progress(
                request=request,
                definition=definition,
                observer=observer,
                state=state,
                unit=unit,
                total_units=total_units,
                unit_rows_fetched=0,
                unit_rows_written=0,
                unit_rows_rejected=0,
                unit_rows_deduplicated=0,
            )

    def _record_unit_exception(self, *, state: _RunState, unit: PlanUnitSnapshot, exc: BaseException) -> None:
        state.unit_failed += 1
        self.session.rollback()
        if isinstance(exc, IngestionCanceledError):
            state.error_counts["ingestion_canceled"] = (
                state.error_counts.get("ingestion_canceled", 0) + 1
            )
            raise exc
        if isinstance(exc, IngestionError):
            error_code = exc.structured_error.error_code
            state.error_counts[error_code] = state.error_counts.get(error_code, 0) + 1
            raise exc
        structured = self.error_mapper.map_exception(exc=exc, phase="executor", unit_id=unit.unit_id)
        state.error_counts[structured.error_code] = state.error_counts.get(structured.error_code, 0) + 1
        raise IngestionError(structured) from exc

    def _report_unit_progress(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        observer: IngestionObserver,
        state: _RunState,
        unit: PlanUnitSnapshot,
        total_units: int,
        unit_rows_fetched: int,
        unit_rows_written: int,
        unit_rows_rejected: int,
        unit_rows_deduplicated: int,
    ) -> None:
        observer.report_progress(
            run_id=request.run_id,
            dataset_key=request.dataset_key,
            unit_total=total_units,
            unit_done=state.unit_done,
            unit_failed=state.unit_failed,
            rows_fetched=state.rows_fetched,
            rows_written=state.rows_written,
            rows_committed=state.rows_committed,
            rows_rejected=state.rows_rejected,
            rows_deduplicated=state.rows_deduplicated,
            ingestion_diagnostics=self._build_ingestion_diagnostics(state),
            rejected_reason_counts=state.rejected_reason_counts,
            rejected_reason_samples=state.rejected_reason_samples,
            current_object=self._build_current_object(unit),
            message=self._build_progress_message(
                progress_label=definition.observability.progress_label,
                current=state.unit_done + state.unit_failed,
                total=total_units,
                rows_fetched=state.rows_fetched,
                rows_written=state.rows_written,
                rows_committed=state.rows_committed,
                rows_rejected=state.rows_rejected,
                unit=unit,
                unit_rows_fetched=unit_rows_fetched,
                unit_rows_written=unit_rows_written,
                unit_rows_committed=unit_rows_written,
                unit_rows_rejected=unit_rows_rejected,
                unit_rows_deduplicated=unit_rows_deduplicated,
                rejected_reason_counts=state.rejected_reason_counts,
            ),
        )

    @staticmethod
    def _set_paged_unit_active(
        *,
        state: _RunState,
        unit: PlanUnitSnapshot,
        unit_index: int,
        unit_total: int,
        phase: str,
        current_page_number: int | None,
        completed_page_count: int,
        unit_rows_fetched: int,
        unit_rows_normalized_before_dedupe: int,
        unit_rows_staged_unique: int,
        unit_rows_deduplicated: int,
        unit_rows_rejected: int,
        retry_count: int,
        observed_short_page: bool,
        terminal_page_rows: int | None,
    ) -> None:
        state.paged_unit_active = {
            "unit_id": unit.unit_id,
            "unit_index": unit_index,
            "unit_total": unit_total,
            "time": {
                "field": "end_date",
                "point": unit.trade_date.isoformat()
                if unit.trade_date is not None
                else None,
            },
            "phase": phase,
            "current_page_number": current_page_number,
            "completed_page_count": completed_page_count,
            "page_limit": unit.page_limit,
            "unit_rows_fetched": unit_rows_fetched,
            "unit_rows_normalized_before_dedupe": unit_rows_normalized_before_dedupe,
            "unit_rows_staged_unique": unit_rows_staged_unique,
            "unit_rows_deduplicated": unit_rows_deduplicated,
            "unit_rows_rejected": unit_rows_rejected,
            "retry_count": retry_count,
            "observed_short_page": observed_short_page,
            "terminal_page_rows": terminal_page_rows,
        }

    @staticmethod
    def _fail_paged_unit(
        *,
        state: _RunState,
        exc: BaseException,
        current_page_number: int | None,
        completed_page_count: int,
        unit_rows_fetched: int,
        unit_rows_normalized_before_dedupe: int,
        unit_rows_staged_unique: int,
        unit_rows_deduplicated: int,
        unit_rows_rejected: int,
        retry_count: int,
        observed_short_page: bool,
        terminal_page_rows: int | None,
    ) -> None:
        if not isinstance(state.paged_unit_active, dict):
            return
        state.paged_unit_active.update(
            {
                "phase": "canceled"
                if isinstance(exc, IngestionCanceledError)
                else "failed",
                "current_page_number": current_page_number,
                "completed_page_count": completed_page_count,
                "unit_rows_fetched": unit_rows_fetched,
                "unit_rows_normalized_before_dedupe": unit_rows_normalized_before_dedupe,
                "unit_rows_staged_unique": unit_rows_staged_unique,
                "unit_rows_deduplicated": unit_rows_deduplicated,
                "unit_rows_rejected": unit_rows_rejected,
                "retry_count": retry_count,
                "observed_short_page": observed_short_page,
                "terminal_page_rows": terminal_page_rows,
            }
        )

    def _complete_paged_unit(
        self,
        *,
        state: _RunState,
        unit: PlanUnitSnapshot,
        unit_index: int,
        page_count: int,
        retry_count: int,
        terminal_page_rows: int,
        unit_rows_fetched: int,
        unit_rows_normalized_before_dedupe: int,
        unit_rows_staged_unique: int,
        unit_rows_deduplicated: int,
        unit_rows_rejected: int,
        unit_rows_inserted: int,
        unit_rows_matched: int,
        unit_rows_committed: int,
        unit_final_scope_count: int,
    ) -> None:
        result = {
            "unit_id": unit.unit_id,
            "unit_index": unit_index,
            "time": {
                "field": "end_date",
                "point": unit.trade_date.isoformat()
                if unit.trade_date is not None
                else None,
            },
            "page_count": page_count,
            "retry_count": retry_count,
            "terminal_page_rows": terminal_page_rows,
            "observed_short_page": True,
            "rows_fetched": unit_rows_fetched,
            "rows_normalized_before_dedupe": unit_rows_normalized_before_dedupe,
            "rows_staged_unique": unit_rows_staged_unique,
            "rows_deduplicated": unit_rows_deduplicated,
            "rows_rejected": unit_rows_rejected,
            "rows_inserted_new": unit_rows_inserted,
            "rows_matched_existing": unit_rows_matched,
            "rows_committed": unit_rows_committed,
            "final_scope_count": unit_final_scope_count,
        }
        if len(state.paged_unit_completed) < self.MAX_PAGED_UNIT_RESULTS:
            state.paged_unit_completed.append(result)
        else:
            state.paged_unit_completed_truncated = True
        state.paged_unit_active = None

    def _report_paged_unit_progress(
        self,
        *,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        observer: IngestionObserver,
        state: _RunState,
        unit: PlanUnitSnapshot,
        total_units: int,
        unit_rows_fetched: int,
        unit_rows_rejected: int,
        unit_rows_deduplicated: int,
    ) -> None:
        rows_fetched = state.rows_fetched + unit_rows_fetched
        rows_rejected = state.rows_rejected + unit_rows_rejected
        rows_deduplicated = state.rows_deduplicated + unit_rows_deduplicated
        observer.report_progress(
            run_id=request.run_id,
            dataset_key=request.dataset_key,
            unit_total=total_units,
            unit_done=state.unit_done,
            unit_failed=state.unit_failed,
            rows_fetched=rows_fetched,
            rows_written=state.rows_written,
            rows_committed=state.rows_committed,
            rows_rejected=rows_rejected,
            rows_deduplicated=rows_deduplicated,
            ingestion_diagnostics=self._build_ingestion_diagnostics(state),
            rejected_reason_counts=state.rejected_reason_counts,
            rejected_reason_samples=state.rejected_reason_samples,
            current_object=self._build_current_object(unit),
            message=self._build_progress_message(
                progress_label=definition.observability.progress_label,
                current=state.unit_done + state.unit_failed,
                total=total_units,
                rows_fetched=rows_fetched,
                rows_written=state.rows_written,
                rows_committed=state.rows_committed,
                rows_rejected=rows_rejected,
                unit=unit,
                unit_rows_fetched=unit_rows_fetched,
                unit_rows_written=0,
                unit_rows_committed=0,
                unit_rows_rejected=unit_rows_rejected,
                unit_rows_deduplicated=unit_rows_deduplicated,
                rejected_reason_counts=state.rejected_reason_counts,
            ),
        )

    @staticmethod
    def _merge_reason_samples(
        target: dict[str, list[dict[str, Any]]],
        source: dict[str, list[dict[str, Any]]] | None,
        *,
        max_samples_per_reason: int = 3,
    ) -> None:
        if not isinstance(source, dict):
            return
        for raw_key, raw_samples in source.items():
            key = str(raw_key or "").strip()
            if not key or not isinstance(raw_samples, list):
                continue
            bucket = target.setdefault(key, [])
            for sample in raw_samples:
                if len(bucket) >= max_samples_per_reason:
                    break
                if isinstance(sample, dict):
                    bucket.append(dict(sample))

    @staticmethod
    def _resolve_result_date(request: ValidatedDatasetActionRequest) -> date | None:
        if request.run_profile == "point_incremental":
            return request.trade_date
        if request.run_profile == "range_rebuild":
            return request.end_date
        return None

    @staticmethod
    def _ensure_not_canceled(*, cancel_checker, run_id: int | None) -> None:  # type: ignore[no-untyped-def]
        if run_id is None or cancel_checker is None:
            return
        if cancel_checker(run_id):
            raise IngestionCanceledError("任务已收到停止请求，正在结束处理。")

    @classmethod
    def _build_progress_message(
        cls,
        *,
        progress_label: str,
        current: int,
        total: int,
        rows_fetched: int,
        rows_written: int,
        rows_committed: int | None,
        rows_rejected: int,
        rejected_reason_counts: dict[str, int],
        unit: PlanUnitSnapshot | None = None,
        unit_rows_fetched: int | None = None,
        unit_rows_written: int | None = None,
        unit_rows_committed: int | None = None,
        unit_rows_rejected: int | None = None,
        unit_rows_deduplicated: int | None = None,
    ) -> str:
        context_parts = cls._build_progress_context_parts(
            unit=unit,
        )
        unit_metric_parts = cls._build_progress_unit_metric_parts(
            unit_rows_fetched=unit_rows_fetched,
            unit_rows_written=unit_rows_written,
            unit_rows_committed=unit_rows_committed,
            unit_rows_rejected=unit_rows_rejected,
            unit_rows_deduplicated=unit_rows_deduplicated,
        )
        saved_rows = rows_committed if rows_committed is not None else rows_written
        message_parts = [
            f"{progress_label}：{current}/{total}",
            f"累计读取 {rows_fetched}",
            f"累计保存 {saved_rows}",
            f"累计拒绝 {rows_rejected}",
        ]
        if context_parts or unit_metric_parts:
            unit_parts = [*context_parts, *unit_metric_parts]
            message_parts.insert(1, f"本单元：{'，'.join(unit_parts)}")
        normalized_counts = cls._normalize_reason_counts(rejected_reason_counts)
        if not normalized_counts:
            return "；".join(message_parts)
        encoded, truncated = cls._encode_reason_counts(normalized_counts, max_items=cls.MAX_REASON_BUCKETS)
        if encoded:
            message_parts.append(f"拒绝原因：{encoded}")
        if truncated:
            message_parts.append("拒绝原因已截断")
        return "；".join(message_parts)

    @staticmethod
    def _normalize_reason_counts(reason_counts: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for reason_code, raw_count in reason_counts.items():
            code = str(reason_code or "").strip()
            if not code:
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            normalized[code] = count
        return normalized

    @staticmethod
    def _encode_reason_counts(reason_counts: dict[str, int], *, max_items: int) -> tuple[str, bool]:
        ordered = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        truncated = len(ordered) > max_items
        limited = ordered[:max_items]
        encoded = "、".join(f"{reason_code} {count}" for reason_code, count in limited)
        return encoded, truncated

    @classmethod
    def _build_progress_context_parts(
        cls,
        *,
        unit: PlanUnitSnapshot | None,
    ) -> list[str]:
        if unit is None:
            return []
        context = dict(unit.progress_context or {})
        parts: list[str] = []
        unit_label = cls._format_progress_value(context.get("unit"))
        if unit_label:
            parts.append(f"单元 {unit_label}")
        security_code = cls._format_progress_value(context.get("ts_code"))
        security_name = cls._format_progress_value(context.get("security_name"))
        if security_name and security_code:
            parts.append(f"证券 {security_name}（{security_code}）")
        elif security_name or security_code:
            parts.append(f"证券 {security_name or security_code}")
        index_code = cls._format_progress_value(context.get("index_code"))
        index_name = cls._format_progress_value(context.get("index_name"))
        if index_name and index_code:
            parts.append(f"指数 {index_name}（{index_code}）")
        elif index_name or index_code:
            parts.append(f"指数 {index_name or index_code}")
        board_code = cls._format_progress_value(context.get("board_code"))
        board_name = cls._format_progress_value(context.get("board_name"))
        if board_name and board_code:
            parts.append(f"板块 {board_name}（{board_code}）")
        elif board_name or board_code:
            parts.append(f"板块 {board_name or board_code}")
        trade_date = cls._format_progress_value(context.get("trade_date"))
        if trade_date:
            parts.append(f"日期 {trade_date}")
        date_field = cls._format_progress_value(context.get("date_field"))
        if date_field and date_field != "trade_date":
            observed_date = cls._format_progress_value(context.get(date_field))
            if observed_date:
                parts.append(f"日期 {observed_date}")
        freq = cls._format_progress_value(context.get("freq"))
        if freq:
            parts.append(f"频率 {freq}")
        start_date = cls._format_progress_value(context.get("start_date"))
        end_date = None if date_field == "end_date" else cls._format_progress_value(context.get("end_date"))
        if start_date or end_date:
            parts.append(cls._range_context_part(start_date=start_date, end_date=end_date))
        enum_field = cls._format_progress_value(context.get("enum_field"))
        enum_value = cls._format_progress_value(context.get("enum_value"))
        if enum_field and enum_value:
            parts.append(f"{enum_field} {enum_value}")
        elif enum_value:
            parts.append(f"类型 {enum_value}")
        return parts

    @staticmethod
    def _build_progress_unit_metric_parts(
        *,
        unit_rows_fetched: int | None,
        unit_rows_written: int | None,
        unit_rows_committed: int | None,
        unit_rows_rejected: int | None,
        unit_rows_deduplicated: int | None = None,
    ) -> list[str]:
        parts: list[str] = []
        if unit_rows_fetched is not None:
            parts.append(f"读取 {int(unit_rows_fetched or 0)}")
        unit_rows_saved = unit_rows_committed if unit_rows_committed is not None else unit_rows_written
        if unit_rows_saved is not None:
            parts.append(f"保存 {int(unit_rows_saved or 0)}")
        if unit_rows_rejected is not None and unit_rows_rejected > 0:
            parts.append(f"拒绝 {int(unit_rows_rejected or 0)}")
        if unit_rows_deduplicated is not None and unit_rows_deduplicated > 0:
            parts.append(f"完全重复去重 {int(unit_rows_deduplicated or 0)}")
        return parts

    @staticmethod
    def _record_pagination_diagnostics(state: _RunState, *, unit: PlanUnitSnapshot, source_result: Any) -> None:
        diagnostics = getattr(source_result, "pagination_diagnostics", None)
        if not isinstance(diagnostics, dict) or not diagnostics:
            return
        page_count = max(int(diagnostics.get("page_count") or 0), 0)
        rows_merged = max(int(diagnostics.get("total_rows_merged") or 0), 0)
        state.pagination_unit_count += 1
        state.pagination_total_page_count += page_count
        state.pagination_total_retry_count += max(int(getattr(source_result, "retry_count", 0) or 0), 0)
        state.pagination_total_rows_merged += rows_merged
        state.pagination_multi_page_unit_count += int(page_count > 1)
        state.pagination_max_pages_per_unit = max(state.pagination_max_pages_per_unit, page_count)
        state.pagination_short_page_unit_count += int(bool(diagnostics.get("observed_short_page")))
        if len(state.pagination_units) >= 3:
            state.pagination_units_truncated = True
            return
        unit_diagnostics = {
            "unit_id": unit.unit_id,
            "page_count": page_count,
            "terminal_offset": diagnostics.get("terminal_offset"),
            "terminal_page_rows": diagnostics.get("terminal_page_rows"),
        }
        if diagnostics.get("request_variants"):
            unit_diagnostics["request_variants"] = list(diagnostics["request_variants"])
        state.pagination_units.append(unit_diagnostics)

    @staticmethod
    def _merge_persistence_diagnostics(
        state: _RunState,
        *,
        persistence_diagnostics: dict[str, Any] | None,
        pagination_diagnostics: dict[str, Any] | None,
    ) -> None:
        if not isinstance(persistence_diagnostics, dict) or not persistence_diagnostics:
            return
        normalized = {
            str(key): dict(value) if isinstance(value, dict) else value
            for key, value in persistence_diagnostics.items()
        }
        snapshot = normalized.get("etf_basic_snapshot")
        if isinstance(snapshot, dict) and isinstance(pagination_diagnostics, dict):
            snapshot["pagination"] = {
                "page_count": max(int(pagination_diagnostics.get("page_count") or 0), 0),
                "terminal_offset": pagination_diagnostics.get("terminal_offset"),
                "terminal_page_rows": max(
                    int(pagination_diagnostics.get("terminal_page_rows") or 0),
                    0,
                ),
                "observed_short_page": bool(
                    pagination_diagnostics.get("observed_short_page")
                ),
            }
        state.persistence_diagnostics.update(normalized)

    @staticmethod
    def _build_ingestion_diagnostics(state: _RunState) -> dict[str, Any]:
        persistence = {
            "immutable_fact": {
                "rows_normalized_before_dedupe": state.rows_normalized_before_dedupe,
                "rows_inserted_new": state.rows_inserted,
                "rows_matched_existing": state.rows_matched,
                "scope_existing_count": state.scope_existing_count,
                "scope_source_unique_count": state.scope_source_unique_count,
                "final_scope_count": state.final_scope_count,
            },
            **state.persistence_diagnostics,
        }
        diagnostics = {
            "source": {
                "pagination": {
                    "unit_count_with_pagination": state.pagination_unit_count,
                    "total_page_count": state.pagination_total_page_count,
                    "total_retry_count": state.pagination_total_retry_count,
                    "total_rows_merged": state.pagination_total_rows_merged,
                    "multi_page_unit_count": state.pagination_multi_page_unit_count,
                    "max_pages_per_unit": state.pagination_max_pages_per_unit,
                    "short_page_unit_count": state.pagination_short_page_unit_count,
                    "unit_samples": [dict(item) for item in state.pagination_units],
                    "truncated": state.pagination_units_truncated,
                },
            },
            "persistence": persistence,
        }
        if state.paged_unit_active is not None or state.paged_unit_completed:
            diagnostics["runtime"] = {
                "paged_unit": {
                    "active": dict(state.paged_unit_active)
                    if state.paged_unit_active is not None
                    else None,
                    "completed": [dict(item) for item in state.paged_unit_completed],
                    "completed_truncated": state.paged_unit_completed_truncated,
                }
            }
        return diagnostics

    @staticmethod
    def _format_progress_value(value) -> str | None:  # type: ignore[no-untyped-def]
        if value in (None, ""):
            return None
        text = " ".join(str(value).strip().split())
        return text or None

    @staticmethod
    def _range_context_part(*, start_date: str | None, end_date: str | None) -> str:
        if start_date and end_date:
            return f"范围 {start_date}" if start_date == end_date else f"范围 {start_date} ~ {end_date}"
        if start_date:
            return f"范围从 {start_date} 开始"
        return f"范围截至 {end_date}"

    @classmethod
    def _build_current_object(cls, unit: PlanUnitSnapshot) -> dict:
        context = dict(unit.progress_context or {})
        request_params = dict(unit.request_params or {})
        date_field = str(context.get("date_field") or "trade_date")
        if unit.trade_date is not None and date_field not in context:
            context[date_field] = unit.trade_date.isoformat()
        for key in ("ts_code", "index_code", "board_code", "freq", "start_date", "end_date"):
            value = request_params.get(key)
            if value not in (None, "") and key not in context:
                context[key] = value
        if not context:
            return {}
        entity = cls._build_current_entity(context)
        time_scope = cls._build_current_time(context)
        attributes = {key: str(context[key]).strip() for key in ("freq", "enum_field", "enum_value", "unit") if context.get(key) not in (None, "")}
        return {
            "entity": entity,
            "time": time_scope,
            "attributes": attributes,
        }

    @staticmethod
    def _build_current_entity(context: dict[str, object]) -> dict[str, str]:
        if context.get("security_name") not in (None, "") or context.get("ts_code") not in (None, ""):
            return {
                "label": str(context.get("security_name") or context.get("ts_code") or "").strip(),
                "code": str(context.get("ts_code") or "").strip(),
                "kind": "security",
            }
        if context.get("index_name") not in (None, "") or context.get("index_code") not in (None, ""):
            return {
                "label": str(context.get("index_name") or context.get("index_code") or "").strip(),
                "code": str(context.get("index_code") or "").strip(),
                "kind": "index",
            }
        if context.get("board_name") not in (None, "") or context.get("board_code") not in (None, ""):
            return {
                "label": str(context.get("board_name") or context.get("board_code") or "").strip(),
                "code": str(context.get("board_code") or "").strip(),
                "kind": "board",
            }
        return {}

    @staticmethod
    def _build_current_time(context: dict[str, object]) -> dict[str, str]:
        if context.get("start_date") not in (None, "") or context.get("end_date") not in (None, ""):
            return {
                "start": str(context.get("start_date") or "").strip(),
                "end": str(context.get("end_date") or "").strip(),
                "mode": "range",
                "field": str(context.get("date_field") or "trade_date"),
            }
        date_field = str(context.get("date_field") or "trade_date")
        if context.get(date_field) not in (None, ""):
            point_date = str(context.get(date_field) or "").strip()
            return {"start": point_date, "end": point_date, "mode": "point", "field": date_field}
        return {}
