from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_action_key, get_dataset_definition_by_action_key
from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.ops.models.ops.dataset_layer_snapshot_current import DatasetLayerSnapshotCurrent
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.models.ops.task_run import TaskRun
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.foundation.config.settings import get_settings
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


@dataclass(slots=True, frozen=True)
class ProbeTickResult:
    processed_rules: int = 0
    triggered_rules: int = 0
    created_task_runs: int = 0


class ProbeRuntimeService:
    def __init__(self) -> None:
        self.task_run_service = TaskRunCommandService()
        self.snapshot_service = DatasetStatusSnapshotService()
        self.freshness_query = OpsFreshnessQueryService()

    def run_once(self, session: Session, *, now: datetime | None = None, limit: int = 100) -> tuple[list[TaskRun], ProbeTickResult]:
        current = now or datetime.now(timezone.utc)
        stmt = (
            select(ProbeRule)
            .where(ProbeRule.status == "active")
            .order_by(ProbeRule.updated_at.asc(), ProbeRule.id.asc())
            .limit(limit)
        )
        rules = list(session.scalars(stmt))
        task_runs: list[TaskRun] = []
        processed = 0
        triggered = 0

        for rule in rules:
            should_probe, skip_reason = self._should_probe(session, rule, current=current)
            if not should_probe:
                continue
            processed += 1
            started_at = datetime.now(timezone.utc)
            matched = False
            message: str | None = None
            payload: dict = {}
            task_run_id: int | None = None
            task_run_correlation_id: str | None = None
            status = "success"
            result_code = "miss"
            result_reason = skip_reason
            try:
                matched, message, payload = self._evaluate_rule(session, rule, current=current)
                rule.last_probed_at = started_at
                if matched:
                    task_run = self._enqueue_on_match(session, rule)
                    task_run_id = task_run.id
                    task_run_correlation_id = str(task_run.id)
                    task_runs.append(task_run)
                    triggered += 1
                    rule.last_triggered_at = datetime.now(timezone.utc)
                    result_code = "hit"
                    result_reason = "condition_hit"
                else:
                    result_code = "miss"
                    result_reason = "condition_miss"
            except Exception as exc:  # pragma: no cover - defensive
                status = "failed"
                matched = False
                message = str(exc)
                payload = {"error": str(exc)}
                result_code = "error"
                result_reason = "probe_runtime_error"
            finally:
                ended_at = datetime.now(timezone.utc)
                run_log = ProbeRunLog(
                    probe_rule_id=rule.id,
                    status=status,
                    condition_matched=matched,
                    message=message or ("命中探测条件" if matched else (skip_reason or "未命中探测条件")),
                    payload_json=payload,
                    probed_at=started_at,
                    triggered_task_run_id=task_run_id,
                    duration_ms=max(int((ended_at - started_at).total_seconds() * 1000), 0),
                    rule_version=rule.rule_version,
                    result_code=result_code,
                    result_reason=result_reason,
                    correlation_id=task_run_correlation_id,
                )
                session.add(run_log)
                session.commit()

        return task_runs, ProbeTickResult(
            processed_rules=processed,
            triggered_rules=triggered,
            created_task_runs=len(task_runs),
        )

    def _evaluate_rule(
        self,
        session: Session,
        rule: ProbeRule,
        *,
        current: datetime,
    ) -> tuple[bool, str, dict]:
        # Refresh snapshot before probing so freshness/result are near-real-time.
        self.snapshot_service.refresh_resources(session, [rule.dataset_key], today=current.date())
        live_items = self.freshness_query.build_live_items(session, today=current.date(), resource_keys=[rule.dataset_key])
        item = next((entry for entry in live_items if entry.dataset_key == rule.dataset_key), None)
        if item is None:
            return False, "未找到数据集状态信息", {"dataset_key": rule.dataset_key}

        condition = dict(rule.probe_condition_json or {})
        condition_type = str(condition.get("type") or "freshness_latest_open")
        exchange = str(condition.get("exchange") or get_settings().default_exchange)
        latest_open = TradeCalendarDAO(session).get_latest_open_date(exchange, current.astimezone(ZoneInfo("Asia/Shanghai")).date())
        source_key = self._normalize_source_key(rule.source_key, dataset_key=rule.dataset_key)
        raw_snapshot = session.get(DatasetLayerSnapshotCurrent, (rule.dataset_key, source_key, "raw"))
        rows_in = raw_snapshot.rows_in if raw_snapshot is not None else None

        payload = {
            "dataset_key": rule.dataset_key,
            "source_key": source_key,
            "latest_business_date": item.latest_business_date.isoformat() if item.latest_business_date else None,
            "latest_open_date": latest_open.isoformat() if latest_open else None,
            "freshness_status": item.freshness_status,
            "raw_rows_in": rows_in,
        }

        if condition_type == "raw_rows_min":
            min_rows = int(condition.get("min_rows_in") or 1)
            matched = rows_in is not None and rows_in >= min_rows
            return matched, (f"raw rows_in={rows_in}，阈值={min_rows}" if not matched else "raw 行数命中"), payload

        # Default: freshness_latest_open
        matched = latest_open is not None and item.latest_business_date == latest_open
        min_rows = condition.get("min_rows_in")
        if min_rows is not None:
            min_rows_int = int(min_rows)
            matched = matched and rows_in is not None and rows_in >= min_rows_int
            payload["min_rows_in"] = min_rows_int
        if matched:
            return True, "最新业务日已命中最新交易日", payload
        return False, "最新业务日尚未到最新交易日", payload

    def _enqueue_on_match(self, session: Session, rule: ProbeRule) -> TaskRun:
        action = dict(rule.on_success_action_json or {})
        action_type = str(action.get("action_type") or "dataset_action")
        if action_type != "dataset_action":
            raise ValueError(f"unsupported probe action_type={action_type}")
        action_key = str(action.get("action_key") or get_dataset_action_key(rule.dataset_key, "maintain"))
        definition, action_name = get_dataset_definition_by_action_key(action_key)
        request = dict(action.get("request") or {})
        time_input = dict(request.get("time_input") or {"mode": "point"})
        filters = dict(request.get("filters") or {})
        if rule.source_key:
            filters.setdefault("source_key", rule.source_key)
        return self.task_run_service.create_task_run(
            session,
            context=TaskRunCreateContext(
                task_type="dataset_action",
                resource_key=definition.dataset_key,
                action=action_name,
                time_input=time_input,
                filters=filters,
                request_payload={"run_scope": request.get("run_scope") or "probe_triggered"},
                trigger_source="probe",
                requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
                schedule_id=rule.schedule_id,
            ),
        )

    def _should_probe(self, session: Session, rule: ProbeRule, *, current: datetime) -> tuple[bool, str | None]:
        tz = self._parse_timezone(rule.timezone_name)
        local_now = current.astimezone(tz)
        if not self._in_window(local_now.time(), rule.window_start, rule.window_end):
            return False, "当前不在探测时间窗口"

        if rule.last_probed_at is not None:
            elapsed = current - self._to_aware_utc(rule.last_probed_at)
            if elapsed.total_seconds() < max(rule.probe_interval_seconds, 1):
                return False, "未到下次探测间隔"

        day_start_local = datetime.combine(local_now.date(), time.min, tzinfo=tz)
        day_end_local = day_start_local + timedelta(days=1)
        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = day_end_local.astimezone(timezone.utc)
        daily_triggered = session_count = 0
        # count condition_matched true runs in local day.
        # pylint: disable=not-callable
        session_count = int(
            session.scalar(
                select(func.count())
                .select_from(ProbeRunLog)
                .where(ProbeRunLog.probe_rule_id == rule.id)
                .where(ProbeRunLog.condition_matched.is_(True))
                .where(ProbeRunLog.probed_at >= day_start_utc)
                .where(ProbeRunLog.probed_at < day_end_utc)
            )
            or 0
        )
        daily_triggered = session_count
        if daily_triggered >= max(rule.max_triggers_per_day, 1):
            return False, "今日触发次数已达上限"
        return True, None

    @staticmethod
    def _parse_timezone(value: str | None) -> ZoneInfo:
        try:
            return ZoneInfo(str(value or "Asia/Shanghai"))
        except Exception:  # pragma: no cover
            return ZoneInfo("Asia/Shanghai")

    @staticmethod
    def _in_window(now: time, start: str | None, end: str | None) -> bool:
        if not start and not end:
            return True
        start_t = ProbeRuntimeService._parse_time(start) if start else time.min
        end_t = ProbeRuntimeService._parse_time(end) if end else time.max
        if start_t <= end_t:
            return start_t <= now <= end_t
        # overnight window: 23:00~01:00
        return now >= start_t or now <= end_t

    @staticmethod
    def _parse_time(value: str | None) -> time:
        if not value:
            return time.min
        text = str(value).strip()
        if len(text) == 5:
            return time.fromisoformat(text)
        if len(text) == 8:
            return time.fromisoformat(text)
        return time.fromisoformat(f"{text}:00")

    @staticmethod
    def _to_aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_source_key(source_key: str | None, *, dataset_key: str) -> str:
        normalized = (source_key or "").strip()
        if normalized:
            return normalized
        if dataset_key.startswith("biying_"):
            return "biying"
        return "tushare"
