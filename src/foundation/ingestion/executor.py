from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.error_mapper import IngestionErrorMapper
from src.foundation.ingestion.errors import IngestionError
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.progress import IngestionObserver
from src.foundation.ingestion.source_client import DatasetSourceClient
from src.foundation.ingestion.writer import DatasetWriter


@dataclass(slots=True)
class _RunState:
    rows_fetched: int = 0
    rows_written: int = 0
    rows_committed: int = 0
    rows_rejected: int = 0
    rows_deduplicated: int = 0
    rows_inserted: int = 0
    rows_matched: int = 0
    scope_existing_count: int = 0
    scope_source_unique_count: int = 0
    pagination_unit_count: int = 0
    pagination_total_page_count: int = 0
    pagination_total_rows_merged: int = 0
    pagination_multi_page_unit_count: int = 0
    pagination_max_pages_per_unit: int = 0
    pagination_short_page_unit_count: int = 0
    pagination_units: list[dict[str, Any]] = field(default_factory=list)
    pagination_units_truncated: bool = False
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)
    rejected_reason_samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
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

        total_units = len(units)
        fetch_concurrency = definition.planning.fetch_concurrency
        if fetch_concurrency <= 1 or total_units <= 1:
            self._run_units_serially(
                request=request,
                definition=definition,
                units=units,
                observer=observer,
                state=state,
                cancel_checker=cancel_checker,
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

    def _run_units_serially(
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
            state.rows_inserted += int(written.rows_inserted or 0)
            state.rows_matched += int(written.rows_matched or 0)
            state.scope_existing_count += int(written.scope_existing_count or 0)
            state.scope_source_unique_count += int(written.scope_source_unique_count or 0)
            for reason_code, count in normalized.rejected_reasons.items():
                state.rejected_reason_counts[reason_code] = state.rejected_reason_counts.get(reason_code, 0) + int(count or 0)
            self._merge_reason_samples(state.rejected_reason_samples, normalized.rejected_samples)
            for reason_code, count in written.rejected_reason_counts.items():
                state.rejected_reason_counts[reason_code] = state.rejected_reason_counts.get(reason_code, 0) + int(count or 0)
            self._merge_reason_samples(state.rejected_reason_samples, written.rejected_reason_samples)
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
        freq = cls._format_progress_value(context.get("freq"))
        if freq:
            parts.append(f"频率 {freq}")
        start_date = cls._format_progress_value(context.get("start_date"))
        end_date = cls._format_progress_value(context.get("end_date"))
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
        state.pagination_total_rows_merged += rows_merged
        state.pagination_multi_page_unit_count += int(page_count > 1)
        state.pagination_max_pages_per_unit = max(state.pagination_max_pages_per_unit, page_count)
        state.pagination_short_page_unit_count += int(bool(diagnostics.get("observed_short_page")))
        if len(state.pagination_units) >= 3:
            state.pagination_units_truncated = True
            return
        state.pagination_units.append(
            {
                "unit_id": unit.unit_id,
                "page_count": page_count,
                "terminal_offset": diagnostics.get("terminal_offset"),
                "terminal_page_rows": diagnostics.get("terminal_page_rows"),
            }
        )

    @staticmethod
    def _build_ingestion_diagnostics(state: _RunState) -> dict[str, Any]:
        return {
            "source": {
                "pagination": {
                    "unit_count_with_pagination": state.pagination_unit_count,
                    "total_page_count": state.pagination_total_page_count,
                    "total_rows_merged": state.pagination_total_rows_merged,
                    "multi_page_unit_count": state.pagination_multi_page_unit_count,
                    "max_pages_per_unit": state.pagination_max_pages_per_unit,
                    "short_page_unit_count": state.pagination_short_page_unit_count,
                    "unit_samples": [dict(item) for item in state.pagination_units],
                    "truncated": state.pagination_units_truncated,
                },
            },
            "persistence": {
                "immutable_fact": {
                    "rows_inserted_new": state.rows_inserted,
                    "rows_matched_existing": state.rows_matched,
                    "scope_existing_count": state.scope_existing_count,
                    "scope_source_unique_count": state.scope_source_unique_count,
                },
            },
        }

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
