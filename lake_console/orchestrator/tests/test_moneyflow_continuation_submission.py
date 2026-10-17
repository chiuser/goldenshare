"""C04/C05/C07/C10: actual filesystem/process locks; deterministic fake native boundary."""

import multiprocessing
import os
from datetime import timedelta

import pytest

from orchestrator.moneyflow_continuation.contract import (
    ContinuationError,
    digest,
    require,
)
from orchestrator.moneyflow_continuation.state import NativeBackend, ReadMeter
from orchestrator.moneyflow_continuation.submission import (
    Journal,
    executor_lock,
    submit_once,
    write_json,
)
from tests.test_moneyflow_continuation_plan import AT, plan_for
from tests.test_moneyflow_continuation_state import snapshot


class FakeNative:
    """Replaces GraphQL/PG/files for controller unit tests, not real integration acceptance."""

    def __init__(self):
        self.meter = ReadMeter()
        self.registered = set()
        self.native = {}
        self.posts = []
        self.stopping = lambda: False
        self.lose_response = False
        self.fail_guard = False
        self.pending = False

    def guard(self, plan, at):
        from datetime import datetime

        require(not self.fail_guard, "dependency_drift")
        require(at < datetime.fromisoformat(plan["valid_until"]), "observation_expired")

    def reconcile(self, unit, action, body):
        self.meter.tick()
        if action == "register":
            return (
                {"partition": unit["trade_date"]}
                if (unit["dataset"], unit["trade_date"]) in self.registered
                else None
            )
        item = self.native.get((unit["dataset"], unit["trade_date"], action))
        if item:
            require(item["body"] == body, "unexplained_native_run")
            return {"run_id": item["run_id"], "status": item["status"]}
        return None

    def mutate(self, body):
        self.posts.append(body)
        v = body["variables"]
        if "partitionKey" in v:
            dataset = (
                v["partitionsDefName"].removeprefix("cn_a_").removesuffix("_trade_days")
            )
            self.registered.add((dataset, v["partitionKey"]))
            return {
                "data": {
                    "addDynamicPartition": {
                        "__typename": "AddDynamicPartitionSuccess",
                        "partitionKey": v["partitionKey"],
                    }
                }
            }
        params = v["executionParams"]
        tags = {t["key"]: t["value"] for t in params["executionMetadata"]["tags"]}
        job = params["selector"]["jobName"]
        layer = "raw" if job.startswith("raw_") else "silver"
        dataset = (
            job.removesuffix("_update_job")
            .removeprefix("raw_tushare_")
            .removeprefix("silver_")
        )
        key = (dataset, tags["dagster/partition"], layer)
        assert key not in self.native
        run_id = f"run-{len(self.native) + 1}"
        self.native[key] = {"run_id": run_id, "status": "QUEUED", "body": body}
        if self.lose_response:
            raise OSError("simulated response loss AFTER native creation")
        return {
            "data": {
                "launchRun": {
                    "__typename": "LaunchRunSuccess",
                    "run": {"runId": run_id, "status": "QUEUED"},
                }
            }
        }

    check_response = staticmethod(NativeBackend.check_response)

    def run_status(self, run_id):
        self.meter.tick()
        item = next(v for v in self.native.values() if v["run_id"] == run_id)
        if not self.pending:
            item["status"] = "SUCCESS"
        return item["status"]

    def snapshots(self, units, journal=None):
        result = []
        for unit in units:
            self.meter.tick()
            snap = snapshot()
            snap.update(
                dataset=unit["dataset"],
                trade_date=unit["trade_date"],
                registered=(unit["dataset"], unit["trade_date"]) in self.registered,
            )
            for layer in ("raw", "silver"):
                item = self.native.get((unit["dataset"], unit["trade_date"], layer))
                if item:
                    files = journal.read(unit, layer) if journal else {}
                    snap[layer].update(
                        ready=item["status"] == "SUCCESS",
                        reason="ready",
                        owned="send_intent" in files,
                        active=item["status"] == "QUEUED",
                        runs=[{"run_id": item["run_id"], "status": item["status"]}],
                        sha256="b" * 64,
                        failed=item["status"] == "FAILURE",
                    )
            result.append(snap)
        return result


def test_prepared_only_can_send_once_and_cross_day_keeps_identity(tmp_path):
    plan, native = plan_for(), FakeNative()
    journal = Journal(plan, tmp_path)
    unit = plan["units"][0]
    journal.prepare(unit, "raw", AT, None, {})
    native.registered.add((unit["dataset"], unit["trade_date"]))
    result = submit_once(native, journal, unit, "raw", AT + timedelta(hours=1))
    assert result["run_id"] == "run-1" and len(native.posts) == 1
    assert submit_once(native, journal, unit, "raw", AT + timedelta(days=1)) == result
    assert len(native.posts) == 1
    assert journal.read(unit, "raw")["request"]["attempt_day"] == "2026-10-17"


def test_response_loss_recovers_native_and_never_posts_twice(tmp_path):
    plan, native = plan_for(), FakeNative()
    journal, unit = Journal(plan, tmp_path), plan["units"][0]
    native.lose_response = True
    with pytest.raises(OSError):
        submit_once(native, journal, unit, "raw", AT)
    assert "response" not in journal.read(unit, "raw")
    assert submit_once(native, journal, unit, "raw", AT)["run_id"] == "run-1"
    assert len(native.posts) == 1


def test_intent_before_real_post_is_ambiguous_not_retriable(tmp_path):
    plan, native = plan_for(), FakeNative()
    journal, unit = Journal(plan, tmp_path), plan["units"][0]
    files = journal.prepare(unit, "raw", AT, None, {})
    write_json(
        journal.action_dir(unit, "raw") / "send_intent.json",
        {"request_sha256": digest(files["request"])},
        immutable=True,
    )
    with pytest.raises(ContinuationError, match="uncertain_submission"):
        submit_once(native, journal, unit, "raw", AT)
    assert native.posts == []


def test_unrecorded_native_run_and_raw_revision_refused(tmp_path):
    plan, native = plan_for(), FakeNative()
    journal, unit = Journal(plan, tmp_path), plan["units"][0]
    from orchestrator.moneyflow_continuation.plan import request_for

    native.mutate(request_for(unit, "raw", AT.date().isoformat()))
    with pytest.raises(ContinuationError, match="unrecorded_native_action"):
        submit_once(native, journal, unit, "raw", AT)
    journal.prepare(unit, "silver", AT, "b" * 64, {})
    with pytest.raises(ContinuationError, match="raw_revision"):
        submit_once(native, journal, unit, "silver", AT, "c" * 64)


@pytest.mark.parametrize(
    "damage", ["missing_request", "invalid_json", "wrong_hash", "symlink"]
)
def test_corrupt_journal_refuses_before_post(tmp_path, damage):
    plan, native = plan_for(), FakeNative()
    journal, unit = Journal(plan, tmp_path), plan["units"][0]
    files = journal.prepare(unit, "raw", AT, None, {})
    directory = journal.action_dir(unit, "raw")
    if damage == "missing_request":
        (directory / "request.json").unlink()  # isolated corruption fixture only
        write_json(directory / "response.json", {})
    elif damage == "invalid_json":
        (directory / "request.json").write_text("{")
    elif damage == "wrong_hash":
        write_json(directory / "send_intent.json", {"request_sha256": "bad"})
    else:
        target = tmp_path / "other.json"
        write_json(target, files["request"])
        (directory / "request.json").unlink()
        (directory / "request.json").symlink_to(target)
    with pytest.raises(ContinuationError):
        submit_once(native, journal, unit, "raw", AT)
    assert native.posts == []


def competing_executor(root, started, release, queue, name):
    try:
        with executor_lock(root):
            queue.put(name + ":entered")
            started.set()
            release.wait(10)
    except ContinuationError as error:
        queue.put(error.reason)


def test_two_real_processes_second_cannot_enter_post_section(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    started, release, queue = ctx.Event(), ctx.Event(), ctx.Queue()
    second_started = ctx.Event()
    first = ctx.Process(
        target=competing_executor, args=(tmp_path, started, release, queue, "first")
    )
    second = ctx.Process(
        target=competing_executor,
        args=(tmp_path, second_started, release, queue, "second"),
    )
    first.start()
    try:
        assert started.wait(10)
        second.start()
        assert {queue.get(timeout=10), queue.get(timeout=10)} == {
            "first:entered",
            "another_executor",
        }
        second.join(10)
        assert second.exitcode == 0
    finally:
        release.set()
        first.join(10)
    with executor_lock(tmp_path):
        assert (tmp_path / "executor.lock").exists()


def test_budget_is_persistent_and_not_reset_by_reinstantiation(tmp_path):
    plan = plan_for()
    Journal(plan, tmp_path).budget("x", 1)
    with pytest.raises(ContinuationError, match="read_budget"):
        Journal(plan, tmp_path).budget("x", 1)


def test_failed_observation_save_preserves_native_no_repost(tmp_path, monkeypatch):
    plan, native = plan_for(), FakeNative()
    journal, unit = Journal(plan, tmp_path), plan["units"][0]
    from orchestrator.moneyflow_continuation import submission

    original = submission.write_json

    def failing(path, value, **kw):
        if path.name == "response.json":
            raise OSError("disk full after successful native mutation")
        return original(path, value, **kw)

    monkeypatch.setattr(submission, "write_json", failing)
    with pytest.raises(OSError):
        submit_once(native, journal, unit, "raw", AT)
    monkeypatch.setattr(submission, "write_json", original)
    assert submit_once(native, journal, unit, "raw", AT)["run_id"] == "run-1"
    assert len(native.posts) == 1


def crash_after_intent(root):
    plan = plan_for()
    journal, unit = Journal(plan, root), plan["units"][0]
    with executor_lock(root):
        files = journal.prepare(unit, "raw", AT, None, {})
        write_json(
            journal.action_dir(unit, "raw") / "send_intent.json",
            {"request_sha256": digest(files["request"])},
            immutable=True,
        )
        os._exit(9)


def test_real_process_crash_releases_lock_but_retains_uncertain_intent(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=crash_after_intent, args=(tmp_path,))
    child.start()
    child.join(10)
    assert child.exitcode == 9
    plan, native = plan_for(), FakeNative()
    with (
        executor_lock(tmp_path),
        pytest.raises(ContinuationError, match="uncertain_submission"),
    ):
        submit_once(native, Journal(plan, tmp_path), plan["units"][0], "raw", AT)
    assert native.posts == []
