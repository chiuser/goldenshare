"""Approved section 10: real local SQL/publication, fake Prod transport only.

Fixtures use the literal eleven-column producer contract in prod_db/index_mins.py
and asset_column_schemas.py. The completed native Raw run and task 18007's bounded
read-only audit establish the real boundary separately; this suite is isolated.
"""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import pytest
from pydantic import ValidationError

from orchestrator.defs.assets import index_mins as raw
from orchestrator.defs.assets import index_mins_raw as raw_defs
from orchestrator.defs.assets import index_mins_silver as silver
from orchestrator.defs.assets import index_mins_silver_defs as silver_defs
from orchestrator.defs.checks import index_mins_checks as checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io import minute_partition_writer as publication
from orchestrator.defs.jobs.index_mins import (
    raw_index_mins_update_job,
    silver_index_mins_update_job,
)
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.prod_db.index_mins import IndexMinsActivePool
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
)
from orchestrator.defs.run_contracts.configs import IndexMinsWriteConfig
from orchestrator.defs.run_contracts.index_mins import (
    build_index_mins_raw_update_job_run_config,
    build_index_mins_silver_update_job_run_config,
    index_mins_code_set_hash,
)

DAY = "2026-11-02"
CODE = "000001.SH"
SCHEMA = (
    ("ts_code", "VARCHAR"), ("freq", "VARCHAR"), ("trade_time", "TIMESTAMP"),
    ("open", "DOUBLE"), ("close", "DOUBLE"), ("high", "DOUBLE"),
    ("low", "DOUBLE"), ("vol", "DOUBLE"), ("amount", "DOUBLE"),
    ("exchange", "VARCHAR"), ("vwap", "DOUBLE"),
)
TIMES_30 = (
    "09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00",
    "13:30:00", "14:00:00", "14:30:00", "15:00:00",
)
TIMES_60 = ("09:30:00", "10:30:00", "11:30:00", "14:00:00", "15:00:00")


class FakeProd(ProdPostgresResource):
    def duckdb_connection_string(self):
        return "fake transport; never connected"


def write_source(path, freq, times, *, day=DAY):
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            "CREATE TABLE fixture (ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP, "
            "open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE, vol DOUBLE, "
            "amount DOUBLE, exchange VARCHAR, vwap DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO fixture VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(CODE, freq, datetime.fromisoformat(f"{day} {clock}"),
              10.0, 10.5, 11.0, 9.0, 100.0, 1000.0, "XSHG", 10.25)
             for clock in times],
        )
        observed = tuple((r[0], r[1]) for r in connection.execute(
            "DESCRIBE fixture"
        ).fetchall())
        assert observed == SCHEMA
        connection.execute(copy_query_to_parquet("SELECT * FROM fixture", path))


def rows(path):
    with DuckDBResource().connect() as connection:
        return connection.execute(
            f"SELECT trade_time,open,close,high,low,vol,amount,vwap "
            f"FROM {read_parquet(path, hive_partitioning=False)} ORDER BY trade_time"
        ).fetchall()


def fake_source(monkeypatch, paths):
    monkeypatch.setattr(raw, "_load_duckdb_postgres_extension", lambda _: None)
    monkeypatch.setattr(raw, "_attach_prod_postgres_database", lambda *a, **kw: None)
    monkeypatch.setattr(
        raw, "build_prod_index_mins_duckdb_source_sql",
        lambda **kw: "SELECT ts_code,freq,trade_time,open,close,high,low,vol,amount,"
        f"exchange,vwap FROM {read_parquet(paths[kw['source_freq']], hive_partitioning=False)}",
    )


def raw_write(root, *, overwrite=False, operation="refresh"):
    return raw.write_raw_index_mins_partition_from_prod_db(
        lake_root=root, duckdb=DuckDBResource(), prod_postgres=FakeProd(),
        source_freq="1min", partition_key=DAY, active_pool=(CODE,),
        publication_id=operation, overwrite=overwrite,
    )


@pytest.mark.parametrize("builder,names", [
    (build_index_mins_raw_update_job_run_config,
     ("raw_index_mins_1m", "raw_index_mins_5m", "raw_index_mins_15m",
      "raw_index_mins_30m", "raw_index_mins_60m")),
    (build_index_mins_silver_update_job_run_config,
     ("silver_index_mins_1m", "silver_index_mins_5m", "silver_index_mins_15m",
      "silver_index_mins_30m", "silver_index_mins_60m",
      "silver_index_mins_90m", "silver_index_mins_120m")),
])
def test_complete_config_default_explicit_and_invalid(builder, names):
    assert IndexMinsWriteConfig().write_mode == "reuse_existing"
    for mode in ("reuse_existing", "replace_existing"):
        config = builder(write_mode=mode)
        assert set(config["ops"]) == set(names)
        assert all(v == {"config": {"write_mode": mode}}
                   for v in config["ops"].values())
    assert builder() == builder(write_mode="reuse_existing")
    with pytest.raises(ValidationError):
        builder(write_mode="replace")


def test_raw_same_code_new_times_replaces_and_default_does_not_query(
    tmp_path, monkeypatch
):
    root = tmp_path / "lake"
    target = raw_index_mins_path(root, "1min", DAY)
    write_source(target, "1min", ("09:30:00",))
    source = tmp_path / "prod.parquet"
    write_source(source, "1min", ("09:30:00", "09:31:00"))
    fake_source(monkeypatch, {"1min": source})
    before = target.stat()
    with patch.object(raw, "_attach_prod_postgres_database",
                      side_effect=AssertionError("default must not query Prod")):
        default = raw_write(root, operation="default")
    assert default.write_mode == "reuse_existing" and default.query_count == 0
    assert target.stat() == before
    other = raw_index_mins_path(root, "1min", "2026-10-30")
    write_source(other, "1min", ("09:30:00",), day="2026-10-30")
    sentinel = other.read_bytes()
    result = raw_write(root, overwrite=True)
    assert result.write_mode == "replace_existing" and result.query_count == 1
    assert result.written_row_count == 2
    assert rows(target) == [
        (datetime.fromisoformat("2026-11-02T09:30:00"), 10, 10.5, 11, 9, 100, 1000, 10.25),
        (datetime.fromisoformat("2026-11-02T09:31:00"), 10, 10.5, 11, 9, 100, 1000, 10.25),
    ]
    assert other.read_bytes() == sentinel
    with patch.object(raw, "_attach_prod_postgres_database",
                      side_effect=AssertionError("completed candidate must be reused")):
        resumed = raw_write(root, overwrite=True)
    assert resumed.query_count == 0 and resumed.write_mode == "replace_existing"
    with pytest.raises(ValueError, match="inputs changed"):
        raw_write(root, overwrite=False)
    assert raw_write(tmp_path / "new-lake", overwrite=True).written_row_count == 2


def test_silver_default_reuse_and_explicit_same_code_refresh(tmp_path):
    source = raw_index_mins_path(tmp_path, "1min", DAY)
    write_source(source, "1min", ("09:30:00",))
    kwargs = {"lake_root": tmp_path, "duckdb": DuckDBResource(), "freq": 1,
              "partition_key": DAY}
    first = silver.write_silver_index_mins_partition(**kwargs)
    before = first.silver_file_path.stat()
    with patch.object(silver, "_stage_and_promote", side_effect=AssertionError("no COPY")):
        reused = silver.write_silver_index_mins_partition(**kwargs)
    assert reused.write_mode == "reuse_existing"
    assert first.silver_file_path.stat() == before
    write_source(source, "1min", ("09:30:00", "09:31:00"))
    refreshed = silver.write_silver_index_mins_partition(
        **kwargs, overwrite=True, publication_id="refresh"
    )
    assert refreshed.write_mode == "replace_existing" and refreshed.written_row_count == 2
    with pytest.raises(ValueError, match="inputs changed"):
        silver.write_silver_index_mins_partition(**kwargs, publication_id="refresh")


def test_bad_raw_replacement_preserves_formal_file(tmp_path, monkeypatch):
    target = raw_index_mins_path(tmp_path, "1min", DAY)
    write_source(target, "1min", ("09:30:00",))
    before = target.read_bytes()
    wrong = tmp_path / "wrong-frequency.parquet"
    # Intentional negative producer-contract sample, not a valid 1min source.
    write_source(wrong, "5min", ("09:30:00",))
    fake_source(monkeypatch, {"1min": wrong})
    with pytest.raises(raw.IndexMinsRawValidationError, match="out_of_scope_rows"):
        raw_write(tmp_path, overwrite=True)
    assert target.read_bytes() == before


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_replacement_interruption_preserves_and_resumes(tmp_path, monkeypatch, after, layer):
    root = tmp_path / "lake"
    source = raw_index_mins_path(root, "1min", DAY)
    write_source(source, "1min", ("09:30:00",))
    if layer == "raw":
        incoming = tmp_path / "prod.parquet"
        write_source(incoming, "1min", ("09:30:00", "09:31:00"))
        fake_source(monkeypatch, {"1min": incoming})
        target = source

        def invoke():
            return raw_write(root, overwrite=True)
    else:
        silver.write_silver_index_mins_partition(
            lake_root=root, duckdb=DuckDBResource(), freq=1, partition_key=DAY
        )
        target = silver_index_mins_path(root, "1min", DAY)
        write_source(source, "1min", ("09:30:00", "09:31:00"))

        def invoke():
            return silver.write_silver_index_mins_partition(
                lake_root=root, duckdb=DuckDBResource(), freq=1, partition_key=DAY,
                publication_id="refresh", overwrite=True,
            )
    old = target.read_bytes()
    original = os.replace

    def interrupt(candidate, destination):
        if Path(destination) == target:
            if after:
                original(candidate, destination)
            raise RuntimeError("isolated interruption")
        return original(candidate, destination)

    with (
        patch.object(publication.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="isolated interruption"),
    ):
        invoke()
    if not after:
        assert target.read_bytes() == old
    module = raw if layer == "raw" else silver
    name = ("_build_raw_index_mins_partition_from_prod_db" if layer == "raw"
            else "_build_silver_index_mins_partition")
    with patch.object(module, name, side_effect=AssertionError("must reuse candidate")):
        result = invoke()
    assert result.write_mode == "replace_existing"
    assert len(rows(target)) == 2


@pytest.mark.parametrize("freq,times", [(90, TIMES_30), (120, TIMES_60)])
def test_incomplete_derived_still_rejected_and_old_target_preserved(tmp_path, freq, times):
    source_freq = "30min" if freq == 90 else "60min"
    source = silver_index_mins_path(tmp_path, source_freq, DAY)
    write_source(source, source_freq, times)
    target = silver.write_silver_index_mins_partition(
        lake_root=tmp_path, duckdb=DuckDBResource(), freq=freq, partition_key=DAY
    ).silver_file_path
    old = target.read_bytes()
    write_source(source, source_freq, times[:-1])
    with pytest.raises(silver.IndexMinsSilverValidationError, match="window is incomplete"):
        silver.write_silver_index_mins_partition(
            lake_root=tmp_path, duckdb=DuckDBResource(), freq=freq,
            partition_key=DAY, publication_id="bad-source", overwrite=True,
        )
    assert target.read_bytes() == old


def test_real_original_jobs_refresh_all_frequencies_in_isolated_instance(tmp_path, monkeypatch):
    # Clock fixtures are independent of the production window builders.
    def clock_range(start, stop, step):
        return tuple(f"{m // 60:02d}:{m % 60:02d}:00" for m in range(start, stop + 1, step))

    clocks = {
        1: clock_range(570, 690, 1) + clock_range(781, 900, 1),
        5: ("09:30:00",) + clock_range(575, 690, 5) + clock_range(785, 900, 5),
        15: ("09:30:00",) + clock_range(585, 690, 15) + clock_range(795, 900, 15),
        30: TIMES_30, 60: TIMES_60,
    }
    root = tmp_path / "lake"
    for layer in ("raw", "silver", "gold"):
        (root / layer).mkdir(parents=True)
    incoming = {}
    for freq, times in clocks.items():
        source_freq = f"{freq}min"
        incoming[source_freq] = tmp_path / f"prod-{freq}.parquet"
        write_source(incoming[source_freq], source_freq, times)
        old = raw_index_mins_path(root, source_freq, DAY)
        write_source(old, source_freq, ("09:30:00",))
        silver.write_silver_index_mins_partition(
            lake_root=root, duckdb=DuckDBResource(), freq=freq, partition_key=DAY
        )
    fake_source(monkeypatch, incoming)
    monkeypatch.setattr(raw_defs, "load_prod_index_mins_active_pool", lambda **kw:
                        IndexMinsActivePool((CODE,), index_mins_code_set_hash((CODE,))))
    defs = dg.Definitions(
        assets=[dg.AssetSpec("silver_index_basic"), *raw_defs.RAW_INDEX_MINS_ASSETS,
                *silver_defs.SILVER_INDEX_MINS_ASSETS],
        asset_checks=[getattr(checks, name) for name in checks.__all__],
        jobs=[raw_index_mins_update_job, silver_index_mins_update_job],
        resources={"lake_root": LakeRootResource(root_path=str(root)),
                   "duckdb": DuckDBResource(), "prod_postgres": FakeProd()},
    )
    raw_job = defs.resolve_job_def(raw_index_mins_update_job.name)
    silver_job = defs.resolve_job_def(silver_index_mins_update_job.name)
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        instance.add_dynamic_partitions(cn_a_index_mins_trade_days.name, [DAY])
        default = raw_job.execute_in_process(instance=instance, partition_key=DAY)
        assert default.success
        assert all(len(rows(raw_index_mins_path(root, f"{f}min", DAY))) == 1
                   for f in clocks)
        new_raw = raw_job.execute_in_process(
            instance=instance, partition_key=DAY,
            run_config=build_index_mins_raw_update_job_run_config(write_mode="replace_existing"),
        )
        assert new_raw.success
        new_silver = silver_job.execute_in_process(
            instance=instance, partition_key=DAY,
            run_config=build_index_mins_silver_update_job_run_config(write_mode="replace_existing"),
        )
        assert new_silver.success
        for result, count in ((new_raw, 5), (new_silver, 7)):
            evaluations = result.get_asset_check_evaluations()
            assert len(evaluations) == count and all(e.passed for e in evaluations)
        for freq, expected in ((1, 241), (5, 49), (15, 17), (30, 9), (60, 5)):
            assert len(rows(raw_index_mins_path(root, f"{freq}min", DAY))) == expected
            assert len(rows(silver_index_mins_path(root, f"{freq}min", DAY))) == expected
        assert [r[5] for r in rows(silver_index_mins_path(root, "90min", DAY))] == [400, 300, 200]
        assert [r[5] for r in rows(silver_index_mins_path(root, "120min", DAY))] == [300, 200]
