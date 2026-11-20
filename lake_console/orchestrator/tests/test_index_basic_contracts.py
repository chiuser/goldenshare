import unittest
from contextlib import contextmanager
from pathlib import Path

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import resources, tushare_api_io
from orchestrator.defs.assets import index_basic as assets
from orchestrator.defs.assets.index_basic import (
    _latest_registered_index_trade_date,
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.checks import index_basic_checks as checks
from orchestrator.defs.duckdb_sql import INDEX_BASIC_RAW_COLUMNS, copy_query_to_parquet
from orchestrator.defs.io import index_basic_publication as publication_io
from orchestrator.defs.io import index_basic_snapshot as snapshots
from orchestrator.defs.jobs.index_basic_update import index_basic_update_job
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import raw_index_basic_path, silver_index_basic_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
    TushareResult,
)


class IndexBasicContractTests(unittest.TestCase):
    def test_latest_registered_index_trade_date_selects_latest_not_after_today(
        self,
    ) -> None:
        self.assertEqual(
            _latest_registered_index_trade_date(
                ("2026-05-25", "2026-05-27", "2026-05-26"),
                "2026-05-26",
            ),
            "2026-05-26",
        )

    def test_latest_registered_index_trade_date_returns_none_without_eligible_day(
        self,
    ) -> None:
        self.assertIsNone(_latest_registered_index_trade_date((), "2026-05-26"))
        self.assertIsNone(
            _latest_registered_index_trade_date(("2026-05-27",), "2026-05-26")
        )

    def test_silver_index_basic_no_longer_exposes_required_config(self) -> None:
        self.assertFalse(silver_index_basic.node_def.compute_fn.has_config_arg())

    def test_index_basic_update_job_accepts_empty_run_config(self) -> None:
        job_def = self._index_basic_update_job_def()
        validated_config = dg.validate_run_config(job_def, {})

        self.assertIn("ops", validated_config)

    def test_index_basic_update_job_rejects_old_ready_for_trade_date_config(
        self,
    ) -> None:
        job_def = self._index_basic_update_job_def()

        with self.assertRaises(dg.DagsterInvalidConfigError):
            dg.validate_run_config(
                job_def,
                {
                    "ops": {
                        "silver_index_basic": {
                            "config": {"ready_for_trade_date": "2026-05-26"}
                        }
                    }
                },
            )

    def _index_basic_update_job_def(self) -> dg.JobDefinition:
        defs = dg.Definitions(
            assets=[raw_tushare_index_basic, silver_index_basic],
            jobs=[index_basic_update_job],
            resources={
                "lake_root": LakeRootResource(root_path="/tmp/goldenshare-test-lake"),
                "duckdb": DuckDBResource(),
                "tushare": TushareResource(token="dummy"),
            },
        )
        return defs.resolve_job_def("index_basic_update_job")


def _source_row(code, market, *, exp_date=None, name=None):
    return dict.fromkeys(INDEX_BASIC_RAW_COLUMNS) | {
        "ts_code": code,
        "market": market,
        "name": name or code,
        "list_date": "20200102",
        "exp_date": exp_date,
    }


@pytest.fixture
def refresh(tmp_path, monkeypatch):
    @contextmanager
    def local_connection():
        with duckdb.connect(":memory:") as connection:
            yield connection

    for module in (assets, checks, resources, tushare_api_io):
        monkeypatch.setattr(module, "connect_configured_duckdb", local_connection)
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    monkeypatch.setattr(snapshots, "TUSHARE_API_PAGE_LIMIT", 2)
    root = tmp_path / "lake"
    root.mkdir()
    (tmp_path / "data_lake_staging").mkdir()
    definitions = dg.Definitions(
        assets=[raw_tushare_index_basic, silver_index_basic],
        jobs=[index_basic_update_job],
        asset_checks=[
            checks.raw_index_basic_contract_check,
            checks.raw_index_basic_key_integrity_check,
            checks.raw_index_basic_date_domain_check,
            checks.silver_index_basic_contract_check,
            checks.silver_index_basic_key_integrity_check,
            checks.silver_index_basic_lifecycle_domain_check,
        ],
        resources={
            "lake_root": LakeRootResource(root_path=str(root)),
            "duckdb": DuckDBResource(),
            "tushare": TushareResource(token="isolated-test"),
        },
    )
    source = {"rows": [], "calls": [], "extra_csi": [], "failure_offset": None}

    def fake_call(_resource, api_name, params, fields):
        assert api_name == "index_basic"
        source["calls"].append(params.copy())
        market = params.get("market")
        offset, limit = params["offset"], params["limit"]
        if offset == source["failure_offset"]:
            raise RuntimeError("isolated request failure")
        rows = source["rows"]
        if market is not None:
            rows = [row for row in rows if row["market"] == market]
            if market == "CSI":
                rows += source["extra_csi"]
        return TushareResult(
            [
                {field: row[field] for field in fields}
                for row in rows[offset : offset + limit]
            ],
            tuple(fields),
            {},
        )

    monkeypatch.setattr(TushareResource, "call", fake_call)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(cn_a_index_trade_days.name, ["2026-11-19"])
        yield (
            root,
            instance,
            definitions.resolve_job_def("index_basic_update_job"),
            source,
        )


def _codes(path: Path):
    with duckdb.connect(":memory:") as connection:
        return {
            code
            for (code,) in connection.execute(
                "SELECT ts_code FROM read_parquet(?)", [str(path)]
            ).fetchall()
        }


def test_full_job_replaces_snapshot_and_attaches_same_batch_evidence(refresh):
    root, instance, job, source = refresh
    source["rows"] = [_source_row("OLD.NH", "NH"), _source_row("000300.SH", "CSI")]
    assert job.execute_in_process(instance=instance).success
    source["rows"] = [
        _source_row("000300.SH", "CSI", name="沪深300"),
        _source_row("930994.CSI", "CSI", exp_date="20261119"),
        _source_row("000001.SH", "SSE", exp_date="20261120"),
    ]
    source["calls"].clear()
    result = job.execute_in_process(
        instance=instance,
        run_config={
            "ops": {
                "raw_tushare_index_basic": {
                    "config": {"verify_source_market_coverage": True}
                }
            }
        },
    )
    assert result.success
    assert _codes(raw_index_basic_path(root)) == {
        "000300.SH",
        "930994.CSI",
        "000001.SH",
    }
    assert _codes(silver_index_basic_path(root)) == {"000300.SH", "000001.SH"}
    assert [call["offset"] for call in source["calls"] if "market" not in call] == [
        0,
        2,
    ]
    assert [
        call["offset"] for call in source["calls"] if call.get("market") == "CSI"
    ] == [0, 2]
    evidence_key = publication_io.INDEX_BASIC_COVERAGE_METADATA_KEY
    evaluations = {
        event.check_name: event for event in result.get_asset_check_evaluations()
    }
    raw = evaluations["raw_index_basic_contract_check"].metadata[evidence_key].value
    silver = (
        evaluations["silver_index_basic_lifecycle_domain_check"]
        .metadata[evidence_key]
        .value
    )
    assert raw["batch_id"] == silver["batch_id"] == result.run_id
    assert raw["sha256"] == silver["raw_sha256"]
    assert raw["candidate_rows"] == 3 and silver["expected_rows"] == 2
    assert silver["ready_for_trade_date"] == "2026-11-19"
    assert silver["materialization_run_id"] == result.run_id
    report = publication_io.read_json(Path(raw["changes_report"]))
    assert report["raw_changes"]["removed"] == ["OLD.NH"]
    assert report["raw_changes"]["changed"] == [
        {"ts_code": "000300.SH", "fields": ["name"]}
    ]


@pytest.mark.parametrize(
    "failure", ["market", "duplicate", "request", "silver", "termination"]
)
def test_failed_preparation_never_replaces_either_snapshot(
    refresh, monkeypatch, failure
):
    root, instance, job, source = refresh
    source["rows"] = [_source_row("OLD.NH", "NH")]
    assert job.execute_in_process(instance=instance).success
    targets = (raw_index_basic_path(root), silver_index_basic_path(root))
    before = [path.read_bytes() for path in targets]
    source["rows"] = [_source_row("000300.SH", "CSI"), _source_row("000001.SH", "SSE")]
    if failure == "market":
        source["extra_csi"] = [_source_row("MISSING.CSI", "CSI")]
    if failure == "duplicate":
        source["rows"].append(source["rows"][0])
    if failure == "request":
        source["failure_offset"] = 2
    if failure == "silver":
        monkeypatch.setattr(
            snapshots,
            "copy_query_to_parquet",
            lambda query, path: copy_query_to_parquet(
                f"SELECT * FROM ({query}) WHERE ts_code <> '000001.SH'", path
            ),
        )
    if failure == "termination":
        monkeypatch.setattr(
            snapshots,
            "copy_query_to_parquet",
            lambda query, path: copy_query_to_parquet(
                f"SELECT * REPLACE (DATE '2026-11-30' AS exp_date) FROM ({query})", path
            ),
        )
    result = job.execute_in_process(
        instance=instance,
        raise_on_error=False,
        run_config={
            "ops": {
                "raw_tushare_index_basic": {
                    "config": {"verify_source_market_coverage": failure == "market"}
                }
            }
        },
    )
    assert not result.success
    assert [path.read_bytes() for path in targets] == before


def test_interrupted_rename_recovers_same_candidates(refresh, monkeypatch):
    root, instance, job, source = refresh
    source["rows"] = [_source_row("000001.SH", "SSE")]

    def interrupted(_directory):
        raise OSError("interrupted after rename")

    with monkeypatch.context() as patch:
        patch.setattr(publication_io, "sync_directory", interrupted)
        attempt = job.execute_in_process(instance=instance, raise_on_error=False)
    assert not attempt.success
    assert _codes(raw_index_basic_path(root)) == {"000001.SH"}
    assert not silver_index_basic_path(root).exists()
    with publication_io.index_basic_publication(root, attempt.run_id) as publication:
        assert publication.promote("raw")["candidate_rows"] == 1
        assert publication.promote("silver")["candidate_rows"] == 1
    assert _codes(silver_index_basic_path(root)) == {"000001.SH"}
    assert len(source["calls"]) == 1


def test_raw_only_refresh_keeps_previous_silver_check_evidence(refresh):
    root, instance, job, source = refresh
    source["rows"] = [_source_row("000001.SH", "SSE")]
    old = job.execute_in_process(instance=instance)
    assert old.success
    source["rows"] = [_source_row("000300.SH", "CSI")]
    raw_only = job.execute_in_process(
        instance=instance, asset_selection=[dg.AssetKey("raw_tushare_index_basic")]
    )
    assert raw_only.success
    assert _codes(raw_index_basic_path(root)) == {"000300.SH"}
    assert _codes(silver_index_basic_path(root)) == {"000001.SH"}
    result = checks.silver_index_basic_no_terminated_indexes(
        dg.build_asset_check_context(instance=instance),
        LakeRootResource(root_path=str(root)),
        DuckDBResource(),
    )
    assert result.passed
    evidence = result.metadata[publication_io.INDEX_BASIC_COVERAGE_METADATA_KEY].value
    assert evidence["batch_id"] == old.run_id
    before = len(source["calls"])
    silver_only = job.execute_in_process(
        instance=instance, asset_selection=[dg.AssetKey("silver_index_basic")]
    )
    assert silver_only.success
    assert _codes(silver_index_basic_path(root)) == {"000300.SH"}
    assert len(source["calls"]) == before


def test_old_silver_without_coverage_preserves_blocking_pass(refresh):
    root, instance, job, source = refresh
    source["rows"] = [_source_row("000001.SH", "SSE")]
    assert job.execute_in_process(instance=instance).success
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key="silver_index_basic",
            metadata={"goldenshare/ready_for_trade_date": "2026-11-19"},
        )
    )
    result = checks.silver_index_basic_no_terminated_indexes(
        dg.build_asset_check_context(instance=instance),
        LakeRootResource(root_path=str(root)),
        DuckDBResource(),
    )
    assert result.passed
    assert publication_io.INDEX_BASIC_COVERAGE_METADATA_KEY not in result.metadata


def test_scheduled_date_mismatch_stops_before_calling_source(refresh):
    root, instance, job, source = refresh
    result = job.execute_in_process(
        instance=instance,
        raise_on_error=False,
        run_config={
            "ops": {
                "raw_tushare_index_basic": {
                    "config": {"scheduled_trade_date": "2026-11-18"}
                }
            }
        },
    )
    assert not result.success
    assert not source["calls"]
    assert not raw_index_basic_path(root).exists()


if __name__ == "__main__":
    unittest.main()
