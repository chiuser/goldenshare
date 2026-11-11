"""One real CLI/HTTP-worker/bootstrap/event path on a tiny, independent local source.

Only clocks, the upstream fixture, resource roots and event fault are substituted.
All execution, checkpoints, COPY, checks and Dagster event storage remain real.
"""

import json
import multiprocessing
import signal
import threading
import time
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
    from tests.factor_repair_fixtures import write_repair_lifecycle
    write_repair_lifecycle(paths.silver_stock_lifecycle_path(root),
                           [{"ts_code": code} for code in ([A, B, C] if newcomer else [A, B])])
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
                "SELECT ? ts_code,?::DATE trade_date,?::DOUBLE adj_factor "
                "UNION ALL SELECT ?,?::DATE,1 UNION ALL SELECT ?,?::DATE,1",
                params=[A, day, factor, B, day, C, day],
            ).write_parquet(str(target))


def test_cli_worker_cancel_and_independent_bootstrap_event_recovery(tmp_path, monkeypatch):
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
                    [params["trade_date"]]
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
        assert not (staging / "stock_period/baseline.json").exists()
        mark("bootstrap_resume")
        versions = {
            p: raw.file_version(p) for p in root.glob("raw/tushare/*/*/*.parquet")
        }
        before = len(sql), len(requests)
        with pytest.raises(Exception, match="isolated_event_failure"):
            cli.main(["events", *argv])
        mark("events_failed")
        assert cli.main(["events", *argv]) == 0
        assert len(requests) == before[1]
        assert not any(e["stage"] in ("partition_copy", "candidate_merged") for e in sql[before[0]:])
        assert versions == {p: raw.file_version(p) for p in versions}
        assert len(instance.get_runs()) == 2
        mark("events_resume")

        assert not (staging / "stock_period/daily.json").exists()
        assert not any(p.pid in workers for p in multiprocessing.active_children())
        mark("bootstrap_final")
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
