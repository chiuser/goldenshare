from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.platform.auth.domain import AuthenticatedUser
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.probe_rule import ProbeRule
from src.platform.exceptions import WebAppError


class OpsProbeCommandService:
    def create_probe_rule(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        name: str,
        dataset_key: str,
        source_key: str | None,
        status: str,
        window_start: str | None,
        window_end: str | None,
        probe_interval_seconds: int,
        probe_condition_json: dict,
        on_success_action_json: dict,
        max_triggers_per_day: int,
        timezone_name: str,
    ) -> int:
        self._validate_inputs(
            name=name,
            dataset_key=dataset_key,
            status=status,
            probe_interval_seconds=probe_interval_seconds,
            max_triggers_per_day=max_triggers_per_day,
            timezone_name=timezone_name,
        )
        rule = ProbeRule(
            name=name.strip(),
            dataset_key=dataset_key.strip(),
            source_key=source_key.strip() if isinstance(source_key, str) and source_key.strip() else None,
            status=status,
            window_start=window_start,
            window_end=window_end,
            probe_interval_seconds=probe_interval_seconds,
            probe_condition_json=dict(probe_condition_json or {}),
            on_success_action_json=dict(on_success_action_json or {}),
            max_triggers_per_day=max_triggers_per_day,
            timezone_name=timezone_name,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        session.add(rule)
        session.flush()
        self._record_revision(
            session,
            object_id=str(rule.id),
            action="created",
            before_json=None,
            after_json=self._snapshot(rule),
            changed_by_user_id=user.id,
        )
        session.commit()
        session.refresh(rule)
        return rule.id

    def update_probe_rule(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        probe_rule_id: int,
        changes: dict,
    ) -> int:
        rule = session.scalar(select(ProbeRule).where(ProbeRule.id == probe_rule_id))
        if rule is None:
            raise WebAppError(status_code=404, code="not_found", message="Probe rule does not exist")

        before = self._snapshot(rule)
        changed_fields = set(changes)
        if "name" in changed_fields:
            value = str(changes["name"] or "").strip()
            if not value:
                raise WebAppError(status_code=422, code="validation_error", message="name cannot be empty")
            rule.name = value
        if "dataset_key" in changed_fields:
            value = str(changes["dataset_key"] or "").strip()
            if not value:
                raise WebAppError(status_code=422, code="validation_error", message="dataset_key cannot be empty")
            rule.dataset_key = value
        if "source_key" in changed_fields:
            value = changes["source_key"]
            if value is None:
                rule.source_key = None
            else:
                normalized = str(value).strip()
                rule.source_key = normalized or None
        if "status" in changed_fields:
            self._ensure_status(changes["status"])
            rule.status = changes["status"]
        if "window_start" in changed_fields:
            rule.window_start = changes["window_start"]
        if "window_end" in changed_fields:
            rule.window_end = changes["window_end"]
        if "probe_interval_seconds" in changed_fields:
            self._ensure_positive_int(int(changes["probe_interval_seconds"]), field_name="probe_interval_seconds")
            rule.probe_interval_seconds = int(changes["probe_interval_seconds"])
        if "probe_condition_json" in changed_fields:
            rule.probe_condition_json = dict(changes["probe_condition_json"] or {})
        if "on_success_action_json" in changed_fields:
            rule.on_success_action_json = dict(changes["on_success_action_json"] or {})
        if "max_triggers_per_day" in changed_fields:
            self._ensure_positive_int(int(changes["max_triggers_per_day"]), field_name="max_triggers_per_day")
            rule.max_triggers_per_day = int(changes["max_triggers_per_day"])
        if "timezone_name" in changed_fields:
            value = str(changes["timezone_name"] or "").strip()
            if not value:
                raise WebAppError(status_code=422, code="validation_error", message="timezone_name cannot be empty")
            rule.timezone_name = value

        rule.updated_by_user_id = user.id
        after = self._snapshot(rule)
        if before == after:
            session.refresh(rule)
            return rule.id

        self._record_revision(
            session,
            object_id=str(rule.id),
            action="updated",
            before_json=before,
            after_json=after,
            changed_by_user_id=user.id,
        )
        session.commit()
        session.refresh(rule)
        return rule.id

    def pause_probe_rule(self, session: Session, *, user: AuthenticatedUser, probe_rule_id: int) -> int:
        return self._change_status(session, user=user, probe_rule_id=probe_rule_id, status="paused", action="paused")

    def resume_probe_rule(self, session: Session, *, user: AuthenticatedUser, probe_rule_id: int) -> int:
        return self._change_status(session, user=user, probe_rule_id=probe_rule_id, status="active", action="resumed")

    def delete_probe_rule(self, session: Session, *, user: AuthenticatedUser, probe_rule_id: int) -> int:
        rule = session.scalar(select(ProbeRule).where(ProbeRule.id == probe_rule_id))
        if rule is None:
            raise WebAppError(status_code=404, code="not_found", message="Probe rule does not exist")
        before = self._snapshot(rule)
        self._record_revision(
            session,
            object_id=str(rule.id),
            action="deleted",
            before_json=before,
            after_json=None,
            changed_by_user_id=user.id,
        )
        session.delete(rule)
        session.commit()
        return probe_rule_id

    def _change_status(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        probe_rule_id: int,
        status: str,
        action: str,
    ) -> int:
        rule = session.scalar(select(ProbeRule).where(ProbeRule.id == probe_rule_id))
        if rule is None:
            raise WebAppError(status_code=404, code="not_found", message="Probe rule does not exist")
        if rule.status == status:
            session.refresh(rule)
            return rule.id
        before = self._snapshot(rule)
        rule.status = status
        rule.updated_by_user_id = user.id
        self._record_revision(
            session,
            object_id=str(rule.id),
            action=action,
            before_json=before,
            after_json=self._snapshot(rule),
            changed_by_user_id=user.id,
        )
        session.commit()
        session.refresh(rule)
        return rule.id

    def _validate_inputs(
        self,
        *,
        name: str,
        dataset_key: str,
        status: str,
        probe_interval_seconds: int,
        max_triggers_per_day: int,
        timezone_name: str,
    ) -> None:
        if not name.strip():
            raise WebAppError(status_code=422, code="validation_error", message="name cannot be empty")
        if not dataset_key.strip():
            raise WebAppError(status_code=422, code="validation_error", message="dataset_key cannot be empty")
        self._ensure_status(status)
        self._ensure_positive_int(probe_interval_seconds, field_name="probe_interval_seconds")
        self._ensure_positive_int(max_triggers_per_day, field_name="max_triggers_per_day")
        if not timezone_name.strip():
            raise WebAppError(status_code=422, code="validation_error", message="timezone_name cannot be empty")

    @staticmethod
    def _ensure_status(status: str) -> None:
        if status not in {"active", "paused", "disabled"}:
            raise WebAppError(status_code=422, code="validation_error", message="status must be active/paused/disabled")

    @staticmethod
    def _ensure_positive_int(value: int, *, field_name: str) -> None:
        if value <= 0:
            raise WebAppError(status_code=422, code="validation_error", message=f"{field_name} must be greater than 0")

    @staticmethod
    def _snapshot(rule: ProbeRule) -> dict:
        return {
            "id": rule.id,
            "schedule_id": rule.schedule_id,
            "name": rule.name,
            "dataset_key": rule.dataset_key,
            "source_key": rule.source_key,
            "status": rule.status,
            "window_start": rule.window_start,
            "window_end": rule.window_end,
            "probe_interval_seconds": rule.probe_interval_seconds,
            "probe_condition_json": dict(rule.probe_condition_json or {}),
            "on_success_action_json": dict(rule.on_success_action_json or {}),
            "max_triggers_per_day": rule.max_triggers_per_day,
            "timezone_name": rule.timezone_name,
            "last_probed_at": rule.last_probed_at.isoformat() if rule.last_probed_at else None,
            "last_triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        }

    @staticmethod
    def _record_revision(
        session: Session,
        *,
        object_id: str,
        action: str,
        before_json: dict | None,
        after_json: dict | None,
        changed_by_user_id: int,
    ) -> None:
        session.add(
            ConfigRevision(
                object_type="probe_rule",
                object_id=object_id,
                action=action,
                before_json=before_json,
                after_json=after_json,
                changed_by_user_id=changed_by_user_id,
                changed_at=datetime.now(timezone.utc),
            )
        )
