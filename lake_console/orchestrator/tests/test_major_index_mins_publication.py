"""Publication boundaries using literal idx_mins contract samples and real SQL.

Fields/types follow the current idx_mins producer contract. Session clocks and
expected counts below are literal CN session examples, independent of writers.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import paths
from orchestrator.defs.assets.major_index_mins_raw import RAW_MAJOR_INDEX_MINS_ASSETS
from orchestrator.defs.assets.major_index_mins_silver import (
    SILVER_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.checks.major_index_mins_checks import (
    RAW_MAJOR_INDEX_MINS_CHECKS,
    SILVER_MAJOR_INDEX_MINS_CHECKS,
)
from orchestrator.defs.io import major_index_mins_raw_writer as raw
from orchestrator.defs.io import major_index_mins_silver_writer as silver
from orchestrator.defs.io import minute_partition_writer as publisher
from orchestrator.defs.jobs.major_index_mins import (
    raw_major_index_mins_update_job,
    silver_major_index_mins_update_job,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
    TushareResult,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

DAY = "2026-11-03"
CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "000510.SH",
    "000016.SH",
    "000680.SH",
)
FIELDS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "exchange",
    "vwap",
)


class Source:
    def __init__(self):
        self.calls = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, params, fields))
        assert api_name == "idx_mins" and tuple(fields) == FIELDS
        assert params["ts_code"] in CODES
        assert params["start_date"] == f"{DAY} 00:00:00"
        assert params["end_date"] == f"{DAY} 23:59:59"
        step = int(params["freq"][:-3])
        # Literal market hours: 09:30 anchor, then 09:30--11:30 / 13--15.
        minutes = [570, *range(570 + step, 691, step), *range(780 + step, 901, step)]
        rows = []
        for m in minutes if params["offset"] == 0 else []:
            values = (
                params["ts_code"],
                params["freq"],
                f"{DAY} {m // 60:02}:{m % 60:02}:00",
                10.0,
                10.5,
                11.0,
                9.0,
                100.0,
                1000.0,
                "XSHG" if params["ts_code"].endswith("SH") else "XSHE",
                10.0,
            )
            rows.append(dict(zip(FIELDS, values, strict=True)))
        return TushareResult(rows=rows, columns=FIELDS, metadata={})


def write_raw(root, *, run_id="raw", source=None):
    return raw.write_major_index_mins_raw_partition(
        lake_root_path=root,
        duckdb_resource=DuckDBResource(),
        tushare=source or Source(),
        source_freq="60min",
        partition_key=DAY,
        run_id=run_id,
        request_policy=TushareRequestPolicy(
            minimum_interval_seconds=0,
            max_retries=0,
            max_requests=100,
            max_elapsed_seconds=30,
        ),
    )


def write_silver(root, *, run_id="silver"):
    return silver.write_major_index_mins_silver_partition(
        lake_root_path=root,
        duckdb_resource=DuckDBResource(),
        freq="60min",
        partition_key=DAY,
        run_id=run_id,
    )


@pytest.mark.parametrize("kind", ["raw", "silver"])
def test_staging_helpers_use_external_root(tmp_path, monkeypatch, kind):
    formal, staging = tmp_path / "formal", tmp_path / "staging"
    monkeypatch.setattr(paths, "DEFAULT_LAKE_ROOT", str(formal))
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    helper = getattr(paths, f"{kind}_major_index_mins_staging_path")
    assert helper(formal, "run", "60min", DAY).is_relative_to(staging)
    assert helper(tmp_path, "run", "60min", DAY).is_relative_to(tmp_path / "_staging")
    for run_id, freq, day in [
        ("../bad", "60min", DAY),
        ("ok", "2min", DAY),
        ("ok", "60min", "20261103"),
    ]:
        with pytest.raises(ValueError):
            helper(formal, run_id, freq, day)


@pytest.mark.parametrize("kind", ["raw", "silver"])
@pytest.mark.parametrize("after_replace", [False, True])
def test_real_builders_resume_without_source_or_recalculation(
    tmp_path, kind, after_replace
):
    if kind == "silver":
        write_raw(tmp_path)
    write = write_raw if kind == "raw" else write_silver
    target = getattr(paths, f"{kind}_major_index_mins_path")(tmp_path, "60min", DAY)
    original = os.replace

    def interrupt(source, destination):
        if Path(destination) == target:
            if after_replace:
                original(source, destination)
            raise RuntimeError("interrupted publication")
        original(source, destination)

    with (
        patch.object(publisher.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="interrupted publication"),
    ):
        write(tmp_path)
    before = target.stat() if after_replace else None
    module = raw if kind == "raw" else silver
    name = f"_build_major_index_mins_{kind}_partition"
    with patch.object(module, name, side_effect=AssertionError("must not rebuild")):
        result = write(tmp_path)
        replay = write(tmp_path)
    assert result.output_row_count == replay.output_row_count == 50
    assert result.write_mode == "reuse_existing"
    assert isinstance(result.target_path, Path) and isinstance(
        result.staging_path, Path
    )
    assert not result.staging_path.exists()
    if before:
        assert target.stat().st_ino == before.st_ino
    if kind == "raw":
        assert (result.request_count, result.page_count, result.retry_count) == (
            0,
            0,
            0,
        )
    with duckdb.connect() as connection:
        values = connection.execute(
            "SELECT count(*), min(open), max(close), min(vol), min(amount) "
            "FROM read_parquet(?, hive_partitioning=false)",
            [str(target)],
        ).fetchone()
    assert values == (50, 10.0, 10.5, 100.0, 1000.0)


@pytest.mark.parametrize("kind", ["raw", "silver"])
def test_business_candidate_failure_retains_file_and_receipt(tmp_path, kind):
    if kind == "silver":
        write_raw(tmp_path)
    module = raw if kind == "raw" else silver
    validate = getattr(module, f"validate_major_index_mins_{kind}_relation")

    def reject_candidate(connection, *, relation_sql, **kwargs):
        if "attempt=" in relation_sql:
            raise ValueError("candidate rejected for test")
        return validate(connection, relation_sql=relation_sql, **kwargs)

    with (
        patch.object(
            module, f"validate_major_index_mins_{kind}_relation", reject_candidate
        ),
        pytest.raises(ValueError, match="candidate rejected"),
    ):
        (write_raw if kind == "raw" else write_silver)(tmp_path)
    target = getattr(paths, f"{kind}_major_index_mins_path")(tmp_path, "60min", DAY)
    receipts = list(
        Path(publisher.gettempdir()).glob(
            f"goldenshare_minute_staging/minute_partitions/{kind}_major_index_mins/**/receipt.json"
        )
    )
    receipt = next(
        json.loads(p.read_text())
        for p in receipts
        if json.loads(p.read_text())["target"] == str(target)
    )
    assert receipt["status"] == "building"
    assert Path(receipt["candidate"]).is_file()
    assert not target.exists()


def test_silver_changed_source_refuses_validated_candidate(tmp_path):
    write_raw(tmp_path)
    target = paths.silver_major_index_mins_path(tmp_path, "60min", DAY)
    original = os.replace

    def interrupt(source, destination):
        if Path(destination) == target:
            raise RuntimeError("before replace")
        original(source, destination)

    with (
        patch.object(publisher.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError),
    ):
        write_silver(tmp_path)
    source = paths.raw_major_index_mins_path(tmp_path, "60min", DAY)
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    with pytest.raises(ValueError, match="inputs changed"):
        write_silver(tmp_path)
    assert not target.exists()


def test_raw_changed_scope_refuses_committed_receipt(tmp_path):
    result = write_raw(tmp_path)
    before = result.target_path.stat()
    with (
        patch.object(raw, "raw_scope_hash_for_partition", return_value="changed"),
        pytest.raises(ValueError, match="inputs changed"),
    ):
        write_raw(tmp_path)
    assert result.target_path.stat().st_ino == before.st_ino


def test_silver_fallback_is_bound_to_real_file_and_scope(tmp_path):
    from orchestrator.defs.duckdb_sql import copy_query_to_parquet
    from tests.test_major_index_mins_silver_writer import (
        _empty_raw_relation,
        _write_fallback_file,
    )

    day, freq = "2009-05-05", "15min"
    source = paths.raw_major_index_mins_path(tmp_path, freq, day)
    source.parent.mkdir(parents=True)
    with duckdb.connect() as connection:
        relation = _empty_raw_relation(connection)
        connection.execute(copy_query_to_parquet(f"SELECT * FROM {relation}", source))
    fallback, codes = _write_fallback_file(tmp_path, trade_date=day, freq=freq)
    kwargs = {
        "lake_root_path": tmp_path,
        "duckdb_resource": DuckDBResource(),
        "freq": freq,
        "partition_key": day,
        "run_id": "fallback",
        "historical_fallback_path": fallback,
        "historical_fallback_codes": codes,
    }
    result = silver.write_major_index_mins_silver_partition_with_historical_fallback(
        **kwargs
    )
    assert result.source_mode == "native_with_historical_fallback"
    st = fallback.stat()
    os.utime(fallback, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    with pytest.raises(ValueError, match="inputs changed"):
        silver.write_major_index_mins_silver_partition_with_historical_fallback(
            **kwargs
        )


def test_original_raw_then_silver_jobs_and_checks(tmp_path, monkeypatch):
    source = Source()
    monkeypatch.setattr(
        TushareResource,
        "call",
        lambda self, *args, **kwargs: source.call(*args, **kwargs),
    )
    # Rate waiting is transport policy, not the business computation under test.
    monkeypatch.setattr(
        "orchestrator.defs.tushare_request_policy.sleep", lambda _: None
    )
    lake = tmp_path / "lake"
    lake.mkdir()
    for layer in ("raw", "silver", "gold"):
        (lake / layer).mkdir()
    definitions = dg.Definitions(
        assets=[*RAW_MAJOR_INDEX_MINS_ASSETS, *SILVER_MAJOR_INDEX_MINS_ASSETS],
        asset_checks=[*RAW_MAJOR_INDEX_MINS_CHECKS, *SILVER_MAJOR_INDEX_MINS_CHECKS],
        jobs=[raw_major_index_mins_update_job, silver_major_index_mins_update_job],
        resources={
            "lake_root": LakeRootResource(root_path=str(lake)),
            "duckdb": DuckDBResource(),
            "tushare": TushareResource(token="isolated-fake"),
        },
    )
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path)) as instance:
        instance.add_dynamic_partitions("cn_major_index_mins_trade_days", [DAY])
        for name, expected in [
            ("raw_major_index_mins_update_job", 5),
            ("silver_major_index_mins_update_job", 7),
        ]:
            result = definitions.resolve_job_def(name).execute_in_process(
                instance=instance, partition_key=DAY
            )
            assert result.success
            assert len(result.get_asset_materialization_events()) == expected
            checks = result.get_asset_check_evaluations()
            assert len(checks) == expected and all(c.passed for c in checks)
    assert len(source.calls) == 50
    assert sum(p.stat().st_size for p in lake.rglob("*.parquet")) < 1024**2


@pytest.mark.parametrize("kind", ["raw", "silver"])
def test_asset_forwards_root_run_identity(tmp_path, monkeypatch, kind):
    from types import SimpleNamespace

    from orchestrator.defs.assets import major_index_mins_raw, major_index_mins_silver

    result = write_raw(tmp_path) if kind == "raw" else None
    if kind == "silver":
        write_raw(tmp_path)
        result = write_silver(tmp_path)
    calls = []

    def writer(**kwargs):
        calls.append(kwargs["run_id"])
        return result

    module = major_index_mins_raw if kind == "raw" else major_index_mins_silver
    monkeypatch.setattr(module, f"write_major_index_mins_{kind}_partition", writer)
    asset = (
        RAW_MAJOR_INDEX_MINS_ASSETS if kind == "raw" else SILVER_MAJOR_INDEX_MINS_ASSETS
    )[-1]
    context = SimpleNamespace(
        partition_key=DAY,
        run=SimpleNamespace(root_run_id="original-root", run_id="new-child"),
    )
    resources = {
        "lake_root": SimpleNamespace(
            root=lambda: tmp_path, ensure_available_for_run=lambda: None
        ),
        "duckdb": DuckDBResource(),
    }
    if kind == "raw":
        resources["tushare"] = Source()
    asset.op.compute_fn.decorated_fn(context, **resources)
    context.run.root_run_id = None
    asset.op.compute_fn.decorated_fn(context, **resources)
    assert calls == ["original-root", "new-child"]
