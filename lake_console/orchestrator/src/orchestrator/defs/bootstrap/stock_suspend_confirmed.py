"""Manual, single-publisher suspension migration: file facts only, never events.

Plans are prepared separately and approved by their exact byte hash. This module
does not discover dates, read CSV/Git, create connections, or invoke asset jobs.
"""

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from itertools import groupby
from pathlib import Path
from uuid import uuid4

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.duckdb_sql import (
    silver_stock_suspend_daily_select,
    stock_suspend_confirmed_conflicts_select,
    suspend_d_normalized_relation_select,
)
from orchestrator.defs.paths import (
    raw_suspend_d_path,
    silver_stock_suspend_confirmed_path,
    silver_stock_suspend_daily_path,
    stock_suspend_confirmed_staging_dir,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
)

_MAX_JSON_BYTES = 100 * 1024 * 1024
_MAX_INPUT_FILE_BYTES = 100 * 1024 * 1024
_MAX_BATCH_DATES = 366
_RELATIONS = {"normalized_relation": "migration_normalized",
              "confirmed_relation": "migration_confirmed", "dates_relation": "migration_dates"}


def _fail(reason: str, details="", exit_code: int = 4):
    raise contract.ConfirmedFactsError(f"停牌人工发布未完成：{reason}；{details}", reason, exit_code)


def _absolute(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        _fail("invalid_path", path, 2)


@dataclass(frozen=True)
class PublicationPaths:
    lake_root: Path
    staging_root: Path
    operation_id: str

    def __post_init__(self):
        _absolute(self.lake_root)
        _absolute(self.staging_root)
        if (self.lake_root.is_relative_to(self.staging_root)
                or self.staging_root.is_relative_to(self.lake_root)):
            _fail("overlapping_roots", exit_code=2)
        stock_suspend_confirmed_staging_dir(self.staging_root, self.operation_id)

    @property
    def operation_dir(self):
        return stock_suspend_confirmed_staging_dir(self.staging_root, self.operation_id)

    @property
    def candidate(self):
        return self.operation_dir / "candidate" / "part-000.parquet"

    @property
    def target(self):
        return silver_stock_suspend_confirmed_path(self.lake_root)

    @property
    def plan(self):
        return self.operation_dir / "plan.json"

    @property
    def comparison(self):
        return self.operation_dir / "comparison.json"

    @property
    def checkpoint(self):
        return self.operation_dir / "file-checkpoint.json"

    @property
    def events_checkpoint(self):
        return self.operation_dir / "events-checkpoint.json"

    def check(self):
        for path, root in ((self.operation_dir, self.staging_root), (self.target, self.lake_root)):
            contract.assert_suspend_path(path, root=root)
        if not self.operation_dir.is_dir():
            _fail("operation_directory_missing", exit_code=2)


@dataclass(frozen=True)
class FileEvidence:
    identity: contract.FileIdentity
    sha256: str


@dataclass(frozen=True)
class FrozenPartition:
    trade_date: str
    raw: FileEvidence
    silver: FileEvidence


@dataclass(frozen=True)
class FrozenMigrationPlan:
    paths: PublicationPaths
    sha256: str
    code_revision: str
    source: tuple[tuple[str, str], ...]
    calendar_dates: tuple[str, ...]
    calendar_sha256: str
    candidate: FileEvidence
    partitions: tuple[FrozenPartition, ...]
    instance_home: str
    storage_identity: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ComparisonBatch:
    year: str
    dates: tuple[str, ...]
    raw_rows: int
    silver_rows: int
    output_rows: int
    added_rows: int
    missing_rows: int
    samples: tuple[dict, ...]
    elapsed_ms: int


@dataclass(frozen=True)
class MigrationComparison:
    plan_sha256: str
    logical_sha256: str
    batches: tuple[ComparisonBatch, ...]
    report_sha256: str | None = None

    @property
    def passed(self):
        return bool(self.batches) and all(b.added_rows == b.missing_rows == 0 for b in self.batches)

    def payload(self):
        return {"schema_version": 1, "plan_sha256": self.plan_sha256,
                "logical_sha256": self.logical_sha256, "batches": [asdict(b) for b in self.batches]}


@dataclass(frozen=True)
class PublicationInspection:
    plan_sha256: str
    candidate_status: str
    target_status: str
    comparison_status: str
    next_action: str


@dataclass(frozen=True)
class FilePublishResult:
    status: str
    target_path: str
    file_committed: bool
    events_complete: bool = False


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        _fail("invalid_document_fields", exit_code=2)


def _hash(value, length=64):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value):
        _fail("invalid_hash", exit_code=2)
    return value


def _integer(value):
    if type(value) is not int or value < 0:
        _fail("invalid_integer", exit_code=2)
    return value


def _dates(value):
    if type(value) is not list or not value:
        _fail("invalid_dates", exit_code=2)
    for item in value:
        if type(item) is not str or date.fromisoformat(item).isoformat() != item:
            _fail("invalid_dates", exit_code=2)
    if value != sorted(set(value)):
        _fail("duplicate_or_unsorted_dates", exit_code=2)
    return tuple(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_document_key", key, 2)
        result[key] = value
    return result


def _read_json(path, expected_sha256=None):
    if expected_sha256 is not None:
        _hash(expected_sha256)
    before = contract.suspend_file_identity(path)
    if before.size > _MAX_JSON_BYTES:
        _fail("document_too_large", path, 2)
    with path.open("rb") as stream:
        payload = stream.read(_MAX_JSON_BYTES + 1)
    if len(payload) > _MAX_JSON_BYTES or contract.suspend_file_identity(path) != before:
        _fail("document_changed", path)
    digest = sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        _fail("document_hash_mismatch", path)
    value = json.loads(payload, object_pairs_hook=_unique_object,
                       parse_constant=lambda token: _fail("invalid_json_number", token, 2))
    return value, digest


def _parse_evidence(value, expected_path):
    _keys(value, ("path", "device", "inode", "size", "mtime_ns", "sha256"))
    if value["path"] != str(expected_path):
        _fail("unexpected_input_path", value["path"], 2)
    identity = contract.FileIdentity(value["path"], *(
        _integer(value[key]) for key in ("device", "inode", "size", "mtime_ns")))
    if identity.size > _MAX_INPUT_FILE_BYTES:
        _fail("input_too_large", expected_path, 3)
    return FileEvidence(identity, _hash(value["sha256"]))


def read_confirmed_plan(*, paths: PublicationPaths, expected_plan_sha256=None) -> FrozenMigrationPlan:
    paths.check()
    value, digest = _read_json(paths.plan, expected_plan_sha256)
    _keys(value, ("schema_version", "operation_id", "code_revision", "source", "calendar_dates",
                  "calendar_sha256", "confirmed", "partitions", "target_path", "instance"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        _fail("plan_version_mismatch", exit_code=2)
    if value["operation_id"] != paths.operation_id or value["target_path"] != str(paths.target):
        _fail("plan_target_mismatch", exit_code=2)
    revision = _hash(value["code_revision"], 40)
    source = value["source"]
    _keys(source, ("csv_revision", "csv_blob", "csv_sha256", "expansion_calendar_sha256"))
    for key in source:
        _hash(source[key], 40 if key in ("csv_revision", "csv_blob") else 64)
    calendar = _dates(value["calendar_dates"])
    calendar_hash = sha256(("stock_suspend_confirmed_calendar|v1\n" + "".join(
        f"SSE\t{day}\n" for day in calendar)).encode()).hexdigest()
    if _hash(value["calendar_sha256"]) != calendar_hash:
        _fail("calendar_hash_mismatch")
    facts = value["confirmed"]
    _keys(facts, ("version", "logical_sha256", "counts", "override_keys", "candidate"))
    if (facts["version"] != contract.STOCK_SUSPEND_CONFIRMED_VERSION
            or facts["logical_sha256"] != contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256
            or type(facts["counts"]) is not list
            or any(type(v) is not int for v in facts["counts"])
            or facts["counts"] != list(contract.STOCK_SUSPEND_CONFIRMED_COUNTS)
            or facts["override_keys"] != [list(key) for key in contract.STOCK_SUSPEND_CONFIRMED_OVERRIDE_KEYS]):
        _fail("plan_approved_content_mismatch", exit_code=3)
    candidate = _parse_evidence(facts["candidate"], paths.candidate)
    if type(value["partitions"]) is not list:
        _fail("invalid_partitions", exit_code=2)
    partitions = []
    for item in value["partitions"]:
        _keys(item, ("trade_date", "raw", "silver"))
        day = _dates([item["trade_date"]])[0]
        partitions.append(FrozenPartition(
            day, _parse_evidence(item["raw"], raw_suspend_d_path(paths.lake_root, day)),
            _parse_evidence(item["silver"], silver_stock_suspend_daily_path(paths.lake_root, day))))
    days = _dates([p.trade_date for p in partitions])
    if not set(days).issubset(calendar):
        _fail("non_calendar_partition", exit_code=3)
    instance = value["instance"]
    _keys(instance, ("home_path", "storage_identity"))
    _absolute(Path(instance["home_path"]))
    _keys(instance["storage_identity"], ("event", "run", "schedule"))
    if any(type(v) is not str or not v or len(v) > 512 for v in instance["storage_identity"].values()):
        _fail("invalid_instance_identity", exit_code=2)
    return FrozenMigrationPlan(paths, digest, revision, tuple(sorted(source.items())), calendar, calendar_hash,
                               candidate, tuple(partitions), instance["home_path"],
                               tuple(sorted(instance["storage_identity"].items())))


def _verify_plan(plan):
    if read_confirmed_plan(paths=plan.paths, expected_plan_sha256=plan.sha256) != plan:
        _fail("plan_object_mismatch")


def _verify_evidence(evidence):
    path = Path(evidence.identity.path)
    before = contract.suspend_file_identity(path)
    if before != evidence.identity or contract.suspend_file_sha256(path) != evidence.sha256:
        _fail("input_drift", path)
    if contract.suspend_file_identity(path) != before:
        _fail("input_drift", path)


def _bounded_file_identity(path):
    identity = contract.suspend_file_identity(path)
    if identity.size > _MAX_INPUT_FILE_BYTES:
        _fail("input_too_large", path, 3)
    return identity


def _batch_partitions(plan):
    for year, grouped in groupby(plan.partitions, key=lambda part: part.trade_date[:4]):
        parts = tuple(grouped)
        if len(parts) > _MAX_BATCH_DATES:
            _fail("batch_date_limit", year, 2)
        yield year, parts


def _load_fixed(connection, plan, *, allow_target):
    contract.assert_suspend_path(plan.paths.candidate, root=plan.paths.staging_root)
    candidate_exists = plan.paths.candidate.exists()
    if candidate_exists:
        _verify_evidence(plan.candidate)
        path = plan.paths.candidate
    elif allow_target:
        path = plan.paths.target
    else:
        _fail("candidate_missing", exit_code=3)
    before = _bounded_file_identity(path)
    fingerprint = contract.suspend_file_sha256(path)
    inspection = contract.inspect_confirmed_file(connection, path)
    contract.load_confirmed_relation(connection, inspection, relation_name="migration_confirmed")
    contract.confirmed_facts_summary(connection, "migration_confirmed")
    unknown_dates = connection.execute(
        "SELECT count(*) FROM migration_confirmed WHERE trade_date NOT IN (SELECT unnest(?)::DATE)",
        [list(plan.calendar_dates)],
    ).fetchone()[0]
    if unknown_dates:
        _fail("confirmed_date_outside_calendar", exit_code=3)
    if (contract.suspend_file_identity(path) != before
            or contract.suspend_file_sha256(path) != fingerprint):
        _fail("input_drift", path)
    if candidate_exists:
        _verify_evidence(plan.candidate)
    return FileEvidence(before, fingerprint)


def _check_batch_schema(connection, evidences, schema):
    paths = [e.identity.path for e in evidences]
    rows = connection.execute(
        "SELECT file_name, name, upper(duckdb_type) FROM parquet_schema(?) "
        "WHERE column_id > 0 ORDER BY file_name, column_id", [paths],
    ).fetchall()
    observed = {path: [] for path in paths}
    for file_name, name, kind in rows:
        if file_name not in observed:
            _fail("unexpected_schema_file", file_name)
        observed[file_name].append((name, kind))
    expected = [(c.name, c.type) for c in schema]
    wrong = [path for path, columns in observed.items() if columns != expected]
    if wrong:
        _fail("input_schema_mismatch", wrong[:contract.CONFIRMED_SAMPLE_LIMIT], 3)


def _load_comparison_batch(connection, parts):
    for layer, schema in (("raw", RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA),
                          ("silver", SILVER_STOCK_SUSPEND_DAILY_SCHEMA)):
        evidences = [getattr(p, layer) for p in parts]
        _check_batch_schema(connection, evidences, schema)
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE migration_{layer} AS SELECT * FROM "
            "read_parquet(?, hive_partitioning=false, filename=true)",
            [[e.identity.path for e in evidences]],
        )
        date_sql = "try_strptime(trade_date, '%Y%m%d')::DATE" if layer == "raw" else "trade_date"
        bad = connection.execute(
            f"SELECT count(*) FROM migration_{layer} WHERE {date_sql} IS DISTINCT FROM "
            "CAST(regexp_extract(filename, 'trade_date=([0-9-]+)/part-000.parquet$', 1) AS DATE)"
        ).fetchone()[0]
        if bad:
            _fail("input_partition_date_mismatch", {"layer": layer, "rows": bad}, 3)
    connection.execute("CREATE OR REPLACE TEMP TABLE migration_dates AS SELECT unnest(?)::DATE trade_date",
                       [[p.trade_date for p in parts]])
    connection.execute("CREATE OR REPLACE TEMP TABLE migration_normalized AS " +
                       suspend_d_normalized_relation_select("migration_raw"))
    conflicts = stock_suspend_confirmed_conflicts_select(**_RELATIONS)
    conflict_count = connection.execute(f"SELECT count(*) FROM ({conflicts})").fetchone()[0]
    if conflict_count:
        _fail("raw_confirmed_conflict", {"rows": conflict_count}, 3)
    connection.execute("CREATE OR REPLACE TEMP TABLE migration_output AS " +
                       silver_stock_suspend_daily_select(**_RELATIONS))


def compare_confirmed_migration(connection, *, plan: FrozenMigrationPlan) -> MigrationComparison:
    _verify_plan(plan)
    batches = []
    sample_budget = contract.CONFIRMED_SAMPLE_LIMIT
    for year, parts in _batch_partitions(plan):
        started = time.monotonic()
        for part in parts:
            _verify_evidence(part.raw)
            _verify_evidence(part.silver)
        fixed_evidence = _load_fixed(connection, plan, allow_target=True)
        _load_comparison_batch(connection, parts)
        projection = "ts_code, trade_date, suspend_timing, suspend_type"
        connection.execute(f"""
            CREATE OR REPLACE TEMP TABLE migration_diff AS
            SELECT 'added' AS direction, * FROM (
              SELECT {projection} FROM migration_output EXCEPT ALL SELECT {projection} FROM migration_silver)
            UNION ALL
            SELECT 'missing' AS direction, * FROM (
              SELECT {projection} FROM migration_silver EXCEPT ALL SELECT {projection} FROM migration_output)
        """)
        raw, silver, output, added, missing = connection.execute("""
            SELECT (SELECT count(*) FROM migration_raw), (SELECT count(*) FROM migration_silver),
              (SELECT count(*) FROM migration_output),
              count(*) FILTER (WHERE direction='added'), count(*) FILTER (WHERE direction='missing')
            FROM migration_diff
        """).fetchone()
        samples = tuple(dict(zip(("direction", "ts_code", "trade_date", "suspend_timing", "suspend_type"), row, strict=True))
                        for row in connection.execute(
                            "SELECT direction, ts_code, trade_date::VARCHAR, suspend_timing, suspend_type "
                            "FROM migration_diff ORDER BY direction, trade_date, ts_code LIMIT ?", [sample_budget],
                        ).fetchall())
        sample_budget -= len(samples)
        for part in parts:
            _verify_evidence(part.raw)
            _verify_evidence(part.silver)
        _verify_evidence(fixed_evidence)
        batch = ComparisonBatch(year, tuple(p.trade_date for p in parts), raw, silver, output,
                                added, missing, samples, round((time.monotonic() - started) * 1000))
        batches.append(batch)
        print(json.dumps({"stage": "compared", "year": year,
                          "completed_dates": sum(len(b.dates) for b in batches),
                          "total_dates": len(plan.partitions), "added_rows": added,
                          "missing_rows": missing, "elapsed_ms": batch.elapsed_ms}), flush=True)
    _verify_plan(plan)
    return MigrationComparison(plan.sha256, contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256, tuple(batches))


def _comparison_from_json(value, plan, digest=None):
    _keys(value, ("schema_version", "plan_sha256", "logical_sha256", "batches"))
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["plan_sha256"] != plan.sha256
            or value["logical_sha256"] != contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256
            or type(value["batches"]) is not list):
        _fail("comparison_identity_mismatch")
    expected = [(year, tuple(p.trade_date for p in parts)) for year, parts in _batch_partitions(plan)]
    batches = []
    total_samples = 0
    for item in value["batches"]:
        _keys(item, ("year", "dates", "raw_rows", "silver_rows", "output_rows", "added_rows",
                     "missing_rows", "samples", "elapsed_ms"))
        days = _dates(item["dates"])
        numbers = [_integer(item[key]) for key in (
            "raw_rows", "silver_rows", "output_rows", "added_rows", "missing_rows")]
        if (numbers[2] - numbers[1] != numbers[3] - numbers[4]
                or numbers[3] > numbers[2] or numbers[4] > numbers[1]):
            _fail("comparison_counts_mismatch")
        if type(item["samples"]) is not list:
            _fail("invalid_comparison_samples", exit_code=2)
        for sample in item["samples"]:
            _keys(sample, ("direction", "ts_code", "trade_date", "suspend_timing", "suspend_type"))
            if sample["direction"] not in ("added", "missing") or sample["trade_date"] not in days:
                _fail("invalid_comparison_samples", exit_code=2)
        total_samples += len(item["samples"])
        if len(item["samples"]) > numbers[3] + numbers[4]:
            _fail("comparison_counts_mismatch")
        batches.append(ComparisonBatch(item["year"], days, *numbers, tuple(item["samples"]), _integer(item["elapsed_ms"])))
    if [(b.year, b.dates) for b in batches] != expected or total_samples > contract.CONFIRMED_SAMPLE_LIMIT:
        _fail("comparison_incomplete_scope")
    return MigrationComparison(plan.sha256, value["logical_sha256"], tuple(batches), digest)


def read_confirmed_comparison(*, plan, expected_comparison_sha256=None):
    _verify_plan(plan)
    value, digest = _read_json(plan.paths.comparison, expected_comparison_sha256)
    return _comparison_from_json(value, plan, digest)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save_json(paths, path, payload):
    if path not in (paths.comparison, paths.checkpoint, paths.events_checkpoint):
        _fail("unexpected_output_path", path, 2)
    paths.check()
    contract.assert_suspend_path(path, root=paths.operation_dir)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > _MAX_JSON_BYTES:
        _fail("document_too_large", path, 2)
    temporary = paths.operation_dir / f"{path.name}.{uuid4().hex}.tmp"
    with temporary.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    contract.assert_suspend_path(path, root=paths.operation_dir)
    os.replace(temporary, path)
    _sync_directory(paths.operation_dir)


def save_confirmed_comparison(*, plan, comparison):
    _verify_plan(plan)
    # Validate the complete report object, including scope, before any write.
    payload = json.loads(json.dumps(comparison.payload(), allow_nan=False))
    checked = _comparison_from_json(payload, plan)
    if plan.paths.comparison.exists():
        existing = read_confirmed_comparison(plan=plan)
        if existing.payload() != checked.payload():
            _fail("comparison_already_exists")
        return existing
    _save_json(plan.paths, plan.paths.comparison, payload)
    return read_confirmed_comparison(plan=plan)


def _inspect_file(connection, path):
    contract.assert_suspend_path(path, root=path.parent if path.parent.exists() else Path(path.anchor))
    if not path.exists():
        return "absent"
    before = _bounded_file_identity(path)
    fingerprint = contract.suspend_file_sha256(path)
    inspection = contract.inspect_confirmed_file(connection, path)
    contract.load_confirmed_relation(connection, inspection, relation_name="publication_verified")
    contract.confirmed_facts_summary(connection, "publication_verified")
    if before != contract.suspend_file_identity(path) or fingerprint != contract.suspend_file_sha256(path):
        _fail("input_drift", path)
    return "approved"


def inspect_confirmed_publication(connection, *, paths):
    plan = read_confirmed_plan(paths=paths)
    statuses = []
    for path in (paths.candidate, paths.target):
        try:
            status = _inspect_file(connection, path)
            if path == paths.candidate and status == "approved":
                _verify_evidence(plan.candidate)
        except (ValueError, OSError, RuntimeError) as error:
            status = getattr(error, "reason_code", "unreadable")
        statuses.append(status)
    comparison_status = "absent"
    if paths.comparison.exists():
        try:
            comparison_status = "passed" if read_confirmed_comparison(plan=plan).passed else "different"
        except (ValueError, OSError) as error:
            comparison_status = getattr(error, "reason_code", "unreadable")
    next_action = "review"
    if comparison_status == "passed" and statuses[1] == "approved":
        next_action = "audit_events"
    elif comparison_status == "passed" and statuses == ["approved", "absent"]:
        next_action = "confirm_file_publish"
    elif statuses[0] == "approved" and statuses[1] == "absent" and comparison_status == "absent":
        next_action = "compare"
    _verify_plan(plan)
    return PublicationInspection(plan.sha256, *statuses, comparison_status, next_action)


def _checkpoint_payload(plan, comparison, stage):
    return {"schema_version": 1, "operation_id": plan.paths.operation_id,
            "plan_sha256": plan.sha256, "comparison_sha256": comparison.report_sha256,
            "logical_sha256": contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256,
            "target_path": str(plan.paths.target), "candidate_sha256": plan.candidate.sha256, "stage": stage}


def _check_checkpoint(plan, comparison):
    if not plan.paths.checkpoint.exists():
        return
    existing, _ = _read_json(plan.paths.checkpoint)
    if type(existing) is not dict or type(existing.get("schema_version")) is not int:
        _fail("checkpoint_identity_mismatch")
    if existing not in (_checkpoint_payload(plan, comparison, "prepared"),
                         _checkpoint_payload(plan, comparison, "committed")):
        _fail("checkpoint_identity_mismatch")
    if existing["stage"] == "committed" and not plan.paths.target.exists():
        _fail("committed_target_missing")


def validate_confirmed_file_publication(connection, *, plan, comparison):
    _verify_plan(plan)
    if comparison.report_sha256 is None:
        _fail("comparison_not_saved")
    actual = read_confirmed_comparison(plan=plan, expected_comparison_sha256=comparison.report_sha256)
    if actual != comparison or not actual.passed:
        _fail("comparison_not_passed", exit_code=3)
    _check_checkpoint(plan, comparison)
    for part in plan.partitions:
        _verify_evidence(part.raw)
        _verify_evidence(part.silver)
    target_status = _inspect_file(connection, plan.paths.target)
    if target_status == "absent":
        _load_fixed(connection, plan, allow_target=False)
        if plan.paths.lake_root.stat().st_dev != plan.paths.candidate.stat().st_dev:
            _fail("cross_device_publication", exit_code=2)
    # A valid existing target completes the file fact even if the candidate was
    # already moved. Do not require the obsolete candidate to be recreated.
    _verify_plan(plan)
    return "reused" if target_status == "approved" else "publish"


def publish_confirmed_file(connection, *, plan: FrozenMigrationPlan,
                           comparison: MigrationComparison) -> FilePublishResult:
    status = validate_confirmed_file_publication(connection, plan=plan, comparison=comparison)
    paths = plan.paths
    replaced = False
    promotion_started = False
    try:
        if status == "reused":
            _save_json(paths, paths.checkpoint, _checkpoint_payload(plan, comparison, "committed"))
            if _inspect_file(connection, paths.target) != "approved":
                _fail("published_file_missing")
            return FilePublishResult("reused", str(paths.target), True)
        paths.target.parent.mkdir(parents=True, exist_ok=True)
        contract.assert_suspend_path(paths.target, root=paths.lake_root)
        if paths.target.parent.stat().st_dev != paths.candidate.stat().st_dev:
            _fail("cross_device_publication", exit_code=2)
        with paths.candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        _save_json(paths, paths.checkpoint, _checkpoint_payload(plan, comparison, "prepared"))
        # Recheck after checkpoint persistence and immediately before promotion.
        status = validate_confirmed_file_publication(connection, plan=plan, comparison=comparison)
        if status == "reused":
            _save_json(paths, paths.checkpoint, _checkpoint_payload(plan, comparison, "committed"))
            if _inspect_file(connection, paths.target) != "approved":
                _fail("published_file_missing")
            return FilePublishResult("reused", str(paths.target), True)
        promotion_started = True
        os.replace(paths.candidate, paths.target)
        replaced = True
        _sync_directory(paths.target.parent)
        _sync_directory(paths.candidate.parent)
        if _inspect_file(connection, paths.target) != "approved":
            _fail("published_file_invalid")
        _save_json(paths, paths.checkpoint, _checkpoint_payload(plan, comparison, "committed"))
    except Exception as error:
        # A filesystem operation can complete before its caller sees an error.
        # Never infer "not published" solely from the missing success return.
        try:
            uncertain = promotion_started and paths.target.exists()
        except OSError:
            uncertain = promotion_started
        if replaced or status == "reused" or uncertain:
            _fail("file_published_observation_incomplete", type(error).__name__, 5)
        raise
    return FilePublishResult("published", str(paths.target), True)
