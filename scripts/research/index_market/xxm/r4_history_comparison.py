"""One bounded historical recognition comparison, isolated from product runtime.

The public entry reads real data. First-batch tests call only the internal
functions with literal source rows; importing this module performs no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import selectors
import subprocess
import sys
import time

from . import r4_history_worker as wire
from . import r4_history_lake as lake


@dataclass(frozen=True, slots=True)
class HistoryComparisonSpec:
    old_commit: str = wire.OLD_COMMIT
    current_commit: str = wire.CURRENT_COMMIT
    ts_code: str = lake.SPEC.ts_code
    period: str = lake.SPEC.period
    start_date: str = lake.SPEC.start_date
    end_date: str = lake.SPEC.end_date
    input_count: int = lake.SPEC.input_count
    calendar_count: int = lake.SPEC.calendar_count
    max_input_bars: int = lake.SPEC.max_input_bars
    max_calendar_days: int = lake.SPEC.max_calendar_days
    total_seconds: float = 20.0
    cleanup_seconds: float = 0.5
    read_seconds: float = lake.SPEC.read_seconds
    git_seconds: float = 2.0
    max_memory_bytes: int = wire.MAX_MEMORY_BYTES
    max_result_bytes: int = wire.MAX_RESULT_BYTES
    max_source_bytes: int = wire.MAX_SOURCE_BYTES
    max_request_bytes: int = wire.MAX_REQUEST_BYTES
    max_control_bytes: int = wire.MAX_CONTROL_BYTES
    max_control_total: int = wire.MAX_TOTAL_CONTROL_BYTES
    max_control_count: int = wire.MAX_CONTROL_MESSAGES
    max_stderr_bytes: int = wire.MAX_STDERR_BYTES
    io_chunk: int = wire.IO_CHUNK_BYTES
    poll_seconds: float = wire.POLL_SECONDS
    final_checks: int = 5

    def __post_init__(self):
        # These are fixed internal limits, not an experiment parameter surface.
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not type(field.default) or value != field.default:
                raise ValueError(f"专项固定参数不能变更：{field.name}")


SPEC = HistoryComparisonSpec()
REPO_ROOT = Path(__file__).resolve().parents[4]
CORE_PATHS = tuple(
    f"src/biz/services/wealth/market/index_detail_xxm/{name}.py"
    for name in ("types", "spec", "snapshot_validation", "calculator")
)


def _encoded(value):
    return wire.encode_json(value)


class ResearchBudget:
    """One clock and a conservative upper bound across serial owned children."""

    def __init__(self, *, check_cancelled=None):
        if sys.platform != "darwin" or sys.version_info[:2] != (3, 13):
            raise RuntimeError("专项要求本机Darwin及现有Python3.13")
        self.spec = SPEC
        self.t0 = time.monotonic()
        self.deadline = self.t0 + SPEC.total_seconds
        self.work_deadline = self.deadline - SPEC.cleanup_seconds
        self.check_cancelled = check_cancelled
        self.parent_peak = self.waited_peak = self.reported_peak = 0
        self.active = None
        self.processes = []
        self.stage = "PRECHECK"
        self.stage_started = self.t0
        self.stage_seconds = {}
        self.process_deadline = self.work_deadline
        self.process_cleanup_deadline = self.deadline
        self.result_sizes = []
        self.schema_reads = self.market_reads = self.calendar_reads = 0
        self.check()

    def measure(self):
        self.parent_peak = max(self.parent_peak, int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
        self.waited_peak = max(self.waited_peak, int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss))
        combined = self.parent_peak + max(self.waited_peak, self.reported_peak)
        if combined > SPEC.max_memory_bytes:
            raise MemoryError(f"专项合计内存超限，阶段{self.stage}")
        return combined

    def check(self):
        if self.check_cancelled is not None and self.check_cancelled():
            from src.biz.services.wealth.market.index_detail_daily_wave.budget import DailyWaveCancelled
            raise DailyWaveCancelled("本次历史对比已取消")
        if time.monotonic() >= min(self.work_deadline, self.process_deadline):
            raise TimeoutError(f"专项超过统一时限，阶段{self.stage}")
        self.measure()

    def enter(self, stage):
        self.check()
        now = time.monotonic()
        self.stage_seconds[self.stage] = self.stage_seconds.get(self.stage, 0.0) + now - self.stage_started
        self.stage, self.stage_started = stage, now

    def register(self, proc, *, git=False):
        if self.active is not None:
            raise RuntimeError("专项不允许两个活动子进程")
        self.active = proc
        self.processes.append(proc)
        self.process_deadline = min(self.work_deadline, time.monotonic() + SPEC.git_seconds) if git else self.work_deadline
        self.process_cleanup_deadline = self.deadline

    def collected(self, proc):
        if self.active is not proc or proc.returncode is None:
            raise RuntimeError("本次子进程尚未确认回收")
        self.active = None
        self.process_deadline = self.work_deadline
        self.process_cleanup_deadline = self.deadline
        self.measure()

    @property
    def result_remaining(self):
        remaining = SPEC.max_result_bytes - sum(self.result_sizes)
        if remaining <= 0:
            raise OverflowError("专项结果已达到总大小上限")
        return remaining


def _close_pipes(proc):
    failure = None
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None and not pipe.closed:
            try:
                pipe.close()
            except BaseException as exc:
                failure = failure or exc
    return failure


def _cleanup_process(proc, budget, original=None):
    """No cancellation callback here: a second cancellation cannot skip wait."""
    failure = None
    deadline = min(budget.deadline, budget.process_cleanup_deadline)
    if proc.stdin is not None and not proc.stdin.closed:
        try:
            proc.stdin.close()
        except BaseException as exc:
            failure = exc
    try:
        if proc.poll() is None:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining:
                proc.terminate()
                try:
                    proc.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    pass
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    failure = TimeoutError("专项清理超时，进程退出尚未确认")
                    # It is already a failed run. Reap this handle after SIGKILL;
                    # no new work and no success within 20s may be claimed.
                    proc.wait(timeout=0.1)
        else:
            proc.wait(timeout=0)
        if time.monotonic() > deadline:
            failure = failure or TimeoutError("专项清理超过原总时限")
    except BaseException as exc:
        failure = failure or exc
    finally:
        closing_error = _close_pipes(proc)
        failure = failure or closing_error
        if proc.returncode is not None and budget.active is proc:
            try:
                budget.collected(proc)
            except BaseException as exc:
                failure = failure or exc
    if failure is not None:
        if original is not None:
            original.add_note(f"专项清理 CLEANUP: {type(failure).__name__}")
        else:
            raise failure


class _WorkerFrames:
    def __init__(self, proc, request, budget):
        self.proc, self.request, self.budget = proc, request, budget
        self.buffer = bytearray()
        self.expected = None
        self.hello = self.done = False
        self.payload = None
        self.result_bytes = 0
        self.controls = self.control_bytes = self.last_peak = 0

    def feed(self, data):
        view = memoryview(data)
        while view:
            self.budget.check()
            if self.done:
                raise ValueError("DONE后仍有额外消息")
            need = (8 if self.expected is None else self.expected) - len(self.buffer)
            size = min(need, len(view))
            self.buffer.extend(view[:size])
            view = view[size:]
            if len(self.buffer) < (8 if self.expected is None else self.expected):
                continue
            if self.expected is None:
                self.expected = int.from_bytes(self.buffer, "big")
                self.buffer.clear()
                if not 1 <= self.expected <= max(SPEC.max_control_bytes, self.request["maxResultBytes"]):
                    raise OverflowError("worker声明的消息大小超限")
                continue
            self.budget.check()
            message = wire.strict_json_loads(bytes(self.buffer))
            length = self.expected
            self.buffer.clear()
            self.expected = None
            self.budget.check()
            self.accept(message, length)

    def accept(self, message, length):
        if type(message) is not dict:
            raise ValueError("worker消息必须为对象")
        base = {"kind", "protocolVersion", "bundle", "commit", "pid"}
        kind = message.get("kind")
        additions = {"HELLO": {"peakMemoryBytes"}, "RESOURCE": {"phase", "peakMemoryBytes"},
                     "RESULT": {"payload"}, "DONE": {"peakMemoryBytes", "processedCounts"},
                     "ERROR": {"phase", "exceptionType", "errorKind"}}
        if type(kind) is not str or kind not in additions or set(message) != base | additions[kind]:
            raise ValueError("worker消息类型或字段错误")
        if (type(message["protocolVersion"]) is not int or message["protocolVersion"] != 1
                or type(message["pid"]) is not int or message["pid"] != self.proc.pid
                or any(message[k] != self.request[k] for k in ("bundle", "commit"))):
            raise ValueError("worker返回身份错误")
        if kind != "RESULT":
            self.controls += 1
            self.control_bytes += length
            if (length > SPEC.max_control_bytes or self.controls > SPEC.max_control_count
                    or self.control_bytes > SPEC.max_control_total):
                raise OverflowError("worker控制消息超限")
        if "peakMemoryBytes" in message:
            peak = message["peakMemoryBytes"]
            if type(peak) is not int or peak < self.last_peak:
                raise ValueError("worker峰值必须为单调非负整数")
            self.last_peak = peak
            self.budget.reported_peak = max(self.budget.reported_peak, peak)
            self.budget.check()
        if "phase" in message and message["phase"] != ("OLD" if self.request["bundle"] == "OLD_PAIR" else "CURRENT"):
            raise ValueError("worker阶段错误")
        if kind == "HELLO":
            if self.hello or self.payload is not None:
                raise ValueError("HELLO重复或顺序错误")
            self.hello = True
        elif kind == "ERROR":
            error_type, error_kind = message["exceptionType"], message["errorKind"]
            if (not isinstance(error_type, str) or not error_type.isidentifier() or len(error_type) > 128
                    or type(error_kind) is not str
                    or error_kind not in {"INPUT", "VERSION", "MODULE", "PROTOCOL", "TIMEOUT", "MEMORY", "SIZE", "INTERNAL"}):
                raise ValueError("worker错误消息不合法")
            errors = {"TIMEOUT": TimeoutError, "MEMORY": MemoryError, "SIZE": OverflowError,
                      "INPUT": ValueError, "VERSION": ValueError, "MODULE": ValueError, "PROTOCOL": ValueError}
            raise errors.get(error_kind, RuntimeError)(f"worker阶段{message['phase']}：{error_type}")
        elif not self.hello:
            raise ValueError("worker尚未HELLO即发送后续消息")
        elif kind == "RESULT":
            if self.payload is not None or type(message["payload"]) is not dict:
                raise ValueError("RESULT重复或正文类型错误")
            if length > self.request["maxResultBytes"]:
                raise OverflowError("worker结果超限")
            self.payload, self.result_bytes = message["payload"], length
        elif kind == "DONE":
            expected = ({"r2": self.request["inputCount"], "r4": self.request["inputCount"]}
                        if self.request["bundle"] == "OLD_PAIR" else {"current": self.request["inputCount"]})
            counts = message["processedCounts"]
            if (self.payload is None or type(counts) is not dict or counts != expected
                    or any(type(n) is not int for n in counts.values())):
                raise ValueError("DONE顺序或计算根数错误")
            self.done = True

    def finish(self):
        if self.buffer or self.expected is not None or not self.hello or not self.done or self.payload is None:
            raise ValueError("worker不完整EOF或缺少完成消息")


class _LakeFrames(_WorkerFrames):
    """Same bounded framing, separate source identity and SELECT deadlines."""

    def __init__(self, proc, request, budget):
        super().__init__(proc, {"maxResultBytes": lake.SPEC.max_read_result_bytes}, budget)
        self.read_work_deadline = min(request["readDeadline"] - SPEC.cleanup_seconds,
                                      budget.work_deadline)
        self.query_index = 0
        self.query_active = None
        budget.process_deadline = self.read_work_deadline

    def accept(self, message, length):
        fields_by_kind = {
            "HELLO": {"peakMemoryBytes"},
            "QUERY_START": {"query", "peakMemoryBytes"},
            "QUERY_DONE": {"query", "peakMemoryBytes"},
            "RESULT": {"payload"}, "DONE": {"peakMemoryBytes"},
            "ERROR": {"exceptionType", "errorKind"},
        }
        if type(message) is not dict:
            raise ValueError("本地读取消息必须为对象")
        kind = message.get("kind")
        base = {"kind", "protocolVersion", "source", "pid"}
        if (type(kind) is not str or kind not in fields_by_kind
                or set(message) != base | fields_by_kind[kind]
                or type(message["protocolVersion"]) is not int or message["protocolVersion"] != 1
                or message["source"] != lake.SPEC.source
                or type(message["pid"]) is not int or message["pid"] != self.proc.pid):
            raise ValueError("本地读取消息身份或字段错误")
        if kind != "RESULT":
            self.controls += 1
            self.control_bytes += length
            if (length > SPEC.max_control_bytes or self.controls > SPEC.max_control_count
                    or self.control_bytes > SPEC.max_control_total):
                raise OverflowError("本地读取控制消息超限")
        if "peakMemoryBytes" in message:
            peak = message["peakMemoryBytes"]
            if type(peak) is not int or peak < self.last_peak:
                raise ValueError("本地读取峰值必须单调且为非负整数")
            self.last_peak = peak
            self.budget.reported_peak = max(self.budget.reported_peak, peak)
            self.budget.check()
        if kind == "ERROR":
            name, error = message["exceptionType"], message["errorKind"]
            if (type(name) is not str or not name.isidentifier() or len(name) > 128
                    or type(error) is not str or error not in {"INPUT", "TIMEOUT", "MEMORY", "SIZE", "INTERNAL"}):
                raise ValueError("本地读取错误消息非法")
            cls = {"INPUT": ValueError, "TIMEOUT": TimeoutError,
                   "MEMORY": MemoryError, "SIZE": OverflowError}.get(error, RuntimeError)
            raise cls(f"本地读取失败：{name}")
        if kind == "HELLO":
            if self.hello:
                raise ValueError("本地读取HELLO重复")
            self.hello = True
            return
        if not self.hello:
            raise ValueError("本地读取缺少HELLO")
        if kind in {"QUERY_START", "QUERY_DONE"}:
            queries = ("SCHEMA", "MARKET", "CALENDAR")
            if (self.payload is not None or self.query_index >= len(queries)
                    or message["query"] != queries[self.query_index]):
                raise ValueError("本地查询顺序错误")
            if kind == "QUERY_START":
                if self.query_active is not None:
                    raise ValueError("本地查询尚未结束")
                self.query_active = message["query"]
                counter = {"SCHEMA": "schema_reads", "MARKET": "market_reads",
                           "CALENDAR": "calendar_reads"}[self.query_active]
                setattr(self.budget, counter, getattr(self.budget, counter) + 1)
                self.budget.process_deadline = min(self.read_work_deadline,
                                                   time.monotonic() + lake.SPEC.query_seconds)
            else:
                if self.query_active != message["query"]:
                    raise ValueError("本地查询未开始即结束")
                # Check the old SQL deadline before restoring the read deadline.
                self.budget.check()
                self.query_active = None
                self.query_index += 1
                self.budget.process_deadline = self.read_work_deadline
        elif kind == "RESULT":
            if (self.query_index != 3 or self.query_active is not None or self.payload is not None
                    or type(message["payload"]) is not dict):
                raise ValueError("本地读取结果顺序或类型错误")
            if length > lake.SPEC.max_read_result_bytes:
                raise OverflowError("本地读取正文超过1MiB")
            self.payload, self.result_bytes = message["payload"], length
        elif kind == "DONE":
            if self.payload is None:
                raise ValueError("本地读取尚无结果即结束")
            self.done = True


def _pump_process(proc, request_bytes, *, protocol, budget):
    """Pump only a process registered by this caller; never wait before draining."""
    if budget.active is not proc:
        raise ValueError("只能处理本次登记的固定协议进程")
    output = bytearray()
    stderr_bytes = sent = 0
    selector = selectors.DefaultSelector()
    original = None
    try:
        if protocol not in {"GIT_BLOBS", "LOCAL_INPUT", "WORKER"}:
            raise ValueError("不支持的固定协议")
        if type(request_bytes) is not bytes or len(request_bytes) > SPEC.max_request_bytes + 8:
            raise OverflowError("请求大小或类型错误")
        frames = None
        if protocol in {"WORKER", "LOCAL_INPUT"}:
            if len(request_bytes) < 9 or int.from_bytes(request_bytes[:8], "big") != len(request_bytes) - 8:
                raise ValueError("请求消息长度错误")
            cls = _WorkerFrames if protocol == "WORKER" else _LakeFrames
            frames = cls(proc, wire.strict_json_loads(request_bytes[8:]), budget)
        for stream, event in ((proc.stdin, selectors.EVENT_WRITE), (proc.stdout, selectors.EVENT_READ),
                              (proc.stderr, selectors.EVENT_READ)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event)
        while selector.get_map():
            budget.check()
            timeout = max(0, min(SPEC.poll_seconds, budget.process_deadline - time.monotonic()))
            for key, event in selector.select(timeout):
                budget.check()
                stream = key.fileobj
                if event & selectors.EVENT_WRITE:
                    if sent == len(request_bytes):
                        selector.unregister(stream)
                        stream.close()
                        continue
                    try:
                        sent += os.write(stream.fileno(), request_bytes[sent:sent + SPEC.io_chunk])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        raise RuntimeError(f"进程提前关闭输入，阶段{budget.stage}") from None
                else:
                    try:
                        data = os.read(stream.fileno(), SPEC.io_chunk)
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    if stream is proc.stderr:
                        stderr_bytes += len(data)
                        if stderr_bytes > SPEC.max_stderr_bytes:
                            raise OverflowError("子进程stderr超限")
                        raise RuntimeError(f"子进程异常输出，阶段{budget.stage}")
                    if frames is not None:
                        frames.feed(data)
                    else:
                        if len(output) + len(data) > SPEC.max_source_bytes:
                            raise OverflowError("Git输出超过源码上限")
                        output.extend(data)
                budget.check()
        while proc.poll() is None:
            budget.check()
            try:
                proc.wait(timeout=max(0, min(SPEC.poll_seconds, budget.process_deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                continue
        proc.wait(timeout=0)
        budget.collected(proc)
        budget.check()
        if frames is not None:
            if proc.returncode != 0:
                raise RuntimeError(f"worker非零退出，阶段{budget.stage}")
            frames.finish()
            return {"payload": frames.payload, "resultBytes": frames.result_bytes}
        return {"stdout": bytes(output), "returnCode": proc.returncode}
    except BaseException as exc:
        original = exc
        raise
    finally:
        selector.close()
        if budget.active is proc:
            _cleanup_process(proc, budget, original)
        else:
            closing_error = _close_pipes(proc)
            if closing_error is not None:
                if original is not None:
                    original.add_note(f"专项清理 CLEANUP: {type(closing_error).__name__}")
                else:
                    raise closing_error


def _spawn(args, budget, *, git=False):
    budget.check()
    if budget.active is not None:
        raise RuntimeError("上一子进程尚未回收")
    try:
        environment = {key: os.environ[key] for key in ("HOME", "TMPDIR", "PATH") if key in os.environ} if git else {}
        proc = subprocess.Popen(args, cwd=REPO_ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, shell=False, bufsize=0, close_fds=True, env=environment)
    except OSError as exc:
        raise RuntimeError(f"子进程无法启动，阶段{budget.stage}：{type(exc).__name__}") from None
    budget.register(proc, git=git)
    return proc


def _git(args, budget, *, request=b"", unset_ok=False):
    command = ["/usr/bin/git", "--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false", *args]
    result = _pump_process(_spawn(command, budget, git=True), request, protocol="GIT_BLOBS", budget=budget)
    if result["returnCode"] and not (unset_ok and result["returnCode"] == 1 and result["stdout"] == b""):
        raise RuntimeError(f"Git命令失败，阶段{budget.stage}")
    return result["stdout"]


def _protection_facts(budget):
    branch = _git(["branch", "--show-current"], budget).decode().strip()
    if branch != "dev-interface":
        raise ValueError("专项只在当前dev-interface工作区运行")
    changed = _git(["diff", "--name-only", SPEC.current_commit, "--", *CORE_PATHS], budget)
    if changed:
        raise ValueError("正式识别核心已变化，须先review固定版本")
    return {"branch": branch, "staged": _git(["diff", "--cached", "--name-status"], budget).decode()}


def _preflight_git(budget):
    if _git(["config", "--get", "extensions.partialclone"], budget, unset_ok=True).strip():
        raise ValueError("专项不允许partial仓库或自动取源")
    promisor = _git(["config", "--get-regexp", r"remote\..*\.promisor"], budget, unset_ok=True)
    for line in promisor.decode().splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[1].lower() != "false":
            raise ValueError("专项不允许promisor或非法配置")
    if _git(["for-each-ref", "--format=%(refname)", "refs/replace"], budget).strip():
        raise ValueError("专项不允许Git replace引用")
    graft_path = Path(_git(["rev-parse", "--git-path", "info/grafts"], budget).decode().strip())
    if not graft_path.is_absolute():
        graft_path = REPO_ROOT / graft_path
    if graft_path.exists() and (graft_path.stat().st_size > SPEC.max_source_bytes or graft_path.read_bytes().strip()):
        raise ValueError("专项不允许非空Git grafts")
    budget.check()
    return _protection_facts(budget)


def _module_lists():
    return {"OLD_PAIR": wire.PRODUCT_MODULES + wire.RESEARCH_MODULES, "CURRENT": wire.PRODUCT_MODULES}


def _parse_git_blobs(body, expected):
    offset, modules, total = 0, [], 0
    for name, path in expected:
        newline = body.find(b"\n", offset)
        if newline < 0:
            raise ValueError("Git blob头不完整")
        header = body[offset:newline].split(b" ")
        if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
            raise ValueError("Git固定对象不是blob或不存在")
        length = int(header[2])
        total += length
        if length <= 0 or total > SPEC.max_source_bytes:
            raise OverflowError("Git算法源码大小超限")
        start, end = newline + 1, newline + 1 + length
        if end >= len(body) or body[end:end + 1] != b"\n":
            raise ValueError("Git blob正文不完整")
        try:
            source = body[start:end].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ValueError("Git源码不是UTF-8") from None
        modules.append({"name": name, "path": path, "source": source})
        offset = end + 1
    if offset != len(body):
        raise ValueError("Git含额外blob正文")
    return tuple(modules)


def read_git_sources(budget):
    budget.enter("GIT")
    lists = _module_lists()
    expected = lists["OLD_PAIR"] + lists["CURRENT"]
    request = "".join(f"{SPEC.old_commit if i < 8 else SPEC.current_commit}:{path}\n"
                      for i, (_, path) in enumerate(expected)).encode()
    body = _git(["cat-file", "--batch"], budget, request=request)
    budget.check()
    modules = _parse_git_blobs(body, expected)
    del body
    budget.check()
    return {"OLD_PAIR": modules[:8], "CURRENT": modules[8:]}


def _read_local_payload(budget, read_deadline):
    request = {"kind": "READ_INPUT", "protocolVersion": 1, "source": lake.SPEC.source,
               "readDeadline": read_deadline,
               "maxWorkerMemoryBytes": SPEC.max_memory_bytes - budget.parent_peak}
    body = _encoded(request)
    proc = _spawn([sys.executable, "-I", "-B", str(Path(lake.__file__).resolve())], budget)
    budget.process_cleanup_deadline = min(read_deadline, budget.deadline)
    budget.process_deadline = min(read_deadline - SPEC.cleanup_seconds, budget.work_deadline)
    received = _pump_process(proc, len(body).to_bytes(8, "big") + body,
                             protocol="LOCAL_INPUT", budget=budget)
    budget.check()
    return received["payload"]


def _iso_source_date(value):
    if type(value) is not str:
        raise ValueError("本地源日期传输必须为ISO文本")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("本地源日期格式错误")
    return parsed


def _validate_local_input(payload, budget, read_deadline):
    # query_service imports ORM/registry/Settings indirectly. Keep this source
    # contract check local and reuse only the I/O-free numeric validator.
    from src.biz.services.wealth.market.index_detail_daily_wave.budget import DailyWaveBudget
    from src.biz.services.wealth.market.index_detail_daily_wave.calculator import _points
    from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC

    budget.check()
    expected = {"marketRows", "calendarRows", "fileCount", "fileBytes", "calendarBytes", "connectionClosed"}
    if type(payload) is not dict or set(payload) != expected or payload["connectionClosed"] is not True:
        raise ValueError("本地源返回字段或关闭状态错误")
    for name, cap in (("fileCount", SPEC.max_input_bars), ("fileBytes", lake.SPEC.max_market_bytes),
                      ("calendarBytes", lake.SPEC.max_calendar_bytes)):
        value = payload[name]
        if type(value) is not int or not 0 < value <= cap:
            raise ValueError("本地源文件数量或大小错误")
    source_spec = replace(DEFAULT_SPEC, requested_start=SPEC.start_date, requested_end=SPEC.end_date,
                          absolute_start=SPEC.start_date, max_main_points=SPEC.max_input_bars,
                          max_context_points=0, max_total_points=SPEC.max_input_bars)

    def cancel_bridge():
        budget.check()
        return False

    guard = DailyWaveBudget(source_spec,
        deadline=min(read_deadline - SPEC.cleanup_seconds, budget.work_deadline),
        check_cancelled=cancel_bridge)
    guard.check()
    when = datetime.now(timezone(timedelta(hours=8)))
    raw, normalized = [], []
    market = payload["marketRows"]
    if type(market) not in (list, tuple) or len(market) != SPEC.input_count:
        raise ValueError("专项要求指定范围恰922根真实行情")
    for values in market:
        guard.check()
        if type(values) not in (list, tuple) or len(values) != len(lake.MARKET_COLUMNS):
            raise ValueError("本地行情必须为六列")
        row = dict(zip(lake.MARKET_COLUMNS, values, strict=True))
        row["trade_date"] = _iso_source_date(row["trade_date"])
        if row["ts_code"] != SPEC.ts_code:
            raise ValueError("本地源行情对象错误")
        closed = datetime.combine(row["trade_date"], datetime.min.time(), when.tzinfo) + timedelta(hours=15)
        if closed > when:
            raise ValueError("本地源行情尚未完成日线收盘")
        point = {"tsCode": row["ts_code"], "date": row["trade_date"].isoformat(), "completed": True}
        for target, name in (("close", "close"), ("dif", "macd_dif_bfq"),
                             ("dea", "macd_dea_bfq"), ("macd", "macd_bfq")):
            value = row[name]
            if type(value) is not float or not math.isfinite(value) or target == "close" and value <= 0:
                raise ValueError("本地源行情必须为有限原始DOUBLE且收盘为正")
            point[target] = str(value)  # For validation only; preserve source floats below.
        normalized.append(point)
        raw.append(row)
    days = [row["date"] for row in normalized]
    if days[0] != SPEC.start_date or days[-1] != SPEC.end_date:
        raise ValueError("专项行情首末日期不符")
    _points(normalized, as_of=SPEC.end_date, spec=source_spec, guard=guard)
    calendar = payload["calendarRows"]
    if type(calendar) not in (list, tuple) or len(calendar) != SPEC.calendar_count:
        raise ValueError("专项要求1394个自然日日历")
    opened = []
    calendar_start = date.fromisoformat(SPEC.start_date)
    for index, values in enumerate(calendar):
        guard.check()
        if type(values) not in (list, tuple) or len(values) != len(lake.CALENDAR_COLUMNS):
            raise ValueError("本地日历必须为三列")
        row = dict(zip(lake.CALENDAR_COLUMNS, values, strict=True))
        row["trade_date"] = _iso_source_date(row["trade_date"])
        if (row["exchange"] != "SSE" or type(row["is_open"]) is not bool
                or row["trade_date"] != calendar_start + timedelta(days=index)):
            raise ValueError("本地SSE日历字段或逐日连续性错误")
        if row["is_open"]:
            opened.append(row["trade_date"].isoformat())
    if opened != days or calendar[-1][1] != SPEC.end_date:
        raise ValueError("专项要求922个开市日与行情逐日对应")
    rows = tuple((row["trade_date"].isoformat(), row["close"], row["macd_dif_bfq"],
                  row["macd_dea_bfq"], row["macd_bfq"], True) for row in raw)
    guard.check()
    return {"rows": rows, "calendarCount": len(calendar), "openCount": len(rows),
            "requestedStart": SPEC.start_date, "requestedEnd": SPEC.end_date,
            "actualStart": rows[0][0], "actualEnd": rows[-1][0],
            "sourceDescription": {"source": lake.SPEC.source, "lakeRoot": lake.SPEC.lake_root,
                "tsCode": SPEC.ts_code, "period": SPEC.period,
                "marketPathTemplate": lake.SPEC.market_relative,
                "calendarPath": lake.SPEC.calendar_relative, "calendar": "SSE",
                "fields": list(lake.MARKET_COLUMNS), "calendarFields": list(lake.CALENDAR_COLUMNS),
                "sourceTypes": "VARCHAR/DATE/DOUBLE;VARCHAR/DATE/BOOLEAN",
                "fileCount": payload["fileCount"], "fileBytes": payload["fileBytes"],
                "calendarBytes": payload["calendarBytes"], "schemaReads": budget.schema_reads,
                "marketReads": budget.market_reads, "calendarReads": budget.calendar_reads,
                "actualStart": rows[0][0], "actualEnd": rows[-1][0], "inputCount": len(rows)}}


def read_input(budget):
    """One local-only read. This does not load or execute any signal algorithm."""
    budget.enter("READ")
    read_deadline = min(time.monotonic() + SPEC.read_seconds, budget.work_deadline)
    payload = _read_local_payload(budget, read_deadline)
    result = _validate_local_input(payload, budget, read_deadline)
    budget.check()
    return result


def _check_identity(payload, request):
    old = request["bundle"] == "OLD_PAIR"
    if set(payload) != ({"metadata", "rows", "summary"} if old else {"identity", "rows"}):
        raise ValueError("worker结果顶层字段错误")
    identity = payload["metadata" if old else "identity"]
    if type(identity) is not dict or any(type(identity.get(k)) is not type(request[k]) or identity.get(k) != request[k]
                                        for k in ("bundle", "commit", "tsCode", "period", "inputIdentity", "inputCount")):
        raise ValueError("worker实际计算身份错误")
    for output, source in (("requestedStartDate", "startDate"), ("requestedEndDate", "endDate")):
        if identity.get(output) != request[source]:
            raise ValueError("worker实际计算区间错误")
    versions = {"r2AlgorithmVersion": "xxm-direction-v0.1-r2", "r4ResearchVersion": "xxm-research-r4-v2"} if old else {
        "algorithmVersion": "xxm-direction-v0.2-r4"}
    if any(identity.get(k) != v for k, v in versions.items()):
        raise ValueError("worker规则版本错误")
    for key in (("r2SpecHash", "r4ResearchHash") if old else ("specHash",)):
        if not isinstance(identity.get(key), str) or not identity[key]:
            raise ValueError("worker缺少真实规则身份")
    rule_specs = (("r2Spec", "r2SpecHash", "algorithm_version", "xxm-direction-v0.1-r2"),
                  ("r4Spec", "r4ResearchHash", "research_version", "xxm-research-r4-v2")) if old else (
                      ("spec", "specHash", "algorithm_version", "xxm-direction-v0.2-r4"),)
    for spec_key, hash_key, version_key, version in rule_specs:
        actual_spec = identity.get(spec_key)
        if type(actual_spec) is not dict or actual_spec.get(version_key) != version:
            raise ValueError("worker实际规则描述缺失或版本错误")
        hashed = {**actual_spec, "parentSpecHash": identity["r2SpecHash"]} if old and spec_key == "r4Spec" else actual_spec
        # This is the original Spec's data identity, never a source-code SHA.
        expected_hash = hashlib.sha256(json.dumps(hashed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if identity[hash_key] != expected_hash:
            raise ValueError("worker实际Spec与规则身份不一致")
    if type(payload["rows"]) is not list or len(payload["rows"]) != request["inputCount"]:
        raise ValueError("worker返回根数错误")


def run_worker(bundle, rows, sources, budget):
    if bundle not in {"OLD_PAIR", "CURRENT"}:
        raise ValueError("不支持的固定计算组")
    budget.enter("OLD" if bundle == "OLD_PAIR" else "CURRENT")
    expected = _module_lists()[bundle]
    if type(sources) is not tuple or tuple((m["name"], m["path"]) for m in sources) != expected:
        raise ValueError("计算模块名单或顺序错误")
    budget.check()
    request = {"kind": "REQUEST", "protocolVersion": 1, "bundle": bundle,
               "commit": SPEC.old_commit if bundle == "OLD_PAIR" else SPEC.current_commit,
               "tsCode": SPEC.ts_code, "period": SPEC.period, "startDate": SPEC.start_date,
               "endDate": SPEC.end_date, "inputIdentity": "000001.SH:day:2023-01-03:2026-10-27",
               "inputCount": len(rows), "rows": rows, "modules": sources,
               "workDeadline": budget.work_deadline,
               "maxWorkerMemoryBytes": SPEC.max_memory_bytes - budget.parent_peak,
               "maxResultBytes": budget.result_remaining}
    # Validate both sides of the transmission; use no arbitrary test command.
    body = _encoded(request)
    if len(body) > SPEC.max_request_bytes:
        raise OverflowError("专项请求超过2MiB")
    decoded = wire.strict_json_loads(body)
    wire.validate_request(decoded)
    for original, transmitted in zip(rows, decoded["rows"], strict=True):
        for left, right in zip(original, transmitted, strict=True):
            if type(left) is not type(right) or left != right or (type(left) is float and left == 0
                                                                and math.copysign(1, left) != math.copysign(1, right)):
                raise ValueError("管道编码改变源数字")
    del decoded
    budget.check()
    path = Path(__file__).with_name("r4_history_worker.py").resolve()
    proc = _spawn([sys.executable, "-I", "-S", "-B", str(path)], budget)
    response = _pump_process(proc, len(body).to_bytes(8, "big") + body, protocol="WORKER", budget=budget)
    payload = response["payload"]
    _check_identity(payload, request)
    budget.result_sizes.append(response["resultBytes"])
    budget.check()
    return payload


def _finish_result(source, old, current, baseline, compared, budget):
    from .r4_history_records import format_report

    budget.enter("REPORT")
    result = {"metadata": {"tsCode": SPEC.ts_code, "period": SPEC.period,
                           "requestedStart": SPEC.start_date, "requestedEnd": SPEC.end_date,
                           "actualStart": source["actualStart"], "actualEnd": source["actualEnd"],
                           "inputCount": len(source["rows"]), "calendarCount": source["calendarCount"],
                           "openCount": source["openCount"], "sourceDescription": source["sourceDescription"],
                           "old": old["metadata"], "current": current["identity"],
                           "leftContextNote": "三组从2023-01-03空状态开始，首段可能不完整"},
              "baselineCheck": baseline, **compared, "metrics": {}, "reportText": ""}
    # Text depends on business facts, never on changing resource counters.
    # Prepare it once so each size check does not allocate another full report.
    result["reportText"] = format_report(result, check=budget.check)
    prepared = _encoded(result)
    if sum(budget.result_sizes) + len(prepared) > SPEC.max_result_bytes:
        raise OverflowError("全部事实与最终报告合计超过16MiB")
    del prepared
    budget.check()
    stages = dict(budget.stage_seconds)
    stages["REPORT"] = time.monotonic() - budget.stage_started
    prepared_elapsed = round(time.monotonic() - budget.t0, 6)
    final_size = 0
    for _ in range(SPEC.final_checks):
        budget.check()
        if budget.active is not None or any(p.returncode is None for p in budget.processes):
            raise RuntimeError("仍有未回收子进程")
        combined = budget.measure()
        result["metrics"] = {"elapsedSeconds": prepared_elapsed,
                             "stageSeconds": stages, "parentPeak": budget.parent_peak,
                             "highestChildPeak": max(budget.waited_peak, budget.reported_peak),
                             "combinedPeakUpper": combined, "stepCounts": {"r2": len(source["rows"]),
                              "historyR4": len(source["rows"]), "currentR4": len(source["rows"])},
                             "marketReads": budget.market_reads, "calendarReads": budget.calendar_reads,
                             "workerResultBytes": list(budget.result_sizes),
                             "finalResultBytes": final_size, "allChildrenReaped": True}
        encoded = _encoded(result)
        size = len(encoded)
        del encoded
        budget.check()
        if sum(budget.result_sizes) + size > SPEC.max_result_bytes:
            raise OverflowError("全部事实与最终报告合计超过16MiB")
        latest_combined = budget.measure()
        latest = {"parentPeak": budget.parent_peak,
                  "highestChildPeak": max(budget.waited_peak, budget.reported_peak),
                  "combinedPeakUpper": latest_combined, "finalResultBytes": size}
        # Only these nonnegative integer tokens change. Equal decimal lengths
        # prove the checked UTF-8 JSON size remains exact after the update.
        # A new measured peak is valid; it need not stop growing after encoding.
        if all(len(str(result["metrics"][key])) == len(str(value))
               for key, value in latest.items()):
            result["metrics"].update(latest)
            return result
        final_size = size
    raise ValueError("最终结果字节及资源检查未在5轮内稳定")


def run_historical_comparison(*, check_cancelled=None):
    """REAL DATA ENTRY. Requires second-batch authorization in a fresh process."""
    from .r4_history_records import compare_fact_groups, validate_baseline

    budget = ResearchBudget(check_cancelled=check_cancelled)
    original = None
    try:
        if resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss:
            raise ValueError("真实专项须在新的独立父进程执行")
        protected = _preflight_git(budget)
        sources = read_git_sources(budget)
        source = read_input(budget)
        old = run_worker("OLD_PAIR", source["rows"], sources["OLD_PAIR"], budget)
        baseline = validate_baseline(old, input_rows=source["rows"], check=budget.check)
        current = run_worker("CURRENT", source["rows"], sources["CURRENT"], budget)
        del sources
        budget.enter("COMPARE")
        compared = compare_fact_groups(old, current, input_rows=source["rows"], check=budget.check)
        if _protection_facts(budget) != protected:
            raise ValueError("本次执行期间分支或暂存清单发生变化")
        return _finish_result(source, old, current, baseline, compared, budget)
    except BaseException as exc:
        original = exc
        raise
    finally:
        if budget.active is not None:
            _cleanup_process(budget.active, budget, original)
