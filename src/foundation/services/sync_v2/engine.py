from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.foundation.services.sync_v2.execution_errors import ExecutionCanceledError
from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    EngineRunSummary,
    PlanUnit,
    RunRequest,
)
from src.foundation.services.sync_v2.error_mapper import SyncV2ErrorMapper
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2Error
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.observer import SyncV2Observer
from src.foundation.services.sync_v2.planner import SyncV2Planner
from src.foundation.services.sync_v2.runtime_contract import to_runtime_contract
from src.foundation.services.sync_v2.validator import ContractValidator
from src.foundation.services.sync_v2.worker_client import SyncV2WorkerClient
from src.foundation.services.sync_v2.writer import SyncV2Writer


class SyncV2Engine:
    MAX_REASON_BUCKETS = 3

    def __init__(self, session: Session) -> None:
        self.session = session
        self.validator = ContractValidator()
        self.planner = SyncV2Planner(session)
        self.worker = SyncV2WorkerClient()
        self.normalizer = SyncV2Normalizer()
        self.writer = SyncV2Writer(session)
        self.error_mapper = SyncV2ErrorMapper()

    def run(
        self,
        *,
        request: RunRequest,
        contract: DatasetSyncContract,
        strict_contract: bool,
        units_override: tuple[PlanUnit, ...] | None = None,
        cancel_checker=None,  # type: ignore[no-untyped-def]
        progress_reporter=None,  # type: ignore[no-untyped-def]
    ) -> EngineRunSummary:
        validated = self.validator.validate(request=request, contract=contract, strict=strict_contract)
        if units_override is not None:
            units = units_override
        else:
            runtime_contract = to_runtime_contract(contract)
            if runtime_contract.strategy_fn is not None:
                units = runtime_contract.strategy_fn(
                    validated,
                    contract,
                    self.planner.dao,
                    self.planner.settings,
                    self.session,
                )
            else:
                units = self.planner.plan(validated, contract)
        observer = SyncV2Observer(progress_reporter=progress_reporter)

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
            self._ensure_not_canceled(cancel_checker=cancel_checker, execution_id=validated.execution_id)
            unit_rows_fetched = 0
            unit_rows_written = 0
            unit_rows_rejected = 0
            try:
                fetched = self.worker.fetch(contract=contract, unit=unit)
                normalized = self.normalizer.normalize(contract=contract, fetch_result=fetched)
                self.normalizer.raise_if_all_rejected(normalized)
                written = self.writer.write(
                    contract=contract,
                    batch=normalized,
                    plan_unit=unit,
                    run_profile=validated.run_profile,
                )
                unit_rows_fetched = len(fetched.rows_raw)
                unit_rows_written = written.rows_written
                unit_rows_rejected = normalized.rows_rejected
                rows_fetched += unit_rows_fetched
                rows_written += unit_rows_written
                rows_rejected += unit_rows_rejected
                for reason_code, count in normalized.rejected_reasons.items():
                    rejected_reason_counts[reason_code] = rejected_reason_counts.get(reason_code, 0) + int(count or 0)
                if contract.transaction_spec.commit_policy == "unit":
                    self.session.commit()
                    rows_committed += unit_rows_written
                unit_done += 1
            except SyncV2Error as exc:
                unit_failed += 1
                if contract.transaction_spec.commit_policy == "unit":
                    self.session.rollback()
                error_code = exc.structured_error.error_code
                error_counts[error_code] = error_counts.get(error_code, 0) + 1
                raise
            except Exception as exc:
                unit_failed += 1
                if contract.transaction_spec.commit_policy == "unit":
                    self.session.rollback()
                structured = self.error_mapper.map_exception(exc=exc, phase="engine", unit_id=unit.unit_id)
                error_counts[structured.error_code] = error_counts.get(structured.error_code, 0) + 1
                raise SyncV2Error(structured) from exc
            finally:
                observer.report_progress(
                    execution_id=validated.execution_id,
                    dataset_key=validated.dataset_key,
                    unit_total=total_units,
                    unit_done=unit_done,
                    unit_failed=unit_failed,
                    rows_fetched=rows_fetched,
                    rows_written=rows_written,
                    rows_committed=rows_committed,
                    rows_rejected=rows_rejected,
                    current_object=self._build_current_object(unit),
                    rejected_reason_counts=rejected_reason_counts,
                    message=self._build_progress_message(
                        progress_label=contract.observe_spec.progress_label,
                        current=index,
                        total=total_units,
                        rows_fetched=rows_fetched,
                        rows_written=rows_written,
                        rows_committed=rows_committed if contract.transaction_spec.commit_policy == "unit" else None,
                        rows_rejected=rows_rejected,
                        unit=unit,
                        unit_rows_fetched=unit_rows_fetched,
                        unit_rows_written=unit_rows_written,
                        unit_rows_committed=unit_rows_written if contract.transaction_spec.commit_policy == "unit" else None,
                        unit_rows_rejected=unit_rows_rejected,
                        rejected_reason_counts=rejected_reason_counts,
                    ),
                )

        return EngineRunSummary(
            dataset_key=validated.dataset_key,
            run_profile=validated.run_profile,
            unit_total=total_units,
            unit_done=unit_done,
            unit_failed=unit_failed,
            rows_fetched=rows_fetched,
            rows_written=rows_written,
            rows_committed=rows_committed,
            rows_rejected=rows_rejected,
            rejected_reason_counts=rejected_reason_counts,
            result_date=self._resolve_result_date(validated),
            message=f"units={total_units} done={unit_done} failed={unit_failed}",
            error_counts=error_counts,
        )

    @staticmethod
    def _resolve_result_date(validated) -> date | None:  # type: ignore[no-untyped-def]
        if validated.run_profile == "point_incremental":
            return validated.trade_date
        if validated.run_profile == "range_rebuild":
            return validated.end_date
        return None

    @staticmethod
    def _ensure_not_canceled(*, cancel_checker, execution_id: int | None) -> None:  # type: ignore[no-untyped-def]
        if execution_id is None or cancel_checker is None:
            return
        if cancel_checker(execution_id):
            raise ExecutionCanceledError("任务已收到停止请求，正在结束处理。")

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
        unit: PlanUnit | None = None,
        unit_rows_fetched: int | None = None,
        unit_rows_written: int | None = None,
        unit_rows_committed: int | None = None,
        unit_rows_rejected: int | None = None,
    ) -> str:
        tokens = cls._build_progress_context_tokens(
            unit=unit,
            unit_rows_fetched=unit_rows_fetched,
            unit_rows_written=unit_rows_written,
            unit_rows_committed=unit_rows_committed,
            unit_rows_rejected=unit_rows_rejected,
        )
        if tokens:
            token_text = " ".join(tokens)
            committed_text = f" committed={rows_committed}" if rows_committed is not None else ""
            message = (
                f"{progress_label}: "
                f"{current}/{total} {token_text} fetched={rows_fetched} written={rows_written}{committed_text} rejected={rows_rejected}"
            )
        else:
            committed_text = f" committed={rows_committed}" if rows_committed is not None else ""
            message = (
                f"{progress_label}: "
                f"{current}/{total} fetched={rows_fetched} written={rows_written}{committed_text} rejected={rows_rejected}"
            )
        normalized_counts = cls._normalize_reason_counts(rejected_reason_counts)
        if not normalized_counts:
            return message
        encoded, truncated = cls._encode_reason_counts(normalized_counts, max_items=cls.MAX_REASON_BUCKETS)
        if encoded:
            message = f"{message} reasons={encoded}"
        if truncated:
            message = f"{message} reason_stats_truncated=1"
        return message

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
        encoded = "|".join(f"{reason_code}:{count}" for reason_code, count in limited)
        return encoded, truncated

    @classmethod
    def _build_progress_context_tokens(
        cls,
        *,
        unit: PlanUnit | None,
        unit_rows_fetched: int | None,
        unit_rows_written: int | None,
        unit_rows_committed: int | None,
        unit_rows_rejected: int | None,
    ) -> list[str]:
        tokens: list[str] = []
        if unit is not None:
            context_keys = (
                "unit",
                "ts_code",
                "security_name",
                "index_code",
                "index_name",
                "board_code",
                "board_name",
                "trade_date",
                "freq",
                "start_date",
                "end_date",
                "enum_field",
                "enum_value",
            )
            for key in context_keys:
                value = unit.progress_context.get(key)
                if value in (None, ""):
                    continue
                tokens.append(f"{key}={cls._format_progress_token_value(value)}")

        if unit_rows_fetched is not None:
            tokens.append(f"unit_fetched={int(unit_rows_fetched or 0)}")
        if unit_rows_written is not None:
            tokens.append(f"unit_written={int(unit_rows_written or 0)}")
        if unit_rows_committed is not None:
            tokens.append(f"unit_committed={int(unit_rows_committed or 0)}")
        if unit_rows_rejected is not None and unit_rows_rejected > 0:
            tokens.append(f"unit_rejected={int(unit_rows_rejected or 0)}")
        return tokens

    @staticmethod
    def _format_progress_token_value(value) -> str:  # type: ignore[no-untyped-def]
        return "_".join(str(value).strip().split())

    @classmethod
    def _build_current_object(cls, unit: PlanUnit) -> dict:
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
        attributes = {
            key: str(context[key]).strip()
            for key in ("freq", "enum_field", "enum_value", "unit")
            if context.get(key) not in (None, "")
        }
        return {
            "entity": entity,
            "time": time_scope,
            "attributes": attributes,
        }

    @staticmethod
    def _build_current_entity(context: dict) -> dict:
        if context.get("ts_code") or context.get("security_name"):
            return {
                "kind": "security",
                "code": str(context.get("ts_code") or "").strip() or None,
                "name": str(context.get("security_name") or context.get("ts_code") or "").strip(),
            }
        if context.get("index_code") or context.get("index_name"):
            return {
                "kind": "index",
                "code": str(context.get("index_code") or "").strip() or None,
                "name": str(context.get("index_name") or context.get("index_code") or "").strip(),
            }
        if context.get("board_code") or context.get("board_name"):
            return {
                "kind": "board",
                "code": str(context.get("board_code") or "").strip() or None,
                "name": str(context.get("board_name") or context.get("board_code") or "").strip(),
            }
        if context.get("enum_value"):
            return {
                "kind": "enum",
                "code": str(context.get("enum_field") or "").strip() or None,
                "name": str(context.get("enum_value") or "").strip(),
            }
        if context.get("trade_date"):
            return {
                "kind": "date",
                "code": None,
                "name": str(context.get("trade_date") or "").strip(),
            }
        return {
            "kind": "dataset",
            "code": None,
            "name": str(context.get("unit") or "").strip(),
        }

    @staticmethod
    def _build_current_time(context: dict) -> dict:
        trade_date = str(context.get("trade_date") or "").strip()
        start_date = str(context.get("start_date") or "").strip()
        end_date = str(context.get("end_date") or "").strip()
        if start_date or end_date:
            return {
                "kind": "range",
                "start_date": start_date or None,
                "end_date": end_date or None,
            }
        if trade_date:
            return {
                "kind": "point",
                "trade_date": trade_date,
            }
        return {"kind": "none"}
