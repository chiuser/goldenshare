"""Bounded saved-source integration; transport/PG facts are explicitly replaced.

Uses the real downloader registry, planner, retry, notifications and session.
Only SourceTransport is substituted. No socket, env configuration or formal
Dagster/database/lake resource is used. The process exit test uses os._exit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import orchestrator.defs.checks.stk_factor_pro as checks
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_download as downloads
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.io import stk_factor_pro_publication as publication
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as models
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.contracts import CONTRACTS
from orchestrator.tushare_download.dataset_transport_mapping import (
    BINDINGS,
    DatasetTransportMapping,
)
from orchestrator.tushare_download.download_api import _build_downloader
from orchestrator.tushare_download.download_errors import DownloadErrorCode
from orchestrator.tushare_download.download_models import (
    AttemptFailure,
    DownloadProgressEvent,
    DownloadStatus,
)
from tests.stk_factor_pro_history_test_support import (
    NAMES,
    connection,
    contract,
    eligibility,
    identity,
    roots,
    row,
    saved_real_rows,
    write_factor_file,
)
from tests.test_stk_factor_pro_history_publication_batches import (
    assert_clean,
    write_rows,
)
from tests.tushare_download.fixtures import FakeClock, ScriptTransport

A = "000001.SZ"
T, P, START = date(2026, 10, 16), date(2026, 10, 15), date(2026, 10, 12)
DATES = tuple(date(2026, 10, day) for day in range(12, 17))
PROJECT = Path(__file__).resolve().parents[1]
REPORT = (
    PROJECT.parent
    / "reports/stock_factor_pro_batch3_20261026/integration-evidence.json"
)


class Metrics:
    """Observe bounded test I/O; distinguish actual work from measurement probes."""

    def __init__(self, conn, base):
        self.conn, self.base = conn, base
        self.phase = "planning"
        self.counts, self.phases, self.elapsed = {}, {}, {}
        self.max_relation_rows = {}
        self.measurement_queries = 0
        self.peak_staging_bytes = self.peak_lake_bytes = self.peak_total_bytes = 0
        self.disk_measurement_seconds = 0.0

    def add(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value
        phase = self.phases.setdefault(self.phase, {})
        phase[name] = phase.get(name, 0) + value

    def switch(self, phase):
        now = perf_counter()
        self.elapsed[self.phase] = (
            self.elapsed.get(self.phase, 0) + now - self.phase_started
        )
        self.phase, self.phase_started = phase, now

    def sample_disk(self):
        before = perf_counter()

        def size(root):
            return sum(
                path.stat().st_size for path in root.rglob("*") if path.is_file()
            )

        staging, lake = size(self.base / "staging"), size(self.base / "lake")
        self.peak_staging_bytes = max(self.peak_staging_bytes, staging)
        self.peak_lake_bytes = max(self.peak_lake_bytes, lake)
        self.peak_total_bytes = max(self.peak_total_bytes, staging + lake)
        self.disk_measurement_seconds += perf_counter() - before

    def __enter__(self):
        self.started = self.phase_started = perf_counter()
        self.stack = ExitStack()
        original_sha, original_replace = checks.factor_file_sha, os.replace
        finish = publication._finish_stk_factor_pro_history_publication

        def sha(path):
            self.add("sha_reads")
            self.add("sha_bytes", path.stat().st_size)
            return original_sha(path)

        def replace_file(source, target):
            source, target = Path(source), Path(target)
            self.sample_disk()
            value = original_replace(source, target)
            self.add("atomic_replaces")
            if target.is_relative_to(self.base / "lake"):
                self.add("formal_replaces")
            elif target.suffix == ".json":
                self.add("json_record_writes")
            elif target.name == "unrefreshed-keys.parquet":
                self.add("diagnostic_parquet_writes")
            elif (
                target.is_relative_to(self.base / "staging")
                and target.suffix == ".parquet"
            ):
                self.add("staging_parquet_promotions")
            self.sample_disk()
            return value

        def final_readback(*args, **kwargs):
            old_phase = self.phase
            self.switch("final_readback")
            try:
                return finish(*args, **kwargs)
            finally:
                self.switch(old_phase)

        for module in (checks, history, downloads, publication, sys.modules[__name__]):
            self.stack.enter_context(patch.object(module, "factor_file_sha", sha))
        self.stack.enter_context(patch.object(os, "replace", replace_file))
        self.stack.enter_context(
            patch.object(
                publication,
                "_finish_stk_factor_pro_history_publication",
                final_readback,
            )
        )
        self.sample_disk()
        return MeasuredConnection(self.conn, self)

    def __exit__(self, *error):
        self.switch("closed")
        self.wall_seconds = perf_counter() - self.started
        self.stack.close()

    def report(self):
        wall = getattr(self, "wall_seconds", perf_counter() - self.started)
        elapsed = self.elapsed.copy()
        if not hasattr(self, "wall_seconds"):
            elapsed[self.phase] = (
                elapsed.get(self.phase, 0) + perf_counter() - self.phase_started
            )
        return {
            "wall_clock_seconds": round(wall, 6),
            "phase_seconds": {key: round(value, 6) for key, value in elapsed.items()},
            "counts": self.counts,
            "counts_by_phase": self.phases,
            "temporary_table_max_rows": self.max_relation_rows,
            "measurement_only_count_queries": self.measurement_queries,
            "disk_scan_measurement_seconds": round(self.disk_measurement_seconds, 6),
            "observed_peak_staging_bytes_at_write_boundaries": self.peak_staging_bytes,
            "observed_peak_lake_bytes_at_write_boundaries": self.peak_lake_bytes,
            "observed_peak_total_bytes_at_write_boundaries": self.peak_total_bytes,
            "scope_note": "SQL/Parquet are query counts, not physical disk read counts; SHA bytes are actual whole-file hash input. Disk peaks are sampled before/after writes, no RSS pressure test.",
        }


class MeasuredConnection:
    def __init__(self, conn, metrics):
        self.conn, self.metrics = conn, metrics

    def __getattr__(self, key):
        return getattr(self.conn, key)

    def execute(self, query, parameters=None):
        text, metric = str(query), self.metrics
        lower = text.lower()
        metric.add("sql_queries")
        if "read_parquet" in lower:
            metric.add("parquet_read_queries")
            metric.add("read_parquet_calls", lower.count("read_parquet"))
        if lower.lstrip().startswith("copy"):
            metric.add("copy_queries")
            if "/candidates/history/" in text:
                metric.add("candidate_copies")
            if "/source/history/units/" in text:
                metric.add("source_unit_copies")
        if re.match(
            r"\s*create\s+temp\s+table\s+stk_factor_pro_history_batch_source\s", lower
        ):
            metric.add("batch_source_ctas")
        value = (
            self.conn.execute(query)
            if parameters is None
            else self.conn.execute(query, parameters)
        )
        table = re.match(
            r'\s*create\s+(?:or\s+replace\s+)?temp\s+table\s+"?(stk_factor_pro_[a-z_]+)"?\s',
            lower,
        )
        if table:
            name = table[1]
            metric.measurement_queries += 1
            count = self.conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            metric.max_relation_rows[name] = max(
                metric.max_relation_rows.get(name, 0), count
            )
        if lower.lstrip().startswith("copy"):
            metric.sample_disk()
        return value


def evidence(section, value):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    existing[section] = value
    write_json(REPORT, existing)


class ObservedDownloader:
    """Observe actual DownloadSession without changing its behavior."""

    def __init__(self, native):
        self.native = native
        self.sessions = []

    def download(self, task, **kwargs):
        session = self.native.download(task, **kwargs)
        self.sessions.append(session)
        return session


def native_saved_source(*, retry_first=False):
    rows, calls, transports = saved_real_rows(), [], []
    clock = FakeClock()

    def respond(request, attempt):
        assert request.api_name == "stk_factor_pro" and request.fields == NAMES
        assert dict(request.params) == {
            "ts_code": A,
            "start_date": "20261012",
            "end_date": "20261016",
            "limit": 10000,
            "offset": 0,
        }
        if retry_first and len(calls) == 1:
            return AttemptFailure(DownloadErrorCode.TRANSIENT_SOURCE)
        return rows

    def factory(binding, current_clock):
        assert binding.source_api_name == "stk_factor_pro" and current_clock is clock
        transport = ScriptTransport(respond, calls)
        transports.append(transport)
        return transport

    native = _build_downloader(
        ConfigurationSnapshot("isolated-not-a-real-token", "http://offline.invalid"),
        ContractRegistry(CONTRACTS),
        DatasetTransportMapping(BINDINGS),
        factory,
        clock,
        clock.sleep,
    )
    return ObservedDownloader(native), calls, transports, clock


def fixtures(conn, base):
    lake, staging = roots(base)
    raw_t = raw_stk_factor_pro_path(lake, T.isoformat())
    silver_t = silver_stock_factor_pro_path(lake, T.isoformat())
    if not raw_t.exists():
        sentinel = (row(A, "20261016", close=Decimal(99)),)
        write_rows(conn, raw_t, sentinel, layer="raw")
        write_rows(conn, silver_t, sentinel, layer="silver")
    refs = (
        write_factor_file(conn, lake, T, ((A, 2.0),)),
        write_factor_file(conn, lake, P, ((A, 1.0),)),
    )
    return lake, staging, refs, (factor_file_sha(raw_t), factor_file_sha(silver_t))


def create_flow(conn, fixture, *, run="run-normal", old=None):
    lake, staging, refs, t_hashes = fixture
    old = (
        models.StkFactorProRecordedResults(
            T, None, None, None, None, None, None, (), (), None, None
        )
        if old is None
        else old
    )
    run_identity = identity(run)
    plan = history.build_stk_factor_pro_history_plan(
        conn,
        identity=run_identity,
        contract=contract(),
        lake_root=lake,
        staging_root=staging,
        factor_t=refs[0],
        factor_p=refs[1],
        prior_results=old,
        history_starts=(models.StkFactorProHistoryStart(A, START, 1, START),),
        check_cancel=lambda: None,
    )
    root = stk_factor_pro_run_staging_root(staging, run, T.isoformat())
    ranges = history.read_stk_factor_pro_history_ranges(conn, root=root, plan=plan)
    verified_upstream = eligibility(run_identity, plan, *t_hashes)

    def recheck():
        # Third-batch boundary: the real PG/readiness readers belong to a later
        # batch. Supply the closed verified-input structure, not a bool flag.
        return (
            refs[0],
            refs[1],
            verified_upstream.raw_coverage,
            verified_upstream.target_silver,
        )

    download_args = {
        "identity": run_identity,
        "contract": contract(),
        "plan": plan,
        "ranges": ranges,
        "prior_results": old,
        "eligibility": verified_upstream,
        "lake_root": lake,
        "staging_root": staging,
        "recheck_inputs": recheck,
        "check_cancel": lambda: None,
    }
    publish_args = {
        "plan": plan,
        "ranges": ranges,
        "lake_root": lake,
        "staging_root": staging,
        "calendar": DATES,
        "registered_dates": DATES[:-1],
        "recheck_inputs": recheck,
        "check_cancel": lambda: None,
    }
    return root, download_args, publish_args


def complete(conn, source, publish_args):
    return tuple(
        publication.publish_stk_factor_pro_history(conn, source=source, **publish_args)
    )


def write_json(path, value):
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def wide_prior_sql(layer):
    # 5,568 rows are generated columnarly, with distinct finite binary fractions
    # and explicit NULLs. No Python list contains full-market business rows.
    parts = []
    for index, name in enumerate(NAMES):
        if index == 0:
            expression = "lpad(i::VARCHAR,6,'0') || '.SZ'"
        elif index == 1:
            expression = (
                "DATE '2026-10-12'" if layer == "silver" else "'20261012'::VARCHAR"
            )
        else:
            expression = f"CASE WHEN i%11=0 THEN NULL::DOUBLE ELSE CAST(i+{index}/16.0 AS DOUBLE) END"
        parts.append(f'{expression} AS "{name}"')
    return "SELECT " + ",".join(parts) + " FROM range(1,5569) r(i)"


def initialize_wide_previous(conn, lake):
    path = raw_stk_factor_pro_path(lake, START.isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(copy_query_to_parquet(wide_prior_sql("raw"), path))


def verify_wide_previous(conn, lake):
    fields = ",".join(f'"{name}"' for name in NAMES)
    for layer, path in (
        ("raw", raw_stk_factor_pro_path(lake, START.isoformat())),
        ("silver", silver_stock_factor_pro_path(lake, START.isoformat())),
    ):
        # Independently recompute the fixed input relation and compare both
        # directions across all 261 fields, excluding only refreshed stock A.
        count, difference = conn.execute(
            f"WITH expected AS ({wide_prior_sql(layer)}),actual AS "
            "(SELECT * FROM read_parquet(?,hive_partitioning=false)) "
            "SELECT (SELECT count(*) FROM actual WHERE ts_code<>?), "
            f"(SELECT count(*) FROM ((SELECT {fields} FROM expected WHERE ts_code<>? "
            f"EXCEPT ALL SELECT {fields} FROM actual WHERE ts_code<>?) UNION ALL "
            f"(SELECT {fields} FROM actual WHERE ts_code<>? EXCEPT ALL "
            f"SELECT {fields} FROM expected WHERE ts_code<>?)))",
            [str(path), A, A, A, A, A],
        ).fetchone()
        assert count == 5567 and difference == 0
        actual_a = conn.execute(
            f"SELECT {fields} FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?",
            [str(path), A],
        ).fetchone()
        expected_a = tuple(
            START
            if index == 1 and layer == "silver"
            else value
            if index < 2 or value is None
            else float(value)
            for index, value in enumerate(saved_real_rows()[0])
        )
        assert actual_a == expected_a


def test_native_saved_response_retry_notifications_and_complete_chain(tmp_path):
    with connection(tmp_path) as conn:
        fixture = fixtures(conn, tmp_path)
        lake, _, _, t_hashes = fixture
        initialize_wide_previous(conn, lake)
        downloader, calls, transports, _ = native_saved_source(retry_first=True)
        events = []
        metric = Metrics(conn, tmp_path)
        with metric as measured:
            root, download_args, publish_args = create_flow(measured, fixture)

            def progress(event):
                events.append(event)
                assert event.notification_version == 1 and not hasattr(event, "records")
                assert not tuple((root / "source/history/units").glob("*.parquet"))
                if len(events) == 1:
                    raise RuntimeError("ordinary observer failure must be isolated")

            metric.switch("download")
            source = downloads.download_stk_factor_pro_history(
                measured, **download_args, downloader=downloader, on_progress=progress
            )
            assert [event.event for event in events] == [
                DownloadProgressEvent.RETRY_SCHEDULED,
                DownloadProgressEvent.PAGE_COMPLETED,
                DownloadProgressEvent.UNIT_COMPLETED,
            ]
            assert len(calls) == 2
            summary = downloader.sessions[0].summary
            assert summary.status is DownloadStatus.SUCCEEDED
            assert summary.progress_error_count == 1 and summary.retry_count == 1
            assert summary.row_count == 5 and summary.total_units == 1
            assert all(transport.closed == 1 for transport in transports)
            metric.switch("publication")
            targets = complete(measured, source, publish_args)
            assert [(target.trade_date, target.layer) for target, _ in targets] == [
                (day, layer) for day in DATES[:-1] for layer in ("raw", "silver")
            ]
            assert all(audit is not None and audit.passed for _, audit in targets)
            metric.switch("verification")
            final = publication.read_stk_factor_pro_history_publication_complete(
                root, expected_target=T, expected_run_id="run-normal"
            )
            assert final.targets == tuple(target for target, _ in targets)
            assert (
                tuple(
                    factor_file_sha(path)
                    for path in (
                        raw_stk_factor_pro_path(lake, T.isoformat()),
                        silver_stock_factor_pro_path(lake, T.isoformat()),
                    )
                )
                == t_hashes
            )
            verify_wide_previous(measured, lake)
            assert_clean(measured)
        assert metric.counts["batch_source_ctas"] == 1
        assert metric.counts["candidate_copies"] == 8
        assert metric.counts["source_unit_copies"] == 1
        assert metric.counts["formal_replaces"] == 8
        assert metric.max_relation_rows["stk_factor_pro_history_batch_source"] == 4
        evidence(
            "normal",
            {
                "source_evidence": "stock_factor_pro_batch1_20261026/source/component-rows.canonical.json",
                "source_rows": 5,
                "units": 1,
                "source_files": 1,
                "requests": len(calls),
                "retry_count": summary.retry_count,
                "transport_boundary": "Real TushareDownloader/registry/planner/session, ScriptTransport only; zero network requests",
                "upstream_boundary": "Raw/Silver readiness facts are closed mock-reader inputs, no PG or Dagster instance",
                "source_dates": [day.isoformat() for day in DATES],
                "published_dates": 4,
                "targets": 8,
                "old_date_rows": 5568,
                "unrelated_rows_compared": 5567,
                "all_261_fields_compared_both_directions": True,
                "source_T_preserved_and_formal_T_unchanged": True,
                "events": [event.event.name for event in events],
                "observer_error_count": summary.progress_error_count,
                "temporary_relations_cleaned": True,
                "cost": metric.report(),
            },
        )


class RejectPreviousDownload:
    def __init__(self, conn, old_root):
        self.conn, self.old_root = conn, old_root

    def __getattr__(self, key):
        return getattr(self.conn, key)

    def execute(self, query, parameters=None):
        text = str(query) + repr(parameters)
        assert str(self.old_root / "source") not in text
        assert str(self.old_root / "candidates") not in text
        return (
            self.conn.execute(query)
            if parameters is None
            else self.conn.execute(query, parameters)
        )


def child_stage(stage, base):
    with connection(base) as conn:
        fixture = fixtures(conn, base)
        lake, staging, _, _ = fixture
        old_root = stk_factor_pro_run_staging_root(staging, "run-exit", T.isoformat())
        original_open = Path.open

        def guard(path, *args, **kwargs):
            if stage == "recover":
                assert not path.is_relative_to(old_root / "source")
                assert not path.is_relative_to(old_root / "candidates")
            return original_open(path, *args, **kwargs)

        metric = Metrics(conn, base)
        with metric as measured, patch.object(Path, "open", guard):
            old = None
            if stage == "recover":
                plan = history.read_stk_factor_pro_history_plan(
                    old_root, expected_target=T, expected_run_id="run-exit"
                )
                plan_ref = models.RecordRef(
                    "run-exit",
                    "history-plan.json",
                    factor_file_sha(old_root / "history-plan.json"),
                )
                old = replace(
                    models.StkFactorProRecordedResults(
                        T, None, None, None, None, None, None, (), (), None, None
                    ),
                    history_plan_ref=plan_ref,
                    history_ranges_ref=plan.ranges_ref,
                    pending_plan_refs=(plan_ref,),
                )
            guarded = (
                RejectPreviousDownload(measured, old_root)
                if stage == "recover"
                else measured
            )
            run = "run-exit" if stage == "exit" else "run-recover"
            root, download_args, publish_args = create_flow(
                guarded, fixture, run=run, old=old
            )
            downloader, calls, _, _ = native_saved_source()
            metric.switch("download")
            source = downloads.download_stk_factor_pro_history(
                guarded, **download_args, downloader=downloader
            )
            metric.switch("publication")
            outputs = publication.publish_stk_factor_pro_history(
                guarded, source=source, **publish_args
            )
            if stage == "exit":
                target, audit = next(outputs)
                assert (
                    target.layer == "raw"
                    and target.trade_date == START
                    and audit.passed
                )
                metric.sample_disk()
                write_json(
                    base / "exit.json",
                    {
                        "requests": len(calls),
                        "units": source.source_complete.completed_unit_count,
                        "rows": downloader.sessions[0].summary.row_count,
                        "first_raw_sha": audit.file_sha256,
                        "source_complete": (
                            root / "source/history/source-complete.json"
                        ).is_file(),
                        "targets": 1,
                        "exit_code": 17,
                        "cost": metric.report(),
                        "cleanup_note": "os._exit intentionally bypasses finally; a new OS process owns fresh in-memory state",
                    },
                )
                os._exit(17)
            targets = tuple(outputs)
            metric.switch("verification")
            final = publication.read_stk_factor_pro_history_publication_complete(
                root, expected_target=T, expected_run_id=run
            )
            assert final.targets == tuple(target for target, _ in targets)
            assert_clean(guarded)
            result = {
                "requests": len(calls),
                "units": source.source_complete.completed_unit_count,
                "rows": downloader.sessions[0].summary.row_count,
                "targets": len(targets),
                "old_source_reads": 0,
                "old_source_guard": "Path.open and SQL reject prior-run source/candidates, metadata intent reads allowed",
                "temporary_relations_cleaned": True,
                "first_raw_sha": factor_file_sha(
                    raw_stk_factor_pro_path(lake, START.isoformat())
                ),
                "scope": [
                    (
                        unit.object_code,
                        unit.start_date.isoformat(),
                        unit.end_date.isoformat(),
                    )
                    for unit in source.source_complete.expected_units
                ],
            }
        result["cost"] = metric.report()
        write_json(base / "recover.json", result)


def test_real_process_exit_then_new_process_redownloads_complete_original_scope(
    tmp_path,
):
    env = os.environ.copy()
    for key in ("DAGSTER_HOME", "TUSHARE_TOKEN", "TUSHARE_BASE_URL"):
        env.pop(key, None)
    command = [
        str(PROJECT / ".venv/bin/python3"),
        "-B",
        "-m",
        "tests.test_stk_factor_pro_history_integration",
    ]
    first = subprocess.run(
        [*command, "exit", str(tmp_path)],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert first.returncode == 17, first.stderr
    old = json.loads((tmp_path / "exit.json").read_text())
    assert (
        old["source_complete"]
        and old["requests"] == old["units"] == 1
        and old["rows"] == 5
    )
    second = subprocess.run(
        [*command, "recover", str(tmp_path)],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    fresh = json.loads((tmp_path / "recover.json").read_text())
    assert fresh["requests"] == fresh["units"] == 1 and fresh["rows"] == 5
    assert fresh["scope"] == [[A, "2026-10-12", "2026-10-16"]]
    assert fresh["targets"] == 8 and fresh["old_source_reads"] == 0
    assert fresh["first_raw_sha"] == old["first_raw_sha"]
    old_root = stk_factor_pro_run_staging_root(
        tmp_path / "staging", "run-exit", T.isoformat()
    )
    assert len(tuple((old_root / "source/history/units").glob("*.parquet"))) == 1
    assert fresh["cost"]["counts"]["source_unit_copies"] == 1
    assert fresh["cost"]["counts"]["batch_source_ctas"] == 1
    evidence(
        "process_exit_and_redownload",
        {
            "failed_process": old,
            "new_process": fresh,
            "formal_first_Raw_preserved": True,
            "old_download_evidence_retained": True,
            "new_process_restarted_complete_scope": True,
            "network_requests": 0,
        },
    )


if __name__ == "__main__":
    child_stage(sys.argv[1], Path(sys.argv[2]))
