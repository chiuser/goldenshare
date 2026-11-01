"""Opt-in replacement through the original jobs, using temporary real Parquet.

Prod fixtures follow prod_db/stk_mins.py's nine-column projection and the literal
five source times in cn_a_derived_minute_bars.py. Reference projections follow
the actual stock identity/daily/lifecycle and suspension producers. Only Prod
transport/completion and Lake mount checks are replaced; writers, SQL,
publication, original job selection and Raw/Silver checks execute unchanged.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import resources
from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    stk_mins_stock_code_set_hash,
)
from orchestrator.defs.assets import stk_mins
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io import minute_partition_writer as publication
from orchestrator.defs.jobs.stock_mins_qfq_daily_update import (
    stock_mins_qfq_daily_update_job,
)
from orchestrator.defs.jobs.stock_mins_raw_update import (
    stock_mins_raw_update_from_prod_job,
)
from orchestrator.defs.jobs.stock_mins_silver_update import stock_mins_silver_update_job
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.run_contracts.configs import (
    build_stock_mins_raw_update_job_run_config,
    build_stock_mins_silver_reuse_existing_run_config,
    parse_stock_mins_raw_config,
    parse_stock_mins_silver_config,
)
from orchestrator.defs.run_contracts.stk_mins import (
    build_prod_stk_mins_completion_reference,
)

DAY = "2026-10-30"
CODE = "000001.SZ"
TIMES = ("09:30:00", "10:30:00", "11:30:00", "14:00:00", "15:00:00")


class TemporaryLake(resources.LakeRootResource):
    def ensure_available_for_run(self):
        assert self.root().is_dir()
        assert self.root().is_relative_to(Path("/private/tmp"))


class IsolatedProd(resources.ProdPostgresResource):
    def duckdb_connection_string(self):
        return "isolated-source"


def reference():
    return build_prod_stk_mins_completion_reference(
        task_run_id=101,
        trade_date=DAY,
        ended_at="2026-10-31T14:00:00+08:00",
        expected_code_count=1,
        expected_code_hash=stk_mins_stock_code_set_hash((CODE,)),
        frequency_code_counts={freq: 1 for freq in (1, 5, 15, 30, 60)},
        coverage_observed_at="2026-10-31T14:04:19+08:00",
    )


def raw_config(mode="replace_existing"):
    return {
        "source": "prod_db",
        "write_mode": {mode: {}},
        "prod_completion_reference": reference().to_config_dict(),
    }


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path.resolve()

    def connect():
        return duckdb.connect(
            config={
                "threads": "1",
                "memory_limit": "256MB",
                "temp_directory": str(root / "duckdb"),
                "max_temp_directory_size": "0B",
            }
        )

    for module in (stk_mins, stk_mins_checks, publication, resources):
        monkeypatch.setattr(module, "connect_configured_duckdb", connect)
    monkeypatch.setattr(publication, "gettempdir", lambda: str(root))
    monkeypatch.setattr(stk_mins, "_load_duckdb_postgres_extension", lambda _: None)
    monkeypatch.setattr(
        stk_mins, "_attach_prod_postgres_database", lambda *a, **k: None
    )
    monkeypatch.setattr(
        stk_mins, "load_current_listed_stock_codes_for_stk_mins", lambda **k: (CODE,)
    )
    monkeypatch.setattr(
        stk_mins,
        "validate_stk_mins_prod_completion_reference",
        lambda **k: SimpleNamespace(present_code_count=1),
    )
    source = root / "prod-source.parquet"
    times = ",".join(f"('{t}')" for t in TIMES)
    copy(
        root,
        source,
        f"""SELECT '{CODE}'::VARCHAR AS ts_code,
        60::INTEGER AS freq, CAST('{DAY} ' || t AS TIMESTAMP) AS trade_time,
        11.74::FLOAT AS open,11.80::FLOAT AS close,
        11.83::FLOAT AS high,11.73::FLOAT AS low,
        1000::BIGINT AS vol,11800::DOUBLE AS amount
        FROM (VALUES {times}) times(t)""",
    )
    monkeypatch.setattr(
        stk_mins,
        "build_prod_stk_mins_duckdb_source_sql",
        lambda **k: f"SELECT * FROM {read_parquet(source, hive_partitioning=False)}",
    )
    return root, source


def copy(root, path, query):
    assert path.resolve().is_relative_to(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with stk_mins.connect_configured_duckdb() as connection:
        connection.execute(copy_query_to_parquet(query, path))


def old_raw(root, source):
    path = raw_stk_mins_path(root, 60, DAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    with stk_mins.connect_configured_duckdb() as connection:
        connection.execute(f"""CREATE TEMP VIEW prod_stk_mins_source AS
            SELECT * FROM {read_parquet(source, hive_partitioning=False)}
            WHERE CAST(trade_time AS TIME) < TIME '15:00:00'""")
        connection.execute(
            copy_query_to_parquet(
                stk_mins._prod_db_raw_stk_mins_output_sql(freq=60), path
            )
        )
    return path


def write_raw(root, **extra):
    return stk_mins.write_raw_stk_mins_partition_from_prod_db(
        lake_root=root,
        duckdb=resources.DuckDBResource(),
        prod_postgres=IsolatedProd(),
        freq=60,
        partition_key=DAY,
        stock_codes=(CODE,),
        publication_id="replacement",
        **extra,
    )


def rows(path):
    with stk_mins.connect_configured_duckdb() as connection:
        return connection.execute(f"""SELECT ts_code,
            CAST(trade_time AS TIME)::VARCHAR,open,close,vol,amount
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY ts_code,trade_time""").fetchall()


def references(root):
    # Field names/types are projections of the current reference producers.
    copy(
        root,
        silver_stock_identity_map_path(root),
        f"""SELECT
        '{CODE}'::VARCHAR AS latest_ts_code,'{CODE}'::VARCHAR AS source_ts_code,
        DATE '2000-01-01' AS valid_from,NULL::DATE AS valid_to""",
    )
    copy(
        root,
        silver_stock_daily_path(root, DAY),
        f"""SELECT
        '{CODE}'::VARCHAR AS ts_code,DATE '{DAY}' AS trade_date""",
    )
    copy(
        root,
        silver_stock_suspend_daily_path(root, DAY),
        """SELECT
        NULL::VARCHAR AS ts_code,NULL::DATE AS trade_date,
        NULL::VARCHAR AS suspend_type,NULL::VARCHAR AS suspend_timing WHERE FALSE""",
    )
    copy(
        root,
        silver_stock_lifecycle_path(root),
        f"""SELECT
        '{CODE}'::VARCHAR AS ts_code,TRUE::BOOLEAN AS is_cny_stock,
        'L'::VARCHAR AS list_status,DATE '2000-01-01' AS list_date,
        NULL::DATE AS delist_date""",
    )
    raw60 = raw_stk_mins_path(root, 60, DAY)
    copy(
        root,
        raw_stk_mins_path(root, 1, DAY),
        f"""SELECT * REPLACE
        (1::INTEGER AS freq) FROM {read_parquet(raw60, hive_partitioning=False)}""",
    )


def definitions():
    assets = [
        *stk_mins.RAW_STK_MINS_ASSETS,
        *stk_mins.SILVER_STK_MINS_ASSETS,
        *stk_mins.GOLD_STK_MINS_QFQ_ASSETS,
    ]
    checks = [
        *stk_mins_checks.RAW_STK_MINS_CHECK_DEFINITIONS,
        *stk_mins_checks.SILVER_STK_MINS_CHECK_DEFINITIONS,
        *stk_mins_checks.GOLD_STK_MINS_QFQ_CHECK_DEFINITIONS,
    ]
    keys = {key for asset in assets for key in asset.keys}
    deps = {key for asset in [*assets, *checks] for key in asset.dependency_keys}
    return dg.Definitions(
        assets=[*assets, *(dg.AssetSpec(key) for key in deps - keys)],
        asset_checks=checks,
        jobs=[
            stock_mins_raw_update_from_prod_job,
            stock_mins_silver_update_job,
            stock_mins_qfq_daily_update_job,
        ],
        resources={
            "lake_root": TemporaryLake(root_path="/private/tmp"),
            "duckdb": resources.DuckDBResource(),
            "prod_postgres": IsolatedProd(),
            "tushare": resources.TushareResource(token="unused-isolated"),
        },
    )


@pytest.mark.parametrize("mode", ("reuse_existing", "replace_existing"))
def test_raw_selector_and_default_builders(mode):
    assert parse_stock_mins_raw_config(raw_config(mode)).write_mode == mode
    assert parse_stock_mins_silver_config({}).write_mode == "write_new"
    assert (
        parse_stock_mins_silver_config(
            {"write_mode": {"replace_existing": {}}}
        ).write_mode
        == "replace_existing"
    )
    for value in build_stock_mins_raw_update_job_run_config(
        source="prod_db", prod_completion_reference=reference()
    )["ops"].values():
        assert value["config"]["write_mode"] == {"reuse_existing": {}}
    for value in build_stock_mins_silver_reuse_existing_run_config()["ops"].values():
        assert value["config"]["write_mode"] == {"reuse_existing": {}}


@pytest.mark.parametrize(
    "config",
    [
        {"source": "tushare", "write_mode": {"replace_existing": {}}},
        {"source": "prod_db", "write_mode": {"replace_existing": {}}},
        {**raw_config(), "write_mode": {"replace_existing": {}, "reuse_existing": {}}},
    ],
)
def test_raw_replacement_rejects_invalid_source_reference_or_multiple_modes(config):
    with pytest.raises(ValueError):
        parse_stock_mins_raw_config(config)


def test_silver_multiple_modes_rejected():
    with pytest.raises(ValueError, match="exactly one"):
        parse_stock_mins_silver_config(
            {"write_mode": {"write_new": {}, "replace_existing": {}}}
        )


def test_real_raw_replacement_and_default_reuse(isolated, monkeypatch):
    root, source = isolated
    target = old_raw(root, source)
    old_bytes = target.read_bytes()
    assert write_raw(root).query_count == 0
    assert target.read_bytes() == old_bytes
    assert write_raw(root, overwrite=True).query_count == 1
    assert rows(target) == [(CODE, t, 11.74, 11.8, 1000, 11800.0) for t in TIMES]
    monkeypatch.setattr(
        stk_mins,
        "_build_raw_stk_mins_rows_from_prod_db_source",
        lambda **k: pytest.fail("completed source was read again"),
    )
    assert write_raw(root, overwrite=True).query_count == 0


@pytest.mark.parametrize("after_replace", [False, True])
def test_real_raw_replace_resume_and_changed_identity(
    isolated, monkeypatch, after_replace
):
    root, source = isolated
    target = old_raw(root, source)
    before = target.read_bytes()
    original = os.replace

    def interrupt(src, dst):
        if Path(dst) == target:
            if after_replace:
                original(src, dst)
            raise RuntimeError("interrupted")
        original(src, dst)

    with monkeypatch.context() as scoped:
        scoped.setattr(publication.os, "replace", interrupt)
        with pytest.raises(RuntimeError, match="interrupted"):
            write_raw(root, overwrite=True)
    if not after_replace:
        assert target.read_bytes() == before
    monkeypatch.setattr(
        stk_mins,
        "_build_raw_stk_mins_rows_from_prod_db_source",
        lambda **k: pytest.fail("validated candidate was rebuilt"),
    )
    assert write_raw(root, overwrite=True).query_count == 0
    assert len(rows(target)) == 5
    with pytest.raises(ValueError, match="inputs changed"):
        stk_mins.write_raw_stk_mins_partition_from_prod_db(
            lake_root=root,
            duckdb=resources.DuckDBResource(),
            prod_postgres=IsolatedProd(),
            freq=60,
            partition_key=DAY,
            stock_codes=(CODE, "600000.SH"),
            publication_id="replacement",
            overwrite=True,
        )


def test_bad_raw_candidate_preserves_old_target(isolated, monkeypatch):
    root, source = isolated
    target = old_raw(root, source)
    before = target.read_bytes()
    monkeypatch.setattr(
        stk_mins,
        "build_prod_stk_mins_duckdb_source_sql",
        lambda **k: (
            f"SELECT * FROM {read_parquet(source, hive_partitioning=False)} "
            f"UNION ALL SELECT * FROM {read_parquet(source, hive_partitioning=False)}"
        ),
    )
    with pytest.raises(ValueError, match="candidate"):
        write_raw(root, overwrite=True)
    assert target.read_bytes() == before


def test_real_silver_replace_preserves_frozen_rows_and_default_safety(isolated):
    root, _ = isolated
    write_raw(root, overwrite=True)
    references(root)
    target = silver_stk_mins_path(root, 60, DAY)
    copy(
        root,
        target,
        f"""SELECT '600355.SH'::VARCHAR AS ts_code,60::INTEGER AS freq,
        DATE '{DAY}' AS trade_date,TIMESTAMP '{DAY} 15:00:00' AS trade_time,
        9::DOUBLE AS open,10::DOUBLE AS high,8::DOUBLE AS low,9.5::DOUBLE AS close,
        200::DOUBLE AS vol,1900::DOUBLE AS amount,'SSE'::VARCHAR AS exchange""",
    )
    old_bytes = target.read_bytes()
    kwargs = {
        "lake_root": root,
        "duckdb": resources.DuckDBResource(),
        "freq": 60,
        "partition_key": DAY,
        "publication_id": "silver-replacement",
    }
    with pytest.raises(FileExistsError):
        stk_mins.write_silver_stk_mins_partition(**kwargs)
    assert target.read_bytes() == old_bytes
    result = stk_mins.write_silver_stk_mins_partition(**kwargs, overwrite=True)
    assert result.frozen_preserved_row_count == 1
    assert rows(target) == [
        *((CODE, t, 11.74, 11.8, 1000.0, 11800.0) for t in TIMES),
        ("600355.SH", "15:00:00", 9.0, 9.5, 200.0, 1900.0),
    ]
    before = target.read_bytes()
    reused = stk_mins.reuse_existing_silver_stk_mins_partition(
        lake_root=root, duckdb=resources.DuckDBResource(), freq=60, partition_key=DAY
    )
    assert reused.write_mode == "reuse_existing"
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    "layer,frequencies,check_count",
    [
        ("raw", [60], 3),
        ("silver", [60], 4),
        ("gold", [60, 120], 8),
    ],
)
def test_original_job_subsets_and_real_raw_silver_checks(
    isolated, layer, frequencies, check_count
):
    root, source = isolated
    old_raw(root, source)
    if layer == "silver":
        write_raw(root, overwrite=True)
        references(root)
        # An actual existing, incomplete Silver partition exercises overwrite.
        stk_mins.write_silver_stk_mins_partition(
            lake_root=root,
            duckdb=resources.DuckDBResource(),
            freq=60,
            partition_key=DAY,
            publication_id="old-silver",
        )
        target = silver_stk_mins_path(root, 60, DAY)
        with stk_mins.connect_configured_duckdb() as connection:
            connection.execute(
                f"CREATE TEMP TABLE old_rows AS SELECT * FROM {read_parquet(target, hive_partitioning=False)} WHERE CAST(trade_time AS TIME)<TIME '15:00:00'"
            )
            connection.execute(copy_query_to_parquet("SELECT * FROM old_rows", target))
    prefix = "gold_stk_mins_qfq" if layer == "gold" else f"{layer}_stk_mins"
    selected = {dg.AssetKey(f"{prefix}_{freq}m") for freq in frequencies}
    defs = definitions()
    name = {
        "raw": "stock_mins_raw_update_from_prod_job",
        "silver": "stock_mins_silver_update_job",
        "gold": "stock_mins_qfq_daily_update_job",
    }[layer]
    original = defs.resolve_job_def(name)
    checks = {
        key
        for key in original.asset_layer.asset_graph.asset_check_keys
        if key.asset_key in selected
    }
    assert len(checks) == check_count
    job = original.get_subset(asset_selection=selected, asset_check_selection=checks)
    assert job.asset_layer.executable_asset_keys == selected
    assert job.asset_check_selection == checks
    if layer == "gold":
        return  # Selection contract only; QFQ business algorithm is unchanged.
    config = {
        "ops": {
            f"{prefix}_60m": {
                "config": raw_config()
                if layer == "raw"
                else {"write_mode": {"replace_existing": {}}}
            }
        }
    }
    with dg.DagsterInstance.ephemeral() as instance:
        partitions = (
            stk_mins.cn_a_stock_mins_trade_days
            if layer == "raw"
            else stk_mins.cn_a_stock_mins_silver_trade_days
        )
        instance.add_dynamic_partitions(partitions.name, [DAY])
        result = job.execute_in_process(
            run_config=config,
            instance=instance,
            partition_key=DAY,
            resources={"lake_root": TemporaryLake(root_path=str(root))},
        )
        assert result.success
        mats = result.get_asset_materialization_events()
        assert len(mats) == 1
        assert mats[0].asset_key == next(iter(selected))
        materialization = mats[0].event_specific_data.materialization
        assert materialization.partition == DAY
        assert (
            materialization.metadata["goldenshare/write_mode"].value
            == "replace_existing"
        )
        assert "goldenshare/reused_existing_partition" not in materialization.metadata
        if layer == "silver":
            assert materialization.metadata["goldenshare/source_row_count"].value == 5
            assert "未改写" not in materialization.metadata["goldenshare/summary"].value
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == check_count
        assert all(item.passed and item.asset_key in selected for item in evaluations)
        assert all(
            item.target_materialization_data.run_id == result.run_id
            for item in evaluations
        )
        # Existing checks have no partition field; target materialization is dated.
        target = (raw_stk_mins_path if layer == "raw" else silver_stk_mins_path)(
            root, 60, DAY
        )
        assert rows(target) == [(CODE, t, 11.74, 11.8, 1000.0, 11800.0) for t in TIMES]
