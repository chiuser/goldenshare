"""Run-local R3 identities, proof indexes and incremental storage accounting.

This module is a leaf: it knows the immutable repair contract, never workers or
business kernels. A runtime belongs to one admitted plan and one process.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from functools import wraps
from pathlib import Path

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    RepairBudget,
    atomic_repair_json,
    check_repair_cancel,
    check_repair_path,
    file_identity,
    repair_hash,
    sync_repair_directory,
)

_ACTIVE = ContextVar("stock_factor_repair_runtime", default=None)
PROOF_VERSION = 1


class RepairRuntime:
    """One admission and first-use identity per version, without market discovery."""

    def __init__(self, plan, *, selection=None, admitted=False):
        self.plan = plan
        self.root = Path(plan["run_root"])
        self.lake_root = Path(plan["lake_root"])
        self.selection = selection
        self.admitted = admitted
        self.binding = repair_hash({
            "plan_hash": plan["plan_hash"],
            "implementations": plan.get("implementation_fingerprints", []),
            "rules": PROOF_VERSION,
        })
        self.sources = {i["path"]: i for i in plan.get("source_fingerprints", [])}
        self.preimages = {i["path"]: i for i in plan.get("target_preimages", [])}
        self.targets = {p: u for u in plan.get("units", []) for p in u["target_paths"]}
        self.identities = {}
        self.records = {}
        self.projections = {}
        self.indexes = {"price_contract": None, "indicator_contract": None} if admitted else {}
        self.counters = Counter()
        self.storage = None

    def identity(self, path, *, cancel=None, progress=None):
        name = str(path)
        if name not in self.identities:
            identity = file_identity(Path(path), cancel=cancel, progress=progress)
            check_repair_cancel(cancel)
            self.counters["hash_files"] += 1
            self.counters["hash_bytes"] += identity.size
            self.identities[name] = identity
        return self.identities[name]

    def verify_source(self, path, *, cancel=None):
        expected = self.sources.get(str(path))
        if expected is None:
            raise FactorRepairError("repair_input_not_frozen")
        if asdict(self.identity(path, cancel=cancel)) != expected:
            raise FactorRepairError("input_drift")
        return path

    def forget(self, path):
        self.identities.pop(str(path), None)
        self.records.pop(str(path), None)

    def once(self, name, build):
        if name not in self.indexes:
            self.indexes[name] = build()
        return self.indexes[name]

    def owns_artifact(self, path):
        """Join this run's single census to its planned paths and existing receipts."""
        relative = Path(path).relative_to(self.root)
        name = relative.as_posix()
        terminal = getattr(self, "terminal_census", False)
        if terminal and name.endswith(".partial"):
            return False
        clean = name.removesuffix(".partial")
        if clean in {"plan.json", "checkpoint.json", "checkpoints/active.json",
                     *(f"{phase}{suffix}-audit.json" for phase in ("factor", "price", "indicator") for suffix in ("", "-sample"))}:
            return True
        if clean.startswith("checkpoints/candidates/"):
            allowed = self.once("record_names", lambda: {
                hashlib.sha256(Path(p).relative_to(self.lake_root).as_posix().encode()).hexdigest() + ".json"
                for p in self.targets})
            return Path(clean).name in allowed and len(Path(clean).parts) == 3
        if clean.startswith("candidates/"):
            target = self.lake_root / clean.removeprefix("candidates/")
            if str(target) not in self.targets:
                return False
            digest = hashlib.sha256(target.relative_to(self.lake_root).as_posix().encode()).hexdigest()
            record_path = self.root / "checkpoints/candidates" / (digest + ".json")
            if not record_path.is_file():
                return False
            record = self.once(("ownership", terminal, str(record_path)), lambda: json.loads(record_path.read_text()))
            return (record.get("plan_hash") == self.plan["plan_hash"]
                    and record.get("target_relative_path") == target.relative_to(self.lake_root).as_posix()
                    and record.get("candidate_relative_path") == clean
                    and (not terminal or record.get("validated") is True and not record.get("commit_pending")))
        if clean.startswith("inputs/indicator_replay/"):
            if terminal:
                return str(path) in self.once("task_manifest_paths", self._task_manifest_paths)
            tasks = self.once("task_ids", lambda: {t["task_id"] for t in self.indexes.get("indicator_tasks", [])})
            return len(relative.parts) == 4 and relative.parts[2] in tasks
        if clean.startswith("inputs/"):
            original = Path(clean.removeprefix("inputs/"))
            if original.suffix == ".json":
                original = original.with_suffix(".parquet")
            return str(self.lake_root / original) in self.sources
        return clean.startswith("temp/")  # This directory is reserved exclusively to DuckDB.

    def _task_manifest_paths(self):
        owned = set()
        for task in self.indexes.get("indicator_tasks", []):
            directory = self.root / "inputs/indicator_replay" / task["task_id"]
            marker = directory / "task.json"
            result = json.loads(check_repair_path(marker).read_text())
            owned.add(str(marker))
            for identity in result["receipts"]:
                receipt = check_repair_path(Path(identity["path"]))
                if receipt.parent != directory:
                    raise FactorRepairError("repair_indicator_fragment_invalid")
                owned.add(str(receipt))
                proof = json.loads(receipt.read_text())
                for output in proof["outputs"].values():
                    path = check_repair_path(Path(output["path"]))
                    if path.parent != directory:
                        raise FactorRepairError("repair_indicator_fragment_invalid")
                    owned.add(str(path))
        return owned

    def source_paths(self, asset, code=None):
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
            repair_asset_for_path,
        )
        def group():
            groups = {}
            for name in self.sources:
                path = Path(name)
                key = repair_asset_for_path(self.lake_root, path)
                groups.setdefault((key, None), []).append(path)
                if path.parent.parent.name.startswith("ts_code="):
                    groups.setdefault((key, path.parent.parent.name.removeprefix("ts_code=")), []).append(path)
            return groups
        return self.once("source_groups", group).get((asset, code), [])

    def release_connection_tables(self, connection, owner):
        if self.indexes.get("connection_owner") == owner:
            return
        for relation, query in (("VIEW", "SELECT view_name FROM duckdb_views() WHERE database_name='temp' AND schema_name='main'"),
                                ("TABLE", "SELECT table_name FROM duckdb_tables() WHERE database_name='temp' AND schema_name='main'")):
            for (name,) in connection.execute(query).fetchall():
                quoted = '"' + name.replace('"', '""') + '"'
                connection.execute(f"DROP {relation} {quoted}")
        self.indexes["connection_owner"] = owner

    def approved_scope(self, target):
        unit = self.targets.get(str(target))
        if unit is None:
            raise FactorRepairError("repair_target_not_frozen")
        unit_digest = self.once(("unit_scope", unit["asset_key"]), lambda: repair_hash(unit))
        return repair_hash([unit_digest, str(target)])

    @staticmethod
    def dependency_digest(record):
        return repair_hash({"inputs": record.get("input_paths", []),
                            "overlays": record.get("overlay_hashes", {}),
                            "replay": record.get("replay_files", []),
                            "tasks": record.get("replay_tasks", []),
                            "business": record.get("business_validation")})

    def restore_binding(self, record, *, transfer=False):
        """A sealed proof binds stable originals; verify outputs, not originals again."""
        proof = record.get("transfer_proof" if transfer else "business_proof")
        if (not isinstance(proof, dict) or type(proof.get("version")) is not int or proof.get("version") != PROOF_VERSION
                or proof.get("runtime_binding") != self.binding
                or proof.get("checks") != {
                    "schema": True, "keys": True, "scope": True,
                    "retained_rows": True, "blocking": not transfer,
                }):
            raise FactorRepairError("repair_business_proof_required")
        target = self.lake_root / record["target_relative_path"]
        if (proof.get("plan_hash") != self.plan["plan_hash"]
                or proof.get("asset_key") != record["asset_key"]
                or proof.get("unit_id") != record["unit_id"]
                or proof.get("preimage_sha256") != record["preimage_sha256"]
                or proof.get("output_sha256") != record["candidate_sha256"]
                or proof.get("approved_keys") != self.approved_scope(target)
                or proof.get("dependencies") != self.dependency_digest({**record, "business_validation": None} if transfer else record)
                or proof.get("counts") != {k: record[k] for k in ("original_rows", "replacement_rows", "changed_stock_rows", "candidate_rows", "candidate_bytes")}):
            raise FactorRepairError("repair_business_proof_binding_invalid")
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
            FileIdentity,
        )

        for name in record.get("input_paths", []):
            expected = self.sources.get(name)
            if expected is None:
                raise FactorRepairError("repair_input_not_frozen")
            if self.admitted:
                self.identities.setdefault(name, FileIdentity(**expected))
            else:
                self.verify_source(Path(name))

    def transfer_proof(self, record, target):
        proof = self.business_proof(record, approved_keys=self.approved_scope(target),
            dependencies=self.dependency_digest({**record, "business_validation": None}))
        proof["checks"]["blocking"] = False
        return proof

    def business_proof(self, record, *, approved_keys, dependencies):
        return {
            "version": PROOF_VERSION,
            "runtime_binding": self.binding,
            "plan_hash": self.plan["plan_hash"],
            "asset_key": record["asset_key"],
            "unit_id": record["unit_id"],
            "preimage_sha256": record["preimage_sha256"],
            "output_sha256": record["candidate_sha256"],
            "approved_keys": approved_keys,
            "dependencies": dependencies,
            "counts": {k: record[k] for k in ("original_rows", "replacement_rows", "changed_stock_rows", "candidate_rows", "candidate_bytes")},
            "checks": {"schema": True, "keys": True, "scope": True,
                       "retained_rows": True, "blocking": True},
        }


@contextmanager
def use_repair_runtime(runtime):
    token = _ACTIVE.set(runtime)
    try:
        yield runtime
    finally:
        _ACTIVE.reset(token)


def current_repair_runtime(plan=None):
    runtime = _ACTIVE.get()
    if runtime is not None and (plan is None or (
            runtime.plan["plan_hash"] == plan["plan_hash"]
            and runtime.root == Path(plan["run_root"]))):
        return runtime
    return None


def repair_runtime_entry(function):
    """Direct library calls get a fresh scope; nested worker calls share admission."""
    import inspect
    signature = inspect.signature(function)

    @wraps(function)
    def call(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs).arguments
        plan = arguments["plan"]
        if current_repair_runtime(plan) is not None:
            return function(*args, **kwargs)
        with use_repair_runtime(RepairRuntime(plan)):
            return function(*args, **kwargs)
    return call


def verified_file_identity(path, *, cancel=None, progress=None):
    runtime = current_repair_runtime()
    if runtime is None:
        return file_identity(path, cancel=cancel, progress=progress)
    return runtime.identity(path, cancel=cancel, progress=progress)


def _atomic_runtime_json(path, payload):
    """Fixed owned metadata temporary, so a reservation also covers its rename."""
    path = check_repair_path(Path(path))
    temporary = check_repair_path(Path(str(path) + ".partial"))
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_repair_directory(path.parent)


class RepairStorageLedger:
    """One run census, then local before/after accounting and durable reservations."""

    def __init__(self, root, *, scan, plan=None):
        self.root = check_repair_path(Path(root))
        self.plan = plan or {}
        self.scan = scan
        self.counts = None
        self.pending = None
        checkpoint = self.root / "checkpoint.json"
        payload = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        saved = payload.get("storage_accounting")
        if (isinstance(saved, dict) and saved.get("plan_hash") == self.plan.get("plan_hash")
                and saved.get("checksum") == repair_hash({k: v for k, v in saved.items() if k != "checksum"})
                and all(type(saved.get("counts", {}).get(k)) is int and saved["counts"][k] >= 0
                        for k in ("candidate_bytes", "spill_bytes", "input_bytes", "staging_bytes"))):
            self.counts = dict(saved["counts"])
            self.pending = saved.get("pending")
            if self.pending:
                path = check_repair_path(Path(self.pending["path"]))
                if not path.is_relative_to(self.root):
                    raise FactorRepairError("repair_storage_accounting_invalid")
                temporary = self.pending.get("temporary")
                if temporary:
                    temporary = check_repair_path(Path(temporary))
                    if temporary != Path(str(path) + ".partial"):
                        raise FactorRepairError("repair_storage_accounting_invalid")
                    if temporary.exists():
                        temporary.unlink()  # Exact, reserved and uncommitted metadata only.
                self._change(path, self.pending["before"], self.size(path))
                self.pending = None
        if self.counts is None:
            self.counts = dict(scan(self.root))
            self.counts["staging_bytes"] -= self.size(checkpoint) + self.size(Path(str(checkpoint) + ".partial"))
        self.check()

    @staticmethod
    def size(path):
        path = check_repair_path(Path(path))
        try:
            info = path.stat()
        except FileNotFoundError:
            return 0
        if not stat.S_ISREG(info.st_mode):
            raise FactorRepairError("repair_storage_path_invalid")
        return info.st_size

    def snapshot(self):
        return {**self.counts, "staging_bytes": self.counts["staging_bytes"] + self.size(self.root / "checkpoint.json") + self.size(self.root / "checkpoint.json.partial")}

    def _change(self, path, before, after):
        if Path(path) in (self.root / "checkpoint.json", self.root / "checkpoint.json.partial"):
            return
        delta = after - before
        self.counts["staging_bytes"] += delta
        for label, directory in (("candidate_bytes", "candidates"), ("spill_bytes", "temp"), ("input_bytes", "inputs")):
            if Path(path).is_relative_to(self.root / directory):
                self.counts[label] += delta
        if any(v < 0 for v in self.counts.values()):
            raise FactorRepairError("repair_storage_accounting_invalid")

    def check(self, *, reserve_bytes=0, candidate=False):
        budget = RepairBudget()
        if (self.counts["candidate_bytes"] > budget.max_candidate_bytes
                or self.counts["spill_bytes"] > budget.max_spill
                or candidate and self.counts["candidate_bytes"] + reserve_bytes > budget.max_candidate_bytes):
            raise FactorRepairError("repair_storage_budget_exceeded")
        remaining = max(0, self.plan.get("space_required_bytes", 0) - self.snapshot()["staging_bytes"])
        required = max(remaining, (reserve_bytes + max(0, budget.max_spill - self.counts["spill_bytes"])) * 6 // 5)
        if shutil.disk_usage(self.root).free < required:
            raise FactorRepairError("repair_space_insufficient")
        return self.snapshot()

    def payload(self):
        result = {"plan_hash": self.plan.get("plan_hash"), "counts": dict(self.counts), "pending": self.pending}
        result["checksum"] = repair_hash(result)
        return result

    def persist(self, summary=None):
        checkpoint = self.root / "checkpoint.json"
        if summary is None:
            summary = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        _atomic_runtime_json(checkpoint, {**summary, "storage_accounting": self.payload()})

    @contextmanager
    def writing(self, path, *, reserve_bytes=0, candidate=False, temporary=None):
        path = check_repair_path(Path(path))
        if not path.is_relative_to(self.root) or self.pending:
            raise FactorRepairError("repair_storage_reservation_invalid")
        before = self.size(path)
        self.check(reserve_bytes=reserve_bytes, candidate=candidate)
        if temporary is not None and check_repair_path(Path(temporary)).exists():
            raise FactorRepairError("repair_storage_reservation_invalid")
        self.pending = {"path": str(path), "before": before, "reserved": reserve_bytes,
                        "temporary": str(temporary) if temporary is not None else None}
        self.persist()
        try:
            yield
        finally:
            if temporary is not None and Path(temporary).exists():
                Path(temporary).unlink()  # Only this reservation's incomplete JSON temporary.
            self._change(path, before, self.size(path))
            self.pending = None
            self.check()
            self.persist()

    def replace(self, source, target):
        before_source, before_target = self.size(source), self.size(target)
        os.replace(source, target)
        self._change(source, before_source, 0)
        self._change(target, before_target, before_source)
        self.persist()

    def remove(self, path):
        before = self.size(path)
        Path(path).unlink()
        self._change(path, before, 0)
        self.persist()

    def reconcile(self):
        """One terminal census of this run, never of Lake or global market data."""
        runtime = current_repair_runtime()
        if runtime is not None:
            runtime.terminal_census = True
        try:
            observed = self.scan(self.root)
        finally:
            if runtime is not None:
                runtime.terminal_census = False
        expected = self.snapshot()
        # DuckDB owns its transient spill files; its hard quota protects the live phase.
        delta = observed["spill_bytes"] - expected["spill_bytes"]
        expected["spill_bytes"] += delta
        expected["staging_bytes"] += delta
        if observed != expected:
            raise FactorRepairError("repair_storage_accounting_mismatch")
        self.counts["spill_bytes"] = observed["spill_bytes"]
        self.counts["staging_bytes"] += delta
        self.check()
        self.persist()
        return observed


def runtime_storage(root):
    runtime = current_repair_runtime()
    return runtime.storage if runtime is not None and runtime.root == Path(root) else None


def write_repair_json(path, payload):
    ledger = runtime_storage(Path(path).parent)
    runtime = current_repair_runtime()
    if runtime is not None and Path(path).is_relative_to(runtime.root):
        ledger = runtime.storage
    if ledger is None:
        return atomic_repair_json(path, payload)
    if Path(path) == ledger.root / "checkpoint.json":
        return ledger.persist(payload)
    with ledger.writing(path, reserve_bytes=len(json.dumps(payload).encode()) + 1,
                        temporary=Path(str(path) + ".partial")):
        _atomic_runtime_json(path, payload)
    runtime.forget(path)


def replace_repair_file(source, target):
    runtime = current_repair_runtime()
    identity = runtime.identities.get(str(source)) if runtime is not None else None
    if runtime is not None and runtime.storage is not None:
        runtime.storage.replace(source, target)
    else:
        os.replace(source, target)
    if runtime is not None:
        runtime.forget(source)
        runtime.forget(target)
        if identity is not None:
            from dataclasses import replace
            runtime.identities[str(target)] = replace(identity, path=str(target))


def remove_repair_file(path):
    runtime = current_repair_runtime()
    if runtime is not None and runtime.storage is not None:
        runtime.storage.remove(path)
        runtime.forget(path)
    else:
        Path(path).unlink()


def write_runtime_candidate_record(run_root, record):
    import hashlib

    target_id = hashlib.sha256(record["target_relative_path"].encode()).hexdigest()
    path = Path(run_root) / "checkpoints/candidates" / f"{target_id}.json"
    write_repair_json(path, {"format_version": 1, **record})
    runtime = current_repair_runtime()
    if runtime is not None:
        runtime.records.pop(str(runtime.lake_root / record["target_relative_path"]), None)
    return path
