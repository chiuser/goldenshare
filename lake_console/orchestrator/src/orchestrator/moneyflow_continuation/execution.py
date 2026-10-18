"""Sequential controller. Stopping the controller never cancels a native job."""

import signal
import threading
from datetime import datetime

from orchestrator.moneyflow_continuation.contract import (
    ACTIVE,
    CONTROL,
    POLICY,
    ContinuationError,
    encoded,
    now,
    require,
)
from orchestrator.moneyflow_continuation.plan import validate_plan
from orchestrator.moneyflow_continuation.recovery import (
    ACTION,
    RECOVERY_ACTIONS,
    action_layer,
)
from orchestrator.moneyflow_continuation.state import next_action
from orchestrator.moneyflow_continuation.submission import (
    Journal,
    executor_lock,
    submit_once,
)


class Progress:
    def __init__(self, total, output=print):
        self.output = output
        self.value = {
            "mode": "apply",
            "total": total,
            "completed": 0,
            "registered": 0,
            "submitted": 0,
            "phase": "starting",
            "run_id": None,
            "status": None,
            "wait_seconds": 0,
            "last_actual_progress_at": now().isoformat(),
            "eta": "暂无法估算",
            "complete": False,
        }
        self.done = threading.Event()

    def update(self, **values):
        if any(
            self.value.get(k) != v for k, v in values.items() if k != "wait_seconds"
        ):
            values["last_actual_progress_at"] = now().isoformat()
        self.value = {**self.value, **values}
        self.emit()

    def emit(self):
        self.output(
            encoded({**self.value, "reported_at": now().isoformat()}).decode().strip()
        )

    def heartbeat(self):
        while not self.done.wait(POLICY.poll_seconds):
            self.emit()


def wait_run(backend, journal, unit, layer, native, stop, progress, clock=now):
    run_id = native["run_id"]
    while True:
        require(not stop.is_set(), "operator_stopped", 130)
        files = journal.read(unit, layer)
        observation = files.get("observation", {})
        started = observation.get("started_at")
        require(started is not None, "observation_budget_missing")
        elapsed = max(0, (clock() - datetime.fromisoformat(started)).total_seconds())
        polls = observation.get("polls", 0)
        require(type(polls) is int and polls >= 0, "observation_budget_corrupt")
        require(
            polls < POLICY.run_reads and elapsed < POLICY.run_seconds,
            "background_run_observation_limit",
            4,
        )
        # Persist consumed quota before the read; crash/restart cannot reset it.
        journal.observe(unit, layer, {"polls": polls + 1, "run_id": run_id})
        backend.meter.consume = lambda: journal.budget(
            "poll:" + run_id, POLICY.run_reads
        )
        status = backend.run_status(run_id)
        journal.observe(unit, layer, {"native": {"run_id": run_id, "status": status}})
        progress.update(
            phase="waiting",
            layer=layer,
            run_id=run_id,
            status=status,
            wait_seconds=int(elapsed),
        )
        if status not in ACTIVE:
            require(status == "SUCCESS", "native_run_failed")
            return
        stop.wait(POLICY.poll_seconds)


def unit_decisions(snapshots):
    decisions = []
    for snapshot in snapshots:
        decision = {
            "dataset": snapshot["dataset"],
            "trade_date": snapshot["trade_date"],
            "facts": snapshot,
        }
        try:
            decision["next"] = next_action(snapshot)
        except ContinuationError as error:
            decision.update(
                next="unknown" if snapshot.get("unknown") else "blocked",
                reason=error.reason,
                code=error.code,
            )
        decisions.append(decision)
    return decisions


def decision_summary(decisions):
    completed = sum(d["next"] == "complete" for d in decisions)
    return {
        "total": len(decisions),
        "completed": completed,
        "remaining": len(decisions) - completed,
        "blocked": sum(d["next"] == "blocked" for d in decisions),
        "unknown": sum(d["next"] == "unknown" for d in decisions),
        "preserved_failures": [
            failure
            for d in decisions
            for layer in ("raw", "silver")
            for failure in [
                d["facts"][layer].get("preserved_failure")
                or d["facts"][layer].get("failed_launch")
            ]
            if failure
        ],
    }


def inspect(backend, plan, root=CONTROL):
    validate_plan(plan)
    snapshots = backend.snapshots(plan["units"], Journal(plan, root))
    decisions = unit_decisions(snapshots)
    return {
        "mode": "inspect",
        "complete": all(d["next"] == "complete" for d in decisions),
        "units": decisions,
        **decision_summary(decisions),
    }


def apply(backend, plan, *, root=CONTROL, stop=None, output=print, clock=now):
    validate_plan(plan)
    stop = stop or threading.Event()
    backend.stopping = stop.is_set
    progress = Progress(len(plan["units"]), output)
    timer = threading.Thread(target=progress.heartbeat, daemon=True)
    timer.start()
    try:
        with executor_lock(root):
            journal = Journal(plan, root)
            # Initial facts use the separate bounded plan audit, never a guessed local count.
            initial = backend.snapshots(plan["units"], journal)
            decisions = unit_decisions(initial)
            progress.update(
                **decision_summary(decisions),
                registered=sum(bool(s["registered"]) for s in initial),
                submitted=sum(
                    len(s[layer]["runs"])
                    for s in initial
                    for layer in ("raw", "silver")
                ),
            )
            blocked = [d for d in decisions if "reason" in d]
            if blocked:
                raise ContinuationError(blocked[0]["reason"], blocked[0]["code"])
            finished = {
                (d["dataset"], d["trade_date"])
                for d in decisions
                if d["next"] == "complete"
            }
            for unit in plan["units"]:
                key = (unit["dataset"], unit["trade_date"])
                if key in finished:
                    continue
                current = next(
                    s for s in initial if (s["dataset"], s["trade_date"]) == key
                )
                phase = next_action(current)
                if phase.startswith("observe_"):
                    # The initial native audit has already identified this
                    # journal's run. Reconnect using its persisted poll budget,
                    # without charging the completed submission phase again.
                    layer = phase.removeprefix("observe_")
                    wait_run(
                        backend,
                        journal,
                        unit,
                        layer,
                        current[action_layer(layer)]["runs"][0],
                        stop,
                        progress,
                        clock,
                    )
                    phase = {
                        "raw": "silver",
                        "silver": "complete",
                        ACTION: "complete",
                    }[layer]
                for _ in range(POLICY.transitions_per_unit):
                    require(not stop.is_set(), "operator_stopped", 130)
                    prefix = unit["dataset"] + ":" + unit["trade_date"] + ":" + phase
                    backend.meter.consume = lambda prefix=prefix: journal.budget(
                        prefix, POLICY.transition_reads
                    )
                    progress.update(
                        dataset=unit["dataset"],
                        trade_date=unit["trade_date"],
                        phase="auditing",
                    )
                    snapshot = backend.snapshots([unit], journal)[0]
                    action = next_action(snapshot)
                    if action == "complete":
                        # A changed load/contract must not be silently accepted after a background run.
                        backend.guard(plan, clock())
                        finished.add(key)
                        progress.update(
                            completed=len(finished),
                            remaining=len(plan["units"]) - len(finished),
                            phase="accepted",
                            run_id=None,
                            status=None,
                        )
                        break
                    if action.startswith("observe_"):
                        layer = action.removeprefix("observe_")
                        native = snapshot[action_layer(layer)]["runs"][0]
                    else:
                        layer = action
                        progress.update(phase="submitting", layer=layer)
                        native = submit_once(
                            backend,
                            journal,
                            unit,
                            action,
                            clock(),
                            snapshot["raw"]["sha256"],
                        )
                        progress.update(
                            submitted=progress.value["submitted"]
                            + (action != "register"),
                            registered=progress.value["registered"]
                            + (action == "register"),
                        )
                    if layer in {"raw", "silver", *RECOVERY_ACTIONS}:
                        wait_run(
                            backend, journal, unit, layer, native, stop, progress, clock
                        )
                    phase = {
                        "register": "raw",
                        "raw": "silver",
                        "silver": "complete",
                        ACTION: "complete",
                    }[layer]
                else:
                    require(False, "transition_limit")
            progress.update(
                complete=len(finished) == len(plan["units"]),
                phase="complete",
                reason="all_accepted",
            )
            require(progress.value["complete"], "incomplete_scope")
            return 0, progress.value
    except ContinuationError as error:
        progress.update(phase="stopped", complete=False, reason=error.reason)
        return error.code, {
            **progress.value,
            "remaining": len(plan["units"]) - progress.value["completed"],
        }
    except Exception as error:  # noqa: BLE001 -- command boundary, fail closed without leaking credentials
        # Do not emit raw exception strings: native diagnostics can contain credentials.
        progress.update(
            phase="stopped",
            complete=False,
            reason="io_or_native_error",
            error_type=type(error).__name__,
        )
        return 3, progress.value
    finally:
        backend.meter.consume = None
        progress.done.set()
        timer.join(timeout=1)


class StopSignals:
    def __init__(self):
        self.event = threading.Event()
        self.previous = {}

    def __enter__(self):
        for number in (signal.SIGINT, signal.SIGTERM):
            self.previous[number] = signal.signal(number, lambda *_: self.event.set())
        return self.event

    def __exit__(self, *_):
        for number, handler in self.previous.items():
            signal.signal(number, handler)
