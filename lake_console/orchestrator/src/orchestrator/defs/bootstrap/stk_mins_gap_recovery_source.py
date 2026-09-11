"""Page cache and per-business-day source resolution for frozen minute plans."""

from __future__ import annotations

import json
import time
from pathlib import Path

from orchestrator.defs.assets.stk_mins import _normalize_tushare_stk_mins_row
from orchestrator.defs.bootstrap.stk_mins_gap_recovery import (
    COLUMNS,
    TYPES,
    atomic_json,
    digest,
    file_digest,
    literal,
    parquet,
    records,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_fetch import (
    SOURCE_MAX_IN_FLIGHT,
    SOURCE_RESPONSE_CONTRACT,
    SourceRequestGate,
    execute_source_steps,
)


def expected_clocks(freq):
    minutes = (
        [570] + list(range(570 + freq, 691, freq)) + list(range(780 + freq, 901, freq))
    )
    return {f"{m // 60:02}:{m % 60:02}:00" for m in minutes}


def write_page(run, key, request, rows, *, imported=False, observed_columns=None):
    """Normalize only one bounded API page; parquet conversion is columnar."""
    if len(rows) > run.budget["page_limit"]:
        raise ValueError("Response exceeds the reviewed page bound")
    directory = run.root / "responses" / key
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / "response.json"
    evidence = {}
    if observed_columns is not None:
        if tuple(observed_columns) != COLUMNS:
            raise ValueError("Cannot cache an unverified response schema")
        evidence = {
            "observed_columns": list(observed_columns),
            "response_contract": SOURCE_RESPONSE_CONTRACT,
        }
    atomic_json(
        raw_path,
        {
            "request": request,
            "rows": rows,
            "imported": imported,
            "plan_hash": run.hash,
            **evidence,
        },
    )
    normalized = []
    seen = set()
    freq = int(str(request["freq"]).removesuffix("min"))
    for row in rows:
        timestamp = str(row.get("trade_time") or "")
        item = _normalize_tushare_stk_mins_row(
            row,
            requested_ts_code=request["ts_code"],
            requested_freq=freq,
            partition_key=timestamp[:10],
            start_datetime=request["start_date"],
            end_datetime=request["end_date"],
        )
        if timestamp in seen:
            raise ValueError("Duplicate source key in page")
        seen.add(timestamp)
        normalized.append(item)
    normalized_path = directory / "normalized.json"
    atomic_json(normalized_path, normalized)
    target = directory / "rows.parquet"
    schema = (
        "{" + ",".join(f"{literal(k)}:{literal(v)}" for k, v in TYPES.items()) + "}"
    )
    with run.db() as c:
        relation = (
            f"read_json({literal(normalized_path)},columns={schema},format='array')"
        )
        parquet(c, f"SELECT {','.join(COLUMNS)} FROM {relation}", target)
    state = {
        "request": request,
        "path": str(target),
        "rows": len(rows),
        "raw_sha256": file_digest(raw_path),
        "imported": imported,
        **evidence,
    }
    run.checkpoint("pages", key, **state)
    return state


def day_facts(run, paths, code, freq, dates):
    if not paths:
        return {
            d: {"status": "source-empty", "source_ts_code": code, "paths": []}
            for d in dates
        }
    clocks = ",".join(literal(t) for t in sorted(expected_clocks(freq)))
    with run.db() as c:
        rows = records(
            c,
            f"""SELECT CAST(trade_time AS DATE)::VARCHAR AS "day",count(*) AS "rows",
            count(*)-count(DISTINCT trade_time) duplicates,
            count(DISTINCT trade_time) FILTER(WHERE strftime(trade_time,'%H:%M:%S') IN ({clocks})) grid,
            count(*) FILTER(WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR vol IS NULL
                OR NOT isfinite(open) OR NOT isfinite(high) OR NOT isfinite(low) OR NOT isfinite(close)
                OR open<0 OR high<0 OR low<0 OR close<0 OR vol<0) bad,
            count(*) FILTER(WHERE strftime(trade_time,'%H:%M:%S') NOT IN ({clocks})
                AND NOT (trade_time::TIME>TIME '15:00:00' AND trade_time::TIME<=TIME '15:30:00')) offgrid
            FROM read_parquet(?,hive_partitioning=false) GROUP BY 1""",
            [list(map(str, paths))],
        )
    by_day = {r["day"]: r for r in rows}
    result = {}
    for day in dates:
        r = by_day.get(day)
        if r and (r["duplicates"] or r["offgrid"]):
            raise ValueError(f"Duplicate or off-grid source rows: {day}")
        status = (
            "source-empty"
            if not r
            else (
                "source-ready"
                if r["grid"] == len(expected_clocks(freq)) and not r["bad"]
                else "source-partial"
            )
        )
        result[day] = {
            "status": status,
            "source_ts_code": code,
            "paths": list(map(str, paths)),
            "source_rows": r["rows"] if r else 0,
        }
    return result


class SourceCache:
    def __init__(
        self,
        run,
        provider=None,
        *,
        cancelled=lambda: False,
        sleep=time.sleep,
        clock=time.monotonic,
        progress=lambda event: None,
    ):
        self.run, self.provider, self.cancelled, self.sleep, self.clock = (
            run,
            provider,
            cancelled,
            sleep,
            clock,
        )
        self.progress = progress
        self.stopping = False
        self.request_gate = SourceRequestGate(self)
        self.seeds = {}

    def check_cancel(self):
        if self.stopping or self.cancelled():
            raise InterruptedError("Cancelled; completed pages and windows retained")

    def import_seeds(self):
        cached = self.run.state("seed-index", "complete")
        if cached:
            self.seeds = {
                (r["code"], r["freq"], r["day"]): r["fact"] for r in cached["entries"]
            }
            return
        for source in self.run.plan["seed_inputs"]:
            source = Path(source)
            expected = next(
                i["sha256"] for i in self.run.plan["inputs"] if i["path"] == str(source)
            )
            if file_digest(source) != expected:
                raise ValueError("Seed input changed since freeze")
            payload = json.loads(source.read_text())
            if isinstance(payload, list):
                items = []
                for probe in payload:
                    response = probe["response"]
                    if response.get("isError"):
                        continue
                    rows = json.loads(
                        "".join(
                            x["text"]
                            for x in response["content"]
                            if x["type"] == "text"
                        )
                    )
                    items.append((probe["request"], rows))
            else:
                rows = payload["rows"]
                if not rows:
                    raise ValueError("Legacy empty seed has no request provenance")
                days = sorted({r["trade_time"][:10] for r in rows})
                items = [
                    (
                        {
                            "ts_code": rows[0]["ts_code"],
                            "freq": rows[0]["freq"],
                            "start_date": days[0] + " 09:00:00",
                            "end_date": days[-1] + " 19:00:00",
                        },
                        rows,
                    )
                ]
            for request, rows in items:
                request = {
                    k: request[k] for k in ("ts_code", "freq", "start_date", "end_date")
                }
                key = digest({"seed": request})[:24]
                state = self.run.state("pages", key) or write_page(
                    self.run, key, request, rows, imported=True
                )
                # Empty probes here are single-day requests. Nonempty multi-day seeds use returned days.
                dates = sorted({r["trade_time"][:10] for r in rows}) or [
                    request["start_date"][:10]
                ]
                if not rows and request["start_date"][:10] != request["end_date"][:10]:
                    raise ValueError(
                        "Empty multi-day seed requires explicit calendar coverage"
                    )
                freq = int(str(request["freq"]).removesuffix("min"))
                facts = day_facts(
                    self.run, [state["path"]], request["ts_code"], freq, dates
                )
                for day, fact in facts.items():
                    identity = (request["ts_code"], freq, day)
                    if identity in self.seeds:
                        raise ValueError(
                            "Overlapping seed requests need explicit reconciliation"
                        )
                    self.seeds[identity] = fact
        self.run.checkpoint(
            "seed-index",
            "complete",
            entries=[
                {"code": code, "freq": freq, "day": day, "fact": fact}
                for (code, freq, day), fact in self.seeds.items()
            ],
        )

    def request(self, code, freq, start, end):
        return execute_source_steps(
            self, [self._request_steps(code, freq, start, end)]
        )[0]

    def resolve_window(self, window, scopes):
        return execute_source_steps(self, [self._window_steps(window, scopes)])[0]

    def resolve_batch(self, batch):
        if len(batch) > self.run.budget["source_batch"]:
            raise ValueError("Source batch exceeds frozen budget")
        if len({w["window_id"] for w, _ in batch}) != len(batch):
            raise ValueError("Duplicate window selection")
        self.progress(
            {
                "stage": "source_batch",
                "total": len(batch),
                "max_in_flight": SOURCE_MAX_IN_FLIGHT,
            }
        )
        completed = 0

        def window_steps(window, scopes):
            nonlocal completed
            self.check_cancel()
            self.progress(
                {
                    "stage": "fetch",
                    "window": window["window_id"],
                    "completed": completed,
                    "total": len(batch),
                }
            )
            result = yield from self._window_steps(window, scopes)
            completed += 1
            self.progress(
                {
                    "stage": "source_window_complete",
                    "window": window["window_id"],
                    "completed": completed,
                    "total": len(batch),
                }
            )
            return result

        return execute_source_steps(
            self, (window_steps(w, scopes) for w, scopes in batch)
        )

    def _request_steps(self, code, freq, start, end):
        self.check_cancel()
        request = {
            "ts_code": code,
            "freq": f"{freq}min",
            "start_date": start + " 09:00:00",
            "end_date": end + " 19:00:00",
        }
        key = digest(request)[:24]
        previous = self.run.state("requests", key)
        if previous and previous["status"] == "complete":
            return previous["paths"]
        paths = []
        for page_number in range(self.run.budget["max_pages"]):
            self.check_cancel()
            offset = page_number * self.run.budget["page_limit"]
            params = dict(request, limit=self.run.budget["page_limit"], offset=offset)
            page_key = digest(params)[:24]
            page = self.run.state("pages", page_key)
            if page is None:
                failure = self.run.state("request-errors", page_key) or {"attempts": 0}
                not_before = self.clock()
                for attempt in range(failure["attempts"], self.run.budget["attempts"]):
                    self.check_cancel()
                    try:
                        result = yield {
                            "params": params,
                            "attempt": attempt + 1,
                            "not_before": not_before,
                        }
                    except InterruptedError:
                        raise
                    except Exception as exc:  # noqa: BLE001 -- SDK API errors are bare exceptions.
                        self.run.checkpoint(
                            "request-errors",
                            page_key,
                            attempts=attempt + 1,
                            error_type=type(exc).__name__,
                        )
                        not_before = self.clock() + min(2**attempt, 4)
                        continue
                    page = write_page(
                        self.run,
                        page_key,
                        params,
                        result.rows,
                        observed_columns=result.columns,
                    )
                    break
                if page is None:
                    raise RuntimeError(
                        f"Request failed after bounded attempts: {page_key}"
                    )
            paths.append(page["path"])
            self.check_cancel()
            if page["rows"] < self.run.budget["page_limit"]:
                self.run.checkpoint(
                    "requests", key, status="complete", request=request, paths=paths
                )
                return paths
        raise RuntimeError("Unexpected pagination volume; stop and revise this window")

    def _window_steps(self, window, scopes):
        if len(scopes) != window["scope_count"] or len(
            {s["scope_id"] for s in scopes}
        ) != len(scopes):
            raise ValueError("Window requires its complete frozen scope membership")
        if any(
            s["window_id"] != window["window_id"]
            or s["freq"] != window["freq"]
            or s["latest_ts_code"] != window["latest_ts_code"]
            for s in scopes
        ):
            raise ValueError("Scope does not belong to this frozen window")
        self.check_cancel()
        key = window["window_id"]
        done = self.run.state("windows", key)
        if done and done["status"] == "complete":
            return done
        results = {
            str(s["trade_date"]): {
                "scope_id": s["scope_id"],
                "latest_ts_code": s["latest_ts_code"],
                "freq": s["freq"],
                "trade_date": str(s["trade_date"]),
                "unconfirmed": s["unconfirmed"],
                "status": "unresolved",
                "source_ts_code": None,
                "paths": [],
            }
            for s in scopes
        }
        attempts = {d: [] for d in results}
        for scope in scopes:
            day = str(scope["trade_date"])
            cached = [
                self.seeds[(code, window["freq"], day)]
                for code in window["candidates"]
                if self.seeds.get((code, window["freq"], day), {}).get("status")
                == "source-ready"
            ]
            if len(cached) > 1:
                with self.run.db() as c:
                    for other in cached[1:]:
                        columns = ["open", "high", "low", "close", "vol", "amount"]
                        mismatch = " OR ".join(
                            f"a.{k} IS DISTINCT FROM b.{k}" for k in columns
                        )
                        conflicts = c.execute(
                            f"""SELECT count(*) FROM read_parquet(?) a JOIN read_parquet(?) b USING(trade_time)
                            WHERE CAST(a.trade_time AS DATE)=CAST(? AS DATE) AND ({mismatch})""",
                            [cached[0]["paths"], other["paths"], day],
                        ).fetchone()[0]
                        if conflicts:
                            raise ValueError("Conflicting cached native aliases")
        try:
            for code in window["candidates"]:
                needed = []
                for scope in scopes:
                    day = str(scope["trade_date"])
                    if results[day]["status"] == "source-ready":
                        continue
                    seed = self.seeds.get((code, window["freq"], day))
                    if seed:
                        attempts[day].append(seed)
                        if seed["status"] == "source-ready":
                            results[day].update(seed)
                    else:
                        needed.append(scope)
                # Split at every already-cached/resolved target day; never re-fetch successful samples.
                groups = []
                omitted = {str(s["trade_date"]) for s in scopes if s not in needed}
                omitted.update(
                    d
                    for (source, f, d) in self.seeds
                    if source == code and f == window["freq"]
                )
                for scope in needed:
                    if not groups or any(
                        str(groups[-1][-1]["trade_date"]) < i < str(scope["trade_date"])
                        for i in omitted
                    ):
                        groups.append([])
                    groups[-1].append(scope)
                for group in groups:
                    self.check_cancel()
                    paths = yield from self._request_steps(
                        code,
                        window["freq"],
                        str(group[0]["trade_date"]),
                        str(group[-1]["trade_date"]),
                    )
                    facts = day_facts(
                        self.run,
                        paths,
                        code,
                        window["freq"],
                        [str(s["trade_date"]) for s in group],
                    )
                    for day, fact in facts.items():
                        attempts[day].append(fact)
                        if fact["status"] == "source-ready":
                            results[day].update(fact)
            for day, value in results.items():
                if value["status"] != "source-ready":
                    value["status"] = (
                        "source-partial"
                        if any(f["status"] == "source-partial" for f in attempts[day])
                        else "source-empty"
                    )
                value["attempts"] = attempts[day]
            return self.save_resolution(key, results, "complete")
        except InterruptedError:
            raise
        except Exception as exc:
            for value in results.values():
                if value["status"] != "source-ready":
                    value["status"] = "request-failed"
            self.save_resolution(key, results, "failed", type(exc).__name__)
            raise

    def save_resolution(self, key, results, status, error=None):
        output = self.run.root / "resolutions" / f"{key}.parquet"
        payload = output.with_suffix(".json")
        atomic_json(
            payload, [dict(plan_hash=self.run.hash, **r) for r in results.values()]
        )
        with self.run.db() as c:
            parquet(
                c,
                f"""SELECT plan_hash,scope_id,latest_ts_code,freq,CAST(trade_date AS DATE) trade_date,
                unconfirmed,status,CAST(source_ts_code AS VARCHAR) source_ts_code,
                CAST(paths AS VARCHAR[]) paths FROM read_json_auto({literal(payload)},format='array')""",
                output,
            )
        return self.run.checkpoint(
            "windows",
            key,
            status=status,
            path=str(output),
            error=error,
            ready=sum(r["status"] == "source-ready" for r in results.values()),
            units=len(results),
        )


def compact_source_index(run):
    pages = sorted((run.root / "pages").glob("*.json"))
    resolutions = sorted((run.root / "resolutions").glob("*.parquet"))
    with run.db() as c:
        if pages:
            parquet(
                c,
                f"SELECT * FROM read_json_auto({literal_list(pages)},union_by_name=true)",
                run.root / "source-index.parquet",
            )
        if resolutions:
            parquet(
                c,
                f"SELECT * FROM read_parquet({literal_list(resolutions)},hive_partitioning=false)",
                run.root / "raw-resolution.parquet",
            )


def literal_list(paths):
    return "[" + ",".join(literal(p) for p in paths) + "]"
