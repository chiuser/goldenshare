from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.assets.etf_basic import raw_tushare_etf_basic
from orchestrator.defs.checks import etf_basic_checks
from orchestrator.defs.checks.etf_basic_checks import (
    CONTENT_HASH_DESCRIPTION,
    KEY_DOMAIN_DESCRIPTION,
    SOURCE_CONTRACT_DESCRIPTION,
    raw_tushare_etf_basic_content_hash_check,
    raw_tushare_etf_basic_key_domain_check,
    raw_tushare_etf_basic_source_contract_check,
)
from orchestrator.defs.jobs.etf_basic_update import raw_etf_basic_update_job
from orchestrator.defs.paths import raw_etf_basic_snapshot_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_PAGE_LIMIT,
    ETF_BASIC_SOURCE_API,
    ETF_BASIC_SOURCE_COLUMNS,
    RAW_ETF_BASIC_CHECKS,
    compute_etf_basic_snapshot_hash,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata


class TestDuckDBResource:
    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with duckdb.connect(":memory:") as connection:
            yield connection


def _row(
    *,
    list_status: str = "L",
    exchange: str | None = "SH",
) -> dict[str, object]:
    return {
        "ts_code": "510300.SH",
        "csname": "沪深300ETF",
        "extname": None,
        "cname": None,
        "index_code": "000300.SH",
        "index_name": "沪深300指数",
        "setup_date": "20120504",
        "list_date": "20120528",
        "list_status": list_status,
        "exchange": exchange,
        "mgr_name": None,
        "custod_name": None,
        "mgt_fee": 0.5,
        "etf_type": "境内",
    }


def _write_parquet(
    path: Path, row: dict[str, object], *, drop_last: bool = False
) -> None:
    columns = ETF_BASIC_SOURCE_COLUMNS[:-1] if drop_last else ETF_BASIC_SOURCE_COLUMNS
    column_types = {
        **{column: "VARCHAR" for column in ETF_BASIC_SOURCE_COLUMNS},
        "mgt_fee": "DOUBLE",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        definitions = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TABLE snapshot ({definitions})")
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO snapshot VALUES ({placeholders})",
            [row[column] for column in columns],
        )
        connection.execute(f"COPY snapshot TO '{path}' (FORMAT PARQUET)")


def _report_materialization(
    *,
    instance: dg.DagsterInstance,
    path: Path,
    raw_snapshot_hash: str,
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=raw_tushare_etf_basic.key,
            metadata=build_materialization_metadata(
                uri=path,
                row_count=1,
                observed_columns=ETF_BASIC_SOURCE_COLUMNS,
                extra_metadata={
                    "source_row_count": 1,
                    "raw_snapshot_hash": raw_snapshot_hash,
                    "observed_at": "2026-08-30T09:00:00+08:00",
                    "api_name": ETF_BASIC_SOURCE_API,
                    "business_params": {},
                    "fields": list(ETF_BASIC_SOURCE_COLUMNS),
                    "page_limit": ETF_BASIC_PAGE_LIMIT,
                    "page_count": 1,
                    "status_counts": {"L": 1},
                    "suffix_counts": {"SH": 1},
                    "list_date_null_counts": {"total": 0, "by_status": {}},
                    "write_mode": "write_new",
                },
            ),
        )
    )


def _check_context(instance: dg.DagsterInstance) -> dg.AssetCheckExecutionContext:
    return dg.build_asset_check_context(instance=instance)


def test_raw_check_definitions_and_job_match_the_lld() -> None:
    checks = (
        raw_tushare_etf_basic_source_contract_check,
        raw_tushare_etf_basic_key_domain_check,
        raw_tushare_etf_basic_content_hash_check,
    )
    specs = tuple(next(iter(check.check_specs)) for check in checks)

    assert tuple(spec.name for spec in specs) == RAW_ETF_BASIC_CHECKS
    assert all(spec.asset_key == raw_tushare_etf_basic.key for spec in specs)
    assert all(spec.blocking is True for spec in specs)
    assert tuple(spec.description for spec in specs) == (
        SOURCE_CONTRACT_DESCRIPTION,
        KEY_DOMAIN_DESCRIPTION,
        CONTENT_HASH_DESCRIPTION,
    )
    assert raw_etf_basic_update_job.name == "raw_etf_basic_update_job"
    assert raw_etf_basic_update_job.description == (
        "获取并验收当天 ETF Basic 完整源快照；相同内容复用，不同内容新建版本，"
        "失败不会覆盖旧版本，可在修复源/合同后重跑。"
    )

    definitions = dg.Definitions(
        assets=[raw_tushare_etf_basic],
        asset_checks=list(checks),
        jobs=[raw_etf_basic_update_job],
        resources={
            "lake_root": LakeRootResource(root_path="/tmp/test-etf-basic-lake"),
            "duckdb": DuckDBResource(),
            "tushare": TushareResource(token="test-token"),
        },
    )
    dg.Definitions.validate_loadable(definitions)
    asset_graph = definitions.resolve_asset_graph()
    assert raw_etf_basic_update_job.selection.resolve(asset_graph) == {
        raw_tushare_etf_basic.key
    }
    assert {
        check_key.name
        for check_key in raw_etf_basic_update_job.selection.resolve_checks(asset_graph)
    } == set(RAW_ETF_BASIC_CHECKS)


def test_all_three_raw_checks_pass_for_matching_latest_materialization(
    tmp_path: Path,
) -> None:
    row = _row()
    raw_hash = compute_etf_basic_snapshot_hash([row])
    path = raw_etf_basic_snapshot_path(tmp_path, raw_hash)
    _write_parquet(path, row)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance=instance, path=path, raw_snapshot_hash=raw_hash)

    results = (
        raw_tushare_etf_basic_source_contract_check(
            _check_context(instance),
            LakeRootResource(root_path=str(tmp_path)),
            TestDuckDBResource(),  # type: ignore[arg-type]
        ),
        raw_tushare_etf_basic_key_domain_check(
            _check_context(instance),
            LakeRootResource(root_path=str(tmp_path)),
            TestDuckDBResource(),  # type: ignore[arg-type]
        ),
        raw_tushare_etf_basic_content_hash_check(
            _check_context(instance),
            LakeRootResource(root_path=str(tmp_path)),
            TestDuckDBResource(),  # type: ignore[arg-type]
        ),
    )

    assert all(result.passed for result in results)
    assert all(
        result.metadata["goldenshare/reason_code"].value == "ok" for result in results
    )


def test_source_contract_check_fails_on_schema_drift(tmp_path: Path) -> None:
    raw_hash = "a" * 64
    path = raw_etf_basic_snapshot_path(tmp_path, raw_hash)
    _write_parquet(path, _row(), drop_last=True)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance=instance, path=path, raw_snapshot_hash=raw_hash)

    result = raw_tushare_etf_basic_source_contract_check(
        _check_context(instance),
        LakeRootResource(root_path=str(tmp_path)),
        TestDuckDBResource(),  # type: ignore[arg-type]
    )

    assert not result.passed
    assert (
        "column_contract_mismatch" in result.metadata["goldenshare/reason_codes"].value
    )


def test_key_domain_check_fails_on_unknown_status(tmp_path: Path) -> None:
    raw_hash = "b" * 64
    path = raw_etf_basic_snapshot_path(tmp_path, raw_hash)
    _write_parquet(path, _row(list_status="X"))
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance=instance, path=path, raw_snapshot_hash=raw_hash)

    result = raw_tushare_etf_basic_key_domain_check(
        _check_context(instance),
        LakeRootResource(root_path=str(tmp_path)),
        TestDuckDBResource(),  # type: ignore[arg-type]
    )

    assert not result.passed
    assert "list_status_unknown" in result.metadata["goldenshare/reason_codes"].value


def test_content_hash_check_fails_when_formal_content_drifts(tmp_path: Path) -> None:
    row = _row()
    raw_hash = compute_etf_basic_snapshot_hash([row])
    path = raw_etf_basic_snapshot_path(tmp_path, raw_hash)
    _write_parquet(path, row)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance=instance, path=path, raw_snapshot_hash=raw_hash)
    changed = _row()
    changed["mgt_fee"] = 0.6
    _write_parquet(path, changed)

    result = raw_tushare_etf_basic_content_hash_check(
        _check_context(instance),
        LakeRootResource(root_path=str(tmp_path)),
        TestDuckDBResource(),  # type: ignore[arg-type]
    )

    assert not result.passed
    assert "content_hash_mismatch" in result.metadata["goldenshare/reason_codes"].value


def test_latest_failed_materialization_does_not_fall_back_to_an_older_file(
    tmp_path: Path,
) -> None:
    row = _row()
    old_hash = compute_etf_basic_snapshot_hash([row])
    old_path = raw_etf_basic_snapshot_path(tmp_path, old_hash)
    _write_parquet(old_path, row)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(
        instance=instance,
        path=old_path,
        raw_snapshot_hash=old_hash,
    )
    missing_hash = "c" * 64
    _report_materialization(
        instance=instance,
        path=raw_etf_basic_snapshot_path(tmp_path, missing_hash),
        raw_snapshot_hash=missing_hash,
    )

    result = raw_tushare_etf_basic_source_contract_check(
        _check_context(instance),
        LakeRootResource(root_path=str(tmp_path)),
        TestDuckDBResource(),  # type: ignore[arg-type]
    )

    assert not result.passed
    assert "file_unreadable" in result.metadata["goldenshare/reason_codes"].value


def test_check_implementation_does_not_persist_dagster_storage_ids() -> None:
    source = inspect.getsource(etf_basic_checks)

    assert "storage_id" not in source
