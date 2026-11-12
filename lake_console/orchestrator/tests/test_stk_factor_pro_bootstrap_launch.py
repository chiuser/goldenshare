"""LLD 22.3: temporary representative window through the existing bootstrap.

Prod is replaced by the existing DATE/float cursor fixture, not a real database.
A's archived 261-field HTTP values are explicitly converted to Prod carriers
and moved to the existing 2019-10-31/11-01 test window; B/EXTRA are synthetic.
The real monthly exporter, audits, publication, coverage and capacity checks run.
"""

import json
import os
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_source as source
from orchestrator.defs.bootstrap import stk_factor_pro_history as bootstrap
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import approval_fixture, native_row
from tests.stk_factor_pro_history_test_support import saved_real_rows
from tests.stk_factor_pro_test_support import NAMES, connection
from tests.test_stk_factor_pro_bootstrap import NoProd
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_bootstrap_progress import SelectedDateProd
from tests.test_stk_factor_pro_dagster_events import _isolated_instance

FIRST, SECOND = date(2019, 10, 31), date(2019, 11, 1)
DAYS = (FIRST, SECOND)
A, B, EXTRA = "000001.SZ", "600000.SH", "000002.SZ"


def file_identities(paths):
    """Only file metadata; the final full read is counted separately."""
    return {
        str(path): (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths
    }


def sizes(case):
    return {
        name: sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        for name, root in (
            ("lake", case.lake),
            ("staging", case.staging),
            ("duckdb", case.base / "duckdb"),
        )
    }


@pytest.fixture
def window(tmp_path, monkeypatch, record_property):
    @contextmanager
    def prepare(variant="complete"):
        archived = saved_real_rows()
        by_day = {}
        for day, saved in zip(DAYS, archived[:2], strict=True):
            # The source values are independent evidence; only carrier/date change.
            a = (
                A,
                day,
                *(None if value is None else float(value) for value in saved[2:]),
            )
            by_day[day] = (a, native_row(B, day=day))
        if variant == "missing":
            by_day[SECOND] = by_day[SECOND][:1]
        elif variant == "extra":
            by_day[SECOND] = tuple(
                sorted((*by_day[SECOND], native_row(EXTRA, day=SECOND)))
            )
        counts = tuple((day, len(by_day[day])) for day in DAYS)
        with connection(tmp_path) as conn:
            lake, staging, approval, identity = approval_fixture(
                conn,
                tmp_path,
                counts=counts,
                operation="bootstrap-launch",
                known_records={},
            )
            assert identity.columns == tuple(
                (
                    name,
                    "text"
                    if index == 0
                    else "date"
                    if index == 1
                    else "double precision",
                    index >= 2,
                )
                for index, name in enumerate(NAMES)
            )
            life = [
                (
                    code,
                    code[:6],
                    code,
                    "SZSE" if code.endswith("SZ") else "SSE",
                    None,
                    "CNY",
                    True,
                    "D" if code == EXTRA else "L",
                    date(2010, 1, 1),
                    date(2018, 1, 1) if code == EXTRA else None,
                )
                for code in (A, B, EXTRA)
            ]
            upstream(conn, lake, days=DAYS, codes=(A, B, EXTRA), life=life)
        with _isolated_instance(tmp_path) as instance:
            case = SimpleNamespace(
                base=tmp_path,
                lake=lake,
                staging=staging,
                approval=approval,
                identity=identity,
                instance=instance,
                rows=by_day,
                counts=counts,
                root=records.operation_root(staging, approval),
                totals=Counter(),
                measurements=[],
                estimates=[],
                forbidden=[],
                label="setup",
                peak=Counter(),
            )
            native_open, native_replace = Path.open, os.replace
            native_space = bootstrap._BootstrapProgress.observe_space

            def guard(value):
                text = str(value)
                assert "/Volumes/datasource/" not in text
                assert all(str(path) not in text for path in case.forbidden)

            def opened(path, *args, **kwargs):
                guard(path)
                if path.suffix == ".parquet" and (not args or "r" in args[0]):
                    case.totals["sha_opens"] += 1
                    case.totals["source_sha_opens"] += "/source/month=" in str(path)
                return native_open(path, *args, **kwargs)

            def sample():
                for name, value in sizes(case).items():
                    case.peak[name] = max(case.peak[name], value)

            def replaced(old, new):
                guard((old, new))
                sample()
                target = Path(new)
                case.totals["target_replaces"] += target.is_relative_to(lake)
                result = native_replace(old, new)
                sample()
                return result

            def space(progress, **kwargs):
                native_space(progress, **kwargs)
                estimate = kwargs["estimate"]
                case.estimates.append(
                    {
                        "label": case.label,
                        "stage": kwargs["stage"],
                        **{
                            name: getattr(estimate, name)
                            for name in (
                                "source_bytes",
                                "candidate_bytes",
                                "temp_bytes",
                                "record_bytes",
                            )
                        },
                        "observation": kwargs.get("observation"),
                    }
                )
                sample()

            def sqlite(conn, cursor, statement, parameters, context, many):
                assert conn.dialect.name == "sqlite"
                case.totals["sqlite_sql"] += 1

            class ObservedConnection:
                def __init__(self, native):
                    self.native = native

                def execute(self, sql, *args, **kwargs):
                    guard((sql, args, kwargs))
                    case.totals["duckdb_sql"] += 1
                    case.totals["parquet_sql"] += "read_parquet" in sql.lower()
                    case.totals["copy_sql"] += sql.lstrip().upper().startswith("COPY")
                    return self.native.execute(sql, *args, **kwargs)

                def __getattr__(self, name):
                    return getattr(self.native, name)

            @contextmanager
            def observed_connection():
                closing = None
                try:
                    with connection(tmp_path) as conn:
                        try:
                            yield ObservedConnection(conn)
                        finally:
                            closing = perf_counter()
                finally:
                    if closing is not None:
                        case.totals["duckdb_close_seconds"] += perf_counter() - closing

            case.connect = observed_connection
            monkeypatch.setattr(Path, "open", opened)
            monkeypatch.setattr(os, "replace", replaced)
            monkeypatch.setattr(bootstrap._BootstrapProgress, "observe_space", space)
            event.listen(Engine, "before_cursor_execute", sqlite)
            try:
                yield case
            finally:
                event.remove(Engine, "before_cursor_execute", sqlite)
                record_property(
                    "measurements", json.dumps(case.measurements, sort_keys=True)
                )
                record_property(
                    "space_estimates", json.dumps(case.estimates, sort_keys=True)
                )
                record_property(
                    "actual_peak_bytes", json.dumps(dict(case.peak), sort_keys=True)
                )

    return prepare


def remote(case):
    class ObservedProd(SelectedDateProd):
        def cursor(self, name=None, **kwargs):
            cursor = super().cursor(name=name, **kwargs)
            fetch = cursor.fetchmany

            def fetched(size):
                started = perf_counter()
                try:
                    rows = fetch(size)
                    if cursor.named:
                        case.totals["detail_rows_fetched"] += len(rows)
                    return rows
                finally:
                    if cursor.named:
                        case.totals["detail_fetch_seconds"] += perf_counter() - started

            cursor.fetchmany = fetched
            return cursor

    return ObservedProd(
        case.approval,
        case.identity,
        case.counts,
        [row for day in DAYS for row in case.rows[day]],
    )


def measure(case, label, action, *, prod=None):
    before = case.totals.copy()
    old_estimates, started = len(case.estimates), perf_counter()
    case.label = label
    try:
        return action()
    finally:
        captured = {} if prod is None else vars(prod)
        queries = captured.get("queries", ())
        case.measurements.append(
            {
                "label": label,
                "seconds": perf_counter() - started,
                **dict(case.totals - before),
                "prod_connections": captured.get("connections", 0),
                "control_sql": sum(not named for named, _, _ in queries),
                "detail_sql": sum(named for named, _, _ in queries),
                "fetch_sizes": captured.get("fetch_sizes", []),
                "space_check_observations": len(case.estimates) - old_estimates,
                "actual_end_bytes": sizes(case),
            }
        )


def execute(case, prod, label):
    def run():
        with case.connect() as conn:
            return bootstrap._run_stk_factor_pro_bootstrap(
                conn,
                lake_root=case.lake,
                staging_root=case.staging,
                operation_id=case.approval.operation_id,
                instance=case.instance,
                prod_postgres=prod,
            )

    return measure(case, label, run, prod=prod)


def target_paths(case, days=DAYS):
    return [
        path(case.lake, str(day))
        for day in days
        for path in (raw_stk_factor_pro_path, silver_stock_factor_pro_path)
    ]


def readback(case, *, missing=0, extra=0):
    def check():
        known = {}
        with case.connect() as conn:
            for day in DAYS:
                completed = records.read_json(
                    case.root / f"source/dates/{day}/source-complete.json",
                    C.StkFactorProBootstrapSourceComplete,
                    known_records=known,
                )
                assert (
                    completed.approved_rows
                    == completed.actual_rows
                    == len(case.rows[day])
                )
                assert completed.close_reason == "eof" and not completed.source_empty
                assert completed.selected_dates == (day,)
                for layer, path in (
                    ("raw", raw_stk_factor_pro_path(case.lake, str(day))),
                    ("silver", silver_stock_factor_pro_path(case.lake, str(day))),
                ):
                    publication = records.read_json(
                        case.root / f"publication/{day}/{layer}/complete.json",
                        C.StkFactorProBootstrapPublicationComplete,
                        known_records=known,
                    )
                    assert (
                        publication.source_complete_digest
                        == completed.source_complete_digest
                    )
                    assert publication.audit.passed and publication.audit.path == path
                    assert publication.actual_rows == len(case.rows[day])
                    assert (
                        publication.actual_file_sha256 == publication.audit.file_sha256
                    )
                    values = conn.execute(
                        "SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code,trade_date",
                        [str(path)],
                    )
                    assert tuple(item[0] for item in values.description) == NAMES
                    assert tuple(str(item[1]) for item in values.description) == (
                        "VARCHAR",
                        "VARCHAR" if layer == "raw" else "DATE",
                        *("DOUBLE" for _ in NAMES[2:]),
                    )
                    expected = [
                        (
                            row[0],
                            day.strftime("%Y%m%d") if layer == "raw" else day,
                            *row[2:],
                        )
                        for row in case.rows[day]
                    ]
                    assert values.fetchall() == expected
                coverage = records.read_json(
                    case.root / f"coverage/{day}/result.json",
                    C.StkFactorProBootstrapDateCoverage,
                    known_records=known,
                )
                assert coverage.import_complete and coverage.unknown_input_kinds == ()
                assert (
                    coverage.source_rows
                    == coverage.raw_rows
                    == coverage.silver_rows
                    == len(case.rows[day])
                )
                assert coverage.current_publication is None
                assert coverage.expected_count == 2
                assert coverage.missing_count == (missing if day == SECOND else 0)
                assert coverage.extra_count == (extra if day == SECOND else 0)
                assert coverage.coverage_complete is (
                    day == FIRST or (missing == 0 and extra == 0)
                )
        assert set(
            case.instance.get_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS)
        ) == {str(day) for day in DAYS}
        assert case.instance.get_runs_count() == 0
        for asset_name, check_name in (
            (C.STK_FACTOR_PRO_RAW_ASSET_KEY, C.STK_FACTOR_PRO_RAW_CHECK_NAME),
            (C.STK_FACTOR_PRO_SILVER_ASSET_KEY, C.STK_FACTOR_PRO_SILVER_CHECK_NAME),
        ):
            key = dg.AssetKey(asset_name)
            assert not case.instance.fetch_materializations(
                dg.AssetRecordsFilter(key, asset_partitions=[str(day) for day in DAYS]),
                limit=1,
            ).records
            assert (
                not case.instance.event_log_storage.get_asset_check_execution_history(
                    dg.AssetCheckKey(key, check_name),
                    limit=1,
                )
            )

    measure(case, "final_readback", check)
    assert case.measurements[-1]["parquet_sql"] == 4


def test_cross_month_window_full_fields_then_expired_local_replay(window, monkeypatch):
    with window() as case:
        prod = remote(case)
        result = execute(case, prod, "normal")
        assert (
            result.verified_source_rows
            == result.verified_raw_rows
            == result.verified_silver_rows
            == 4
        )
        assert result.import_pending_dates == () and result.all_expected_present
        cost = case.measurements[-1]
        assert (cost["prod_connections"], cost["control_sql"], cost["detail_sql"]) == (
            2,
            2,
            2,
        )
        assert cost["fetch_sizes"] == [3, 1, 3, 1]
        assert cost["detail_rows_fetched"] == cost["target_replaces"] == 4
        for is_named, statement, _ in prod.queries:
            if is_named:
                # Independent contract, not SelectedDateProd's parameter filter:
                # a broken SQL predicate must not pass through a helpful fake.
                projection, predicate = statement.split(
                    ' FROM "raw_tushare"."stk_factor_pro" WHERE '
                )
                assert [
                    column.strip()
                    for column in projection.removeprefix("SELECT ").split(",")
                ] == [f'"{name}"' for name in NAMES]
                assert predicate == (
                    "trade_date >= %s AND trade_date < %s "
                    "AND trade_date = ANY(%s::date[]) "
                    "ORDER BY trade_date, ts_code LIMIT %s"
                )
        named = [
            (params[0], params[1], params[2], params[3])
            for is_named, _, params in prod.queries
            if is_named
        ]
        assert named == [
            (FIRST, SECOND, [FIRST], 3),
            (SECOND, date(2019, 11, 2), [SECOND], 3),
        ]
        assert (
            len(list(case.root.glob("source/month=*/attempt_id=*/fragment-*.parquet")))
            == 2
        )
        assert not list(case.root.glob("candidates/**/*.parquet"))
        before = file_identities(target_paths(case))
        source_facts = {
            day: (case.root / f"source/dates/{day}/source-complete.json").read_bytes()
            for day in DAYS
        }
        monkeypatch.setattr(
            bootstrap, "_now", lambda: case.approval.source_maintenance_end
        )
        monkeypatch.setattr(
            source, "_now", lambda: case.approval.source_maintenance_end
        )
        again = execute(case, NoProd(), "local_replay_after_expiry")
        assert (
            again.verified_source_rows
            == again.current_raw_rows
            == again.current_silver_rows
            == 4
        )
        assert again.all_expected_present
        local = case.measurements[-1]
        assert (
            local["detail_sql"]
            == local["control_sql"]
            == local["prod_connections"]
            == 0
        )
        assert (
            local.get("copy_sql", 0)
            == local.get("target_replaces", 0)
            == local.get("source_sha_opens", 0)
            == 0
        )
        assert file_identities(target_paths(case)) == before
        assert all(
            (case.root / f"source/dates/{day}/source-complete.json").read_bytes()
            == source_facts[day]
            for day in DAYS
        )
        readback(case)


def test_unfinished_second_month_retains_first_day_and_redownloads_whole_day(window):
    with window() as case:
        first = remote(case)
        first.read_failure_at = (
            4  # Second month's real EOF fetch, after its data batch.
        )
        with pytest.raises(RuntimeError, match="injected remote read failure"):
            execute(case, first, "unfinished_source")
        assert all(path.is_file() for path in target_paths(case, (FIRST,)))
        assert not any(path.exists() for path in target_paths(case, (SECOND,)))
        assert not (case.root / f"source/dates/{SECOND}/source-complete.json").exists()
        assert case.measurements[-1]["target_replaces"] == 2
        assert first.closes == ["named", "control", "rollback", "connection"] * 2
        pending = records.read_json(
            case.root / "coverage/summary.json",
            C.StkFactorProBootstrapCoverageSummary,
            known_records={},
        )
        assert pending.verified_source_rows == 2 and pending.import_pending_dates == (
            SECOND,
        )
        before = file_identities(target_paths(case, (FIRST,)))
        (abandoned,) = (case.root / "source/month=2019-11").iterdir()
        case.forbidden.append(abandoned)
        second = remote(case)
        result = execute(case, second, "restore_whole_second_day")
        assert (
            result.verified_source_rows
            == result.current_raw_rows
            == result.current_silver_rows
            == 4
        )
        assert result.all_expected_present and result.import_pending_dates == ()
        restored = case.measurements[-1]
        assert restored["detail_sql"] == restored["prod_connections"] == 1
        assert restored["control_sql"] == 1 and restored["fetch_sizes"] == [3, 1]
        assert restored["detail_rows_fetched"] == restored["target_replaces"] == 2
        assert [params[2] for named, _, params in second.queries if named] == [[SECOND]]
        assert file_identities(target_paths(case, (FIRST,))) == before
        readback(case)


@pytest.mark.parametrize(
    "variant,missing,extra,total", [("missing", 1, 0, 3), ("extra", 0, 1, 5)]
)
def test_faithful_import_keeps_source_rows_and_reports_current_gap(
    window, variant, missing, extra, total
):
    with window(variant) as case:
        result = execute(case, remote(case), "faithful_" + variant)
        assert (
            result.verified_source_rows
            == result.current_raw_rows
            == result.current_silver_rows
            == total
        )
        assert result.import_pending_dates == () and result.all_coverage_determined
        assert (
            result.total_missing_count == missing
            and result.extra_count_known_dates == extra
        )
        # LLD 10.5: gap_dates records missing required codes only. Extra codes
        # remain separately counted and make DateCoverage.coverage_complete false.
        assert result.gap_dates == ((SECOND,) if missing else ())
        assert result.all_expected_present is (missing == 0)
        assert (
            case.measurements[-1]["target_replaces"],
            case.measurements[-1]["detail_sql"],
        ) == (4, 2)
        readback(case, missing=missing, extra=extra)


def test_formal_entry_rejects_temporary_root_before_connecting(window, monkeypatch):
    with window() as case:
        monkeypatch.setattr(
            bootstrap,
            "connect_configured_duckdb",
            lambda: pytest.fail("formal connection opened"),
        )
        resource = SimpleNamespace(
            root=lambda: case.lake, ensure_available_for_run=lambda: None
        )
        with pytest.raises(ValueError, match="正式bootstrap入口不接受任意Lake根"):
            bootstrap.bootstrap_stk_factor_pro_history(
                operation_id=case.approval.operation_id,
                instance=case.instance,
                prod_postgres=NoProd(),
                lake_root=resource,
            )
        assert not any(path.exists() for path in target_paths(case))
