"""Fixed-version, standard-library-only worker for the historical r4 audit.

This is an internal pipe entry, not a market reader or a public CLI. Algorithm
source is supplied in memory by the parent; no repository package is loaded.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
import importlib.abc
import json
import math
import os
import resource
import selectors
import struct
import sys
import time
from types import ModuleType


OLD_COMMIT = "da4a97eeffd4840191fcb9f95283d6be97bb8d28"
CURRENT_COMMIT = "c6a845fe3e8f13258b3c12f3ecfa843bce544f85"
PRODUCT_PACKAGE = "src.biz.services.wealth.market.index_detail_xxm"
RESEARCH_PACKAGE = "scripts.research.index_market.xxm"
PRODUCT_MODULES = tuple(
    (f"{PRODUCT_PACKAGE}.{name}", f"src/biz/services/wealth/market/index_detail_xxm/{name}.py")
    for name in ("types", "spec", "snapshot_validation", "calculator")
)
RESEARCH_MODULES = tuple(
    (f"{RESEARCH_PACKAGE}.{name}", f"scripts/research/index_market/xxm/{name}.py")
    for name in ("r4_reference_trial", "r4_observation", "r4_comparison_records", "r4_comparison")
)
PROTOCOL_VERSION = 1
MAX_INPUT_BARS = 1000
MAX_SOURCE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 100 * 1024 * 1024
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
MAX_CONTROL_BYTES = 4 * 1024
MAX_TOTAL_CONTROL_BYTES = 256 * 1024
MAX_CONTROL_MESSAGES = 1024
MAX_STDERR_BYTES = 64 * 1024
IO_CHUNK_BYTES = 64 * 1024
POLL_SECONDS = 0.05
RESOURCE_INTERVAL_SECONDS = 0.05
RESOURCE_IMMEDIATE_BYTES = 1024 * 1024
REQUEST_FIELDS = frozenset((
    "kind", "protocolVersion", "bundle", "commit", "tsCode", "period", "startDate", "endDate",
    "inputIdentity", "inputCount", "rows", "modules", "workDeadline", "maxWorkerMemoryBytes",
    "maxResultBytes",
))


def encode_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def strict_json_loads(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Non-finite JSON number")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number

    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                      parse_constant=invalid_constant, parse_float=finite_float)


def frame_bytes(value) -> bytes:
    body = encode_json(value)
    return struct.pack(">Q", len(body)) + body


def _integer(value, upper: int) -> bool:
    return type(value) is int and 0 < value <= upper


def _day(value: object) -> str:
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Invalid daily date")
    return value


def validate_request(value) -> dict:
    if type(value) is not dict or set(value) != REQUEST_FIELDS:
        raise ValueError("Invalid request fields")
    if (value["kind"] != "REQUEST" or type(value["protocolVersion"]) is not int
            or value["protocolVersion"] != PROTOCOL_VERSION):
        raise ValueError("Invalid protocol version")
    bundle = value["bundle"]
    if bundle not in ("OLD_PAIR", "CURRENT") or type(bundle) is not str:
        raise ValueError("Invalid bundle")
    expected_commit = OLD_COMMIT if bundle == "OLD_PAIR" else CURRENT_COMMIT
    if (value["commit"] != expected_commit or value["tsCode"] != "000001.SH"
            or value["period"] != "day"):
        raise ValueError("Invalid fixed calculation identity")
    start, end = _day(value["startDate"]), _day(value["endDate"])
    if start > end or start < "2023-01-03" or end > "2026-10-27":
        raise ValueError("Invalid calculation interval")
    if type(value["inputIdentity"]) is not str or not value["inputIdentity"]:
        raise ValueError("Missing input identity")
    if not _integer(value["inputCount"], MAX_INPUT_BARS):
        raise ValueError("Invalid input count")
    rows = value["rows"]
    if type(rows) not in (list, tuple) or len(rows) != value["inputCount"]:
        raise ValueError("Input count does not match rows")
    previous = None
    for row in rows:
        if type(row) not in (tuple, list) or len(row) != 6:
            raise ValueError("Expected six scalar input fields")
        day = _day(row[0])
        if not start <= day <= end or previous is not None and day <= previous:
            raise ValueError("Input dates are outside the interval or not unique ascending")
        if (row[5] is not True or any(type(number) is not float or not math.isfinite(number)
                                    for number in row[1:5]) or row[1] <= 0):
            raise ValueError("Expected completed bars with finite original floats")
        previous = day
    deadline = value["workDeadline"]
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("Invalid work deadline")
    if not _integer(value["maxWorkerMemoryBytes"], MAX_MEMORY_BYTES):
        raise ValueError("Invalid worker memory allowance")
    if not _integer(value["maxResultBytes"], MAX_RESULT_BYTES):
        raise ValueError("Invalid result allowance")
    expected = PRODUCT_MODULES + (RESEARCH_MODULES if bundle == "OLD_PAIR" else ())
    modules = value["modules"]
    if type(modules) not in (tuple, list) or len(modules) != len(expected):
        raise ValueError("Invalid module list")
    total = 0
    for module, (name, path) in zip(modules, expected):
        if (type(module) is not dict or set(module) != {"name", "path", "source"}
                or module["name"] != name or module["path"] != path
                or type(module["source"]) is not str):
            raise ValueError("Invalid fixed module identity")
        total += len(module["source"].encode("utf-8", errors="strict"))
        if total > MAX_SOURCE_BYTES:
            raise OverflowError("Module sources exceed the byte allowance")
    return value


def _peak_memory_bytes() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("Historical comparison requires Darwin")
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _read_request(fd: int) -> dict:
    """Read one bounded frame and EOF. The owning parent enforces its deadline."""
    os.set_blocking(fd, False)
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_READ)
    header, body = bytearray(), bytearray()
    size = None
    try:
        while True:
            _peak_memory_bytes()
            for _key, _mask in selector.select(POLL_SECONDS):
                try:
                    # Read no more than the outstanding field, then one byte for EOF.
                    wanted = 8 - len(header) if size is None else max(1, size - len(body))
                    block = os.read(fd, min(IO_CHUNK_BYTES, wanted))
                except BlockingIOError:
                    continue
                if not block:
                    if size is None or len(body) != size:
                        raise ValueError("Incomplete request frame")
                    return validate_request(strict_json_loads(body))
                if size is None:
                    header.extend(block)
                    if len(header) == 8:
                        size = struct.unpack(">Q", header)[0]
                        if not 0 < size <= MAX_REQUEST_BYTES:
                            raise OverflowError("Request exceeds the byte allowance")
                elif len(body) == size:
                    raise ValueError("Extra bytes after request")
                else:
                    body.extend(block)
    finally:
        selector.close()


class _Runtime:
    """One nonrecursive sender, with resource updates between complete frames."""

    def __init__(self, request: dict, output_fd: int):
        self.request, self.output_fd = request, output_fd
        self.phase = "OLD" if request["bundle"] == "OLD_PAIR" else "CURRENT"
        self.partial_frame = False
        self.hello_sent = self.closed = self.sending = False
        self.peak = self.reported_peak = self.pending_peak = 0
        self.last_reported_at = 0.0
        self.control_bytes = self.control_count = 0
        os.set_blocking(output_fd, False)

    def _sample(self):
        self.peak = max(self.peak, _peak_memory_bytes())
        self.pending_peak = max(self.pending_peak, self.peak)
        if time.monotonic() >= self.request["workDeadline"]:
            raise TimeoutError("Worker deadline expired")
        if self.peak > self.request["maxWorkerMemoryBytes"]:
            raise MemoryError("Worker memory allowance exceeded")

    def check(self, *, force: bool = False):
        self._sample()
        if not self.sending and self.hello_sent and not self.closed:
            self._flush_resource(force=force)

    def _flush_resource(self, *, force=False):
        now = time.monotonic()
        increase = self.pending_peak - self.reported_peak
        if force or increase > 0 and (increase >= RESOURCE_IMMEDIATE_BYTES
                                     or now - self.last_reported_at >= RESOURCE_INTERVAL_SECONDS):
            peak = self.pending_peak
            self.send("RESOURCE", phase=self.phase, peakMemoryBytes=peak)
            self.reported_peak = peak
            self.last_reported_at = now

    def send(self, kind: str, **fields):
        if self.closed or self.sending:
            raise RuntimeError("Cannot insert a frame into an unfinished message")
        self.sending = True
        try:
            message = dict(kind=kind, protocolVersion=PROTOCOL_VERSION,
                           bundle=self.request["bundle"], commit=self.request["commit"], pid=os.getpid(),
                           **fields)
            self._sample()
            body = encode_json(message)
            self._sample()
            limit = self.request["maxResultBytes"] if kind == "RESULT" else MAX_CONTROL_BYTES
            if len(body) > limit:
                raise OverflowError("Worker message exceeds its byte allowance")
            if kind != "RESULT":
                if (self.control_count + 1 > MAX_CONTROL_MESSAGES
                        or self.control_bytes + len(body) > MAX_TOTAL_CONTROL_BYTES):
                    raise OverflowError("Worker control messages exceed their allowance")
                self.control_count += 1
                self.control_bytes += len(body)
            self._write_frame(body)
            if kind == "HELLO":
                self.hello_sent = True
                self.reported_peak = fields["peakMemoryBytes"]
                self.last_reported_at = time.monotonic()
            if kind in ("DONE", "ERROR"):
                self.closed = True
        finally:
            self.sending = False

    def _write_frame(self, body: bytes):
        selector = selectors.DefaultSelector()
        selector.register(self.output_fd, selectors.EVENT_WRITE)
        try:
            for part in (struct.pack(">Q", len(body)), body):
                view = memoryview(part)
                position = 0
                while position < len(view):
                    self._sample()  # Never sends a nested RESOURCE or ERROR.
                    wait = min(POLL_SECONDS, max(0, self.request["workDeadline"] - time.monotonic()))
                    for _key, _mask in selector.select(wait):
                        try:
                            size = os.write(self.output_fd, view[position:position + IO_CHUNK_BYTES])
                        except BlockingIOError:
                            continue
                        if size <= 0:
                            raise BrokenPipeError("Output pipe closed")
                        self.partial_frame = True
                        position += size
            self.partial_frame = False
        finally:
            selector.close()

    def error(self, error: BaseException):
        if self.partial_frame or self.closed:
            return
        kind = ("TIMEOUT" if isinstance(error, TimeoutError) else
                "MEMORY" if isinstance(error, MemoryError) else
                "SIZE" if isinstance(error, OverflowError) else
                "MODULE" if isinstance(error, ImportError) else
                "INPUT" if isinstance(error, (ValueError, TypeError)) else "INTERNAL")
        # A budget failure may prevent even this small final message. In that
        # case exiting nonzero remains mandatory; error reporting is best effort.
        try:
            self.send("ERROR", phase=self.phase, exceptionType=type(error).__name__[:128], errorKind=kind)
        except BaseException:
            pass


class _BusinessImportGuard(importlib.abc.MetaPathFinder):
    def __init__(self, allowed):
        self.allowed = frozenset(allowed)

    def find_spec(self, fullname, path=None, target=None):
        if (fullname == "src" or fullname.startswith("src.")
                or fullname == "scripts" or fullname.startswith("scripts.")):
            if fullname not in self.allowed:
                raise ImportError("Business module outside the fixed list")
        return None


def _load_modules(request: dict, runtime: _Runtime):
    names = {module["name"] for module in request["modules"]}
    packages = set()
    for name in names:
        pieces = name.split(".")
        packages.update(".".join(pieces[:index]) for index in range(1, len(pieces)))
    guard = _BusinessImportGuard(names | packages)
    sys.meta_path.insert(0, guard)
    for name in sorted(packages, key=lambda item: (item.count("."), item)):
        if name in sys.modules:
            raise ImportError("Worker namespace was not empty")
        package = ModuleType(name)
        package.__path__ = []
        package.__package__ = name
        sys.modules[name] = package
        if "." in name:
            parent, attribute = name.rsplit(".", 1)
            setattr(sys.modules[parent], attribute, package)
    loaded = {}
    for module in request["modules"]:
        runtime.check(force=True)
        name = module["name"]
        instance = ModuleType(name)
        instance.__package__ = name.rsplit(".", 1)[0]
        instance.__file__ = f"<git:{request['commit']}:{module['path']}>"
        sys.modules[name] = instance
        setattr(sys.modules[instance.__package__], name.rsplit(".", 1)[1], instance)
        exec(compile(module["source"], instance.__file__, "exec"), instance.__dict__)
        loaded[name] = instance
        runtime.check(force=True)
    return loaded


@contextmanager
def _observe_old_memory(module, runtime):
    original = module._memory_bytes

    def observed():
        value = original()
        runtime.check()
        return value

    module._memory_bytes = observed
    try:
        yield
    finally:
        module._memory_bytes = original


def _calculate(request, runtime, modules):
    product_spec = modules[f"{PRODUCT_PACKAGE}.spec"].MAIN_SPEC
    types = modules[f"{PRODUCT_PACKAGE}.types"]
    expected_version = "xxm-direction-v0.1-r2" if request["bundle"] == "OLD_PAIR" else "xxm-direction-v0.2-r4"
    if product_spec.algorithm_version != expected_version:
        raise ValueError("Fixed product rule version mismatch")
    bars = tuple(types.XxmBar(*row) for row in request["rows"])
    runtime.check(force=True)
    if request["bundle"] == "OLD_PAIR":
        trial_spec = modules[f"{RESEARCH_PACKAGE}.r4_reference_trial"].R4_TRIAL_SPEC
        if trial_spec.research_version != "xxm-research-r4-v2":
            raise ValueError("Fixed research rule version mismatch")
        comparison = modules[f"{RESEARCH_PACKAGE}.r4_comparison"]
        with _observe_old_memory(comparison, runtime):
            result = comparison.compare_r4(
                bars, period="day", source_identity=request["inputIdentity"],
                start_date=request["startDate"], end_date=request["endDate"],
                deadline=request["workDeadline"],
            )
        payload = {name: result.pop(name) for name in ("metadata", "rows", "summary")}
        result.clear()  # Drop differences/idPairs before encoding the retained facts.
        payload["metadata"].update(bundle=request["bundle"], commit=request["commit"],
                                   inputIdentity=request["inputIdentity"], inputCount=len(bars),
                                   r2Spec=asdict(product_spec), r4Spec=asdict(trial_spec))
        return payload, {"r2": len(bars), "r4": len(bars)}
    calculator = modules[f"{PRODUCT_PACKAGE}.calculator"].XxmCalculator(
        period="day", source_identity=request["inputIdentity"], record_decisions=True)
    rows = []
    for bar in bars:
        runtime.check()
        step = calculator.step(bar)
        rows.append(dict(time=bar.time, point=step.point, events=list(step.events),
                         structures=list(step.structures), decision=step.decision))
        runtime.check()
    if (calculator.spec is not product_spec or calculator.source_identity != request["inputIdentity"]
            or calculator.period != "day" or calculator.processed != len(bars)):
        raise ValueError("Current calculation identity changed")
    identity = dict(bundle=request["bundle"], commit=request["commit"], tsCode=request["tsCode"],
                    period=request["period"], inputIdentity=request["inputIdentity"], inputCount=len(bars),
                    requestedStartDate=request["startDate"], requestedEndDate=request["endDate"],
                    algorithmVersion=product_spec.algorithm_version, specHash=product_spec.spec_hash,
                    spec=asdict(product_spec))
    return dict(identity=identity, rows=rows), {"current": len(bars)}


def worker_main() -> int:
    """Consume exactly one request, emit verified facts, then exit."""
    runtime = None
    try:
        if len(sys.argv) != 1:
            raise ValueError("No worker command-line parameters are supported")
        request = _read_request(sys.stdin.fileno())
        runtime = _Runtime(request, sys.stdout.fileno())
        runtime.check()
        runtime.send("HELLO", peakMemoryBytes=runtime.peak)
        modules = _load_modules(request, runtime)
        payload, counts = _calculate(request, runtime, modules)
        runtime.check(force=True)
        runtime.send("RESULT", payload=payload)
        del payload
        runtime.check(force=True)
        runtime.send("DONE", peakMemoryBytes=runtime.peak, processedCounts=counts)
        return 0
    except BaseException as error:
        if runtime is not None:
            runtime.error(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(worker_main())
