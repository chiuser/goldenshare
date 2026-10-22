"""Memory transport uses independent literals, never formal Basic files.

The window adapter tests replace only event/file evidence collection, and test
the actual cache seeding/get path. They do not claim six-rule file acceptance.
The separate completion regression covers physical file/evidence acceptance.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

import orchestrator.defs.asset_guards.etf_adj_factor_history_completion as completion
import orchestrator.defs.asset_guards.etf_daily_lake_readiness as readiness
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    silver_etf_basic_snapshot_path,
)
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_SOURCE_COLUMNS,
    build_etf_basic_silver_snapshot_reference,
    compute_etf_basic_silver_content_hash,
    compute_etf_basic_snapshot_hash,
)
from orchestrator.defs.run_contracts.etf_daily import ETF_FACTOR_COMPLETION_METADATA_KEY

SCOPE = json.loads(
    (
        Path(__file__).parent / "fixtures/etf_adj_factor_history_completion_scope.json"
    ).read_text()
)
DAYS = tuple(sorted(SCOPE["additions"]))


def _target_hash(targets):
    # Literal expected target sets are independent of the production classifier.
    return hashlib.sha256(
        json.dumps(
            targets, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()


@pytest.fixture
def memory_basic(tmp_path):
    # Real producer: assets/etf_basic.py:_etf_basic_silver_select_sql, 14 fields,
    # DATE setup/list dates and DECIMAL(12,6) fee. This is synthetic Silver input.
    first = dict(
        zip(
            ETF_BASIC_SOURCE_COLUMNS,
            (
                "510330.SH",
                "literal-A",
                None,
                "literal-A",
                None,
                None,
                date(2019, 12, 1),
                date(2020, 1, 1),
                "L",
                "SH",
                None,
                None,
                Decimal("0.500000"),
                None,
            ),
            strict=True,
        )
    )
    second = {
        **first,
        "ts_code": "561530.SH",
        "csname": "literal-B",
        "cname": "literal-B",
        "list_date": date(2026, 9, 4),
    }
    snapshots = ((first, second), ({**first, "list_status": "D"}, dict(second)))
    root = tmp_path / "lake"
    references = {}
    with duckdb.connect() as connection:
        cache = completion.CompletionBasicCache(connection, root, allow_full_read=False)
        for index, rows in enumerate(snapshots):
            raw_rows = tuple(
                {
                    key: value.strftime("%Y%m%d")
                    if isinstance(value, date)
                    else float(value)
                    if isinstance(value, Decimal)
                    else value
                    for key, value in row.items()
                }
                for row in rows
            )
            raw_hash = compute_etf_basic_snapshot_hash(raw_rows)
            for day in (*DAYS, "2026-10-21"):
                targets = []
                if index == 0:
                    targets.append(
                        {
                            "ts_code": "510330.SH",
                            "list_date": "2020-01-01",
                            "exchange": "SH",
                        }
                    )
                if day >= "2026-09-04":
                    targets.append(
                        {
                            "ts_code": "561530.SH",
                            "list_date": "2026-09-04",
                            "exchange": "SH",
                        }
                    )
                reference = build_etf_basic_silver_snapshot_reference(
                    raw_snapshot_hash=raw_hash,
                    silver_content_hash=compute_etf_basic_silver_content_hash(rows),
                    raw_uri=str(raw_etf_basic_snapshot_path(root, raw_hash)),
                    silver_uri=str(silver_etf_basic_snapshot_path(root, raw_hash)),
                    raw_observed_at="2026-09-03T20:00:00+08:00",
                    silver_observed_at="2026-09-03T20:01:00+08:00",
                    eligibility_as_of=day,
                    requestable_code_count=len(targets),
                    requestable_code_hash=_target_hash(targets),
                )
                cache.seed(reference, rows)
                cache.get(reference)
                references[index, day] = reference
        prepared = completion.PreparedCompletionBasic.from_cache(cache)
    return SimpleNamespace(
        root=root, prepared=prepared, references=references, source_cache=cache
    )


@pytest.fixture
def no_basic_reads(monkeypatch):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("unexpected_complete_basic_read")

    monkeypatch.setattr(completion, "audit_etf_basic_silver_snapshot", forbidden)
    return attempts


def _refs(fixture, day):
    return (fixture.references[1, "2026-10-21"], fixture.references[0, day])


def test_prepared_contents_are_copied_and_immutable(memory_basic):
    f = memory_basic
    key = next(iter(f.prepared.snapshots))
    original_name = f.prepared.snapshots[key][0]["csname"]
    f.source_cache.snapshots[key][0][0]["csname"] = "source-cache-later-change"
    assert f.prepared.snapshots[key][0]["csname"] == original_name
    with pytest.raises(TypeError):
        f.prepared.snapshots[key][0]["csname"] = "mutate-prepared"
    with pytest.raises(TypeError):
        del f.prepared.snapshots[key]


def test_prepared_basic_uses_independent_connections_and_validates_each_reference(
    memory_basic,
    no_basic_reads,
):
    f = memory_basic
    connections = []
    for day in DAYS[:2]:
        with duckdb.connect() as connection:
            connections.append(connection)
            cache = f.prepared.seed_cache(connection, f.root, _refs(f, day))
            assert not cache.allow_full_read
            assert len(cache.snapshots) == 2 and len(cache.references) == 2
            rows = connection.execute(cache.get(_refs(f, day)[1])).fetchall()
            assert len(rows) == 2
            assert type(rows[0][6]) is date
            assert type(rows[0][12]) is Decimal
        with pytest.raises(duckdb.ConnectionException):
            connection.execute("SELECT 1")
    assert connections[0] is not connections[1]
    assert no_basic_reads == []


@pytest.mark.parametrize("value", [None, {}, [], object()])
def test_maintenance_missing_prepared_input_cannot_be_daily_default(
    value, no_basic_reads
):
    with pytest.raises(TypeError, match="completion_prepared_basic_required"):
        completion.require_prepared_basic(value)
    assert no_basic_reads == []


@pytest.mark.parametrize("bad_input", ["reference", "snapshot", "content"])
def test_wrong_prepared_input_stops_before_complete_read(
    memory_basic,
    no_basic_reads,
    bad_input,
):
    f = memory_basic
    prepared = f.prepared
    references = _refs(f, DAYS[0])
    if bad_input == "reference":
        # Another valid dated reference, deliberately removed from the approved set.
        prepared = completion.PreparedCompletionBasic(
            prepared.snapshots,
            {
                key: value
                for key, value in prepared.references.items()
                if key != references[1].reference_fingerprint
            },
        )
    else:
        snapshots = {
            key: tuple(dict(row) for row in rows)
            for key, rows in prepared.snapshots.items()
        }
        key = next(iter(snapshots))
        if bad_input == "snapshot":
            del snapshots[key]
        else:
            snapshots[key][0]["csname"] = "changed-after-original-audit"
        prepared = completion.PreparedCompletionBasic(snapshots, prepared.references)
    with duckdb.connect() as connection, pytest.raises(ValueError):
        prepared.seed_cache(connection, f.root, references)
    assert no_basic_reads == []


def test_strict_cache_rejects_unseeded_but_daily_default_keeps_existing_read_path(
    memory_basic,
    no_basic_reads,
):
    f = memory_basic
    with duckdb.connect() as connection:
        strict = completion.CompletionBasicCache(
            connection, f.root, allow_full_read=False
        )
        with pytest.raises(
            ValueError, match="completion_prepared_basic_reference_not_seeded"
        ):
            strict.get(_refs(f, DAYS[0])[0])
        assert no_basic_reads == []
        ordinary = completion.CompletionBasicCache(connection, f.root)
        with pytest.raises(AssertionError, match="unexpected_complete_basic_read"):
            ordinary.get(_refs(f, DAYS[0])[0])
    assert len(no_basic_reads) == 1


def test_strict_cache_rejects_unapproved_date_even_when_snapshot_is_seeded(
    memory_basic,
    no_basic_reads,
):
    f = memory_basic
    with duckdb.connect() as connection:
        cache = f.prepared.seed_cache(connection, f.root, _refs(f, DAYS[0]))
        same_snapshot_other_day = f.references[0, DAYS[1]]
        with pytest.raises(
            ValueError, match="completion_prepared_basic_reference_not_seeded"
        ):
            cache.get(same_snapshot_other_day)
        assert len(cache.references) == 2
    assert no_basic_reads == []


def test_two_real_checks_then_three_readiness_windows_and_required_recheck(
    memory_basic,
    no_basic_reads,
    monkeypatch,
):
    f = memory_basic
    observed = []
    partitions = dg.StaticPartitionsDefinition(list(DAYS))

    @dg.asset(partitions_def=partitions)
    def factor_target():
        pytest.fail("writer must not execute")

    @dg.asset_check(
        asset=factor_target,
        required_resource_keys={"prepared_basic"},
        partitions_def=partitions,
        blocking=True,
    )
    def transport(context):
        prepared = completion.require_prepared_basic(context.resources.prepared_basic)
        assert prepared is f.prepared
        with duckdb.connect() as connection:
            cache = prepared.seed_cache(
                connection, f.root, _refs(f, context.partition_key)
            )
            assert len(cache.references) == 2
        observed.append(context.partition_key)
        return dg.AssetCheckResult(passed=True)

    definitions = dg.Definitions(
        assets=[factor_target],
        asset_checks=[transport],
        jobs=[
            dg.define_asset_job(
                "transport", selection=dg.AssetSelection.assets(factor_target)
            )
        ],
        resources={
            "prepared_basic": dg.ResourceDefinition.hardcoded_resource(f.prepared)
        },
    )
    job = definitions.resolve_job_def("transport").get_subset(
        asset_selection=set(),
        asset_check_selection=set(transport.check_keys),
    )
    with dg.DagsterInstance.ephemeral() as instance:
        results = [
            job.execute_in_process(instance=instance, partition_key=day)
            for day in DAYS[:2]
        ]
        assert all(result.success for result in results)
        assert results[0].run_id != results[1].run_id
        missing = job.execute_in_process(
            instance=instance,
            partition_key=DAYS[0],
            raise_on_error=False,
            resources={
                "prepared_basic": dg.ResourceDefinition.hardcoded_resource(None)
            },
        )
        assert not missing.success and not missing.get_asset_check_evaluations()
    assert observed == list(DAYS[:2])

    # Isolate event/file acceptance only; actual seed/get and dated-reference
    # validation remain live across the three bounded readiness window calls.
    plan = SimpleNamespace(
        plan_hash="synthetic-window-adapter",
        basic_reference=_refs(f, DAYS[0])[0].model_dump(mode="json"),
        file=lambda day: SimpleNamespace(
            original_metadata={
                "goldenshare/basic_reference": _refs(f, day)[1].model_dump(mode="json"),
            }
        ),
    )
    monkeypatch.setattr(
        readiness, "EtfFactorCompletionPlan", SimpleNamespace(from_dict=lambda _: plan)
    )
    monkeypatch.setattr(
        readiness,
        "_latest_materializations",
        lambda **kwargs: (
            {
                day: SimpleNamespace(
                    storage_id=i + 1,
                    run_id="synthetic",
                    metadata={
                        ETF_FACTOR_COMPLETION_METADATA_KEY: {},
                    },
                )
                for i, day in enumerate(kwargs["trade_dates"])
            },
            1,
        ),
    )
    monkeypatch.setattr(readiness, "load_factor_history_evidence", lambda *args: {})
    monkeypatch.setattr(
        readiness,
        "load_completion_evidence",
        lambda **kwargs: completion.CompletionEvidence(
            {day: () for day in kwargs["days"]},
        ),
    )

    def verify_cache(**kwargs):
        day = kwargs["trade_date"]
        cache = kwargs["completion_cache"]
        assert not cache.allow_full_read
        assert _refs(f, day)[1].reference_fingerprint in cache.references
        assert kwargs["connection"].execute(cache.get(_refs(f, day)[1])).fetchall()
        return readiness.EtfDailyPartitionReadiness(
            asset_key="silver_etf_adj_factor",
            trade_date=day,
            ready=True,
            materialized=True,
            file_exists=True,
            checks_passed=True,
            reason_code="ready",
            row_count=2,
            content_hash=None,
        )

    monkeypatch.setattr(readiness, "_silver_status", verify_cache)
    for window in [DAYS[:10], DAYS[10:20], DAYS[20:], DAYS[:1]]:
        with duckdb.connect() as connection:
            result = readiness.batch_etf_adj_factor_silver_lake_readiness(
                instance=SimpleNamespace(event_log_storage=None),
                connection=connection,
                lake_root=f.root,
                trade_dates=window,
                prepared_basic=f.prepared,
            )
            assert all(status.ready for status in result.statuses)
    assert no_basic_reads == []


def test_completion_audit_reads_raw_and_silver_only_once(
    completion_files, no_basic_reads
):
    # The physical fixture and expected business rows are defined below using
    # the already audited producer fixture; only the SQL call count is new here.
    f, prepared = completion_files
    calls = []

    class CountedConnection:
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, *args, **kwargs):
            calls.append(sql)
            return self.inner.execute(sql, *args, **kwargs)

    with duckdb.connect() as inner:
        connection = CountedConnection(inner)
        refs = [f.new, f.old]
        cache = prepared.seed_cache(connection, f.lake, refs)
        result = completion.audit_completion_file(
            connection=connection,
            lake_root=f.lake,
            plan=f.plan,
            trade_date="2026-09-15",
            basic_cache=cache,
            relation_sql=f"SELECT * FROM read_parquet('{f.candidate}', hive_partitioning=false)",
        )
        assert not result.errors and result.relation.row_count == 16
        assert (
            inner.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE table_name LIKE 'completion_actual_%' OR table_name LIKE 'completion_raw_%'"
            ).fetchone()[0]
            == 0
        )
    scans = [sql for sql in calls if "read_parquet(" in sql]
    assert len(scans) == 2
    assert all(sql.startswith("CREATE TEMP TABLE") for sql in scans)
    assert sum(sql.count("read_parquet(") for sql in calls) == 2
    assert no_basic_reads == []


def test_maintenance_readiness_missing_completion_evidence_never_uses_daily_path(
    completion_files,
    no_basic_reads,
):
    f, prepared = completion_files
    # This is the accepted original target, without an appended completion
    # record. Maintenance must reject it instead of taking the daily I/O path.
    with duckdb.connect() as connection:
        result = readiness.batch_etf_adj_factor_silver_lake_readiness(
            instance=f.instance,
            connection=connection,
            lake_root=f.lake,
            trade_dates=["2026-09-15"],
            prepared_basic=prepared,
        )
    assert not result.statuses[0].ready
    assert no_basic_reads == []


@pytest.fixture
def completion_files(tmp_path, monkeypatch):
    # Reuse independently specified accepted rows from the completion regression.
    # Redirect its resource before it creates inputs; never use default Lake temp.
    from contextlib import contextmanager

    from orchestrator.defs.resources import DuckDBResource
    from tests.test_etf_adj_factor_history_completion import completion as fixture

    @contextmanager
    def isolated_connect(self):
        with duckdb.connect() as connection:
            yield connection

    monkeypatch.setattr(DuckDBResource, "connect", isolated_connect)
    generator = fixture.__wrapped__(tmp_path)
    f = next(generator)
    # Existing fixture is tiny and exclusively under tmp_path. Reading it here
    # constructs the already-audited in-memory input before the no-read sentinel.
    with duckdb.connect() as connection:
        cache = completion.CompletionBasicCache(connection, f.lake)
        cache.get(f.new)
        cache.get(f.old)
        prepared = completion.PreparedCompletionBasic.from_cache(cache)
    yield f, prepared
    next(generator, None)
