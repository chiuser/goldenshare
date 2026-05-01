from __future__ import annotations

from datetime import date

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.error_mapper import IngestionErrorMapper
from src.foundation.ingestion.errors import IngestionError, StructuredError
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.progress import IngestionObserver
from src.foundation.ingestion.source_client import DatasetSourceClient
from src.foundation.ingestion.writer import DatasetWriter


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
        rejected_reason_counts: dict[str, int],
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
        self.rejected_reason_counts = rejected_reason_counts
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

        rows_fetched = 0
        rows_written = 0
        rows_committed = 0
        rows_rejected = 0
        rejected_reason_counts: dict[str, int] = {}
        unit_done = 0
        unit_failed = 0
        error_counts: dict[str, int] = {}

        total_units = len(units)
        for index, unit in enumerate(units, start=1):
            self._ensure_not_canceled(cancel_checker=cancel_checker, run_id=request.run_id)
            unit_rows_fetched = 0
            unit_rows_written = 0
            unit_rows_rejected = 0
            try:
                fetched = self.source_client.fetch(definition=definition, unit=unit)
                normalized = self.normalizer.normalize(definition=definition, fetch_result=fetched)
                self.normalizer.raise_if_all_rejected(normalized)
                written = self.writer.write(
                    definition=definition,
                    batch=normalized,
                    plan_unit=unit,
                    run_profile=request.run_profile,
                )
                unit_rows_fetched = len(fetched.rows_raw)
                unit_rows_written = written.rows_written
                unit_rows_rejected = normalized.rows_rejected + int(written.rows_rejected or 0)
                rows_fetched += unit_rows_fetched
                rows_written += unit_rows_written
                rows_rejected += unit_rows_rejected
                for reason_code, count in normalized.rejected_reasons.items():
                    rejected_reason_counts[reason_code] = rejected_reason_counts.get(reason_code, 0) + int(count or 0)
                for reason_code, count in written.rejected_reason_counts.items():
                    rejected_reason_counts[reason_code] = rejected_reason_counts.get(reason_code, 0) + int(count or 0)
                self.session.commit()
                rows_committed += unit_rows_written
                unit_done += 1
            except IngestionError as exc:
                unit_failed += 1
                self.session.rollback()
                error_code = exc.structured_error.error_code
                error_counts[error_code] = error_counts.get(error_code, 0) + 1
                raise
            except Exception as exc:
                unit_failed += 1
                self.session.rollback()
                structured = self.error_mapper.map_exception(exc=exc, phase="executor", unit_id=unit.unit_id)
                error_counts[structured.error_code] = error_counts.get(structured.error_code, 0) + 1
                raise IngestionError(structured) from exc
            finally:
                observer.report_progress(
                    run_id=request.run_id,
                    dataset_key=request.dataset_key,
                    unit_total=total_units,
                    unit_done=unit_done,
                    unit_failed=unit_failed,
                    rows_fetched=rows_fetched,
                    rows_written=rows_written,
                    rows_committed=rows_committed,
                    rows_rejected=rows_rejected,
                    rejected_reason_counts=rejected_reason_counts,
                    current_object=self._build_current_object(unit),
                    message=self._build_progress_message(
                        progress_label=definition.observability.progress_label,
                        current=index,
                        total=total_units,
                        rows_fetched=rows_fetched,
                        rows_written=rows_written,
                        rows_committed=rows_committed,
                        rows_rejected=rows_rejected,
                        unit=unit,
                        unit_rows_fetched=unit_rows_fetched,
                        unit_rows_written=unit_rows_written,
                        unit_rows_committed=unit_rows_written,
                        unit_rows_rejected=unit_rows_rejected,
                        rejected_reason_counts=rejected_reason_counts,
                    ),
                )

        return IngestionRunSummary(
            dataset_key=request.dataset_key,
            run_profile=request.run_profile,
            unit_total=total_units,
            unit_done=unit_done,
            unit_failed=unit_failed,
            rows_fetched=rows_fetched,
            rows_written=rows_written,
            rows_committed=rows_committed,
            rows_rejected=rows_rejected,
            rejected_reason_counts=rejected_reason_counts,
            result_date=self._resolve_result_date(request),
            message=f"共 {total_units} 个单元，成功 {unit_done} 个，失败 {unit_failed} 个",
            error_counts=error_counts,
        )

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
    ) -> str:
        context_parts = cls._build_progress_context_parts(
            unit=unit,
        )
        unit_metric_parts = cls._build_progress_unit_metric_parts(
            unit_rows_fetched=unit_rows_fetched,
            unit_rows_written=unit_rows_written,
            unit_rows_committed=unit_rows_committed,
            unit_rows_rejected=unit_rows_rejected,
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
    ) -> list[str]:
        parts: list[str] = []
        if unit_rows_fetched is not None:
            parts.append(f"读取 {int(unit_rows_fetched or 0)}")
        unit_rows_saved = unit_rows_committed if unit_rows_committed is not None else unit_rows_written
        if unit_rows_saved is not None:
            parts.append(f"保存 {int(unit_rows_saved or 0)}")
        if unit_rows_rejected is not None and unit_rows_rejected > 0:
            parts.append(f"拒绝 {int(unit_rows_rejected or 0)}")
        return parts

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
        if unit.trade_date is not None and "trade_date" not in context:
            context["trade_date"] = unit.trade_date.isoformat()
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
            }
        if context.get("trade_date") not in (None, ""):
            trade_date = str(context.get("trade_date") or "").strip()
            return {"start": trade_date, "end": trade_date, "mode": "point"}
        return {}
