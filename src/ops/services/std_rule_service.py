from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.queries.std_rule_query_service import StdRuleQueryService
from src.app.exceptions import WebAppError


class OpsStdRuleCommandService:
    def create_mapping_rule(self, session: Session, *, user: AuthenticatedUser, payload: dict) -> int:
        self._validate_mapping_required(payload)
        rule = StdMappingRule(
            dataset_key=payload["dataset_key"].strip(),
            source_key=payload["source_key"].strip(),
            src_field=payload["src_field"].strip(),
            std_field=payload["std_field"].strip(),
            src_type=payload.get("src_type"),
            std_type=payload.get("std_type"),
            transform_fn=payload.get("transform_fn"),
            lineage_preserved=bool(payload.get("lineage_preserved", True)),
            status=payload.get("status", "active"),
            rule_set_version=int(payload.get("rule_set_version", 1)),
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        self._ensure_rule_status(rule.status)
        if rule.rule_set_version <= 0:
            raise WebAppError(status_code=422, code="validation_error", message="规则版本必须大于 0")
        session.add(rule)
        session.flush()
        self._record_revision("std_mapping_rule", str(rule.id), "created", None, self._snapshot_mapping(rule), user.id, session)
        session.commit()
        session.refresh(rule)
        return rule.id

    def update_mapping_rule(self, session: Session, *, user: AuthenticatedUser, rule_id: int, changes: dict) -> int:
        rule = StdRuleQueryService.get_mapping_rule(session, rule_id)
        before = self._snapshot_mapping(rule)
        changed_fields = set(changes)
        if "src_type" in changed_fields:
            rule.src_type = changes["src_type"]
        if "std_type" in changed_fields:
            rule.std_type = changes["std_type"]
        if "transform_fn" in changed_fields:
            rule.transform_fn = changes["transform_fn"]
        if "lineage_preserved" in changed_fields:
            rule.lineage_preserved = bool(changes["lineage_preserved"])
        if "status" in changed_fields:
            self._ensure_rule_status(changes["status"])
            rule.status = changes["status"]
        if "rule_set_version" in changed_fields:
            version = int(changes["rule_set_version"])
            if version <= 0:
                raise WebAppError(status_code=422, code="validation_error", message="规则版本必须大于 0")
            rule.rule_set_version = version
        rule.updated_by_user_id = user.id
        after = self._snapshot_mapping(rule)
        if before == after:
            session.refresh(rule)
            return rule.id
        self._record_revision("std_mapping_rule", str(rule.id), "updated", before, after, user.id, session)
        session.commit()
        session.refresh(rule)
        return rule.id

    def disable_mapping_rule(self, session: Session, *, user: AuthenticatedUser, rule_id: int) -> int:
        return self._set_mapping_status(session, user=user, rule_id=rule_id, status="disabled", action="disabled")

    def enable_mapping_rule(self, session: Session, *, user: AuthenticatedUser, rule_id: int) -> int:
        return self._set_mapping_status(session, user=user, rule_id=rule_id, status="active", action="enabled")

    def create_cleansing_rule(self, session: Session, *, user: AuthenticatedUser, payload: dict) -> int:
        self._validate_cleansing_required(payload)
        rule = StdCleansingRule(
            dataset_key=payload["dataset_key"].strip(),
            source_key=payload["source_key"].strip(),
            rule_type=payload["rule_type"].strip(),
            target_fields_json=list(payload.get("target_fields_json") or []),
            condition_expr=payload.get("condition_expr"),
            action=payload["action"].strip(),
            status=payload.get("status", "active"),
            rule_set_version=int(payload.get("rule_set_version", 1)),
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        self._ensure_rule_status(rule.status)
        if rule.rule_set_version <= 0:
            raise WebAppError(status_code=422, code="validation_error", message="规则版本必须大于 0")
        session.add(rule)
        session.flush()
        self._record_revision("std_cleansing_rule", str(rule.id), "created", None, self._snapshot_cleansing(rule), user.id, session)
        session.commit()
        session.refresh(rule)
        return rule.id

    def update_cleansing_rule(self, session: Session, *, user: AuthenticatedUser, rule_id: int, changes: dict) -> int:
        rule = StdRuleQueryService.get_cleansing_rule(session, rule_id)
        before = self._snapshot_cleansing(rule)
        changed_fields = set(changes)
        if "rule_type" in changed_fields:
            value = str(changes["rule_type"] or "").strip()
            if not value:
                raise WebAppError(status_code=422, code="validation_error", message="规则类型不能为空")
            rule.rule_type = value
        if "target_fields_json" in changed_fields:
            rule.target_fields_json = list(changes["target_fields_json"] or [])
        if "condition_expr" in changed_fields:
            rule.condition_expr = changes["condition_expr"]
        if "action" in changed_fields:
            value = str(changes["action"] or "").strip()
            if not value:
                raise WebAppError(status_code=422, code="validation_error", message="处理动作不能为空")
            rule.action = value
        if "status" in changed_fields:
            self._ensure_rule_status(changes["status"])
            rule.status = changes["status"]
        if "rule_set_version" in changed_fields:
            version = int(changes["rule_set_version"])
            if version <= 0:
                raise WebAppError(status_code=422, code="validation_error", message="规则版本必须大于 0")
            rule.rule_set_version = version
        rule.updated_by_user_id = user.id
        after = self._snapshot_cleansing(rule)
        if before == after:
            session.refresh(rule)
            return rule.id
        self._record_revision("std_cleansing_rule", str(rule.id), "updated", before, after, user.id, session)
        session.commit()
        session.refresh(rule)
        return rule.id

    def disable_cleansing_rule(self, session: Session, *, user: AuthenticatedUser, rule_id: int) -> int:
        return self._set_cleansing_status(session, user=user, rule_id=rule_id, status="disabled", action="disabled")

    def enable_cleansing_rule(self, session: Session, *, user: AuthenticatedUser, rule_id: int) -> int:
        return self._set_cleansing_status(session, user=user, rule_id=rule_id, status="active", action="enabled")

    def _set_mapping_status(self, session: Session, *, user: AuthenticatedUser, rule_id: int, status: str, action: str) -> int:
        rule = StdRuleQueryService.get_mapping_rule(session, rule_id)
        if rule.status == status:
            session.refresh(rule)
            return rule.id
        before = self._snapshot_mapping(rule)
        rule.status = status
        rule.updated_by_user_id = user.id
        self._record_revision("std_mapping_rule", str(rule.id), action, before, self._snapshot_mapping(rule), user.id, session)
        session.commit()
        session.refresh(rule)
        return rule.id

    def _set_cleansing_status(self, session: Session, *, user: AuthenticatedUser, rule_id: int, status: str, action: str) -> int:
        rule = StdRuleQueryService.get_cleansing_rule(session, rule_id)
        if rule.status == status:
            session.refresh(rule)
            return rule.id
        before = self._snapshot_cleansing(rule)
        rule.status = status
        rule.updated_by_user_id = user.id
        self._record_revision("std_cleansing_rule", str(rule.id), action, before, self._snapshot_cleansing(rule), user.id, session)
        session.commit()
        session.refresh(rule)
        return rule.id

    @staticmethod
    def _validate_mapping_required(payload: dict) -> None:
        for field in ("dataset_key", "source_key", "src_field", "std_field"):
            if not str(payload.get(field) or "").strip():
                raise WebAppError(status_code=422, code="validation_error", message=f"{OpsStdRuleCommandService._field_label(field)}不能为空")

    @staticmethod
    def _validate_cleansing_required(payload: dict) -> None:
        for field in ("dataset_key", "source_key", "rule_type", "action"):
            if not str(payload.get(field) or "").strip():
                raise WebAppError(status_code=422, code="validation_error", message=f"{OpsStdRuleCommandService._field_label(field)}不能为空")

    @staticmethod
    def _ensure_rule_status(status: str) -> None:
        if status not in {"active", "disabled"}:
            raise WebAppError(status_code=422, code="validation_error", message="规则状态无效")

    @staticmethod
    def _field_label(field_name: str) -> str:
        labels = {
            "dataset_key": "数据集",
            "source_key": "来源",
            "src_field": "源字段",
            "std_field": "标准字段",
            "rule_type": "规则类型",
            "action": "处理动作",
        }
        return labels.get(field_name, field_name)

    @staticmethod
    def _snapshot_mapping(rule: StdMappingRule) -> dict:
        return {
            "id": rule.id,
            "dataset_key": rule.dataset_key,
            "source_key": rule.source_key,
            "src_field": rule.src_field,
            "std_field": rule.std_field,
            "src_type": rule.src_type,
            "std_type": rule.std_type,
            "transform_fn": rule.transform_fn,
            "lineage_preserved": rule.lineage_preserved,
            "status": rule.status,
            "rule_set_version": rule.rule_set_version,
        }

    @staticmethod
    def _snapshot_cleansing(rule: StdCleansingRule) -> dict:
        return {
            "id": rule.id,
            "dataset_key": rule.dataset_key,
            "source_key": rule.source_key,
            "rule_type": rule.rule_type,
            "target_fields_json": list(rule.target_fields_json or []),
            "condition_expr": rule.condition_expr,
            "action": rule.action,
            "status": rule.status,
            "rule_set_version": rule.rule_set_version,
        }

    @staticmethod
    def _record_revision(
        object_type: str,
        object_id: str,
        action: str,
        before_json: dict | None,
        after_json: dict | None,
        changed_by_user_id: int,
        session: Session,
    ) -> None:
        session.add(
            ConfigRevision(
                object_type=object_type,
                object_id=object_id,
                action=action,
                before_json=before_json,
                after_json=after_json,
                changed_by_user_id=changed_by_user_id,
                changed_at=datetime.now(timezone.utc),
            )
        )
