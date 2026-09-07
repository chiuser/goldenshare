"""Bounded manual event reconciliation for an already-published fixed file.

No asset execution, Parquet writer, source requests or default instance discovery.
Uncertain event writes require reconciliation, never an automatic retry.
"""

import math
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import dagster as dg
import yaml
from dagster._config import process_config
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.instance.ref import InstanceRef
from dagster._core.instance.types import InstanceType
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)
from dagster._core.storage.config import pg_config
from dagster._core.storage.root import LocalArtifactStorage
from dagster._serdes import ConfigurableClassData
from dagster_postgres import (
    PostgresEventLogStorage,
    PostgresRunStorage,
    PostgresScheduleStorage,
)
from dagster_postgres.utils import pg_url_from_config
from sqlalchemy.engine import make_url

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.bootstrap import stock_suspend_confirmed as publication
from orchestrator.defs.run_contracts import metadata as keys

_INSTANCE_HOME = Path("/Users/congming/.goldenshare/dagster_home")
_HISTORY_LIMIT = 10
_SMALL_DOCUMENT_BYTES = 1024 * 1024


def _existing_directory(path):
    publication._absolute(path)
    contract.assert_suspend_path(path, root=Path(path.anchor))
    if not path.is_dir():
        publication._fail("instance_directory_missing", exit_code=2)


def _storage_identity(url):
    parsed = make_url(url)
    if (parsed.drivername not in ("postgresql", "postgresql+psycopg2")
            or parsed.host not in ("localhost", "127.0.0.1", "::1") or parsed.query
            or not parsed.database or not parsed.username):
        publication._fail("unsupported_instance_storage", exit_code=2)
    # Passwords never leave this adapter. Reject URL options that can redirect IO.
    return parsed.set(drivername="postgresql", port=parsed.port or 5432)._replace(password=None).render_as_string()


def _instance_configuration(plan):
    home = Path(plan.instance_home)
    if home != _INSTANCE_HOME:
        publication._fail("instance_home_mismatch", exit_code=2)
    _existing_directory(home)
    path = home / "dagster.yaml"
    contract.assert_suspend_path(path, root=home)
    before = contract.suspend_file_identity(path)
    if before.size > _SMALL_DOCUMENT_BYTES:
        publication._fail("instance_config_too_large", exit_code=2)
    with path.open("rb") as stream:
        payload = stream.read(_SMALL_DOCUMENT_BYTES + 1)
    if len(payload) > _SMALL_DOCUMENT_BYTES or contract.suspend_file_identity(path) != before:
        publication._fail("instance_config_changed")
    config = yaml.safe_load(payload)
    if (type(config) is not dict or "instance_class" in config
            or any(name in config for name in ("run_storage", "event_log_storage", "schedule_storage"))):
        publication._fail("unsupported_instance_configuration", exit_code=2)
    publication._keys(config.get("storage"), ("postgres",))
    postgres = config["storage"]["postgres"]
    if type(postgres) is not dict or "auth" in postgres:
        publication._fail("unsupported_instance_storage", exit_code=2)
    resolved = process_config(pg_config(), postgres)
    if not resolved.success:
        publication._fail("invalid_instance_storage_config", exit_code=2)
    url = pg_url_from_config(resolved.value)
    identity = _storage_identity(url)
    if dict(plan.storage_identity) != dict.fromkeys(("event", "run", "schedule"), identity):
        publication._fail("instance_storage_identity_mismatch")
    artifact = config.get("local_artifact_storage")
    if (type(artifact) is not dict or artifact.get("module") not in (
            "dagster.core.storage.root", "dagster._core.storage.root")
            or artifact.get("class") != "LocalArtifactStorage"):
        publication._fail("unsupported_instance_artifact_storage", exit_code=2)
    publication._keys(artifact.get("config"), ("base_dir",))
    artifact_root = Path(artifact["config"]["base_dir"])
    _existing_directory(artifact_root)
    evidence = publication.FileEvidence(before, sha256(payload).hexdigest())
    publication._verify_evidence(evidence)
    return url, artifact_root, evidence


def verify_confirmed_instance(instance, *, plan):
    """Validate actual, already-constructed storage URLs, without opening a DB."""
    if type(instance) is not dg.DagsterInstance or not instance.is_persistent:
        publication._fail("instance_type_mismatch")
    _, artifact_root, _ = _instance_configuration(plan)
    if instance.root_directory != str(artifact_root):
        publication._fail("instance_artifact_identity_mismatch")
    for name, storage, expected_type in (
        ("event", instance.event_log_storage, PostgresEventLogStorage),
        ("run", instance.run_storage, PostgresRunStorage),
        ("schedule", instance.schedule_storage, PostgresScheduleStorage),
    ):
        if (type(storage) is not expected_type or storage.should_autocreate_tables is not False
                or _storage_identity(storage.postgres_url) != dict(plan.storage_identity)[name]):
            publication._fail("instance_storage_identity_mismatch")


@contextmanager
def open_confirmed_event_instance(*, plan):
    """Existing local PG storage only; no get/from_ref, DDL, logs or launchers."""
    publication._verify_plan(plan)
    url, artifact_root, config_evidence = _instance_configuration(plan)
    # Build inert descriptors from the validated bytes. Do not reread the YAML
    # through from_dir: a changed custom class could be imported before recheck.
    ref = InstanceRef(
        local_artifact_storage_data=ConfigurableClassData(
            "dagster._core.storage.root", "LocalArtifactStorage", yaml.safe_dump({"base_dir": str(artifact_root)})),
        compute_logs_data=ConfigurableClassData("dagster._core.storage.noop_compute_log_manager", "NoOpComputeLogManager", "{}"),
        scheduler_data=None, run_coordinator_data=None, run_launcher_data=None,
        settings={"telemetry": {"enabled": False}}, run_storage_data=None,
        event_storage_data=None, schedule_storage_data=None,
    )
    with ExitStack() as stack:
        stores = []
        for storage_type in (PostgresRunStorage, PostgresEventLogStorage, PostgresScheduleStorage):
            storage = storage_type(url, should_autocreate_tables=False)
            stack.callback(storage.dispose)
            stores.append(storage)
        instance = dg.DagsterInstance(
            instance_type=InstanceType.PERSISTENT, local_artifact_storage=LocalArtifactStorage(str(artifact_root)),
            run_storage=stores[0], event_storage=stores[1], schedule_storage=stores[2],
            compute_log_manager=None, run_coordinator=None, run_launcher=None,
            settings={"telemetry": {"enabled": False}}, ref=ref,
        )
        verify_confirmed_instance(instance, plan=plan)
        publication._verify_evidence(config_evidence)
        yield instance


def _kinds():
    return ("materialization", *contract.STOCK_SUSPEND_CONFIRMED_CHECKS)


def _token(kind):
    return (f"stock_suspend_confirmed:{contract.STOCK_SUSPEND_CONFIRMED_VERSION}:"
            f"{contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256}:{kind}")


def _identity_metadata():
    return {keys.CONFIRMED_FACT_VERSION_METADATA_KEY: contract.STOCK_SUSPEND_CONFIRMED_VERSION,
            keys.CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY: contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256}


@dataclass(frozen=True)
class EventRecordIdentity:
    # For materialization this is event storage_id; for a check it is execution id.
    kind: str
    record_id: int
    run_id: str
    timestamp: float


@dataclass(frozen=True)
class EventAudit:
    plan_sha256: str
    file_evidence: publication.FileEvidence
    records: tuple[EventRecordIdentity | None, ...]
    pending_found: tuple[str, ...]
    uncertain: tuple[str, ...]

    @property
    def complete(self):
        return all(self.records) and not self.uncertain


@dataclass(frozen=True)
class EventPublishResult:
    status: str
    file_committed: bool
    events_complete: bool
    written_events: int


def _checkpoint_base(plan):
    return {"schema_version": 1, "operation_id": plan.paths.operation_id, "plan_sha256": plan.sha256,
            "target_path": str(plan.paths.target), "instance_home": plan.instance_home,
            "storage_identity": dict(plan.storage_identity), **_identity_metadata()}


def _read_checkpoint(plan):
    path = plan.paths.events_checkpoint
    contract.assert_suspend_path(path, root=plan.paths.operation_dir)
    if not path.exists():
        return {**_checkpoint_base(plan), "entries": {}}
    if contract.suspend_file_identity(path).size > _SMALL_DOCUMENT_BYTES:
        publication._fail("event_checkpoint_too_large")
    value, _ = publication._read_json(path)
    base = _checkpoint_base(plan)
    publication._keys(value, (*base, "entries"))
    if type(value["schema_version"]) is not int or any(value[key] != expected for key, expected in base.items()):
        publication._fail("event_checkpoint_identity_mismatch")
    entries = value["entries"]
    if type(entries) is not dict or not set(entries).issubset(_kinds()):
        publication._fail("event_checkpoint_entries_invalid")
    for kind, item in entries.items():
        publication._keys(item, ("token", "state", "record"))
        if item["token"] != _token(kind) or item["state"] not in ("pending", "confirmed", "uncertain"):
            publication._fail("event_checkpoint_entry_invalid")
        record = item["record"]
        if item["state"] != "confirmed":
            if record is not None:
                publication._fail("event_checkpoint_entry_invalid")
        else:
            publication._keys(record, ("kind", "record_id", "run_id", "timestamp"))
            if (record["kind"] != kind or type(record["record_id"]) is not int or record["record_id"] <= 0
                    or type(record["run_id"]) is not str or type(record["timestamp"]) not in (int, float)
                    or not math.isfinite(record["timestamp"]) or record["timestamp"] <= 0):
                publication._fail("event_checkpoint_record_invalid")
    return value


def _metadata_matches(metadata, expected):
    return all(getattr(metadata.get(key), "value", None) == value for key, value in expected.items())


def _read_event_records(instance, plan):
    asset = dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY)
    materializations = instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=asset), limit=_HISTORY_LIMIT).records
    if len(materializations) > 1:
        publication._fail("multiple_confirmed_publications")
    result = []
    mat_identity = None
    if materializations:
        record = materializations[0]
        mat = record.asset_materialization
        source = dict(plan.source)
        expected = {
            **_identity_metadata(), keys.DAGSTER_URI_METADATA_KEY: str(plan.paths.target),
            keys.DAGSTER_ROW_COUNT_METADATA_KEY: contract.STOCK_SUSPEND_CONFIRMED_COUNTS[0],
            keys.OBSERVED_COLUMNS_METADATA_KEY: list(contract.CONFIRMED_COLUMNS),
            keys.CONFIRMED_FACT_SOURCE_REVISION_METADATA_KEY: source["csv_revision"],
            keys.CONFIRMED_FACT_SOURCE_SHA256_METADATA_KEY: source["csv_sha256"],
            keys.CONFIRMED_FACT_CALENDAR_SHA256_METADATA_KEY: source["expansion_calendar_sha256"],
        }
        if (mat.asset_key != asset or mat.partition is not None or not _metadata_matches(
                mat.metadata, expected)):
            publication._fail("publication_identity_mismatch")
        token = getattr(mat.metadata.get(keys.CONFIRMED_FACT_EVENT_TOKEN_METADATA_KEY), "value", None)
        operation = getattr(mat.metadata.get(keys.CONFIRMED_FACT_OPERATION_ID_METADATA_KEY), "value", None)
        if token != _token("materialization") or type(operation) is not str:
            publication._fail("publication_token_mismatch")
        # An equivalent prior operation can be reused, but it must be a real,
        # well-formed manual publication, not an incomplete synthetic green.
        publication.PublicationPaths(plan.paths.lake_root, plan.paths.staging_root, operation)
        mat_identity = EventRecordIdentity("materialization", record.storage_id, record.event_log_entry.run_id, record.timestamp)
        result.append([(mat_identity, token)])
    else:
        result.append([])
    for kind in contract.STOCK_SUSPEND_CONFIRMED_CHECKS:
        history = instance.event_log_storage.get_asset_check_execution_history(dg.AssetCheckKey(asset, kind), limit=_HISTORY_LIMIT)
        checked = []
        for index, record in enumerate(history):
            event = record.event
            evaluation = event.dagster_event.event_specific_data if event and event.dagster_event else None
            target = getattr(evaluation, "target_materialization_data", None)
            valid = bool(mat_identity and evaluation and target
                         and record.status == AssetCheckExecutionRecordStatus.SUCCEEDED
                         and record.partition is None and evaluation.partition is None
                         and evaluation.asset_key == asset and evaluation.check_name == kind
                         and evaluation.passed and evaluation.blocking and evaluation.severity == dg.AssetCheckSeverity.ERROR
                         and (target.storage_id, target.run_id, target.timestamp) == (
                             mat_identity.record_id, mat_identity.run_id, mat_identity.timestamp)
                         and _metadata_matches(evaluation.metadata, _identity_metadata()))
            token = getattr(getattr(evaluation, "metadata", {}).get(keys.CONFIRMED_FACT_EVENT_TOKEN_METADATA_KEY), "value", None)
            if not valid and (index == 0 or token is not None):
                publication._fail("existing_check_not_valid", kind)
            if token not in (None, _token(kind)):
                publication._fail("check_token_mismatch", kind)
            if valid:
                checked.append((EventRecordIdentity(kind, record.id, event.run_id, event.timestamp), token))
        if sum(token == _token(kind) for _, token in checked) > 1:
            publication._fail("duplicate_event_token", kind)
        result.append(checked)
    return result


def audit_confirmed_events(instance, connection, *, plan):
    publication._verify_plan(plan)
    before = publication._bounded_file_identity(plan.paths.target)
    evidence = publication.FileEvidence(before, contract.suspend_file_sha256(plan.paths.target))
    if publication._inspect_file(connection, plan.paths.target) != "approved":
        publication._fail("published_file_missing", exit_code=3)
    verify_confirmed_instance(instance, plan=plan)
    checkpoint = _read_checkpoint(plan)
    history = _read_event_records(instance, plan)
    pending_found, uncertain = [], []
    for kind, records in zip(_kinds(), history, strict=True):
        entry = checkpoint["entries"].get(kind)
        if entry is None:
            continue
        if entry["state"] == "confirmed":
            if not any(asdict(record) == entry["record"] and token == _token(kind) for record, token in records):
                publication._fail("confirmed_event_outside_window_or_changed", kind)
        elif any(token == _token(kind) for _, token in records):
            pending_found.append(kind)
        else:
            uncertain.append(kind)
    publication._verify_evidence(evidence)
    publication._verify_plan(plan)
    return EventAudit(plan.sha256, evidence, tuple(records[0][0] if records else None for records in history),
                      tuple(pending_found), tuple(uncertain))


def _build_event(kind, plan, materialization):
    identity = {**_identity_metadata(), keys.CONFIRMED_FACT_OPERATION_ID_METADATA_KEY: plan.paths.operation_id,
                keys.CONFIRMED_FACT_EVENT_TOKEN_METADATA_KEY: _token(kind)}
    asset = dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY)
    if kind == "materialization":
        source = dict(plan.source)
        return dg.AssetMaterialization(asset_key=asset, partition=None, metadata=keys.build_materialization_metadata(
            uri=plan.paths.target, row_count=contract.STOCK_SUSPEND_CONFIRMED_COUNTS[0],
            observed_columns=contract.CONFIRMED_COLUMNS,
            extra_metadata={**identity, keys.CONFIRMED_FACT_SOURCE_REVISION_METADATA_KEY: source["csv_revision"],
                            keys.CONFIRMED_FACT_SOURCE_SHA256_METADATA_KEY: source["csv_sha256"],
                            keys.CONFIRMED_FACT_CALENDAR_SHA256_METADATA_KEY: source["expansion_calendar_sha256"]}))
    return AssetCheckEvaluation(
        asset_key=asset, check_name=kind, passed=True, blocking=True, partition=None, severity=dg.AssetCheckSeverity.ERROR,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=materialization.record_id, run_id=materialization.run_id, timestamp=materialization.timestamp),
        metadata=keys.build_check_metadata(
            check_scope=keys.CheckScope.SCHEMA if kind == contract.STOCK_SUSPEND_CONFIRMED_CHECKS[0] else keys.CheckScope.RECONCILIATION,
            file_path=plan.paths.target, checked_row_count=contract.STOCK_SUSPEND_CONFIRMED_COUNTS[0], failed_row_count=0,
            extra_metadata=identity))


def _save_entry(plan, checkpoint, kind, state, record=None):
    checkpoint["entries"][kind] = {"token": _token(kind), "state": state,
                                    "record": asdict(record) if record else None}
    try:
        publication._save_json(plan.paths, plan.paths.events_checkpoint, checkpoint)
    except OSError as error:
        publication._fail("event_checkpoint_write_failed", type(error).__name__, 5)


def register_confirmed_events(instance, connection, *, plan, audit):
    current = audit_confirmed_events(instance, connection, plan=plan)
    if current != audit:
        publication._fail("event_audit_changed")
    checkpoint = _read_checkpoint(plan)
    written = 0
    if current.uncertain:
        for kind in current.uncertain:
            _save_entry(plan, checkpoint, kind, "uncertain")
        publication._fail("event_result_uncertain", exit_code=5)
    for index, kind in enumerate(_kinds()):
        if kind in current.uncertain:
            _save_entry(plan, checkpoint, kind, "uncertain")
            publication._fail("event_result_uncertain", kind, 5)
        if current.records[index] is not None:
            if kind in current.pending_found:
                # Recover the actual token record, which may precede a daily check.
                records = _read_event_records(instance, plan)[index]
                record = next(record for record, token in records if token == _token(kind))
                _save_entry(plan, checkpoint, kind, "confirmed", record)
            continue
        _save_entry(plan, checkpoint, kind, "pending")
        publication._verify_evidence(current.file_evidence)
        publication._verify_plan(plan)
        try:
            instance.report_runless_asset_event(_build_event(kind, plan, current.records[0]))
            written += 1
            observed = audit_confirmed_events(instance, connection, plan=plan)
            if kind not in observed.pending_found:
                publication._fail("event_readback_missing", kind, 5)
            _save_entry(plan, checkpoint, kind, "confirmed", observed.records[index])
        except Exception as error:  # noqa: BLE001 -- any attempted write may have committed.
            # Keep pending if recording uncertain also fails; never repeat the API.
            try:
                _save_entry(plan, checkpoint, kind, "uncertain")
            except Exception as checkpoint_error:  # noqa: BLE001
                publication._fail("event_result_and_checkpoint_uncertain", type(checkpoint_error).__name__, 5)
            publication._fail("event_result_uncertain", type(error).__name__, 5)
        current = observed
        print(f'{{"event_completed":{index + 1},"event_total":3}}', flush=True)
    final = audit_confirmed_events(instance, connection, plan=plan)
    if not final.complete:
        publication._fail("events_incomplete", exit_code=5)
    return EventPublishResult("published" if written else "reused", True, True, written)
