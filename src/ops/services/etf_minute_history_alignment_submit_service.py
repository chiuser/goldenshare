from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.dao.etf_basic_dao import EtfBasicDAO
from src.foundation.ingestion.etf_minute_windows import build_etf_minute_windows
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.etf_minute_history_alignment_plan_service import (
    ETF_MINUTE_FREQUENCIES,
    EtfMinuteHistoryAlignmentAction,
    EtfMinuteHistoryAlignmentPlanService,
    canonical_etf_minute_alignment_hash,
    etf_minute_request_target_hash,
)
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


ETF_MINUTE_ALIGNMENT_SUBMIT_ADVISORY_LOCK_KEY = 8_491_716_207
ETF_MINUTE_ALIGNMENT_OPEN_TASK_STATUSES = ("queued", "running", "canceling")
_CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_HASH_LENGTH = 64
_PLAN_FIELDS = frozenset(
    {
        "plan_id",
        "plan_content_hash",
        "generated_at",
        "request_target_hash",
        "eligibility_as_of",
        "alignment_start_date",
        "alignment_end_date",
        "requestable_etf_count",
        "alignment_target_etf_count",
        "list_date_after_alignment_end_count",
        "excluded_reason_counts",
        "frequency_summaries",
        "raw_covered_target_frequency_count",
        "successful_task_only_covered_target_frequency_count",
        "missing_prefix_target_frequency_count",
        "missing_suffix_target_frequency_count",
        "planned_action_count",
        "planned_unit_count",
        "source_request_lower_bound",
        "page_request_upper_bound",
        "interior_gap_not_audited",
        "actions",
    }
)
_ACTION_FIELDS = frozenset(
    {"ts_code", "frequencies", "start_date", "end_date", "planned_unit_count"}
)


@dataclass(frozen=True, slots=True)
class ConfirmedEtfMinuteAlignmentPlan:
    plan_id: str
    plan_content_hash: str
    request_target_hash: str
    alignment_start_date: date
    alignment_end_date: date
    actions: tuple[EtfMinuteHistoryAlignmentAction, ...]


@dataclass(frozen=True, slots=True)
class EtfMinuteHistoryAlignmentSubmitResult:
    plan_id: str
    plan_content_hash: str
    requested_batch_size: int
    created_task_run_ids: tuple[int, ...]
    skipped_covered_action_count: int
    remaining_action_count: int

    @property
    def created_task_run_count(self) -> int:
        return len(self.created_task_run_ids)

    def render_summary(self) -> str:
        task_run_ids = ",".join(str(value) for value in self.created_task_run_ids)
        return "\n".join(
            (
                "ETF minute alignment submit",
                f"plan_id={self.plan_id}",
                f"plan_content_hash={self.plan_content_hash}",
                f"requested_batch_size={self.requested_batch_size}",
                f"created_task_run_count={self.created_task_run_count}",
                f"created_task_run_ids={task_run_ids}",
                f"skipped_covered_action_count={self.skipped_covered_action_count}",
                f"remaining_action_count={self.remaining_action_count}",
            )
        )


class EtfMinuteHistoryAlignmentSubmitError(ValueError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = MappingProxyType(dict(details or {}))


class EtfMinuteHistoryAlignmentSubmitService:
    def __init__(
        self,
        *,
        plan_service: EtfMinuteHistoryAlignmentPlanService | None = None,
        task_run_service: TaskRunCommandService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plan_service = plan_service or EtfMinuteHistoryAlignmentPlanService()
        self._task_run_service = task_run_service or TaskRunCommandService()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def validate_plan_payload(
        cls,
        payload: Any,
        *,
        confirmed_plan_hash: str,
    ) -> ConfirmedEtfMinuteAlignmentPlan:
        if not isinstance(payload, dict):
            raise cls._error("plan_schema_invalid", "alignment plan 必须是 JSON 对象")
        if set(payload) != _PLAN_FIELDS:
            raise cls._error(
                "plan_schema_invalid",
                "alignment plan 字段与当前 P9A 契约不一致",
                missing_fields=sorted(_PLAN_FIELDS - set(payload)),
                unexpected_fields=sorted(set(payload) - _PLAN_FIELDS),
            )

        embedded_hash = cls._require_hash(payload.get("plan_content_hash"), "plan_content_hash")
        confirmed_hash = cls._require_hash(confirmed_plan_hash, "confirm_plan_hash")
        if confirmed_hash != embedded_hash:
            raise cls._error(
                "plan_confirmation_mismatch",
                "确认 hash 与计划文件不一致",
            )
        canonical_payload = dict(payload)
        canonical_payload.pop("plan_content_hash")
        calculated_hash = canonical_etf_minute_alignment_hash(canonical_payload)
        if calculated_hash != embedded_hash:
            raise cls._error(
                "plan_content_hash_mismatch",
                "alignment plan 内容已变化，请重新 preview",
            )

        plan_id = cls._require_text(payload.get("plan_id"), "plan_id")
        if not plan_id.startswith("etf-minute-alignment-"):
            raise cls._error("plan_schema_invalid", "plan_id 不是 ETF 分钟对齐计划")
        cls._require_aware_datetime(payload.get("generated_at"), "generated_at")
        cls._require_date(payload.get("eligibility_as_of"), "eligibility_as_of")
        request_target_hash = cls._require_hash(
            payload.get("request_target_hash"),
            "request_target_hash",
        )
        alignment_start_date = cls._require_date(
            payload.get("alignment_start_date"),
            "alignment_start_date",
        )
        alignment_end_date = cls._require_date(
            payload.get("alignment_end_date"),
            "alignment_end_date",
        )
        if alignment_start_date > alignment_end_date:
            raise cls._error(
                "plan_schema_invalid",
                "alignment plan 开始日晚于截止日",
            )
        if payload.get("interior_gap_not_audited") is not True:
            raise cls._error(
                "plan_schema_invalid",
                "alignment plan 必须保留 interior_gap_not_audited=true",
            )

        for field_name in (
            "requestable_etf_count",
            "alignment_target_etf_count",
            "list_date_after_alignment_end_count",
            "raw_covered_target_frequency_count",
            "successful_task_only_covered_target_frequency_count",
            "missing_prefix_target_frequency_count",
            "missing_suffix_target_frequency_count",
            "planned_action_count",
            "planned_unit_count",
            "source_request_lower_bound",
            "page_request_upper_bound",
        ):
            cls._require_non_negative_int(payload.get(field_name), field_name)
        if not isinstance(payload.get("excluded_reason_counts"), dict):
            raise cls._error("plan_schema_invalid", "excluded_reason_counts 必须是对象")
        frequency_summaries = payload.get("frequency_summaries")
        if not isinstance(frequency_summaries, list) or len(frequency_summaries) != len(
            ETF_MINUTE_FREQUENCIES
        ):
            raise cls._error("plan_schema_invalid", "frequency_summaries 必须包含五个频率")

        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list):
            raise cls._error("plan_schema_invalid", "actions 必须是数组")
        actions = tuple(
            cls._parse_action(
                raw_action,
                alignment_start_date=alignment_start_date,
                alignment_end_date=alignment_end_date,
            )
            for raw_action in raw_actions
        )
        if len({cls._action_key(action) for action in actions}) != len(actions):
            raise cls._error("plan_schema_invalid", "actions 存在重复项")
        if actions != tuple(sorted(actions, key=cls._action_sort_key)):
            raise cls._error("plan_schema_invalid", "actions 未按 P9A 契约稳定排序")

        planned_action_count = cls._require_non_negative_int(
            payload.get("planned_action_count"),
            "planned_action_count",
        )
        planned_unit_count = cls._require_non_negative_int(
            payload.get("planned_unit_count"),
            "planned_unit_count",
        )
        if planned_action_count != len(actions):
            raise cls._error("plan_schema_invalid", "planned_action_count 与 actions 不一致")
        if planned_unit_count != sum(action.planned_unit_count for action in actions):
            raise cls._error("plan_schema_invalid", "planned_unit_count 与 actions 不一致")
        if payload.get("source_request_lower_bound") != planned_unit_count:
            raise cls._error("plan_schema_invalid", "source_request_lower_bound 与 unit 数不一致")
        if payload.get("page_request_upper_bound") != planned_unit_count * 4:
            raise cls._error("plan_schema_invalid", "page_request_upper_bound 与 unit 数不一致")

        return ConfirmedEtfMinuteAlignmentPlan(
            plan_id=plan_id,
            plan_content_hash=embedded_hash,
            request_target_hash=request_target_hash,
            alignment_start_date=alignment_start_date,
            alignment_end_date=alignment_end_date,
            actions=actions,
        )

    def submit(
        self,
        session: Session,
        *,
        plan: ConfirmedEtfMinuteAlignmentPlan,
        batch_size: int,
    ) -> EtfMinuteHistoryAlignmentSubmitResult:
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
        ):
            raise self._error("batch_size_invalid", "batch_size 必须是正整数")

        try:
            self._acquire_submit_lock(session)
            self._ensure_no_open_etf_minute_task(session)

            submitted_at = self._clock()
            if submitted_at.tzinfo is None:
                raise ValueError("alignment submit clock must return a timezone-aware datetime")
            submitted_at = submitted_at.astimezone(timezone.utc)
            eligibility_as_of = submitted_at.astimezone(_CHINA_TIMEZONE).date()
            snapshot = EtfBasicDAO(session).load_requestability_snapshot(
                as_of_date=eligibility_as_of
            )
            current_target_hash = etf_minute_request_target_hash(snapshot.targets)
            if current_target_hash != plan.request_target_hash:
                raise self._error(
                    "request_target_hash_changed",
                    "当前 ETF Basic 请求对象已经变化，请重新 preview",
                    expected=plan.request_target_hash,
                    actual=current_target_hash,
                )

            targets_by_code = {target.ts_code: target for target in snapshot.targets}
            for action in plan.actions:
                target = targets_by_code.get(action.ts_code)
                if target is None:
                    raise self._error(
                        "plan_target_not_requestable",
                        "计划中的 ETF 当前不可请求，请重新 preview",
                        ts_code=action.ts_code,
                    )
                if action.start_date < target.list_date:
                    raise self._error(
                        "plan_before_list_date",
                        "计划 action 早于当前上市日，请重新 preview",
                        ts_code=action.ts_code,
                        list_date=target.list_date.isoformat(),
                        action_start_date=action.start_date.isoformat(),
                    )

            current_plan = self._plan_service.build_plan_for_snapshot(
                session,
                snapshot=snapshot,
                generated_at=submitted_at,
                alignment_start_date=plan.alignment_start_date,
                alignment_end_date=plan.alignment_end_date,
            )
            pending_actions, skipped_covered_count = self._classify_actions(
                confirmed_actions=plan.actions,
                current_actions=current_plan.actions,
            )

            self._ensure_no_open_etf_minute_task(session)
            selected_actions = pending_actions[:batch_size]
            created_task_run_ids: list[int] = []
            action_numbers = {
                self._action_key(action): index
                for index, action in enumerate(plan.actions, start=1)
            }
            for action in selected_actions:
                task_run = self._task_run_service.stage_task_run(
                    session,
                    context=TaskRunCreateContext(
                        task_type="dataset_action",
                        resource_key="etf_mins",
                        action="maintain",
                        time_input={
                            "mode": "range",
                            "start_date": action.start_date.isoformat(),
                            "end_date": action.end_date.isoformat(),
                        },
                        filters={
                            "ts_code": action.ts_code,
                            "freq": list(action.frequencies),
                        },
                        request_payload={
                            "alignment_plan_id": plan.plan_id,
                            "alignment_plan_content_hash": plan.plan_content_hash,
                            "alignment_action_number": action_numbers[
                                self._action_key(action)
                            ],
                        },
                        trigger_source="manual",
                        requested_by_user_id=None,
                    ),
                    task_frozen_at=submitted_at,
                )
                created_task_run_ids.append(task_run.id)

            session.commit()
            return EtfMinuteHistoryAlignmentSubmitResult(
                plan_id=plan.plan_id,
                plan_content_hash=plan.plan_content_hash,
                requested_batch_size=batch_size,
                created_task_run_ids=tuple(created_task_run_ids),
                skipped_covered_action_count=skipped_covered_count,
                remaining_action_count=len(pending_actions) - len(selected_actions),
            )
        except Exception:
            session.rollback()
            raise

    @staticmethod
    def _acquire_submit_lock(session: Session) -> None:
        if session.get_bind().dialect.name != "postgresql":
            return
        session.execute(
            select(func.pg_advisory_xact_lock(ETF_MINUTE_ALIGNMENT_SUBMIT_ADVISORY_LOCK_KEY))
        )

    @staticmethod
    def _ensure_no_open_etf_minute_task(session: Session) -> None:
        existing_id = session.scalar(
            select(TaskRun.id)
            .where(TaskRun.resource_key == "etf_mins")
            .where(TaskRun.status.in_(ETF_MINUTE_ALIGNMENT_OPEN_TASK_STATUSES))
            .order_by(TaskRun.id)
            .limit(1)
        )
        if existing_id is not None:
            raise EtfMinuteHistoryAlignmentSubmitService._error(
                "open_etf_mins_task_exists",
                "已有 ETF 历史分钟任务正在等待或执行，本次未创建新任务",
                task_run_id=int(existing_id),
            )

    @classmethod
    def _classify_actions(
        cls,
        *,
        confirmed_actions: Sequence[EtfMinuteHistoryAlignmentAction],
        current_actions: Sequence[EtfMinuteHistoryAlignmentAction],
    ) -> tuple[tuple[EtfMinuteHistoryAlignmentAction, ...], int]:
        confirmed_pair_intervals = cls._pair_intervals(confirmed_actions)
        current_pair_intervals = cls._pair_intervals(current_actions)
        for pair, intervals in current_pair_intervals.items():
            confirmed_intervals = confirmed_pair_intervals.get(pair, ())
            if any(interval not in confirmed_intervals for interval in intervals):
                raise cls._error(
                    "plan_coverage_changed",
                    "分钟覆盖范围已变化，请重新 preview 后再提交",
                    ts_code=pair[0],
                    frequency=pair[1],
                )

        current_keys = {cls._action_key(action) for action in current_actions}
        pending: list[EtfMinuteHistoryAlignmentAction] = []
        skipped_covered = 0
        for action in confirmed_actions:
            if cls._action_key(action) in current_keys:
                pending.append(action)
                continue
            if any(
                interval in current_pair_intervals.get((action.ts_code, frequency), ())
                for frequency in action.frequencies
                for interval in ((action.start_date, action.end_date),)
            ):
                raise cls._error(
                    "plan_coverage_changed",
                    "分钟覆盖范围只发生了部分变化，请重新 preview 后再提交",
                    ts_code=action.ts_code,
                )
            skipped_covered += 1
        return tuple(pending), skipped_covered

    @staticmethod
    def _pair_intervals(
        actions: Sequence[EtfMinuteHistoryAlignmentAction],
    ) -> Mapping[tuple[str, str], tuple[tuple[date, date], ...]]:
        values: defaultdict[tuple[str, str], list[tuple[date, date]]] = defaultdict(list)
        for action in actions:
            for frequency in action.frequencies:
                values[(action.ts_code, frequency)].append(
                    (action.start_date, action.end_date)
                )
        return {
            pair: tuple(sorted(intervals))
            for pair, intervals in values.items()
        }

    @classmethod
    def _parse_action(
        cls,
        payload: Any,
        *,
        alignment_start_date: date,
        alignment_end_date: date,
    ) -> EtfMinuteHistoryAlignmentAction:
        if not isinstance(payload, dict) or set(payload) != _ACTION_FIELDS:
            raise cls._error("plan_schema_invalid", "action 字段与当前 P9A 契约不一致")
        ts_code = cls._require_text(payload.get("ts_code"), "action.ts_code")
        if ts_code != ts_code.upper() or not ts_code.endswith((".SH", ".SZ")):
            raise cls._error("plan_schema_invalid", "action.ts_code 必须是大写 .SH/.SZ 代码")
        raw_frequencies = payload.get("frequencies")
        if not isinstance(raw_frequencies, list) or not raw_frequencies:
            raise cls._error("plan_schema_invalid", "action.frequencies 必须是非空数组")
        if any(not isinstance(value, str) for value in raw_frequencies):
            raise cls._error("plan_schema_invalid", "action.frequencies 包含非法值")
        frequencies = tuple(raw_frequencies)
        expected_frequencies = tuple(
            frequency
            for frequency in ETF_MINUTE_FREQUENCIES
            if frequency in set(frequencies)
        )
        if frequencies != expected_frequencies:
            raise cls._error("plan_schema_invalid", "action.frequencies 非法、重复或顺序错误")
        start_date = cls._require_date(payload.get("start_date"), "action.start_date")
        end_date = cls._require_date(payload.get("end_date"), "action.end_date")
        if (
            start_date > end_date
            or start_date < alignment_start_date
            or end_date > alignment_end_date
        ):
            raise cls._error("plan_schema_invalid", "action 日期范围超出 alignment plan")
        planned_unit_count = cls._require_non_negative_int(
            payload.get("planned_unit_count"),
            "action.planned_unit_count",
        )
        expected_unit_count = sum(
            len(
                build_etf_minute_windows(
                    freq=frequency,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            for frequency in frequencies
        )
        if planned_unit_count != expected_unit_count:
            raise cls._error("plan_schema_invalid", "action unit 数与当前切窗算法不一致")
        return EtfMinuteHistoryAlignmentAction(
            ts_code=ts_code,
            frequencies=frequencies,
            start_date=start_date,
            end_date=end_date,
            planned_unit_count=planned_unit_count,
        )

    @staticmethod
    def _action_key(
        action: EtfMinuteHistoryAlignmentAction,
    ) -> tuple[str, date, date, tuple[str, ...]]:
        return (
            action.ts_code,
            action.start_date,
            action.end_date,
            action.frequencies,
        )

    @staticmethod
    def _action_sort_key(
        action: EtfMinuteHistoryAlignmentAction,
    ) -> tuple[str, date, date, tuple[int, ...]]:
        order = {frequency: index for index, frequency in enumerate(ETF_MINUTE_FREQUENCIES)}
        return (
            action.ts_code,
            action.start_date,
            action.end_date,
            tuple(order[frequency] for frequency in action.frequencies),
        )

    @classmethod
    def _require_date(cls, value: Any, field_name: str) -> date:
        if not isinstance(value, str):
            raise cls._error("plan_schema_invalid", f"{field_name} 必须是 ISO 日期")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise cls._error("plan_schema_invalid", f"{field_name} 必须是 ISO 日期") from exc

    @classmethod
    def _require_aware_datetime(cls, value: Any, field_name: str) -> datetime:
        if not isinstance(value, str):
            raise cls._error("plan_schema_invalid", f"{field_name} 必须是 ISO 时间")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise cls._error("plan_schema_invalid", f"{field_name} 必须是 ISO 时间") from exc
        if parsed.tzinfo is None:
            raise cls._error("plan_schema_invalid", f"{field_name} 必须包含时区")
        return parsed

    @classmethod
    def _require_text(cls, value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise cls._error("plan_schema_invalid", f"{field_name} 必须是非空字符串")
        return value

    @classmethod
    def _require_hash(cls, value: Any, field_name: str) -> str:
        text_value = cls._require_text(value, field_name)
        if (
            len(text_value) != _HASH_LENGTH
            or text_value != text_value.lower()
            or any(character not in "0123456789abcdef" for character in text_value)
        ):
            raise cls._error("plan_schema_invalid", f"{field_name} 必须是 SHA-256")
        return text_value

    @classmethod
    def _require_non_negative_int(cls, value: Any, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise cls._error("plan_schema_invalid", f"{field_name} 必须是非负整数")
        return value

    @staticmethod
    def _error(code: str, message: str, **details: Any) -> EtfMinuteHistoryAlignmentSubmitError:
        return EtfMinuteHistoryAlignmentSubmitError(
            code=code,
            message=message,
            details=details,
        )
