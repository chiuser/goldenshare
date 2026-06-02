from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, aliased

from src.app.exceptions import WebAppError
from src.app.models.app_user import AppUser
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime import (
    STOCK_RT_MIN_ALLOWED_FREQS,
    RealtimeRuntimeConfigError,
    build_realtime_runtime_config_from_json,
    clear_realtime_runtime_config_cache,
)
from src.foundation.realtime.config_catalog import (
    STOCK_RT_DAILY_CATALOG,
    STOCK_RT_DAILY_OBJECT_KEY,
    STOCK_RT_MIN_CATALOG,
    STOCK_RT_MIN_FEED_KEY_PREFIX,
    STOCK_RT_MIN_OBJECT_KEY,
    RealtimeConfigCatalogEntry,
)
from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.schemas.realtime_config import (
    RealtimeConfigDiffItem,
    RealtimeConfigField,
    RealtimeConfigFieldOption,
    RealtimeConfigImpact,
    RealtimeConfigObjectDetailResponse,
    RealtimeConfigObjectListResponse,
    RealtimeConfigObjectSummary,
    RealtimeConfigPublishResponse,
    RealtimeConfigRevisionItem,
    RealtimeConfigRevisionListResponse,
    RealtimeConfigValidateResponse,
    RealtimeConfigValidationErrorItem,
    RealtimeConfigWarningItem,
)


REALTIME_RUNTIME_CONFIG_OBJECT_TYPE = "realtime_runtime_config"
PUBLISH_RESTART_MESSAGE = "发布后需要重启 collector 才会生效"


@dataclass(frozen=True, slots=True)
class _EditableFieldSpec:
    key: str
    label: str
    control: str
    value_type: str
    options: tuple[RealtimeConfigFieldOption, ...] = ()


@dataclass(frozen=True, slots=True)
class _RealtimeConfigObjectSpec:
    catalog: RealtimeConfigCatalogEntry
    editable_fields: tuple[_EditableFieldSpec, ...]
    locked_fields: tuple[str, ...]

    @property
    def editable_keys(self) -> set[str]:
        return {field.key for field in self.editable_fields}


_BOOLEAN_FIELD = "boolean"
_INTEGER_FIELD = "integer"
_STRING_LIST_FIELD = "string_list"


_DAILY_EDITABLE_FIELDS = (
    _EditableFieldSpec("enabled", "是否启用", "switch", _BOOLEAN_FIELD),
    _EditableFieldSpec("poll_interval_seconds", "采集间隔秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("max_calls_per_minute", "每分钟最大请求数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("lease_ttl_seconds", "采集租约 TTL 秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("stale_after_seconds", "滞后阈值秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("snapshot_ttl_seconds", "快照 TTL 秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("keep_recent_batches", "保留批次数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("batch_stream_maxlen", "批次事件流长度", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("delta_stream_maxlen", "变化事件流长度", "number_input", _INTEGER_FIELD),
)


_MIN_FREQ_OPTIONS = tuple(RealtimeConfigFieldOption(label=freq, value=freq) for freq in STOCK_RT_MIN_ALLOWED_FREQS)
_MIN_EDITABLE_FIELDS = (
    _EditableFieldSpec("enabled", "是否启用", "switch", _BOOLEAN_FIELD),
    _EditableFieldSpec("enabled_freqs", "启用频率", "checkbox_group", _STRING_LIST_FIELD, _MIN_FREQ_OPTIONS),
    _EditableFieldSpec("poll_interval_seconds", "采集间隔秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("max_calls_per_minute", "每分钟最大请求数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("lease_ttl_seconds", "采集租约 TTL 秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("stale_after_seconds", "滞后阈值秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("snapshot_ttl_seconds", "快照 TTL 秒数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("keep_recent_batches", "保留批次数", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("batch_stream_maxlen", "批次事件流长度", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("delta_stream_maxlen", "变化事件流长度", "number_input", _INTEGER_FIELD),
    _EditableFieldSpec("source_timeout_seconds", "源请求超时秒数", "number_input", _INTEGER_FIELD),
)


_OBJECT_SPECS: dict[str, _RealtimeConfigObjectSpec] = {
    STOCK_RT_DAILY_OBJECT_KEY: _RealtimeConfigObjectSpec(
        catalog=STOCK_RT_DAILY_CATALOG,
        editable_fields=_DAILY_EDITABLE_FIELDS,
        locked_fields=("source_api_name", "exchange", "collection_sessions", "ts_code_pattern", "feed_key"),
    ),
    STOCK_RT_MIN_OBJECT_KEY: _RealtimeConfigObjectSpec(
        catalog=STOCK_RT_MIN_CATALOG,
        editable_fields=_MIN_EDITABLE_FIELDS,
        locked_fields=("source_api_name", "exchange", "collection_sessions", "ts_code_pattern", "feed_key_pattern"),
    ),
}


class RealtimeConfigCommandService:
    def list_objects(self, session: Session) -> RealtimeConfigObjectListResponse:
        records = _load_required_records(session)
        runtime = _build_valid_runtime_config(records)
        return RealtimeConfigObjectListResponse(
            items=[
                _object_summary(spec, records[spec.catalog.object_key], runtime)
                for spec in _OBJECT_SPECS.values()
            ]
        )

    def get_object_detail(self, session: Session, object_key: str) -> RealtimeConfigObjectDetailResponse:
        spec = _get_object_spec(object_key)
        records = _load_required_records(session)
        runtime = _build_valid_runtime_config(records)
        return _object_detail(spec, records[object_key], runtime)

    def validate_object_config(
        self,
        session: Session,
        object_key: str,
        *,
        runtime_config: dict[str, Any],
    ) -> RealtimeConfigValidateResponse:
        spec = _get_object_spec(object_key)
        records = _load_required_records(session)
        result = _validate_candidate(spec, records, runtime_config)
        return RealtimeConfigValidateResponse(
            valid=not result.errors,
            errors=result.errors,
            warnings=_restart_warnings(),
            diff=result.diff if not result.errors else [],
            impact=_impact_for_spec(spec),
        )

    def publish_object_config(
        self,
        session: Session,
        object_key: str,
        *,
        version: int,
        runtime_config: dict[str, Any],
        changed_by_user_id: int,
    ) -> RealtimeConfigPublishResponse:
        spec = _get_object_spec(object_key)
        records = _load_required_records(session)
        record = records[object_key]
        if int(record.version) != int(version):
            raise WebAppError(status_code=409, code="conflict", message="实时流配置已被更新，请刷新后重试")

        result = _validate_candidate(spec, records, runtime_config)
        if result.errors:
            first_error = result.errors[0]
            raise WebAppError(status_code=422, code=first_error.code, message=first_error.message)

        before = _record_snapshot(record)
        revision_id: int | None = None
        if result.diff:
            record.runtime_config_json = dict(result.normalized_config)
            record.version = int(record.version) + 1
            record.requires_collector_restart = True
            record.updated_by_user_id = changed_by_user_id
            session.flush()
            after = _record_snapshot(record)
            revision = ConfigRevision(
                object_type=REALTIME_RUNTIME_CONFIG_OBJECT_TYPE,
                object_id=object_key,
                action="published",
                before_json=before,
                after_json=after,
                changed_by_user_id=changed_by_user_id,
                changed_at=datetime.now(timezone.utc),
            )
            session.add(revision)
            session.flush()
            revision_id = revision.id

        session.commit()
        clear_realtime_runtime_config_cache()
        session.refresh(record)
        refreshed_records = _load_required_records(session)
        runtime = _build_valid_runtime_config(refreshed_records)
        return RealtimeConfigPublishResponse(
            **_object_detail(spec, record, runtime).model_dump(),
            warnings=_restart_warnings(),
            impact=_impact_for_spec(spec),
            revision_id=revision_id,
        )

    def list_revisions(self, session: Session, object_key: str) -> RealtimeConfigRevisionListResponse:
        _get_object_spec(object_key)
        changed_by = aliased(AppUser)
        stmt = (
            select(ConfigRevision, changed_by.username)
            .outerjoin(changed_by, changed_by.id == ConfigRevision.changed_by_user_id)
            .where(ConfigRevision.object_type == REALTIME_RUNTIME_CONFIG_OBJECT_TYPE)
            .where(ConfigRevision.object_id == object_key)
            .order_by(desc(ConfigRevision.changed_at), desc(ConfigRevision.id))
        )
        rows = session.execute(stmt).all()
        return RealtimeConfigRevisionListResponse(
            total=len(rows),
            items=[
                RealtimeConfigRevisionItem(
                    id=revision.id,
                    object_type=revision.object_type,
                    object_id=revision.object_id,
                    action=revision.action,
                    before_json=revision.before_json,
                    after_json=revision.after_json,
                    changed_by_username=username,
                    changed_at=revision.changed_at,
                )
                for revision, username in rows
            ],
        )


@dataclass(frozen=True, slots=True)
class _CandidateValidationResult:
    normalized_config: dict[str, Any]
    errors: list[RealtimeConfigValidationErrorItem]
    diff: list[RealtimeConfigDiffItem]


def _get_object_spec(object_key: str) -> _RealtimeConfigObjectSpec:
    spec = _OBJECT_SPECS.get(object_key)
    if spec is None:
        raise WebAppError(status_code=404, code="not_found", message="实时流配置对象不存在")
    return spec


def _load_required_records(session: Session) -> dict[str, RealtimeRuntimeConfigRecord]:
    records: dict[str, RealtimeRuntimeConfigRecord] = {}
    for object_key, spec in _OBJECT_SPECS.items():
        record = session.get(RealtimeRuntimeConfigRecord, object_key)
        if record is None:
            raise WebAppError(status_code=422, code="runtime_config_missing", message=f"实时流配置缺少初始化记录：{object_key}")
        if record.object_kind != spec.catalog.object_kind:
            raise WebAppError(status_code=422, code="validation_error", message=f"实时流配置对象类型异常：{object_key}")
        if not isinstance(record.runtime_config_json, dict):
            raise WebAppError(status_code=422, code="validation_error", message=f"实时流配置内容必须是对象：{object_key}")
        records[object_key] = record
    return records


def _build_valid_runtime_config(records: dict[str, RealtimeRuntimeConfigRecord]) -> Any:
    try:
        return build_realtime_runtime_config_from_json(
            daily_config=records[STOCK_RT_DAILY_OBJECT_KEY].runtime_config_json,
            minute_config=records[STOCK_RT_MIN_OBJECT_KEY].runtime_config_json,
        )
    except RealtimeRuntimeConfigError as exc:
        raise WebAppError(status_code=422, code="validation_error", message=str(exc)) from exc


def _validate_candidate(
    spec: _RealtimeConfigObjectSpec,
    records: dict[str, RealtimeRuntimeConfigRecord],
    runtime_config: dict[str, Any],
) -> _CandidateValidationResult:
    if not isinstance(runtime_config, dict):
        return _CandidateValidationResult(
            normalized_config={},
            errors=[RealtimeConfigValidationErrorItem(code="validation_error", message="runtime_config 必须是对象")],
            diff=[],
        )

    object_key = spec.catalog.object_key
    errors = _field_errors(spec, runtime_config)
    if errors:
        return _CandidateValidationResult(normalized_config={}, errors=errors, diff=[])

    candidate = {field.key: runtime_config[field.key] for field in spec.editable_fields if field.key in runtime_config}
    daily_config = dict(records[STOCK_RT_DAILY_OBJECT_KEY].runtime_config_json)
    minute_config = dict(records[STOCK_RT_MIN_OBJECT_KEY].runtime_config_json)
    if object_key == STOCK_RT_DAILY_OBJECT_KEY:
        daily_config = candidate
    else:
        minute_config = candidate

    try:
        runtime = build_realtime_runtime_config_from_json(
            daily_config=daily_config,
            minute_config=minute_config,
        )
    except RealtimeRuntimeConfigError as exc:
        return _CandidateValidationResult(
            normalized_config=candidate,
            errors=[RealtimeConfigValidationErrorItem(code="validation_error", message=str(exc))],
            diff=[],
        )

    normalized = _effective_config_for_object(spec, runtime)
    current_runtime = _build_valid_runtime_config(records)
    current = _effective_config_for_object(spec, current_runtime)
    return _CandidateValidationResult(
        normalized_config=normalized,
        errors=[],
        diff=[
            RealtimeConfigDiffItem(field=field.key, before=current.get(field.key), after=normalized.get(field.key))
            for field in spec.editable_fields
            if current.get(field.key) != normalized.get(field.key)
        ],
    )


def _field_errors(
    spec: _RealtimeConfigObjectSpec,
    runtime_config: dict[str, Any],
) -> list[RealtimeConfigValidationErrorItem]:
    editable_keys = spec.editable_keys
    locked_keys = set(spec.locked_fields)
    errors: list[RealtimeConfigValidationErrorItem] = []
    for key in runtime_config:
        if key in locked_keys:
            errors.append(
                RealtimeConfigValidationErrorItem(
                    field=key,
                    code="locked_field",
                    message=f"{key} 是锁定配置项，不能通过配置中心发布修改",
                )
            )
        elif key not in editable_keys:
            errors.append(
                RealtimeConfigValidationErrorItem(
                    field=key,
                    code="unknown_field",
                    message=f"{key} 不是可编辑配置项",
                )
            )
    if spec.catalog.object_key == STOCK_RT_MIN_OBJECT_KEY and "enabled_freqs" in runtime_config and not isinstance(
        runtime_config["enabled_freqs"],
        list,
    ):
        errors.append(
            RealtimeConfigValidationErrorItem(
                field="enabled_freqs",
                code="validation_error",
                message="enabled_freqs 必须使用数组提交",
            )
        )
    return errors


def _object_summary(
    spec: _RealtimeConfigObjectSpec,
    record: RealtimeRuntimeConfigRecord,
    runtime: Any,
) -> RealtimeConfigObjectSummary:
    config = _effective_config_for_object(spec, runtime)
    return RealtimeConfigObjectSummary(
        object_key=record.object_key,
        object_kind=record.object_kind,
        display_name=spec.catalog.display_name,
        enabled=bool(config.get("enabled")),
        version=record.version,
        requires_collector_restart=record.requires_collector_restart,
    )


def _object_detail(
    spec: _RealtimeConfigObjectSpec,
    record: RealtimeRuntimeConfigRecord,
    runtime: Any,
) -> RealtimeConfigObjectDetailResponse:
    return RealtimeConfigObjectDetailResponse(
        object_key=record.object_key,
        display_name=spec.catalog.display_name,
        object_kind=record.object_kind,
        version=record.version,
        requires_collector_restart=record.requires_collector_restart,
        effective_config=_effective_config_for_object(spec, runtime),
        locked_config=_locked_config_for_spec(spec),
        fields=[
            RealtimeConfigField(
                key=field.key,
                label=field.label,
                editable=True,
                control=field.control,
                value_type=field.value_type,
                options=list(field.options),
            )
            for field in spec.editable_fields
        ]
        + [
            RealtimeConfigField(
                key=key,
                label=_locked_field_label(key),
                editable=False,
                control="locked_text",
                value_type="string",
            )
            for key in spec.locked_fields
        ],
    )


def _effective_config_for_object(
    spec: _RealtimeConfigObjectSpec,
    runtime: Any,
) -> dict[str, Any]:
    if spec.catalog.object_key == STOCK_RT_DAILY_OBJECT_KEY:
        config = runtime.stock_rt_daily
        return {
            "enabled": config.enabled,
            "poll_interval_seconds": config.poll_interval_seconds,
            "max_calls_per_minute": config.max_calls_per_minute,
            "lease_ttl_seconds": config.lease_ttl_seconds,
            "stale_after_seconds": config.stale_after_seconds,
            "snapshot_ttl_seconds": config.storage.snapshot_ttl_seconds,
            "keep_recent_batches": config.storage.keep_recent_batches,
            "batch_stream_maxlen": config.storage.batch_stream_maxlen,
            "delta_stream_maxlen": config.storage.delta_stream_maxlen,
        }

    config = runtime.stock_rt_min
    return {
        "enabled": config.enabled,
        "enabled_freqs": list(config.enabled_freqs),
        "poll_interval_seconds": config.poll_interval_seconds,
        "max_calls_per_minute": config.max_calls_per_minute,
        "lease_ttl_seconds": config.lease_ttl_seconds,
        "stale_after_seconds": config.stale_after_seconds,
        "snapshot_ttl_seconds": config.storage.snapshot_ttl_seconds,
        "keep_recent_batches": config.storage.keep_recent_batches,
        "batch_stream_maxlen": config.storage.batch_stream_maxlen,
        "delta_stream_maxlen": config.storage.delta_stream_maxlen,
        "source_timeout_seconds": config.source_timeout_seconds,
    }


def _locked_config_for_spec(spec: _RealtimeConfigObjectSpec) -> dict[str, Any]:
    catalog = spec.catalog
    payload: dict[str, Any] = {
        "source_api_name": catalog.source_api_name,
        "exchange": catalog.exchange,
        "collection_sessions": catalog.collection_sessions,
        "ts_code_pattern": catalog.ts_code_pattern,
    }
    if catalog.feed_key:
        payload["feed_key"] = catalog.feed_key
    if catalog.feed_key_prefix:
        payload["feed_key_pattern"] = f"{catalog.feed_key_prefix}" + "_{freq}"
    return payload


def _locked_field_label(key: str) -> str:
    return {
        "source_api_name": "源接口",
        "exchange": "交易所",
        "collection_sessions": "采集时段",
        "ts_code_pattern": "源站请求范围",
        "feed_key": "Redis Feed Key",
        "feed_key_pattern": "Redis Feed Key 规则",
    }.get(key, key)


def _impact_for_spec(spec: _RealtimeConfigObjectSpec) -> RealtimeConfigImpact:
    if spec.catalog.object_key == STOCK_RT_DAILY_OBJECT_KEY:
        affected_feeds = [STOCK_RT_DAILY_CATALOG.feed_key or ""]
    else:
        affected_feeds = [f"{STOCK_RT_MIN_FEED_KEY_PREFIX}_{freq.lower()}" for freq in STOCK_RT_MIN_ALLOWED_FREQS]
    return RealtimeConfigImpact(
        requires_collector_restart=True,
        affected_feeds=[feed_key for feed_key in affected_feeds if feed_key],
    )


def _restart_warnings() -> list[RealtimeConfigWarningItem]:
    return [RealtimeConfigWarningItem(message=PUBLISH_RESTART_MESSAGE)]


def _record_snapshot(record: RealtimeRuntimeConfigRecord) -> dict[str, Any]:
    return {
        "object_key": record.object_key,
        "object_kind": record.object_kind,
        "runtime_config_json": dict(record.runtime_config_json or {}),
        "version": record.version,
        "requires_collector_restart": record.requires_collector_restart,
        "updated_by_user_id": record.updated_by_user_id,
    }
