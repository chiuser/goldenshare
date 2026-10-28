"""Silver event admission follows the native check's scope and committed inputs.

Source facts: stock_period_silver.materialization_metadata and the existing
literal 21-column producer fixture. Expected refusal and dates are independent
of the scope/admission helper; only owned temporary files/instances are used.
"""

import dagster as dg
import pytest

from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.bootstrap import stock_period_silver_cli as cli
from orchestrator.defs.checks import stock_period_silver_checks as checks
from orchestrator.defs.io.stock_period_silver import read_json, run_directory
from orchestrator.defs.run_contracts.stock_period_silver import (
    asset_name,
    materialization_scope,
    validate_materialization_scope,
)
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit fixture re-export.
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414 -- Explicit fixture re-export.
)
from tests.test_stock_period_silver_execution import execute


def completed_item(fixture, freq):
    execute(fixture)
    execution = silver.load_execution(
        fixture["lake"], fixture["staging"], fixture["run_id"]
    )
    identity = execution["identity"]
    unit = next(u for u in identity["units"] if u["freq"] == freq)
    item = read_json(
        silver.checkpoint_path(run_directory(fixture["staging"], fixture["run_id"]), unit)
    )
    return item, identity


@pytest.mark.parametrize("freq", ["week", "month"])
def test_first_report_refuses_missing_asof_before_green(period_fixture, freq):
    from types import SimpleNamespace

    f = period_fixture
    item, identity = completed_item(f, freq)
    metadata = silver.materialization_metadata(item, identity)
    del metadata["goldenshare/silver_asof"]
    asset = dg.AssetKey(asset_name(freq))
    with dg.DagsterInstance.ephemeral() as instance:
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=asset, partition=item["period"], metadata=metadata
            )
        )
        with pytest.raises(ValueError, match="scope_missing"):
            checks.evaluate(
                SimpleNamespace(instance=instance, partition_key=item["period"]),
                f["lake"], f["staging"], freq, "file_contract",
            )
        before = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset), limit=10
        ).records
        with pytest.raises(ValueError, match="checks_not_ready"):
            cli.run_reporting(
                instance, lambda ctx: cli.report_file(instance, ctx, item, identity)
            )
        assert instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset), limit=10
        ).records == before
        from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
            batch_event_evidence,
        )

        evidence = batch_event_evidence(instance, freq, [item["period"]], include_raw=False)
        assert evidence[(asset.to_user_string(), item["period"])]["checks"] == {}


@pytest.mark.parametrize("freq,period,asof,lower", [
    ("week", "2014-01-03", "2014-01-01", "2014-01-01"),
    ("week", "2026-10-23", "2026-10-22", "2014-01-01"),
    ("month", "2026-10", "2026-10-22", "2014-01-01"),
    ("week", "2020-04-03", "2026-10-16", "2014-01-01"),
    ("month", "2020-02", "2026-10-16", "2014-01-01"),
])
def test_scope_preserves_period_coordinates_and_history(freq, period, asof, lower):
    assert validate_materialization_scope(freq, period, asof, lower) == (asof, lower)


@pytest.mark.parametrize("freq,period", [("week", "2026-10-23"), ("month", "2026-10")])
@pytest.mark.parametrize("asof,lower", [
    (None, "2014-01-01"), ("", "2014-01-01"),
    ("20261023", "2014-01-01"), (20261023, "2014-01-01"),
    ("2026-02-30", "2014-01-01"), ("2026-10-23", None),
    ("2026-10-23", "2026-10-24"), ("2026-09-01", "2014-01-01"),
    ("2026-10-23", "2026-11-01"),
])
def test_scope_rejects_invalid_or_outside_dates(freq, period, asof, lower):
    with pytest.raises(ValueError):
        validate_materialization_scope(freq, period, asof, lower)


def test_update_date_never_falls_back_to_batch_maximum():
    identity = {"intent": "update", "asof": "2026-10-23", "lower": "2014-01-01"}
    record = {"freq": "week", "period": "2020-04-03", "asof": "2026-10-20"}
    assert materialization_scope(record, identity) == ("2026-10-20", "2014-01-01")
    for bad in ({k: v for k, v in record.items() if k != "asof"}, {**record, "asof": None}):
        with pytest.raises(ValueError, match="scope_missing"):
            materialization_scope(bad, identity)
    assert materialization_scope(
        {k: v for k, v in record.items() if k != "asof"},
        {"asof": "2026-10-16", "lower": "2014-01-01"},
    ) == ("2026-10-16", "2014-01-01")
    with pytest.raises(ValueError, match="scope_invalid"):
        materialization_scope(record, {"asof": "2026-10-16", "lower": "2014-01-01"})


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("fault", ["wrong_asof", "float_rows", "bool_rows", "version", "missing_lower"])
def test_first_report_refuses_conflicting_current_metadata(period_fixture, freq, fault):
    f = period_fixture
    item, identity = completed_item(f, freq)
    metadata = silver.materialization_metadata(item, identity)
    if fault == "wrong_asof":
        metadata["goldenshare/silver_asof"] = "2026-10-15"
    elif fault == "float_rows":
        metadata["dagster/row_count"] = float(item["rows"])
    elif fault == "bool_rows":
        metadata["dagster/row_count"] = True
    elif fault == "version":
        metadata["goldenshare/period_file_version"] = dg.MetadataValue.json("bad")
    else:
        del metadata["goldenshare/silver_lower"]
    asset = dg.AssetKey(asset_name(freq))
    with dg.DagsterInstance.ephemeral() as instance:
        instance.report_runless_asset_event(dg.AssetMaterialization(
            asset_key=asset, partition=item["period"], metadata=metadata,
        ))
        before = instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=asset), limit=20).records
        with pytest.raises(ValueError, match="checks_not_ready"):
            cli.run_reporting(instance, lambda ctx: cli.report_file(instance, ctx, item, identity))
        assert instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=asset), limit=20).records == before


def test_last_bad_unit_prevents_all_first_batch_events(period_fixture):
    f = period_fixture
    execute(f)
    execution = silver.load_execution(f["lake"], f["staging"], f["run_id"])
    identity = execution["identity"]
    unit = identity["units"][-1]
    work = run_directory(f["staging"], f["run_id"])
    item = read_json(silver.checkpoint_path(work, unit))
    metadata = silver.materialization_metadata(item, identity)
    del metadata["goldenshare/silver_asof"]
    asset = dg.AssetKey(asset_name(unit["freq"]))
    with dg.DagsterInstance.ephemeral() as instance:
        instance.report_runless_asset_event(dg.AssetMaterialization(
            asset_key=asset, partition=item["period"], metadata=metadata,
        ))
        before = {freq: instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=dg.AssetKey(asset_name(freq))), limit=20
        ).records for freq in ("week", "month")}
        with pytest.raises(ValueError, match="checks_not_ready"):
            cli.run_reporting(instance, lambda ctx: cli.replay_events(
                f["lake"], f["staging"], f["run_id"], instance, ctx
            ))
        for freq, original in before.items():
            assert instance.fetch_materializations(dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(asset_name(freq))
            ), limit=20).records == original
        assert not (work / "events").exists()
        assert not (work / "events_complete.json").exists()


def test_first_batch_reads_by_frequency_and_rechecks_existing_receipts(period_fixture, monkeypatch):
    from orchestrator.defs.asset_guards import (
        stock_period_silver_readiness as readiness,
    )

    f = period_fixture
    execute(f)
    calls = []
    original = readiness.batch_event_evidence

    def batch(*args, **kwargs):
        calls.append((args[1], len(args[2])))
        return original(*args, **kwargs)

    monkeypatch.setattr(readiness, "batch_event_evidence", batch)
    with dg.DagsterInstance.ephemeral() as instance:
        monkeypatch.setattr(instance, "fetch_materializations", lambda *a, **k: pytest.fail("per-file fetch"))
        cli.run_reporting(instance, lambda ctx: cli.replay_events(
            f["lake"], f["staging"], f["run_id"], instance, ctx
        ))
        assert sorted(calls) == [("month", 3), ("month", 3), ("week", 3), ("week", 3)]
        calls.clear()
        cli.run_reporting(instance, lambda ctx: cli.replay_events(
            f["lake"], f["staging"], f["run_id"], instance, ctx
        ))
        assert sorted(calls) == [("month", 3), ("week", 3)]


def test_existing_receipt_cannot_hide_new_bad_materialization(period_fixture):
    f = period_fixture
    execute(f)
    work = run_directory(f["staging"], f["run_id"])
    execution = silver.load_execution(f["lake"], f["staging"], f["run_id"])
    identity = execution["identity"]
    unit = identity["units"][-1]
    item = read_json(silver.checkpoint_path(work, unit))
    asset = dg.AssetKey(asset_name(unit["freq"]))
    with dg.DagsterInstance.ephemeral() as instance:
        cli.run_reporting(instance, lambda ctx: cli.replay_events(
            f["lake"], f["staging"], f["run_id"], instance, ctx
        ))
        cp = work / "events" / unit["freq"] / (unit["period"] + ".json")
        before_cp = cp.read_bytes()
        metadata = silver.materialization_metadata(item, identity)
        del metadata["goldenshare/silver_asof"]
        instance.report_runless_asset_event(dg.AssetMaterialization(
            asset_key=asset, partition=item["period"], metadata=metadata,
        ))
        before = instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=asset), limit=20).records
        with pytest.raises(ValueError, match="checks_not_ready"):
            cli.run_reporting(instance, lambda ctx: cli.replay_events(
                f["lake"], f["staging"], f["run_id"], instance, ctx
            ))
        assert instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=asset), limit=20).records == before
        assert cp.read_bytes() == before_cp


@pytest.mark.parametrize("version", ["bad", [1], [1, 2, 128, 3, True], [1, 2, 128, 3, 4.0], [1, 2, 128, 3, -1]])
def test_readonly_metadata_rejects_invalid_file_version_without_stat(version, monkeypatch):
    from types import SimpleNamespace

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        require_silver_materialization,
    )
    from orchestrator.defs.io import stock_period_raw

    monkeypatch.setattr(stock_period_raw, "file_version", lambda *a: pytest.fail("metadata stat"))
    mat = SimpleNamespace(asset_materialization=dg.AssetMaterialization(
        asset_key="silver_stock_weekly", partition="2026-10-23", metadata={
            "dagster/uri": "/synthetic/part.parquet", "dagster/row_count": 1,
            "goldenshare/period_file_version": dg.MetadataValue.json(version),
            "goldenshare/silver_rule": "stock-period-silver@1",
            "goldenshare/silver_lower": "2014-01-01",
            "goldenshare/silver_asof": "2026-10-22",
        },
    ))
    with pytest.raises(ValueError, match="checks_not_ready"):
        require_silver_materialization(mat, "week")


@pytest.mark.parametrize("lower", ["2013-01-01", "2014-01-02"])
def test_readonly_and_preimage_keep_the_original_lower_contract(lower):
    from types import SimpleNamespace

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        require_silver_materialization,
    )

    mat = SimpleNamespace(asset_materialization=dg.AssetMaterialization(
        asset_key="silver_stock_weekly", partition="2026-10-23", metadata={
            "dagster/uri": "/synthetic/part.parquet", "dagster/row_count": 1,
            "goldenshare/period_file_version": dg.MetadataValue.json([1, 2, 128, 3, 4]),
            "goldenshare/silver_rule": "stock-period-silver@1",
            "goldenshare/silver_lower": lower,
            "goldenshare/silver_asof": "2026-10-21",
        },
    ))
    with pytest.raises(ValueError, match="checks_not_ready"):
        require_silver_materialization(mat, "week")
    record = {"freq": "week", "period": "2026-10-23", "rows": 1,
              "target": "/synthetic/part.parquet", "version": [1, 2, 128, 3, 5],
              "event_preimage": [1, 2, 128, 3, 4]}
    with pytest.raises(ValueError, match="checks_not_ready"):
        require_silver_materialization(mat, "week", record,
                                       {"asof": "2026-10-23", "lower": "2014-01-01"},
                                       allow_preimage=True)


@pytest.mark.parametrize("freq", ["week", "month"])
def test_update_last_wrong_unit_date_prevents_all_new_events(update_fixture, freq):
    from uuid import uuid4

    from tests.test_stock_period_silver_contracts import A

    f = update_fixture
    for row in f["state"]["rows"]:
        if row[0] == A and row[3] == freq:
            row[9:13] = ["19.1000", "19.5000", "19.0000", "19.2500"]
    reference = f["capture"](freq=freq, asof="2026-10-20")
    result = silver.build(f["lake"], f["staging"], str(uuid4()), freq=freq,
                          source_completion=reference, instance=f["instance"], emit=lambda _: None)
    execution = silver.load_execution(f["lake"], f["staging"], result["run_id"])
    identity = execution["identity"]
    unit = identity["units"][-1]
    work = run_directory(f["staging"], result["run_id"])
    item = read_json(silver.checkpoint_path(work, unit))
    metadata = silver.materialization_metadata(item, identity)
    assert metadata["goldenshare/silver_asof"] == "2026-10-20"
    metadata["goldenshare/silver_asof"] = "2026-10-19"
    asset = dg.AssetKey(asset_name(freq))
    instance = f["instance"]
    instance.report_runless_asset_event(dg.AssetMaterialization(
        asset_key=asset, partition=item["period"], metadata=metadata,
    ))
    before = instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=asset), limit=20).records
    with pytest.raises(ValueError, match="checks_not_ready"):
        cli.run_reporting(instance, lambda ctx: cli.replay_events(
            f["lake"], f["staging"], result["run_id"], instance, ctx
        ))
    assert instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=asset), limit=20).records == before
    assert not (work / "events").exists()
    assert not (work / "events_complete.json").exists()


@pytest.mark.parametrize("count", [2, 100])
def test_metadata_capacity_has_two_reads_without_file_access(tmp_path, monkeypatch, count):
    """Capacity only: real SDK events, literal metadata and an explicit stat seam."""
    from contextlib import contextmanager
    from datetime import date, timedelta

    import sqlalchemy as sa

    from orchestrator.defs.asset_guards import (
        stock_period_silver_readiness as readiness,
    )
    from tests.test_stock_period_check_evidence import evaluate

    version = [1, 2, 128, 3, 4]
    identity = {"run_id": "00000000-0000-0000-0000-000000000001", "asof": "2026-10-16",
                "lower": "2014-01-01", "references": {}, "reference_versions": {}}
    items = [{"freq": "week", "period": (date(2014, 1, 3) + timedelta(weeks=i)).isoformat(),
              "rows": 1, "version": version, "source_version": version,
              "target": str(tmp_path / "synthetic-silver" / str(i)),
              "source": str(tmp_path / "synthetic-raw" / str(i))} for i in range(count)]
    asset = dg.AssetKey("silver_stock_weekly")
    with dg.DagsterInstance.ephemeral() as instance:
        for item in items:
            # Independent literal facts required by the real metadata producer.
            instance.report_runless_asset_event(dg.AssetMaterialization(
                asset_key=asset, partition=item["period"], metadata={
                    "dagster/uri": item["target"], "dagster/row_count": 1,
                    "goldenshare/period_file_version": dg.MetadataValue.json(version),
                    "goldenshare/silver_rule": "stock-period-silver@1",
                    "goldenshare/silver_lower": "2014-01-01",
                    "goldenshare/silver_asof": "2026-10-16",
                },
            ))
        initial = readiness.batch_event_evidence(instance, "week", [i["period"] for i in items], include_raw=False)

        def seed(context):
            for item in items:
                evaluate(instance, context, readiness.check_names("week"),
                         initial[(asset.to_user_string(), item["period"])]["materialization"],
                         asset=asset, partition=item["period"])

        cli.run_reporting(instance, seed)
        original, reads = instance.event_log_storage.index_connection, []

        @contextmanager
        def counted():
            with original() as connection:
                class Proxy:
                    def execute(self, statement, *args, **kwargs):
                        sql = str(statement)
                        if isinstance(statement, sa.sql.Select) and (
                            "event_logs" in sql or "asset_check_executions" in sql
                        ):
                            reads.append(sql)
                        return connection.execute(statement, *args, **kwargs)

                    def __getattr__(self, name):
                        return getattr(connection, name)
                yield Proxy()

        allowed = {i[key] for i in items for key in ("target", "source")}

        def stat(path):
            assert str(path) in allowed
            return version

        monkeypatch.setattr(instance.event_log_storage, "index_connection", counted)
        monkeypatch.setattr(cli, "file_version", stat)
        monkeypatch.setattr(instance, "fetch_materializations", lambda *a, **k: pytest.fail("per-file fetch"))
        actual = cli.run_reporting(instance, lambda ctx: cli._report_files(instance, ctx, items, identity))
        assert len(actual) == count
        assert len(reads) == 2
        assert not any((tmp_path / name).exists() for name in ("synthetic-raw", "synthetic-silver"))


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("lower", ["2013-01-01", "2014-01-02"])
def test_native_and_reporting_share_the_fixed_lower(period_fixture, freq, lower):
    from types import SimpleNamespace

    f = period_fixture
    item, identity = completed_item(f, freq)
    metadata = silver.materialization_metadata(item, identity)
    metadata["goldenshare/silver_lower"] = lower
    with pytest.raises(ValueError, match="scope_invalid"):
        validate_materialization_scope(freq, item["period"], "2026-10-16", lower)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.report_runless_asset_event(dg.AssetMaterialization(
            asset_key=dg.AssetKey(asset_name(freq)), partition=item["period"], metadata=metadata,
        ))
        with pytest.raises(ValueError, match="scope_invalid"):
            checks.evaluate(SimpleNamespace(instance=instance, partition_key=item["period"]),
                            f["lake"], f["staging"], freq, "file_contract")
        with pytest.raises(ValueError, match="checks_not_ready"):
            cli.run_reporting(instance, lambda ctx: cli.report_file(instance, ctx, item, identity))


def test_legacy_bootstrap_source_metadata_does_not_block_first_update(update_fixture, monkeypatch):
    from uuid import uuid4

    from orchestrator.defs.io.stock_period_raw import file_version

    f = update_fixture
    execution = silver.load_execution(f["lake"], f["staging"], f["run_id"])
    identity = execution["identity"]
    unit = next(u for u in identity["units"] if u["freq"] == "week")
    item = read_json(silver.checkpoint_path(run_directory(f["staging"], f["run_id"]), unit))
    metadata = silver.materialization_metadata(item, identity)
    for key in ("goldenshare/silver_source_version", "goldenshare/silver_reference_versions"):
        del metadata[key]
    instance = f["instance"]
    instance.report_runless_asset_event(dg.AssetMaterialization(
        asset_key="silver_stock_weekly", partition=unit["period"], metadata=metadata,
    ))
    cli.run_reporting(instance, lambda ctx: cli.report_file(instance, ctx, item, identity))
    selected = []
    original = silver.select_period

    def tracked(con, source, freq, period, **kwargs):
        selected.append(period)
        return original(con, source, freq, period, **kwargs)

    monkeypatch.setattr(silver, "select_period", tracked)
    previous = file_version(unit["target"])
    result = silver.build(f["lake"], f["staging"], str(uuid4()), freq="week",
                          source_completion=f["base_reference"], instance=instance, emit=lambda _: None)
    assert result["totals"]["week"] == {"files": 3, "rows": 6}
    assert selected == ["2014-01-03"]
    assert file_version(unit["target"]) != previous
