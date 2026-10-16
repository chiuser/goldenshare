"""One real CLI/HTTP-worker/handoff/job path on a tiny, independent local source.

Only clocks, the upstream fixture, resource roots and event fault are substituted.
All execution, checkpoints, COPY, checks and Dagster event storage remain real.
"""

import json
import multiprocessing
import signal
import threading
import time
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs import paths
from orchestrator.defs import stock_period_source as source
from orchestrator.defs import stock_period_update as update
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.bootstrap import stock_period_history_cli as cli
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import FIELDS

A, B, C = "000001.SZ", "920000.BJ", "301569.SZ"


def source_row(code, day, freq, asof, price):
    # Literal prices, including NULL, exercise source preservation, not formulas.
    return [code, day, asof, freq] + [price] * 16 + [None]


def write_upstreams(root, work, *, newcomer=False):
    with raw.connection(work) as con:
        basic = paths.silver_stock_basic_path(root)
        basic.parent.mkdir(parents=True, exist_ok=True)
        con.sql(
            "SELECT unnest(?) ts_code,'L' list_status,'CNY' curr_type",
            params=[[A, B, C] if newcomer else [A, B]],
        ).write_parquet(str(basic))
        identity = paths.silver_stock_identity_map_path(root)
        identity.parent.mkdir(parents=True, exist_ok=True)
        con.sql(
            "SELECT '832000.BJ' source_ts_code,'920000.BJ' latest_ts_code,'confirmed' confidence"
        ).write_parquet(str(identity))
        calendar = paths.silver_trade_calendar_path(root)
        calendar.parent.mkdir(parents=True, exist_ok=True)
        # Contract: SILVER_TRADE_CALENDAR_SCHEMA; source cal_date is already normalized.
        con.sql(
            "SELECT 'SSE' exchange,DATE '2026-10-01'+i::INTEGER trade_date,"
            "(isodow(DATE '2026-10-01'+i::INTEGER)<=5) is_open,"
            "NULL::DATE pretrade_date FROM range(61) t(i)"
        ).write_parquet(str(calendar))
        for day, factor in [("2026-10-30", 1), ("2026-11-02", 2), ("2026-11-03", 2)]:
            target = paths.silver_adj_factor_path(root, day)
            target.parent.mkdir(parents=True, exist_ok=True)
            con.sql(
                "SELECT ? ts_code,?::DOUBLE adj_factor UNION ALL SELECT ?,1 UNION ALL SELECT ?,1",
                params=[A, factor, B, C],
            ).write_parquet(str(target))


def test_cli_worker_cancel_events_handoff_and_actual_daily_jobs(tmp_path, monkeypatch):
    root, staging = tmp_path / "lake", tmp_path / "staging"
    write_upstreams(root, tmp_path / "fixtures")
    kept = root / "raw/unrelated/keep.txt"
    kept.parent.mkdir(parents=True)
    kept.write_text("untouched")
    for freq in ("week", "month"):
        old = root / f"raw/tushare/stk_period_bar_adj_{freq}/old.txt"
        old.parent.mkdir(parents=True)
        old.write_text("old temporary dataset")

    class Clock(datetime):
        instant = datetime.fromisoformat("2026-10-30T20:00:00+08:00")

        @classmethod
        def now(cls, tz=None):
            return (
                cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)
            )

    monkeypatch.setattr(update, "datetime", Clock)
    monkeypatch.setattr(history, "execution_time", lambda: Clock.instant.isoformat())
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    from orchestrator.defs.resources import LakeRootResource

    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    requests, timings, sql, stages, workers, sleeps, phases = [], [], [], [], [], [], []
    memory, accounted = [], []
    active_http = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received = time.monotonic()
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload["api_name"] == "stk_week_month_adj"
            assert payload["fields"] == ",".join(FIELDS)
            assert payload["token"] == "isolated-fixture-token"
            params = payload["params"]
            requests.append(dict(params))
            active_http["received"] = received
            freq = params["freq"]
            codes = [params["ts_code"]] if "ts_code" in params else [A, B, C]
            assert set(codes) <= {A, B, C}  # No old BSE code request.
            initial = Clock.instant.month == 10
            dates = (
                (["20260925", "20261030"] if initial else ["20261030", "20261106"])
                if freq == "week"
                else (["20260930", "20261031"] if initial else ["20261031", "20261130"])
            )
            if "ts_code" not in params:
                dates = (
                    [params["trade_date"]] if freq == "week" else [params["end_date"]]
                )
            else:
                assert not ({"start_date", "end_date", "trade_date"} & params.keys())
            asof = Clock.instant.strftime("%Y%m%d")
            rows = [
                source_row(
                    code,
                    day,
                    freq,
                    asof,
                    "9" if code == B else "7" if code == C else "1" if initial else "3",
                )
                for code in codes
                for day in dates
            ]
            body = json.dumps(
                {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            active_http.update(
                service_seconds=time.monotonic() - received, rows=len(rows)
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TUSHARE_TOKEN", "isolated-fixture-token")
    monkeypatch.setenv("TUSHARE_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("TUSHARE_MAX_CALLS_PER_MINUTE", "280")
    original_http, original_sql = source.HttpPage.__call__, raw.execute

    def measured_sleep(seconds):
        began = time.monotonic()
        time.sleep(seconds)
        sleeps.append(time.monotonic() - began)

    # Observe the source module's waits without changing the clock or wait duration.
    monkeypatch.setattr(
        source,
        "time",
        SimpleNamespace(
            monotonic=time.monotonic,
            time_ns=time.time_ns,
            sleep=measured_sleep,
        ),
    )
    original_record = raw.StorageBudget.record

    def measured_record(self, path):
        result = original_record(self, path)
        accounted.append(self.used)
        return result

    monkeypatch.setattr(raw.StorageBudget, "record", measured_record)

    def measured_http(self, params):
        began = time.monotonic()
        sleep_index = len(sleeps)
        limiter_remaining = max(0, self.next_request - began)
        original_progress = self.progress
        startup = []

        def progress(event):
            if event["stage"] == "source_worker_started":
                startup.append(time.monotonic())
                workers.append(event["worker_pid"])
            return original_progress(event)

        self.progress = progress
        try:
            body = original_http(self, params)
            timings.append(
                {
                    "seconds": time.monotonic() - began,
                    "limiter_remaining_at_entry": limiter_remaining,
                    "actual_wait_seconds": sum(sleeps[sleep_index:]),
                    "spawn_to_server_seconds": active_http["received"] - startup[0],
                    "http_service_seconds": active_http["service_seconds"],
                    "rows": active_http["rows"],
                    "bytes": len(body),
                }
            )
            return body
        finally:
            self.progress = original_progress

    def measured_sql(*args, **kwargs):
        began = time.monotonic()
        result = original_sql(*args, **kwargs)
        sql.append({"stage": kwargs.get("stage"), "seconds": time.monotonic() - began})
        memory.append(raw.current_rss_bytes())
        return result

    monkeypatch.setattr(source.HttpPage, "__call__", measured_http)
    monkeypatch.setattr(raw, "execute", measured_sql)
    for name in ("_save_body", "_decode_page"):
        original = getattr(source, name)

        def measured(*args, _original=original, _name=name, **kwargs):
            began = time.monotonic()
            result = _original(*args, **kwargs)
            stages.append({"stage": _name, "seconds": time.monotonic() - began})
            return result

        monkeypatch.setattr(source, name, measured)

    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    (instance_dir / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    instance = dg.DagsterInstance.local_temp(str(instance_dir))
    dispose = instance.dispose
    monkeypatch.setattr(instance, "dispose", lambda: None)
    monkeypatch.setattr(dg.DagsterInstance, "get", lambda: instance)
    events, fault = [], {"armed": True}
    event_depth = 0
    for name in ("report_runless_asset_event", "report_dagster_event"):
        original = getattr(instance, name)

        def measured_event(*args, _original=original, _name=name, **kwargs):
            nonlocal event_depth
            event = args[0] if args else kwargs.get("dagster_event")
            evaluation = getattr(event, "event_specific_data", None)
            if fault["armed"] and getattr(evaluation, "asset_key", None) == dg.AssetKey(
                "raw_tushare_stk_period_bar_adj_month"
            ):
                fault["armed"] = False
                raise OSError("isolated_event_failure")
            began = time.monotonic()
            top_level = event_depth == 0
            event_depth += 1
            try:
                return _original(*args, **kwargs)
            finally:
                event_depth -= 1
                events.append(
                    {
                        "method": _name,
                        "top_level": top_level,
                        "seconds": time.monotonic() - began,
                    }
                )

        monkeypatch.setattr(instance, name, measured_event)

    progress, cancelled = [], False

    def observed_print(value, **kwargs):
        nonlocal cancelled
        item = json.loads(value)
        progress.append(item)
        if not cancelled and item.get("stage") == "source_unit_complete":
            cancelled = True
            signal.raise_signal(signal.SIGINT)

    monkeypatch.setattr(cli, "print", observed_print, raising=False)
    common = ["--lake-root", str(root), "--staging-root", str(staging)]
    began = time.monotonic()
    last_phase = began
    completed, output = False, []

    def mark(name):
        nonlocal last_phase
        now = time.monotonic()
        phases.append(
            {
                "name": name,
                "seconds": now - last_phase,
                "requests_completed": len(requests),
            }
        )
        last_phase = now

    try:
        with pytest.raises(raw.PeriodCancelled):
            cli.main(
                [
                    "apply",
                    *common,
                    "--request-id",
                    "step67-integrated",
                    "--confirm-delete-existing",
                ]
            )
        assert len(requests) == 1
        run = next((staging / "stock_period/runs").iterdir())
        frozen = raw.read_json(run / "manifest.json")["identity_hash"]
        complete = next((run / "source").glob("*/complete.json"))
        captured = complete.read_bytes()
        assert not any(p.pid in workers for p in multiprocessing.active_children())
        with history.writer(staging):
            pass
        assert kept.read_text() == "untouched"
        assert not list(root.glob("raw/tushare/*/old.txt"))
        mark("bootstrap_cancel")
        argv = [*common, "--run-id", run.name]
        assert cli.main(["resume", *argv]) == 0
        assert len(requests) == 4 and complete.read_bytes() == captured
        assert raw.read_json(run / "manifest.json")["identity_hash"] == frozen
        assert (
            raw.read_json(staging / "stock_period/baseline.json")["status"]
            == "files_ready"
        )
        mark("bootstrap_resume")
        versions = {
            p: raw.file_version(p) for p in root.glob("raw/tushare/*/*/*.parquet")
        }
        before = len(sql), len(requests)
        with pytest.raises(OSError, match="isolated_event_failure"):
            cli.main(["events", *argv])
        mark("events_failed")
        assert cli.main(["events", *argv]) == 0
        assert (len(sql), len(requests)) == before
        assert versions == {p: raw.file_version(p) for p in versions}
        assert len(instance.get_runs()) == 2
        mark("events_resume")

        Clock.instant = datetime.fromisoformat("2026-11-02T20:00:00+08:00")
        write_upstreams(root, tmp_path / "fixtures2", newcomer=True)
        assert cli.main(["handoff", *argv]) == 0
        assert len(requests) == 12
        assert (
            raw.read_json(staging / "stock_period/baseline.json")["status"] == "ready"
        )
        state = raw.read_json(staging / "stock_period/daily.json")
        assert state["completed_through"] == {"week": "2026-10-30", "month": "2026-10"}
        assert state["factor_through"] == "2026-11-02"
        assert Counter(p["ts_code"] for p in requests[4:] if "ts_code" in p) == {
            A: 2,
            C: 2,
        }
        mark("handoff")
        before = len(sql), len(requests), len(events)
        assert cli.main(["handoff", *argv]) == 0
        assert (len(sql), len(requests), len(events)) == before
        mark("handoff_repeat")

        from orchestrator.defs.assets import stock_monthly, stock_weekly
        from orchestrator.defs.checks import stock_monthly_checks, stock_weekly_checks
        from orchestrator.defs.jobs import stock_monthly as monthly_jobs
        from orchestrator.defs.jobs import stock_weekly as weekly_jobs
        from orchestrator.defs.run_contracts.configs import (
            build_stock_period_run_config,
        )
        from orchestrator.defs.run_contracts.stock_monthly import (
            StockMonthlySource,
            monthly_check_names,
        )
        from orchestrator.defs.run_contracts.stock_weekly import (
            StockWeeklySource,
            weekly_check_names,
        )

        assets = [
            stock_weekly.raw_tushare_stk_period_bar_adj_week,
            stock_monthly.raw_tushare_stk_period_bar_adj_month,
        ]
        checks = [
            getattr(stock_weekly_checks, n)
            for n in weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)
        ]
        checks += [
            getattr(stock_monthly_checks, n)
            for n in monthly_check_names(StockMonthlySource.PRIMARY_ADJUSTED)
        ]
        defs = dg.Definitions(
            assets=assets,
            asset_checks=checks,
            jobs=[
                weekly_jobs.raw_stk_period_bar_adj_week_update_job,
                monthly_jobs.raw_stk_period_bar_adj_month_update_job,
            ],
            resources={"lake_root": LakeRootResource(root_path=str(root))},
        )
        Clock.instant = datetime.fromisoformat("2026-11-03T20:00:00+08:00")
        for index, (freq, period) in enumerate(
            [
                ("week", "2026-11-06"),
                ("month", "2026-11"),
                ("month", "2026-11"),
            ]
        ):
            if index == 2:
                repeated = {
                    p: raw.file_version(p)
                    for p in root.glob("raw/tushare/*/*/*.parquet")
                }
                before_repeat = len(requests), len(sql)
            job = defs.resolve_job_def(f"raw_stk_period_bar_adj_{freq}_update_job")
            result = job.execute_in_process(
                instance=instance,
                partition_key=period,
                run_config=build_stock_period_run_config(freq, "2026-11-03"),
            )
            assert result.success
            evaluated = result.get_asset_check_evaluations()
            materialization = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey("raw_tushare_stk_period_bar_adj_" + freq),
                    asset_partitions=[period],
                ),
                limit=1,
            ).records[0]
            assert len(evaluated) == 3 and all(
                e.passed
                and e.blocking
                and e.partition == period
                and e.target_materialization_data is not None
                and e.target_materialization_data.storage_id
                == materialization.storage_id
                for e in evaluated
            )
            if index == 2:
                assert (len(requests), len(sql)) == before_repeat
                assert repeated == {p: raw.file_version(p) for p in repeated}
            mark(["daily_week", "daily_month", "anchor_ack_month"][index])
        assert len(requests) == 14
        assert not raw.read_json(staging / "stock_period/daily.json")["pending_work"]
        assert len(instance.get_runs()) == 6
        with raw.connection(tmp_path / "readback") as con:
            output = con.execute(
                "SELECT ts_code,trade_date,end_date,close,pct_chg FROM read_parquet(?,hive_partitioning=false) ORDER BY 1,2",
                [[str(p) for p in root.glob("raw/tushare/*/*/*.parquet")]],
            ).fetchall()
        assert len(output) == 14
        assert [(r[0], r[1]) for r in output if r[1] in ("20260925", "20260930")] == [
            (B, "20260925"),
            (B, "20260930"),
        ]
        assert all(r[-1] is None for r in output)
        assert all(
            r[2]
            == {
                "20260925": "20261030",
                "20260930": "20261030",
                "20261030": "20261102",
                "20261031": "20261102",
                "20261106": "20261103",
                "20261130": "20261103",
            }[r[1]]
            for r in output
        )
        assert all(
            r[3] == {A: 3, B: 9, C: 7}[r[0]]
            for r in output
            if r[1] not in ("20260925", "20260930")
        )
        counts = Counter(i["stage"] for i in sql)
        assert counts["partition_copy"] == 6 and counts["import_source"] == 6
        assert not any(p.pid in workers for p in multiprocessing.active_children())
        mark("final_readback")
        completed = True
    finally:
        # One bounded metadata inventory of this tiny fixture, never a formal root.
        files = [p for tree in (root, staging) for p in tree.rglob("*") if p.is_file()]
        report = {
            "completed": completed,
            "elapsed_seconds": time.monotonic() - began,
            "phases": phases,
            "requests": requests,
            "http": timings,
            "sql": sql,
            "source_stages": stages,
            "events": events,
            "current_rss_max_sample_bytes": max(memory, default=0),
            "run_accounted_max_bytes": max(accounted, default=0),
            "final_fixture_file_bytes": sum(p.stat().st_size for p in files),
            "final_fixture_file_count": len(files),
            "final_output_bytes": sum(
                p.stat().st_size
                for p in files
                if p.suffix == ".parquet" and p.is_relative_to(root / "raw/tushare")
            ),
            "spill_bytes_at_final_boundary": sum(
                p.stat().st_size for p in files if "spill" in p.parts
            ),
            "output_rows": len(output),
            "file_commits": len(
                list(staging.glob("stock_period/runs/*/committed/*/*.json"))
            ),
            "progress_file_commits": sum(
                p.get("stage") == "file_committed" for p in progress
            ),
        }
        (tmp_path / "performance.json").write_text(json.dumps(report, indent=2))
        dispose()
        server.shutdown()
        server.server_close()
        thread.join(2)
