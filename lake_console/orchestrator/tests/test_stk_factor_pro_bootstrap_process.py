"""Real process exit and same-operation recovery, using only temporary resources."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_coverage as coverage
from orchestrator.defs.bootstrap import (
    stk_factor_pro_bootstrap_publication as publication,
)
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_source as source
from orchestrator.defs.bootstrap import stk_factor_pro_history as bootstrap
from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_bootstrap_operation_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import approval_fixture, native_row
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap_coverage import DAY, upstream
from tests.test_stk_factor_pro_bootstrap_source import FakeProd

EXIT_AFTER_RAW = 73
OPERATION = "bootstrap-process-a"


class IsolatedInstance:
    def __init__(self):
        self.active_queries = 0
        self.registered = set()

    def get_run_records(self, *, filters, limit):
        assert filters.job_name in C.STK_FACTOR_PRO_WRITE_JOB_NAMES
        assert limit == 2
        self.active_queries += 1
        return ()

    def add_dynamic_partitions(self, name, keys):
        assert name == C.STK_FACTOR_PRO_PARTITIONS
        self.registered.update(keys)


class ControlOnlyProd(FakeProd):
    def cursor(self, name=None, **kwargs):
        if name is not None:
            raise AssertionError("saved complete day must not reread Prod detail rows")
        return super().cursor(name, **kwargs)


class NoProd:
    def __getattr__(self, name):
        raise AssertionError(f"local statistics unexpectedly accessed Prod: {name}")


class CountingConnection:
    def __init__(self, underlying, costs):
        self.underlying, self.costs = underlying, costs

    def execute(self, query, parameters=None):
        text = str(query).lower()
        self.costs["duckdb_sql"] += 1
        self.costs["parquet_sql"] += int("read_parquet" in text)
        self.costs["copy_sql"] += int(text.startswith("copy"))
        if parameters is None:
            return self.underlying.execute(query)
        return self.underlying.execute(query, parameters)

    def __getattr__(self, name):
        return getattr(self.underlying, name)


def _save_costs(path, costs, remote, instance):
    result = dict(costs)
    # Inspect the fake's own captured state without probing the forbidden NoProd API.
    captured = vars(remote)
    result.update(
        prod_connections=captured.get("connections", 0),
        prod_control_queries=sum(
            not named for named, _, _ in captured.get("queries", ())
        ),
        prod_detail_queries=sum(
            named for named, _, _ in captured.get("queries", ())
        ),
        prod_detail_fetches=len(captured.get("fetch_sizes", ())),
        active_queries=instance.active_queries,
        registered=sorted(instance.registered),
    )
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _process_worker(root, mode):
    """Called in fresh interpreters; production files and instance are unreachable."""
    lake, staging = root / "lake", root / "staging"
    operation = stk_factor_pro_bootstrap_operation_root(staging, OPERATION)
    approval = records.read_json(
        operation / "approval.json", C.StkFactorProBootstrapApproval
    )
    costs = Counter()
    for module in (
        coverage,
        publication,
        records,
        source,
        bootstrap,
        checks,
        candidates,
    ):
        for name in ("factor_file_sha", "_file_sha"):
            if hasattr(module, name):
                original_sha = getattr(module, name)

                def sha(path, original=original_sha):
                    costs["file_sha"] += 1
                    return original(path)

                setattr(module, name, sha)
    instance = IsolatedInstance()
    if mode == "local":
        for key in tuple(os.environ):
            if key.startswith("PROD_POSTGRES_"):
                del os.environ[key]
        # Change only execution time. The original immutable approval stays intact.
        expired = approval.source_maintenance_end
        bootstrap._now = source._now = lambda: expired
        remote = NoProd()
    else:
        with connection(root) as conn:
            _, evidence, _ = source._approved_inputs(
                conn, staging_root=staging, approval=approval
            )
        remote_type = FakeProd if mode == "crash" else ControlOnlyProd
        remote = remote_type(
            approval, evidence.source_identity, ((DAY, 1),), [native_row()]
        )
    if mode == "crash":

        def exit_before_silver(*_args, **_kwargs):
            # Abrupt exit bypasses all Python contextmanager/finally cleanup.
            _save_costs(root / "crash-cost.json", costs, remote, instance)
            os._exit(EXIT_AFTER_RAW)

        publication.build_stk_factor_pro_silver_candidate = exit_before_silver
    with connection(root) as native:
        conn = CountingConnection(native, costs)
        summary = bootstrap._run_stk_factor_pro_bootstrap(
            conn,
            lake_root=lake,
            staging_root=staging,
            operation_id=OPERATION,
            instance=instance,
            prod_postgres=remote,
        )
        assert summary.import_pending_dates == ()
        assert (
            summary.verified_source_rows
            == summary.verified_raw_rows
            == summary.verified_silver_rows
            == 1
        )
        assert summary.current_raw_rows == summary.current_silver_rows == 1
        assert summary.all_coverage_determined and summary.all_expected_present
        assert summary.total_missing_count == 0
        assert (
            native.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name LIKE 'stk_factor_pro_%'"
            ).fetchone()[0]
            == 0
        )
        rows = native.execute(
            "SELECT ts_code,trade_date,open,close FROM read_parquet(?)",
            [str(silver_stock_factor_pro_path(lake, DAY.isoformat()))],
        ).fetchall()
        assert rows == [("000001.SZ", DAY, 1.25, 10.0)]
    _save_costs(root / f"{mode}-cost.json", costs, remote, instance)


def _launch(root, mode):
    project = Path(__file__).resolve().parents[1]
    assert Path(sys.executable).parent == project / ".venv" / "bin"
    command = [
        sys.executable,
        "-B",
        "-c",
        "from pathlib import Path; from tests.test_stk_factor_pro_bootstrap_process import _process_worker; import sys; _process_worker(Path(sys.argv[1]),sys.argv[2])",
        str(root),
        mode,
    ]
    return subprocess.run(
        command, cwd=project, capture_output=True, text=True, timeout=60, check=False
    )


def _fingerprint(paths):
    return {
        str(path): (checks.factor_file_sha(path), path.stat().st_mtime_ns)
        for path in paths
    }


def test_real_process_exit_raw_complete_new_process_restores_silver_then_local_stats(
    tmp_path,
):
    # Approved source uses actual Prod DATE/float carrier types and the independently
    # checked full 261 fields. Upstreams use their real producer schemas via upstream().
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = approval_fixture(
            conn, tmp_path, operation=OPERATION
        )
        upstream(conn, lake, days=(DAY,), codes=("000001.SZ",))
    approval_path = records.operation_root(staging, approval) / "approval.json"
    approval_before = _fingerprint((approval_path,))
    first = _launch(tmp_path, "crash")
    assert first.returncode == EXIT_AFTER_RAW, first.stdout + first.stderr
    raw_path = raw_stk_factor_pro_path(lake, DAY.isoformat())
    silver_path = silver_stock_factor_pro_path(lake, DAY.isoformat())
    source_path = records.operation_path(
        staging, approval, f"source/dates/{DAY}/source-complete.json"
    )
    raw_complete = records.operation_path(
        staging, approval, f"publication/{DAY}/raw/complete.json"
    )
    assert raw_path.is_file() and source_path.is_file() and raw_complete.is_file()
    assert not silver_path.exists()
    retained = (
        raw_path,
        source_path,
        raw_complete,
        *records.operation_root(staging, approval).rglob("fragment-*.parquet"),
    )
    before = _fingerprint(retained)
    second = _launch(tmp_path, "recover")
    assert second.returncode == 0, second.stdout + second.stderr
    assert _fingerprint(retained) == before
    assert _fingerprint((approval_path,)) == approval_before
    assert silver_path.is_file()
    crash = json.loads((tmp_path / "crash-cost.json").read_text())
    recovery = json.loads((tmp_path / "recover-cost.json").read_text())
    assert (
        crash["prod_connections"],
        crash["prod_detail_queries"],
        crash["prod_detail_fetches"],
    ) == (1, 1, 2)
    assert (
        recovery["prod_connections"],
        recovery["prod_control_queries"],
        recovery["prod_detail_queries"],
        recovery["prod_detail_fetches"],
    ) == (1, 5, 0, 0)
    assert recovery["registered"] == [DAY.isoformat()]
    formal_before = _fingerprint((raw_path, silver_path))
    last = _launch(tmp_path, "local")
    assert last.returncode == 0, last.stdout + last.stderr
    local = json.loads((tmp_path / "local-cost.json").read_text())
    assert (
        local["prod_connections"]
        == local["prod_control_queries"]
        == local["prod_detail_queries"]
        == local["prod_detail_fetches"]
        == 0
    )
    assert local["copy_sql"] == 0 and local["active_queries"] == 2
    assert _fingerprint((raw_path, silver_path)) == formal_before
    assert _fingerprint((approval_path,)) == approval_before
    summary_path = records.operation_path(staging, approval, "coverage/summary.json")
    summary = records.read_json(summary_path, C.StkFactorProBootstrapCoverageSummary)
    assert summary.import_pending_dates == () and summary.all_expected_present
    assert (
        summary.verified_source_rows
        == summary.current_raw_rows
        == summary.current_silver_rows
        == 1
    )
