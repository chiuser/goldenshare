"""One-use Git-backed old r4 capture; never a product algorithm entry.

Only the five fixed blobs below are loaded, in this disposable process's RAM.
The two positional deadline values are internal parent/child protocol fields.
Importing this module does not read Git, import an engine, or calculate.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from . import xxm_product_v1_migration_worker as protocol

MigrationError = protocol.MigrationError
BASELINE_COMMIT = "528659ae97843f06e5be560aa24fc10019fdb039"
SOURCE_BYTES = 64_493
MAX_SOURCE_BYTES = 1024 * 1024
ROOT = Path(__file__).resolve().parents[4]
SOURCE_BLOBS = {
    "src/biz/services/wealth/market/index_detail_xxm/spec.py": dict(
        module="src.biz.services.wealth.market.index_detail_xxm.spec",
        oid="ca22cbd4a6807350b6eab2afe781a26911bda2fd", size=1351),
    "src/biz/services/wealth/market/index_detail_xxm/types.py": dict(
        module="src.biz.services.wealth.market.index_detail_xxm.types",
        oid="3eae37dcb09d74c28d04678da6808b3089f610ef", size=3169),
    "src/biz/services/wealth/market/index_detail_xxm/snapshot_validation.py": dict(
        module="src.biz.services.wealth.market.index_detail_xxm.snapshot_validation",
        oid="feb46bb8f1e193f79d495b2f04e94097289f0c00", size=10647),
    "src/biz/services/wealth/market/index_detail_xxm/calculator.py": dict(
        module="src.biz.services.wealth.market.index_detail_xxm.calculator",
        oid="45aad036f1478752076ca7afa280477b5d65adf8", size=26029),
    "scripts/research/index_market/xxm/r4_reference_trial.py": dict(
        module="scripts.research.index_market.xxm.r4_reference_trial",
        oid="bc56921e7b647c5ebcef6343680f4d510cb67902", size=23297),
}
R2_SPEC_FIELDS = dict(
    algorithm_version="xxm-direction-v0.1-r2", dif_turn_pct=1.0, max_refs=2, min_bars=2,
    reference_policy="strongest_eligible", macd_parameters=(12, 26, 9), histogram_multiplier=2,
    color_flip=True, flip_requires_turn=False, historical_price_only=True, fixed_expiry=None,
    bottom_history_policy="closed_origin_close_break_v1", same_segment_bottom_policy="current_close_rearm_v1",
    bottom_dull_reference_policy="prebreak_strongest_eligible_v1")
R4_SPEC_FIELDS = dict(
    research_version="xxm-research-r4-v2", reference_policy="nearest_then_farther_two",
    active_reference_policy="same_bar_near_to_far_on_dull_break", zero_policy="neutral_real_opposite",
    allow_zero_activation=True, allow_zero_reactivation=True, dif_turn_pct=1.0, max_refs=2,
    min_colored_bars=2, max_input_bars=1000, deadline_seconds=20.0,
    max_memory_bytes=256 * 1024 * 1024, max_result_bytes=16 * 1024 * 1024)
R2_SPEC_HASH = hashlib.sha256(json.dumps(R2_SPEC_FIELDS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
R4_RESEARCH_HASH = hashlib.sha256(json.dumps(
    {**R4_SPEC_FIELDS, "parentSpecHash": R2_SPEC_HASH}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
_MODULES = {item["module"]: path for path, item in SOURCE_BLOBS.items()}
_PARENTS = frozenset({"scripts.research.index_market.tests"} | {
    name.rsplit(".", i)[0] for name in _MODULES for i in range(1, name.count(".") + 1)})
_STDLIB_IMPORTS = frozenset(("__future__", "copy", "dataclasses", "datetime", "hashlib", "json", "math", "typing"))
_PROJECT_ROOTS = frozenset(("src", "scripts", "qtf", "lake_console", "tests", "reports", "wealth"))


def parse_git_batch(data, expected=None):
    """Check the exact batch framing and blob identities without executing it."""
    expected = SOURCE_BLOBS if expected is None else expected
    if type(data) not in (bytes, bytearray) or len(data) > MAX_SOURCE_BYTES + 128 * len(expected):
        raise MigrationError("Git response exceeded source limit")
    position, total, sources = 0, 0, {}
    for path, identity in expected.items():
        end = data.find(b"\n", position, position + 129)
        if end == -1:
            raise MigrationError("Git header missing or truncated")
        try:
            oid, kind, length = bytes(data[position:end]).decode("ascii").split(" ")
            size = int(length)
        except (ValueError, UnicodeError) as exc:
            raise MigrationError("Git header invalid or source missing") from exc
        if (oid != identity["oid"] or kind != "blob" or size != identity["size"]
                or size < 0 or str(size) != length):
            raise MigrationError("Git blob identity/type/length differs")
        total += size
        if total > MAX_SOURCE_BYTES:
            raise MigrationError("Git sources exceeded 1 MiB")
        position = end + 1
        body = bytes(data[position:position + size])
        position += size
        if len(body) != size or data[position:position + 1] != b"\n":
            raise MigrationError("Git blob body or delimiter truncated")
        position += 1
        actual = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0" + body).hexdigest()
        if actual != oid:
            raise MigrationError("Git blob content identity differs")
        sources[path] = body
    if position != len(data):
        raise MigrationError("Git returned extra response data")
    return sources


def _reap_git(child, budget):
    # Cleanup has only the parent's already reserved final second.  The work
    # alarm must not interrupt a wait between TERM and the mandatory KILL/reap.
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    if old_timer[0]:
        signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        try:
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()
            if child.poll() is None:
                child.terminate()
                try:
                    remaining = max(0, budget.end - time.monotonic())
                    child.wait(timeout=min(.2, remaining / 2))
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=max(.000001, budget.end - time.monotonic()))
    finally:
        if old_timer[0] and time.monotonic() < budget.work_end:
            signal.setitimer(signal.ITIMER_REAL, budget.work_end - time.monotonic())


def read_git_sources(budget):
    """One Git process and one request for each fixed source, with bounded IO."""
    budget.check()
    request = "".join(f"{BASELINE_COMMIT}:{path}\n" for path in SOURCE_BLOBS).encode("ascii")
    child = None
    selector = selectors.DefaultSelector()
    output, errors = bytearray(), bytearray()
    limit = SOURCE_BYTES + 128 * len(SOURCE_BLOBS)
    try:
        environment = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
        child = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT, env=environment,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # This fixed request is below PIPE_BUF; all response reads are bounded.
        child.stdin.write(request)
        child.stdin.close()
        for stream, kind in ((child.stdout, "stdout"), (child.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, kind)
        while selector.get_map():
            budget.check()
            for key, _mask in selector.select(max(0, min(.05, budget.work_end - time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target, maximum = (output, limit) if key.data == "stdout" else (errors, protocol.MAX_STDERR)
                if len(target) + len(chunk) > maximum:
                    raise MigrationError(f"Git {key.data} exceeded limit")
                target.extend(chunk)
        budget.check()
        if child.wait(timeout=max(.000001, budget.work_end - time.monotonic())) != 0 or errors:
            raise MigrationError("Git failed or wrote stderr")
        sources = parse_git_batch(output)
        if sum(map(len, sources.values())) != SOURCE_BYTES:
            raise MigrationError("Git source total differs")
        return sources
    finally:
        selector.close()
        if child is not None:
            _reap_git(child, budget)


def validate_package_source(source, label="parent package"):
    try:
        tree = ast.parse(source, filename=label)
    except (SyntaxError, UnicodeError) as exc:
        raise MigrationError(f"{label}: invalid parent package source") from exc
    if any(not (isinstance(node, ast.Pass) or isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant) and type(node.value.value) is str) for node in tree.body):
        raise MigrationError(f"{label}: parent package contains executable statements")


def validate_parent_packages(root=None):
    root = ROOT if root is None else Path(root).resolve()
    for name in sorted(_PARENTS):
        directory = root.joinpath(*name.split("."))
        if directory.resolve() != directory or not directory.is_dir():
            raise MigrationError(f"{name}: parent package is outside expected repository path")
        initializer = directory / "__init__.py"
        if initializer.exists():
            if initializer.resolve() != initializer or initializer.stat().st_size > 65536:
                raise MigrationError(f"{name}: parent initializer path/size differs")
            validate_package_source(initializer.read_bytes(), name)
        loaded = sys.modules.get(name)
        if loaded is not None:
            if set(map(lambda path: Path(path).resolve(), getattr(loaded, "__path__", ()))) != {directory}:
                raise MigrationError(f"{name}: loaded parent package path differs")
            origin = getattr(loaded, "__file__", None)
            if origin is not None and Path(origin).resolve() != initializer:
                raise MigrationError(f"{name}: loaded parent initializer differs")


def validate_source_imports(sources):
    if set(sources) != set(SOURCE_BLOBS):
        raise MigrationError("old source set differs")
    for path, source in sources.items():
        module = SOURCE_BLOBS[path]["module"]
        tree = ast.parse(source, filename=f"git:{BASELINE_COMMIT}:{path}")
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                names = [importlib.util.resolve_name(target, module.rsplit(".", 1)[0]) if node.level else target]
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ("__import__", "eval", "exec", "compile")):
                raise MigrationError("old source contains dynamic loading")
            if any(name not in _MODULES and name not in _STDLIB_IMPORTS for name in names):
                raise MigrationError(f"{path}: unapproved source dependency")


class _MemoryLoader(importlib.abc.Loader):
    def __init__(self, path, source, budget):
        self.path, self.source, self.budget = path, source, budget

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self.budget.check()
        origin = f"git:{BASELINE_COMMIT}:{self.path}"
        module.__file__, module.__cached__ = origin, None
        exec(compile(self.source, origin, "exec"), module.__dict__)
        self.budget.check()


class BaselineFinder(importlib.abc.MetaPathFinder):
    def __init__(self, sources, budget):
        self.sources, self.budget = sources, budget

    def find_spec(self, fullname, path=None, target=None):
        if fullname in _MODULES:
            if target is not None:
                raise MigrationError("old source reload is prohibited")
            source_path = _MODULES[fullname]
            loader = _MemoryLoader(source_path, self.sources[source_path], self.budget)
            return importlib.util.spec_from_loader(fullname, loader, origin=f"git:{BASELINE_COMMIT}:{source_path}")
        if fullname.split(".", 1)[0] in _PROJECT_ROOTS and fullname not in _PARENTS:
            raise MigrationError(f"{fullname}: unapproved project module")
        return None


@contextmanager
def baseline_modules(sources, budget):
    if any(name in sys.modules for name in _MODULES):
        raise MigrationError("old module name is already loaded")
    validate_parent_packages()
    validate_source_imports(sources)
    finder = BaselineFinder(sources, budget)
    sys.meta_path.insert(0, finder)
    try:
        with budget.stage("capture/import"):
            trial = importlib.import_module("scripts.research.index_market.xxm.r4_reference_trial")
            spec = importlib.import_module("src.biz.services.wealth.market.index_detail_xxm.spec")
            types = importlib.import_module("src.biz.services.wealth.market.index_detail_xxm.types")
        yield trial, spec, types
    finally:
        sys.meta_path.remove(finder)
        for name in _MODULES:
            module = sys.modules.pop(name, None)
            parent_name, _, attribute = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if module is not None and parent is not None and getattr(parent, attribute, None) is module:
                delattr(parent, attribute)


def _check_spec(actual, expected, label):
    values = asdict(actual)

    def same(left, right):
        if type(left) is not type(right):
            return False
        if type(right) is dict:
            return left.keys() == right.keys() and all(same(left[key], value) for key, value in right.items())
        if type(right) in (tuple, list):
            return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right, strict=True))
        return left == right

    if not same(values, expected):
        raise MigrationError(f"{label}: old Spec fields/type differ")


def capture_records(cases, budget):
    protocol.validate_inputs(cases, budget)
    with budget.stage("capture/git"):
        sources = read_git_sources(budget)
    records, identities = [], []
    retained = protocol.RetainedSize(cases, sources, records, identities, budget=budget)
    with baseline_modules(sources, budget) as (trial, spec, types):
        _check_spec(spec.MAIN_SPEC, R2_SPEC_FIELDS, "r2")
        _check_spec(trial.R4_TRIAL_SPEC, R4_SPEC_FIELDS, "research r4-v2")
        spec_hash, research_hash = spec.MAIN_SPEC.spec_hash, trial.R4_TRIAL_SPEC.research_hash
        if (spec_hash, research_hash) != (R2_SPEC_HASH, R4_RESEARCH_HASH):
            raise MigrationError("old Spec hashes differ")
        for case in cases:
            with budget.stage("capture/calculate", case=f"{case['period']}/{case['caseName']}"):
                calculator = trial.R4Calculator(period=case["period"], source_identity=case["sourceIdentity"], ts_code="000001.SH")
                record = deepcopy(case)
                record["steps"] = []
                retained.add(record)
                wrapped_source = f"r4|{research_hash}|{case['period']}|{case['sourceIdentity']}"

                def snapshot_state():
                    snapshot = calculator.snapshot()
                    protocol.fields(snapshot, {"researchVersion", "researchHash", "tsCode", "period", "inputIdentity", "parentState"}, "research wrapper")
                    expected = (R4_SPEC_FIELDS["research_version"], research_hash, "000001.SH", case["period"], case["sourceIdentity"])
                    if tuple(snapshot[key] for key in ("researchVersion", "researchHash", "tsCode", "period", "inputIdentity")) != expected:
                        raise MigrationError("capture wrapper identity differs")
                    parent = snapshot["parentState"]
                    if tuple(parent.get(key) for key in ("specHash", "tsCode", "period", "sourceIdentity")) != (spec_hash, "000001.SH", case["period"], wrapped_source):
                        raise MigrationError("capture parent identity differs")
                    return protocol.state_from_snapshot(parent)

                for bar in case["bars"]:
                    budget.check()
                    before = snapshot_state()
                    step = calculator.step(types.XxmBar(**bar))
                    stored = protocol.step_record(step, before, snapshot_state())
                    retained.add(stored)
                    record["steps"].append(stored)
                    retained.refresh(record["steps"])
                    retained.check(before)
                protocol.validate_record(record, budget)
                records.append(record)
                retained.refresh(records)
                identity = dict(caseName=case["caseName"], period=case["period"], inputIdentity=case["sourceIdentity"], sourceIdentity=wrapped_source)
                retained.add(identity)
                identities.append(identity)
                retained.refresh(identities)
                del calculator, snapshot_state, before, step, stored, record
    result = dict(records=records, metadata=dict(
        algorithmVersion=R2_SPEC_FIELDS["algorithm_version"], specHash=spec_hash,
        researchVersion=R4_SPEC_FIELDS["research_version"], researchHash=research_hash, identities=identities,
        commit=BASELINE_COMMIT, sourceReads={path: 1 for path in SOURCE_BLOBS}, sourceBytes=sum(map(len, sources.values()))))
    retained.add(result)
    budget.check()
    return result


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise MigrationError("capture requires the parent's two internal deadlines")
        work_end, end = map(float, args)
        if (not all(map(math.isfinite, (work_end, end))) or not 0 < end - work_end <= 1.000001
                or end - time.monotonic() > 20.000001):
            raise MigrationError("capture deadline differs from parent phase")
        if not sys.dont_write_bytecode:
            raise MigrationError("capture interpreter requires -B at startup")
        budget = protocol.Budget(work_end=work_end, end=end)
        with budget.interrupt_at_deadline():
            with budget.stage("capture/input"):
                data = bytearray()
                while True:
                    budget.check()
                    chunk = sys.stdin.buffer.read1(65536)
                    if not chunk:
                        break
                    if len(data) + len(chunk) > protocol.MAX_BYTES:
                        raise MigrationError("capture input exceeded 16 MiB")
                    data.extend(chunk)
                cases = protocol.decode(data, budget)
                del data
            result = capture_records(cases, budget)
            with budget.stage("capture/output"):
                retained = protocol.RetainedSize(cases, result, budget=budget)
                data = protocol.encode(result, budget, retained=retained)
                protocol.bounded_size(cases, result, data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
                budget.check()
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        location = getattr(locals().get("budget"), "location", "capture/start")
        sys.stderr.write((f"{location}: {type(exc).__name__}: {str(exc)[:500]}\n")[:protocol.MAX_STDERR])
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
