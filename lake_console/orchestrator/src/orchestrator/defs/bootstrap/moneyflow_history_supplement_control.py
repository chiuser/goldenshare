"""Fixed seven-date supplement intent and durable, operation-wide limits."""

import hashlib
import json
import os
import threading
import time
from pathlib import Path

from orchestrator.defs.bootstrap.moneyflow_history_events import _atomic_json
from orchestrator.defs.bootstrap.moneyflow_history_supplement_code import (
    supplement_code_identity,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_directory,
)
from orchestrator.defs.io.moneyflow_update_publication import (
    assert_moneyflow_update_path,
    assert_moneyflow_update_roots,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.run_contracts.moneyflow import (
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)
from orchestrator.moneyflow_continuation.contract import CONTRACTS

SCOPE = (
    ("moneyflow_mkt_dc", "2026-07-09", 1),
    ("moneyflow_ind_ths", "2026-07-09", 90),
    ("moneyflow_ind_ths", "2026-08-05", 90),
    ("moneyflow_cnt_ths", "2026-07-09", 382),
    ("moneyflow_ths", "2026-07-06", 5200),
    ("moneyflow_ths", "2026-07-09", 5205),
    ("moneyflow_dc", "2026-05-19", 5955),
)
CUTOFF = "2026-09-30"
LIMITS = {
    "copies": 16,
    "metadata": 12,
    "connections": 26,
    "reads": 400,
    "seconds": 1200,
    "bytes": 128 * 1024**2,
    "files": 512,
    "materializations": 14,
    "checks": 14,
    "partitions": 6,
}


def require(condition, reason):
    if not condition:
        raise MoneyflowContractError("supplement_" + reason)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def report_progress(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def read_json(path):
    assert_moneyflow_update_path(path)
    require(path.is_file() and path.stat().st_size <= 1024**2, "control_file")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "control_json")
    return value


def save_json(path, value):
    _atomic_json(path, value, limit=1024**2)


def code_identity():
    return supplement_code_identity()


def validate_code(plan, sha, source_review=None, expected_source_review_sha=None):
    current = code_identity()
    if source_review is None:
        require(expected_source_review_sha is None, "source_review_missing")
        require(plan["code"] == current, "code_changed")
        return
    require(
        isinstance(source_review, dict)
        and set(source_review)
        == {"revision", "plan_sha256", "prior_code_sha256", "candidates_sha256", "code"}
        and expected_source_review_sha is not None
        and digest(source_review) == expected_source_review_sha,
        "source_review_digest",
    )
    require(
        source_review["revision"] == "moneyflow_supplement_code_review_v1"
        and source_review["plan_sha256"] == sha
        and source_review["prior_code_sha256"] == digest(plan["code"]),
        "source_review_parent",
    )
    require(source_review["code"] == current, "reviewed_code_changed")


def target(lake, dataset, day, layer):
    domain = "tushare" if layer == "raw" else "moneyflow"
    path = lake / layer / domain / dataset / ("trade_date=" + day) / "part-000.parquet"
    assert_moneyflow_update_path(path)
    return path


def file_hash(path):
    assert_moneyflow_update_path(path)
    require(not path.exists() or path.is_file(), "target_type")
    return candidate_file_hash(path) if path.exists() else None


def child_directory(staging, operation, dataset, day):
    return (
        moneyflow_candidate_directory(
            staging, operation + "-" + day.replace("-", ""), CUTOFF, dataset=dataset
        )
        / "history_candidates"
    )


def root_directory(staging, operation):
    return (
        moneyflow_candidate_directory(
            staging, operation, CUTOFF, dataset=SCOPE[0][0]
        ).parents[1]
        / "supplement"
    )


def validate_plan(
    plan, expected_sha, *, source_review=None, expected_source_review_sha=None
):
    require(isinstance(plan, dict) and digest(plan) == expected_sha, "plan_digest")
    require(
        plan["revision"] == "moneyflow_supplement_v1" and plan["limits"] == LIMITS,
        "plan_revision",
    )
    lake, staging = Path(plan["lake_root"]), Path(plan["staging_root"])
    assert_moneyflow_update_roots(lake, staging)
    if lake != Path(DEFAULT_LAKE_ROOT):
        require(
            any(
                p in lake.parents and p in staging.parents
                for p in (Path("/private/tmp"), Path("/tmp").resolve())
            ),
            "isolated_roots",
        )
    require(
        [(e["dataset"], e["day"]) for e in plan["entries"]]
        == [(d, t) for d, t, _ in SCOPE],
        "scope",
    )
    root_directory(staging, plan["operation_id"])
    validate_code(plan, expected_sha, source_review, expected_source_review_sha)
    require(
        isinstance(plan["source_evidence"], str) and plan["source_evidence"],
        "source_evidence",
    )
    total = 0
    for entry, (_, _, rows) in zip(plan["entries"], SCOPE, strict=True):
        keys = entry["keys"]
        require(
            isinstance(keys, list)
            and keys == sorted(set(keys))
            and all(isinstance(k, str) and k.strip() for k in keys),
            "source_keys",
        )
        require(0 < len(keys) <= 10000, "source_rows")
        if lake == Path(DEFAULT_LAKE_ROOT):
            require(len(keys) == rows, "formal_source_rows_changed")
        require(
            entry["dataset"] != "moneyflow_mkt_dc" or keys == [entry["day"]],
            "market_key",
        )
        require(set(entry["baseline"]) == {"raw", "silver"}, "baseline")
        require(
            all(
                bool(v["hash"]) == (entry["dataset"] == "moneyflow_dc")
                for v in entry["baseline"].values()
            ),
            "baseline_presence",
        )
        total += len(keys)
    require(total <= 20000, "total_rows")
    require(
        set(plan["sensors"])
        == {
            job + "_sensor"
            for c in CONTRACTS.values()
            for job in (c.raw_job, c.silver_job)
        },
        "sensor_scope",
    )
    return lake, staging


class Control:
    """Charge before external actions; never refund unknown completed requests."""

    def __init__(
        self,
        plan,
        sha,
        root=None,
        *,
        cancel=lambda: False,
        clock=time.monotonic,
        progress=lambda value: None,
    ):
        self.plan, self.sha, self.root = plan, sha, root
        self.cancel, self.clock, self.progress = cancel, clock, progress
        self.lock = threading.RLock()
        self.last = clock()
        self.last_saved = self.last
        self.state = (
            read_json(root / "state.json")
            if root and (root / "state.json").exists()
            else {
                "plan_sha": sha,
                "counts": {
                    k: (
                        5
                        if k in {"metadata", "connections"}
                        else plan.get("preparation_reads", 0)
                        if k == "reads"
                        else 0
                    )
                    for k in LIMITS
                    if k not in {"bytes", "files", "seconds"}
                },
                "seconds": plan.get("preparation_seconds", 0),
                "items": {},
                "actions": {},
                "stage": "planned",
                "sensors": {},
                "post_metadata": False,
            }
        )
        require(self.state.get("plan_sha") == sha, "state_plan")
        require(
            all(
                type(self.state["counts"].get(k)) is int
                and 0 <= self.state["counts"][k] <= v
                for k, v in LIMITS.items()
                if k not in {"bytes", "files", "seconds"}
            ),
            "state_counts",
        )
        require(
            type(self.state.get("seconds")) in (int, float)
            and 0 <= self.state["seconds"] <= LIMITS["seconds"],
            "state_seconds",
        )
        self.check()

    def save(self):
        if self.root:
            save_json(self.root / "state.json", self.state)

    def check(self):
        with self.lock:
            if self.cancel():
                raise InterruptedError("supplement_cancelled")
            now = self.clock()
            self.state["seconds"] += max(0, now - self.last)
            self.last = now
            require(self.state["seconds"] <= LIMITS["seconds"], "time_budget")
            assert_moneyflow_memory_budget()
            if now - self.last_saved >= 1:
                self.disk()
                self.state["last_updated"] = time.time()
                self.save()
                self.progress(
                    {
                        "stage": self.state["stage"],
                        "current": self.state.get("current"),
                        "accepted": sum(
                            i.get("accepted", False)
                            for i in self.state["items"].values()
                        ),
                        "total": 7,
                        "counts": dict(self.state["counts"]),
                        "seconds": self.state["seconds"],
                        "last_updated": self.state["last_updated"],
                        "eta": "暂无法估算",
                    }
                )
                self.last_saved = now

    def disk(self):
        if not self.root:
            return
        staging, operation = Path(self.plan["staging_root"]), self.plan["operation_id"]
        roots = {
            self.root,
            *(child_directory(staging, operation, d, t) for d, t, _ in SCOPE),
        }
        size, count = 0, 0
        for base in roots:
            for directory, dirs, files in os.walk(base):
                require(not Path(directory).is_symlink(), "staging_symlink")
                for name in (*dirs, *files):
                    require(
                        not (Path(directory) / name).is_symlink(), "staging_symlink"
                    )
                for name in files:
                    size += (Path(directory) / name).stat().st_size
                    count += 1
                    require(
                        size <= LIMITS["bytes"] and count <= LIMITS["files"],
                        "disk_budget",
                    )

    def charge(self, kind):
        with self.lock:
            self.check()
            require(self.state["counts"][kind] < LIMITS[kind], kind + "_budget")
            self.state["counts"][kind] += 1
            if kind in {"copies", "metadata"}:
                require(
                    self.state["counts"]["connections"] < LIMITS["connections"],
                    "connection_budget",
                )
                self.state["counts"]["connections"] += 1
            self.save()

    def read(self, function, *args, **kwargs):
        self.charge("reads")
        return function(*args, **kwargs)

    def intent(self, key, kind):
        self.check()
        require(key not in self.state["actions"], "uncertain_action:" + key)
        self.charge(kind)
        self.state["actions"][key] = "intent"
        self.save()


class Source:
    def __init__(self, source, control):
        self.source, self.control = source, control

    def _call(self, kind, request, sink, check):
        control = self.control
        control.charge(kind)
        control.state["seconds"] += 120
        require(control.state["seconds"] <= LIMITS["seconds"], "time_budget")
        control.save()
        started = control.clock()

        def checked():
            check()
            control.check()
            require(control.clock() - started <= 120, "source_timeout")

        # An exception leaves the reservation charged, including across restarts.
        getattr(self.source, "copy" if kind == "copies" else "metadata")(
            request, sink, checked
        )
        control.state["seconds"] -= 120
        require(control.clock() - started <= 120, "source_timeout")
        control.check()
        control.save()

    def copy(self, request, sink, check):
        self._call("copies", request, sink, check)

    def metadata(self, request, sink, check):
        self._call("metadata", request, sink, check)
