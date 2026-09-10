"""Bounded source scheduling; all recovery state is owned by the calling thread."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Lock

from orchestrator.defs.bootstrap.stk_mins_gap_recovery import COLUMNS, records

# Reviewed execution bound, independent of the frozen data scope and cache keys.
SOURCE_MAX_IN_FLIGHT = 2


def load_source_batch(run, limit, window_ids=()):
    """Select unfinished windows, then read their complete membership once."""
    if not 1 <= limit <= run.budget["source_batch"]:
        raise ValueError("Source batch exceeds frozen budget")
    if len(set(window_ids)) != len(window_ids):
        raise ValueError("Unknown or duplicate window selection")
    with run.db() as connection:
        windows = records(
            connection,
            """SELECT window_id,latest_ts_code,freq,candidates,scope_count,start_date,end_date
            FROM read_parquet(?) ORDER BY freq,start_date,latest_ts_code""",
            [str(run.plan_dir / "source-windows.parquet")],
        )
        if window_ids:
            by_id = {w["window_id"]: w for w in windows}
            if any(key not in by_id for key in window_ids):
                raise ValueError("Unknown or duplicate window selection")
            windows = [by_id[key] for key in window_ids]
        selected = []
        for window in windows:
            state = run.state("windows", window["window_id"])
            if state and state["status"] == "complete":
                continue
            selected.append(window)
            if len(selected) == limit:
                break
        if not selected:
            return []
        members = records(
            connection,
            """SELECT window_id,scope_id,latest_ts_code,freq,trade_date,unconfirmed
            FROM read_parquet(?) WHERE window_id IN (SELECT unnest(?::VARCHAR[]))
            ORDER BY window_id,trade_date""",
            [str(run.plan_dir / "scope.parquet"), [w["window_id"] for w in selected]],
        )
    grouped = {w["window_id"]: [] for w in selected}
    for member in members:
        grouped[member["window_id"]].append(member)
    batch = [(w, grouped[w["window_id"]]) for w in selected]
    for window, scopes in batch:
        if (
            len(scopes) != window["scope_count"]
            or len({s["scope_id"] for s in scopes}) != len(scopes)
            or len(scopes) > run.budget["window_days"][str(window["freq"])]
            or any(
                s["latest_ts_code"] != window["latest_ts_code"]
                or s["freq"] != window["freq"]
                for s in scopes
            )
        ):
            raise ValueError("Batch requires complete frozen scope membership")
    return batch


class SourceRequestGate:
    """One start-time gate shared by both workers, including retries."""

    def __init__(self, cache):
        self.cache = cache
        self.lock = Lock()
        self.next_start = 0.0

    def call(self, page):
        cache = self.cache
        while True:
            cache.check_cancel()
            with self.lock:
                delay = max(self.next_start, page["not_before"]) - cache.clock()
                if delay <= 0:
                    cache.check_cancel()
                    started = cache.clock()
                    self.next_start = (
                        started + 60 / cache.run.budget["requests_per_minute"]
                    )
                    break
            cache.sleep(min(delay, 0.05))
        params = page["params"]
        cache.progress(dict(stage="source_page", attempt=page["attempt"], **params))
        if cache.provider is None:
            raise RuntimeError(
                "No source provider; network was not authorized for this action"
            )
        result = cache.provider.call("stk_mins", params, COLUMNS)
        cache.progress(
            dict(
                stage="source_response",
                rows=len(result.rows),
                elapsed_seconds=cache.clock() - started,
                **params,
            )
        )
        return result


def execute_source_steps(cache, steps):
    """Workers return API responses; generators persist them on this thread.

    On cancellation or failure, drain every submitted call through its generator
    so successful responses are cached before propagating the first exception.
    """
    pending, completed = {}, []
    iterator = iter(steps)
    exhausted = False
    first_error = None

    def fail(error):
        nonlocal first_error
        if first_error is None:
            first_error = error
        cache.stopping = True

    with ThreadPoolExecutor(max_workers=SOURCE_MAX_IN_FLIGHT) as pool:

        def advance(generator, response=None, error=None):
            try:
                page = (
                    generator.throw(error)
                    if error is not None
                    else generator.send(response)
                )
                cache.check_cancel()
            except StopIteration as done:
                completed.append(done.value)
            except BaseException as exc:  # noqa: BLE001 -- Drain sibling responses before propagating.
                fail(exc)
                generator.close()
            else:
                pending[pool.submit(cache.request_gate.call, page)] = generator

        try:
            while pending or not exhausted:
                if cache.cancelled() and first_error is None:
                    fail(
                        InterruptedError(
                            "Cancelled; completed pages and windows retained"
                        )
                    )
                while (
                    not first_error
                    and not exhausted
                    and len(pending) < SOURCE_MAX_IN_FLIGHT
                ):
                    try:
                        generator = next(iterator)
                    except StopIteration:
                        exhausted = True
                    else:
                        advance(generator)
                if not pending:
                    break
                done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                for future in done:
                    generator = pending.pop(future)
                    try:
                        response = future.result()
                    except BaseException as exc:  # noqa: BLE001 -- Drain sibling responses before propagating.
                        advance(generator, error=exc)
                    else:
                        advance(generator, response=response)
        finally:
            cache.stopping = False
    if first_error is not None:
        raise first_error
    return completed
