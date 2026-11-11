"""Actual batch-five job in a temporary Dagster instance with local Parquet inputs."""

from contextlib import contextmanager
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import dagster as dg
import pytest

from orchestrator.defs.assets import stk_factor_pro as asset
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from orchestrator.defs.jobs.stk_factor_pro import raw_tushare_stk_factor_pro_update_job
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.sensors import readiness as upstream_readiness
from orchestrator.tushare_download import DownloadMode
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from tests.stk_factor_pro_history_test_support import (
    HistoryDownloader,
    roots,
    saved_real_rows,
    write_factor_file,
)
from tests.stk_factor_pro_test_support import (
    DAY,
    NAMES,
    Downloader,
    connection,
    result,
    row,
)
from tests.test_stk_factor_pro_bootstrap_coverage import (
    DAY as INITIAL_DAY,
)
from tests.test_stk_factor_pro_bootstrap_coverage import (
    save as save_initial_date,
)
from tests.test_stk_factor_pro_bootstrap_coverage import (
    setup as setup_initial_import,
)
from tests.test_stk_factor_pro_bootstrap_coverage import (
    summary as save_initial_summary,
)
from tests.test_stk_factor_pro_bootstrap_coverage import (
    upstream,
)
from tests.test_stk_factor_pro_dagster_events import _isolated_instance
from tests.test_stk_factor_pro_history_starts import write_keys

FIRST = date(2026, 10, 13)
UNMATERIALIZED = date(2026, 10, 14)
PREVIOUS = date(2026, 10, 15)
A, B, EXTRA = "000001.SZ", "600000.SH", "000002.SZ"


def config(day=DAY, *, execution_day=None, purpose="today", slot=0):
    return {
        "ops": {
            "stk_factor_pro": {
                "config": {
                    "execution_day": str(execution_day or day),
                    "target_trade_date": str(day),
                    "purpose": purpose,
                    "scheduled_slot": slot,
                }
            }
        }
    }


@pytest.fixture
def actual_job(tmp_path, monkeypatch):
    with isolated_update_environment(tmp_path, monkeypatch) as environment:
        yield environment


@contextmanager
def isolated_update_environment(
    tmp_path,
    monkeypatch,
    *,
    substitute_upstream=True,
    old_run_root=None,
    observe_sql=None,
):
    lake, staging = roots(tmp_path)
    counts = {"dates": [], "types": [], "aggregate": [], "initialization": []}

    class CountingConnection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, parameters=None):
            if observe_sql is not None:
                observe_sql(sql)
            if old_run_root is not None:
                query = sql + repr(parameters)
                assert all(
                    str(old_run_root / part) not in query
                    for part in ("source", "candidates")
                )
            if "min(CAST(try_strptime" in sql:
                counts["aggregate"].append(parameters)
            if "parquet_schema" in sql and "trade_date" in sql and "ts_code" in sql:
                counts["types"].append(parameters)
            if parameters is None:
                return self.conn.execute(sql)
            return self.conn.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self.conn, name)

    class IsolatedDuckDB(DuckDBResource):
        @contextmanager
        def connect(self):
            with connection(tmp_path) as conn:
                yield CountingConnection(conn)

    class IsolatedLake(LakeRootResource):
        def ensure_available_for_run(self):
            assert self.root() == lake

    monkeypatch.setattr(asset, "DEFAULT_LAKE_STAGING_ROOT", staging)
    monkeypatch.setattr(
        asset,
        "_now",
        lambda: datetime.combine(DAY, time(20), ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE)),
    )
    resolve_initialization = (
        asset.initialization.resolve_stk_factor_pro_bootstrap_context
    )

    def initialization(instance, conn, **kwargs):
        counts["initialization"].append(kwargs["run_input"].purpose)
        assert kwargs["run_input"].purpose == "bootstrap_supplement"
        return resolve_initialization(instance, conn, **kwargs)

    monkeypatch.setattr(
        asset.initialization, "resolve_stk_factor_pro_bootstrap_context", initialization
    )
    # These job tests substitute upstream status and the two-column HTTP probe.
    # Files use producer schemas; native bindings and HTTP are tested separately.
    monkeypatch.setattr(
        asset.ConfigurationLoader,
        "load_configuration",
        lambda: ConfigurationSnapshot("isolated-token", "http://127.0.0.1:1"),
    )
    monkeypatch.setattr(
        asset,
        "probe_stk_factor_pro_source",
        lambda *a, **k: SimpleNamespace(ready=True),
    )
    if substitute_upstream:
        # Historical repair keeps the same upstream gate, now referenced directly.
        monkeypatch.setattr(
            upstream_readiness,
            "raw_tushare_adj_factor_ready_for_trade_date",
            lambda *_: SimpleNamespace(ready=True),
        )

        def ready_upstream(
            instance, *, target_trade_date, previous_trade_date, known_pg
        ):
            known_pg[("suspend_readiness", target_trade_date)] = SimpleNamespace(
                ready=True
            )
            return SimpleNamespace(ready=True, reason="")

        monkeypatch.setattr(
            asset.readiness, "read_stk_factor_pro_upstream_status", ready_upstream
        )
        monkeypatch.setattr(
            asset,
            "suspend_d_ready_for_trade_date",
            lambda *_: SimpleNamespace(ready=True),
        )
    defs = dg.Definitions(
        assets=[asset.stk_factor_pro],
        jobs=[raw_tushare_stk_factor_pro_update_job],
        resources={
            "lake_root": IsolatedLake(root_path=str(lake)),
            "duckdb": IsolatedDuckDB(),
        },
    )

    def source(rows, day=DAY):
        downloader = Downloader(result(rows, day=day))
        monkeypatch.setattr(
            asset.download.TushareDownloader, "load", lambda: downloader
        )
        return downloader

    with _isolated_instance(tmp_path) as instance:
        read_dates = instance.get_materialized_partitions

        def counted_dates(asset_key, **kwargs):
            if asset_key == asset._RAW:
                counts["dates"].append(asset_key)
            return read_dates(asset_key, **kwargs)

        monkeypatch.setattr(instance, "get_materialized_partitions", counted_dates)
        instance.add_dynamic_partitions(
            C.STK_FACTOR_PRO_PARTITIONS,
            [
                str(d)
                for d in (
                    FIRST,
                    UNMATERIALIZED,
                    PREVIOUS,
                    DAY,
                )
            ],
        )
        yield (
            instance,
            defs.resolve_job_def(C.STK_FACTOR_PRO_UPDATE_JOB_NAME),
            source,
            lake,
            staging,
            counts,
        )


def input_files(tmp_path, lake, *, changed, codes=(A, B), seed_history=False):
    with connection(tmp_path) as conn:
        upstream(conn, lake, (FIRST, UNMATERIALIZED, PREVIOUS, DAY), codes=codes)
        write_factor_file(conn, lake, PREVIOUS, tuple((code, 1) for code in codes))
        write_factor_file(
            conn,
            lake,
            DAY,
            tuple((code, 2 if code in changed else 1) for code in codes),
        )
        if seed_history:
            # Complete Raw producer contract is needed now that complete days may
            # proceed to historical publication, rather than stop at partial coverage.
            for day, existing in (
                (FIRST, (A,)),
                (PREVIOUS, (A, B)),
                (UNMATERIALIZED, (B,)),
            ):
                path = raw_stk_factor_pro_path(lake, str(day))
                path.parent.mkdir(parents=True, exist_ok=True)
                frame = candidates.build_stk_factor_pro_raw_batch(
                    rows=tuple(row(code, day.strftime("%Y%m%d")) for code in existing),
                    source="http",
                    source_fields=NAMES,
                    expected_dates=(day,),
                )
                conn.register("fixture_history", frame)
                conn.execute("COPY fixture_history TO ? (FORMAT PARQUET)", [str(path)])
                conn.unregister("fixture_history")


def test_actual_job_queries_dates_and_two_keys_once_then_reuses_starts(
    tmp_path, monkeypatch, actual_job
):
    instance, job, set_source, lake, _, counts = actual_job
    input_files(tmp_path, lake, changed=(A, B), seed_history=True)
    for day in (FIRST, PREVIOUS):
        instance.report_runless_asset_event(
            dg.AssetMaterialization(asset._RAW, partition=str(day))
        )
    for expected_calls in ((1, 1, 1), (0, 0, 0)):
        for calls in counts.values():
            calls.clear()
        downloader = set_source((row(A), row(B)))
        remote = HistoryDownloader(
            {
                A: (row(A, day="20261013"), row(A, day="20261015"), row(A)),
                B: (row(B, day="20261015"), row(B)),
            }
        )

        class CombinedDownloader:
            daily = downloader
            history = remote

            def download(self, task, **kwargs):
                return (
                    self.daily if task.mode is DownloadMode.BY_POINT else self.history
                ).download(task, **kwargs)

        monkeypatch.setattr(
            asset.download.TushareDownloader, "load", CombinedDownloader
        )
        completed = job.execute_in_process(
            instance=instance,
            partition_key=str(DAY),
            run_config=config(),
            raise_on_error=False,
        )
        assert completed.success, completed.failure_data_for_node("stk_factor_pro")
        assert len(downloader.calls) == 1 and downloader.closed
        assert (
            tuple(len(counts[k]) for k in ("dates", "types", "aggregate"))
            == expected_calls
        )
        if expected_calls[0]:
            assert counts["aggregate"][0][-1] == [A, B]
            assert len(counts["types"][0][0]) == 2
        assert not counts["initialization"]
        facts = asset.readiness.read_stk_factor_pro_recorded_results(
            instance, target_trade_date=DAY, known_pg={}
        )
        assert facts.raw_coverage.missing_sample_codes == ()
        with connection(tmp_path) as conn:
            _, load = asset.history.read_stk_factor_pro_prior_history(
                conn,
                staging_root=actual_job[4],
                target=DAY,
                contract=asset._CONTRACT,
                prior=facts,
                known_records={},
            )
            _, ranges = load(facts.history_plan_ref)
        assert [(r.ts_code, r.start_date) for r in ranges] == [
            (A, FIRST),
            (B, PREVIOUS),
        ]


@pytest.mark.parametrize(
    "rows,ready,success,expected_events",
    [
        ((row(A), row(B)), True, True, 2),
        ((), True, False, 0),
        ((), False, True, 0),
    ],
)
def test_actual_job_no_start_lookup_without_changes(
    tmp_path, monkeypatch, actual_job, rows, ready, success, expected_events
):
    instance, job, set_source, lake, _, counts = actual_job
    input_files(tmp_path, lake, changed=())
    monkeypatch.setattr(
        asset.readiness,
        "read_stk_factor_pro_upstream_status",
        lambda *a, **k: SimpleNamespace(ready=ready, reason="测试未就绪"),
    )
    downloader = set_source(rows)
    completed = job.execute_in_process(
        instance=instance,
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert completed.success is success, completed.failure_data_for_node(
        "stk_factor_pro"
    )
    assert len(downloader.calls) == int(ready)
    assert len(completed.get_asset_materialization_events()) == expected_events
    assert len(completed.get_asset_check_evaluations()) == expected_events
    assert counts == {"dates": [], "types": [], "aggregate": [], "initialization": []}
    if not success:
        failure = completed.failure_data_for_node("stk_factor_pro").user_failure_data
        assert failure.metadata["goldenshare/retryable"].value is True
        assert "本次完整日源" in failure.metadata["goldenshare/summary"].value


def seed_first_raw(tmp_path, instance, lake, first_row):
    first_path = raw_stk_factor_pro_path(lake, str(FIRST))
    first_path.parent.mkdir(parents=True)
    with connection(tmp_path) as conn:
        frame = candidates.build_stk_factor_pro_raw_batch(
            rows=(first_row,),
            source="http",
            source_fields=NAMES,
            expected_dates=(FIRST,),
        )
        conn.register("fixture_day", frame)
        conn.execute("COPY fixture_day TO ? (FORMAT PARQUET)", [str(first_path)])
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset._RAW, partition=str(FIRST))
    )


def test_actual_daily_job_publishes_history_using_first_start_query(
    tmp_path, monkeypatch, actual_job
):
    instance, job, set_source, lake, staging, counts = actual_job
    input_files(tmp_path, lake, changed=(A,), codes=(A,))
    replay = saved_real_rows()
    remote = HistoryDownloader({A: replay[1:]})
    day_source = set_source((replay[-1],))

    class ReplayedDownloader:
        def download(self, task, **kwargs):
            source = day_source if task.mode is DownloadMode.BY_POINT else remote
            return source.download(task, **kwargs)

    monkeypatch.setattr(asset.download.TushareDownloader, "load", ReplayedDownloader)
    seed_first_raw(tmp_path, instance, lake, replay[1])
    executed = job.execute_in_process(
        instance=instance,
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert executed.success, executed.failure_data_for_node(
        "stk_factor_pro"
    ).error.to_string()
    assert tuple(len(counts[k]) for k in ("dates", "types", "aggregate")) == (1, 1, 1)
    assert len(day_source.calls) == len(remote.calls) == 1
    assert [session.rows for session in remote.sessions] == [4]
    assert remote.calls[0][0].object_ranges[0].time_range.start == str(FIRST)
    for day in (FIRST, UNMATERIALIZED, PREVIOUS, DAY):
        assert raw_stk_factor_pro_path(lake, str(day)).is_file()
        assert silver_stock_factor_pro_path(lake, str(day)).is_file()
    facts = asset.readiness.read_stk_factor_pro_recorded_results(
        instance, target_trade_date=DAY, known_pg={}
    )
    assert facts.raw_coverage.complete is True
    assert len(facts.successful_publication_refs) == 1
    assert not facts.pending_plan_refs
    assert not (
        asset.stk_factor_pro_run_staging_root(staging, executed.run_id, str(DAY))
        / "source/day"
    ).exists()


@pytest.mark.parametrize("revised_day", [DAY, PREVIOUS], ids=["T", "P"])
def test_same_night_revision_retries_the_whole_range_until_source_catches_up(
    tmp_path, monkeypatch, revised_day
):
    queries = []
    with isolated_update_environment(
        tmp_path, monkeypatch, observe_sql=queries.append
    ) as environment:
        instance, job, set_source, lake, staging, _ = environment
        replay = saved_real_rows()[1:]
        monkeypatch.setattr(
            asset,
            "_now",
            lambda: datetime.combine(DAY, time(21), ZoneInfo("Asia/Shanghai")),
        )
        input_files(tmp_path, lake, changed=())
        seed_first_raw(tmp_path, instance, lake, replay[0])

        def run(slot):
            return job.execute_in_process(
                instance=instance,
                partition_key=str(DAY),
                run_config=config(slot=slot),
                raise_on_error=False,
            )

        def recorded():
            return asset.readiness.read_stk_factor_pro_recorded_results(
                instance, target_trade_date=DAY, known_pg={}
            )

        def with_factor(values, factor):
            # The column position comes from the source contract, the values below
            # are independent literals for the authoritative T/P comparison.
            index = NAMES.index("adj_factor")
            return (*values[:index], factor, *values[index + 1 :])

        set_source((with_factor(replay[-1], 1), row(B, adj_factor=1)))
        first = run(0)
        assert first.success
        assert recorded().raw_coverage.complete is True
        assert not recorded().pending_plan_refs

        with connection(tmp_path) as conn:
            write_factor_file(conn, lake, revised_day, ((A, 2), (B, 1)))
        t_factor, p_factor = (2, 1) if revised_day == DAY else (1, 2)

        class ReplayedDownloader:
            def __init__(self, daily, history):
                self.daily = daily
                self.history = history

            def download(self, task, **kwargs):
                source = (
                    self.daily if task.mode is DownloadMode.BY_POINT else self.history
                )
                return source.download(task, **kwargs)

        stale_t = (with_factor(replay[-2], p_factor), with_factor(replay[-1], p_factor))
        stale_p = (with_factor(replay[-2], t_factor), with_factor(replay[-1], t_factor))
        updated_without_t = (with_factor(replay[-2], p_factor),)
        for slot, tail in enumerate((stale_t, stale_p, updated_without_t), start=1):
            queries.clear()
            day_source = set_source(
                (with_factor(replay[-1], t_factor), row(B, adj_factor=1))
            )
            remote = HistoryDownloader({A: (*replay[:2], *tail)})
            replayed = ReplayedDownloader(day_source, remote)
            monkeypatch.setattr(
                asset.download.TushareDownloader,
                "load",
                lambda replayed=replayed: replayed,
            )
            executed = run(slot)
            assert len(day_source.calls) == len(remote.calls) == 1
            window = remote.calls[0][0].object_ranges[0].time_range
            assert (window.start, window.end) == (str(FIRST), str(DAY))
            assert (
                sum("authority USING (ts_code, trade_date)" in q for q in queries) == 1
            )
            assert sum("IS DISTINCT FROM factor.adj_factor" in q for q in queries) == 1
            assert any(
                "DROP TABLE IF EXISTS stk_factor_pro_history_source" in q
                for q in queries
            )
            root = asset.stk_factor_pro_run_staging_root(
                staging, executed.run_id, str(DAY)
            )
            plan = asset.history.read_stk_factor_pro_history_plan(
                root,
                expected_target=DAY,
                expected_run_id=executed.run_id,
                known_records={},
            )
            with connection(tmp_path) as conn:
                ranges = asset.history.read_stk_factor_pro_history_ranges(
                    conn, root=root, plan=plan, known_records={}
                )
            assert [(r.ts_code, r.start_date, r.end_date) for r in ranges] == [
                (A, FIRST, DAY)
            ]
            assert 7 in ranges[0].plan_reasons
            facts = recorded()
            assert facts.day_result_ref.run_id == executed.run_id
            assert facts.raw_coverage.complete is True
            published = executed.get_asset_materialization_events()
            checked = executed.get_asset_check_evaluations()
            if slot < 3:
                assert not executed.success
                failure = executed.failure_data_for_node(
                    "stk_factor_pro"
                ).user_failure_data
                assert failure.metadata["goldenshare/failure_phase"].value == "history"
                assert failure.metadata["goldenshare/retryable"].value is True
                assert failure.metadata["goldenshare/source_error_code"].value is None
                assert facts.pending_plan_refs == (facts.history_plan_ref,)
                assert len(published) == 2 and {
                    event.partition for event in published
                } == {str(DAY)}
                assert len(checked) == 2 and {check.partition for check in checked} == {
                    str(DAY)
                }
                assert not (root / "candidates/history").exists()
                assert not (root / "publication/history").exists()
            else:
                assert executed.success
                assert not facts.pending_plan_refs
                assert len(facts.successful_publication_refs) == 1
                assert len(published) == len(checked) == 8
                assert {event.partition for event in published} == {
                    str(FIRST),
                    str(UNMATERIALIZED),
                    str(PREVIOUS),
                    str(DAY),
                }


@pytest.mark.parametrize("probe_ready", [False, True])
def test_actual_initialization_first_start_uses_existing_import_dates(
    tmp_path, monkeypatch, actual_job, probe_ready
):
    instance, job, set_source, lake, staging, counts = actual_job
    day = INITIAL_DAY
    previous = date(2019, 10, 15)
    now = datetime.combine(day, time(10), ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE))
    monkeypatch.setattr(asset, "_now", lambda: now)
    monkeypatch.setattr(asset.initialization, "_now", lambda: now)
    known = {}
    with connection(tmp_path) as conn:
        args = setup_initial_import(
            conn,
            tmp_path,
            codes=(A,),
            known_records=known,
            date_results={},
            calendar=(
                ("SSE", previous, True, date(2019, 10, 14)),
                ("SSE", day, True, previous),
            ),
        )
        original = save_initial_date(conn, args, known_records=known)
        save_initial_summary(args, known_records=known)
        write_factor_file(conn, lake, previous, ((A, 1), (B, 1), (EXTRA, 1)))
        write_factor_file(conn, lake, day, ((A, 2), (B, 1), (EXTRA, 1)))
    approved = args["approval"]
    assert original.raw_rows == 1 and original.missing_count == 2
    instance.add_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS, [str(day)])
    path = asset.records.operation_path(
        staging, approved, f"coverage/{day}/result.json"
    )
    run_config = config(day, purpose="bootstrap_supplement", slot=None)
    run_config["ops"]["stk_factor_pro"]["config"].update(
        bootstrap_operation_id=approved.operation_id,
        expected_bootstrap_approval_digest=args["_approval_digest"],
        expected_bootstrap_date_result_digest=known[path][1],
    )
    downloader = set_source(
        tuple(row(code, day.strftime("%Y%m%d")) for code in (A, B, EXTRA)), day
    )
    remote = HistoryDownloader({A: (row(A, day.strftime("%Y%m%d"), adj_factor=2),)})

    class CombinedDownloader:
        def download(self, task, **kwargs):
            return (
                downloader if task.mode is DownloadMode.BY_POINT else remote
            ).download(task, **kwargs)

    monkeypatch.setattr(asset.download.TushareDownloader, "load", CombinedDownloader)
    if not probe_ready:
        monkeypatch.setattr(
            asset,
            "probe_stk_factor_pro_source",
            lambda *a, **k: SimpleNamespace(
                ready=False, coverage_counts=None, reason="源端缺码"
            ),
        )
    calculations = []
    calculate = asset.readiness.calculate_stk_factor_pro_coverage

    def counted(conn, **kwargs):
        calculations.append(kwargs["raw_relation"])
        return calculate(conn, **kwargs)

    monkeypatch.setattr(asset.readiness, "calculate_stk_factor_pro_coverage", counted)
    executed = job.execute_in_process(
        instance=instance,
        partition_key=str(day),
        run_config=run_config,
        raise_on_error=False,
    )
    assert executed.success, executed.failure_data_for_node(
        "stk_factor_pro"
    ).error.to_string()
    if not probe_ready:
        assert not downloader.calls and not remote.calls
        assert not executed.get_asset_materialization_events()
        assert not calculations
        assert tuple(len(counts[k]) for k in ("dates", "types", "aggregate")) == (
            0,
            0,
            0,
        )
        assert (
            asset.records.read_json(
                path, C.StkFactorProBootstrapDateCoverage, known_records={}
            )
            == original
        )
        return
    assert calculations == [candidates.DAY_SOURCE, candidates.RAW_EXPECTED]
    assert len(downloader.calls) == 1
    assert tuple(len(counts[k]) for k in ("dates", "types", "aggregate")) == (0, 1, 1)
    assert counts["initialization"] == ["bootstrap_supplement"]
    persisted = asset.records.read_json(
        path, C.StkFactorProBootstrapDateCoverage, known_records={}
    )
    assert (
        persisted.source_rows,
        persisted.raw_rows,
        persisted.silver_rows,
        persisted.missing_count,
    ) == (1, 3, 3, 0)
    assert persisted.missing_codes_ref is None
    recorded = asset.readiness.read_stk_factor_pro_recorded_results(
        instance, target_trade_date=day, known_pg={}
    )
    assert recorded.raw_coverage.complete is True
    assert recorded.raw_coverage.missing_codes_ref is None


@pytest.mark.parametrize(
    "problem,expected_calls",
    [
        ("missing", (1, 0, 0)),
        ("type", (1, 1, 0)),
        ("date", (1, 1, 1)),
    ],
)
def test_actual_job_refuses_shortening_untrustworthy_approved_history(
    tmp_path, actual_job, problem, expected_calls
):
    instance, job, set_source, lake, _, counts = actual_job
    input_files(tmp_path, lake, changed=(A,), seed_history=True)
    path = raw_stk_factor_pro_path(lake, str(FIRST))
    path.unlink()
    if problem != "missing":
        with connection(tmp_path) as conn:
            if problem == "type":
                conn.execute(
                    "COPY (SELECT '000001.SZ' AS ts_code, DATE '2026-10-13' AS trade_date) TO ? (FORMAT PARQUET)",
                    [str(path)],
                )
            else:
                write_keys(conn, lake, FIRST, (A,), raw_day="20261014")
    for day in (FIRST, PREVIOUS):
        instance.report_runless_asset_event(
            dg.AssetMaterialization(asset._RAW, partition=str(day))
        )
    downloader = set_source((row(A),))
    executed = job.execute_in_process(
        instance=instance,
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert not executed.success
    assert not downloader.calls and not executed.get_asset_materialization_events()
    assert (
        tuple(len(counts[k]) for k in ("dates", "types", "aggregate")) == expected_calls
    )


def test_manual_date_precheck_then_native_reexecution_reads_original_date(
    tmp_path, monkeypatch, actual_job
):
    from dagster._core.definitions.job_base import InMemoryJob
    from dagster._core.execution.api import execute_run

    instance, job, set_source, lake, _, counts = actual_job
    input_files(tmp_path, lake, changed=())
    with connection(tmp_path) as conn:
        write_factor_file(conn, lake, UNMATERIALIZED, ((A, 1), (B, 1)))
    run_config = config(PREVIOUS, execution_day=DAY, purpose="manual_date", slot=None)
    downloader = set_source((row(A, "20261015"), row(B, "20261015")), PREVIOUS)
    monkeypatch.setattr(
        asset.readiness,
        "read_stk_factor_pro_upstream_status",
        lambda *a, **k: SimpleNamespace(ready=False, reason="等待上游"),
    )
    parent = job.execute_in_process(
        instance=instance,
        partition_key=str(PREVIOUS),
        run_config=run_config,
        raise_on_error=False,
    )
    assert parent.success and not downloader.calls
    monkeypatch.setattr(
        asset.readiness,
        "read_stk_factor_pro_upstream_status",
        lambda *a, **k: SimpleNamespace(ready=True),
    )
    monkeypatch.setattr(
        asset,
        "_now",
        lambda: datetime.combine(
            date(2026, 10, 19), time(10), ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE)
        ),
    )
    parent_run = instance.get_run_by_id(parent.run_id)
    child = instance.create_run_for_job(
        job,
        parent_run_id=parent.run_id,
        root_run_id=parent.run_id,
        tags=parent_run.tags,
        run_config=parent_run.run_config,
    )
    executed = execute_run(InMemoryJob(job), child, instance, raise_on_error=False)
    assert executed.success
    assert len(downloader.calls) == 1
    assert downloader.calls[0][0].points == (str(PREVIOUS),)
    assert raw_stk_factor_pro_path(lake, str(PREVIOUS)).is_file()
    assert not raw_stk_factor_pro_path(lake, str(DAY)).is_file()
    assert all(not calls for calls in counts.values())


def test_incomplete_asset_selection_stops_before_io(actual_job):
    instance, job, set_source, _lake, _staging, counts = actual_job
    downloader = set_source(())
    executed = job.execute_in_process(
        instance=instance,
        partition_key=str(DAY),
        run_config=config(),
        asset_selection=[asset._RAW],
        raise_on_error=False,
    )
    assert not executed.success
    assert not downloader.calls and all(not calls for calls in counts.values())
    error = executed.failure_data_for_node("stk_factor_pro").user_failure_data
    assert "必须同时选择" in error.metadata["goldenshare/summary"].value


def test_missing_persisted_start_stops_before_the_download(
    tmp_path, monkeypatch, actual_job
):
    instance, job, set_source, lake, _, counts = actual_job
    input_files(tmp_path, lake, changed=())
    downloader = set_source((row(A), row(B)))
    existing = instance.get_records_for_run

    def cannot_read_start(run_id, **kwargs):
        if kwargs.get(
            "of_type"
        ) == dg.DagsterEventType.ASSET_OBSERVATION and not kwargs.get("ascending"):
            return SimpleNamespace(records=())
        return existing(run_id, **kwargs)

    monkeypatch.setattr(instance, "get_records_for_run", cannot_read_start)
    executed = job.execute_in_process(
        instance=instance,
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert not executed.success and not downloader.calls
    assert not executed.get_asset_materialization_events()
    assert all(not calls for calls in counts.values())
    assert (
        "start观察未持久化"
        in executed.failure_data_for_node("stk_factor_pro").error.message
    )
