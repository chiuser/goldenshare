import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.definitions import defs as load_project_definitions
from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    EtfMinsBarDomainCheckEvidence,
    EtfMinsRawMaterializationEvidence,
    evaluate_etf_mins_raw_bar_domain,
)
from orchestrator.defs.assets.etf_basic import silver_etf_basic
from orchestrator.defs.assets.etf_mins import (
    RAW_ETF_MINS_ASSETS,
    SILVER_ETF_MINS_ASSETS,
    EtfMinsSilverWriteError,
    write_silver_etf_mins_partition,
)
from orchestrator.defs.checks.etf_mins_checks import (
    RAW_ETF_MINS_CHECK_DEFINITIONS,
    SILVER_ETF_MINS_CHECK_DEFINITIONS,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.jobs.etf_mins_update import (
    raw_etf_mins_update_job,
    silver_etf_mins_update_job,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
)
from orchestrator.defs.run_contracts.etf_basic import (
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_ASSET_FREQS,
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_FREQS,
    get_etf_mins_raw_decision_policy,
    raw_etf_mins_check_names,
    silver_etf_mins_check_names,
)

TRADE_DATE = "2026-08-28"


class CountingDuckDBResource:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        self.connection_count += 1
        with duckdb.connect(":memory:") as connection:
            yield connection


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _basic_reference():  # type: ignore[no-untyped-def]
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash="a" * 64,
        silver_content_hash="b" * 64,
        raw_uri="/isolated/raw/etf_basic.parquet",
        silver_uri="/isolated/silver/etf_basic.parquet",
        raw_observed_at="2026-08-28T07:00:00+08:00",
        silver_observed_at="2026-08-28T07:01:00+08:00",
        eligibility_as_of=TRADE_DATE,
        requestable_code_count=1,
        requestable_code_hash="c" * 64,
    )


def _write_raw_file(
    *,
    path: Path,
    source_freq: str,
    clock_times: tuple[str, ...],
    zero_volume: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            "510300.SH",
            source_freq,
            datetime.fromisoformat(f"{TRADE_DATE}T{clock_time}"),
            10.0,
            10.1,
            10.2,
            9.9,
            0 if zero_volume else 100,
            0.0 if zero_volume else 1000.0,
            10.05,
            "XSHG",
        )
        for clock_time in clock_times
    ]
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE rows (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
              vol BIGINT, amount DOUBLE, vwap DOUBLE, exchange VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            "COPY (SELECT * FROM rows ORDER BY ts_code, trade_time) TO ? "
            "(FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(path)],
        )


def _raw_evidences(
    tmp_path: Path,
    *,
    zero_volume: bool = False,
    drop_last_from: str | None = None,
) -> tuple[EtfMinsRawMaterializationEvidence, ...]:
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    reference = _basic_reference()
    evidences = []
    for index, (asset, source_freq) in enumerate(
        zip(RAW_ETF_MINS_ASSETS, ETF_MINS_SOURCE_FREQS, strict=True),
        start=1,
    ):
        clock_times = policy.expected_clock_times(source_freq)
        if source_freq == drop_last_from:
            clock_times = clock_times[:-1]
        path = tmp_path / source_freq / "part-000.parquet"
        _write_raw_file(
            path=path,
            source_freq=source_freq,
            clock_times=clock_times,
            zero_volume=zero_volume,
        )
        evidences.append(
            EtfMinsRawMaterializationEvidence(
                asset_key=asset.key,
                storage_id=index,
                partition_key=TRADE_DATE,
                source_freq=source_freq,
                raw_path=path,
                raw_sha256=_sha256_file(path),
                row_count=len(clock_times),
                code_count=1,
                expected_count=1,
                present_count=1,
                missing_count=0,
                known_non_required_present_count=0,
                retained_legacy_count=0,
                unexplained_new_count=0,
                basic_reference=reference,
            )
        )
    return tuple(evidences)


def test_bar_domain_uses_one_connection_and_applies_green_warn_blocked_policy(
    tmp_path: Path,
) -> None:
    green_duckdb = CountingDuckDBResource()
    green = evaluate_etf_mins_raw_bar_domain(
        duckdb=green_duckdb,  # type: ignore[arg-type]
        evidences=_raw_evidences(tmp_path / "green"),
    )
    assert green_duckdb.connection_count == 1
    assert tuple(result.decision for result in green) == ("green",) * 5
    assert all(result.silver_eligible for result in green)

    warn_duckdb = CountingDuckDBResource()
    warned = evaluate_etf_mins_raw_bar_domain(
        duckdb=warn_duckdb,  # type: ignore[arg-type]
        evidences=_raw_evidences(tmp_path / "warn", zero_volume=True),
    )
    assert warn_duckdb.connection_count == 1
    assert tuple(result.decision for result in warned) == ("warn",) * 5
    assert all(
        "full_zero_volume_etf_day_observed" in result.reason_codes for result in warned
    )

    blocked_duckdb = CountingDuckDBResource()
    blocked = evaluate_etf_mins_raw_bar_domain(
        duckdb=blocked_duckdb,  # type: ignore[arg-type]
        evidences=_raw_evidences(tmp_path / "blocked", drop_last_from="5min"),
    )
    assert blocked_duckdb.connection_count == 1
    by_freq = {result.source_freq: result for result in blocked}
    assert by_freq["5min"].decision == "blocked"
    assert "minute_grid_contract_anomaly" in by_freq["5min"].reason_codes
    assert all(
        result.decision == "green"
        for source_freq, result in by_freq.items()
        if source_freq != "5min"
    )


def test_silver_writer_is_an_exact_copy_and_never_overwrites_conflict(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    raw_evidence = _raw_evidences(tmp_path / "raw-source")[0]
    check_evidence = EtfMinsBarDomainCheckEvidence(
        raw_storage_id=raw_evidence.storage_id,
        gap_policy_version=ETF_MINS_RAW_APPROVED_POLICY_VERSION,
        gap_policy_hash=get_etf_mins_raw_decision_policy(
            ETF_MINS_RAW_APPROVED_POLICY_VERSION
        ).policy_hash,
        decision="green",
        reason_codes=(),
        raw_sha256=raw_evidence.raw_sha256,
    )
    resource = CountingDuckDBResource()
    first = write_silver_etf_mins_partition(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id="first",
        duckdb=resource,  # type: ignore[arg-type]
        raw_evidence=raw_evidence,
        bar_domain_evidence=check_evidence,
    )
    assert first.write_disposition == "added"
    assert first.row_count == raw_evidence.row_count
    with duckdb.connect(":memory:") as connection:
        columns = tuple(
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                [str(first.target_path)],
            ).fetchall()
        )
        assert columns == ETF_MINS_SOURCE_COLUMNS

    second = write_silver_etf_mins_partition(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id="second",
        duckdb=resource,  # type: ignore[arg-type]
        raw_evidence=raw_evidence,
        bar_domain_evidence=check_evidence,
    )
    assert second.write_disposition == "reused"
    formal_hash = _sha256_file(first.target_path)

    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT * REPLACE (close + 1 AS close) FROM "
            f"read_parquet({duckdb_string(first.target_path)}, "
            "hive_partitioning=false)) TO "
            f"{duckdb_string(tmp_path / 'conflict.parquet')} (FORMAT PARQUET)"
        )
    first.target_path.write_bytes((tmp_path / "conflict.parquet").read_bytes())
    with dg.instance_for_test():
        try:
            write_silver_etf_mins_partition(
                lake_root=lake_root,
                staging_root=staging_root,
                operation_id="conflict",
                duckdb=resource,  # type: ignore[arg-type]
                raw_evidence=raw_evidence,
                bar_domain_evidence=check_evidence,
            )
        except EtfMinsSilverWriteError as error:
            assert "etf_mins_target_conflict" in str(error)
        else:
            raise AssertionError("conflicting Silver target must fail closed")
    assert _sha256_file(first.target_path) != formal_hash


def test_assets_checks_and_jobs_match_the_lld_selection_contract() -> None:
    assert len(RAW_ETF_MINS_ASSETS) == 5
    assert len(SILVER_ETF_MINS_ASSETS) == 5
    assert all(
        asset.partitions_def is cn_a_etf_mins_trade_days
        for asset in RAW_ETF_MINS_ASSETS
    )
    assert all(
        asset.partitions_def is cn_a_etf_mins_trade_days
        for asset in SILVER_ETF_MINS_ASSETS
    )

    check_specs = tuple(
        spec
        for definition in (
            *RAW_ETF_MINS_CHECK_DEFINITIONS,
            *SILVER_ETF_MINS_CHECK_DEFINITIONS,
        )
        for spec in definition.check_specs
    )
    expected_names = {
        *(
            name
            for minutes in ETF_MINS_ASSET_FREQS
            for name in raw_etf_mins_check_names(minutes)
        ),
        *(
            name
            for minutes in ETF_MINS_ASSET_FREQS
            for name in silver_etf_mins_check_names(minutes)
        ),
    }
    assert {spec.name for spec in check_specs} == expected_names
    assert len(check_specs) == 25
    assert all(spec.blocking for spec in check_specs)
    assert all(spec.partitions_def is cn_a_etf_mins_trade_days for spec in check_specs)

    definitions = dg.Definitions(
        assets=[silver_etf_basic, *RAW_ETF_MINS_ASSETS, *SILVER_ETF_MINS_ASSETS],
        asset_checks=[
            *RAW_ETF_MINS_CHECK_DEFINITIONS,
            *SILVER_ETF_MINS_CHECK_DEFINITIONS,
        ],
        jobs=[raw_etf_mins_update_job, silver_etf_mins_update_job],
        resources={
            "duckdb": DuckDBResource(),
            "lake_root": LakeRootResource(),
            "prod_postgres": ProdPostgresResource(),
        },
    )
    dg.Definitions.validate_loadable(definitions)
    raw_job = definitions.resolve_job_def("raw_etf_mins_update_job")
    silver_job = definitions.resolve_job_def("silver_etf_mins_update_job")
    assert raw_job.executor_def.name == "in_process"
    assert silver_job.executor_def.name == "in_process"


def test_project_definitions_discover_all_checks_and_wire_blocking_dependencies() -> (
    None
):
    repository = load_project_definitions().get_repository_def()
    etf_mins_check_keys = {
        check_key
        for check_key in repository.asset_graph.asset_check_keys
        if "etf_mins" in check_key.asset_key.to_user_string()
    }
    assert len(etf_mins_check_keys) == 25

    raw_job = repository.get_job("raw_etf_mins_update_job")
    silver_job = repository.get_job("silver_etf_mins_update_job")
    assert len(raw_job.graph.node_names()) == 16
    assert len(silver_job.graph.node_names()) == 26
    assert not any(
        node_name in {asset.key.to_user_string() for asset in RAW_ETF_MINS_ASSETS}
        for node_name in silver_job.graph.node_names()
    )

    dependencies = silver_job.graph.dependency_structure
    for minutes in ETF_MINS_ASSET_FREQS:
        silver_node = f"silver_etf_mins_{minutes}m"
        upstream_nodes = {
            output.node.name
            for output in dependencies.all_upstream_outputs_from_node(silver_node)
        }
        assert (
            f"raw_etf_mins_{minutes}m_raw_etf_mins_{minutes}m_file_contract_check"
            in upstream_nodes
        )
        assert (
            f"raw_etf_mins_{minutes}m_raw_etf_mins_{minutes}m_request_scope_check"
            in upstream_nodes
        )
        assert "raw_etf_mins_bar_domain_checks" in upstream_nodes
    raw_nodes = {node.name for node in raw_job.graph.nodes}
    silver_nodes = {node.name for node in silver_job.graph.nodes}
    assert {asset.key.path[-1] for asset in RAW_ETF_MINS_ASSETS} <= raw_nodes
    assert not ({asset.key.path[-1] for asset in SILVER_ETF_MINS_ASSETS} & raw_nodes)
    assert {asset.key.path[-1] for asset in SILVER_ETF_MINS_ASSETS} <= silver_nodes
    assert not ({asset.key.path[-1] for asset in RAW_ETF_MINS_ASSETS} & silver_nodes)
    assert "raw_etf_mins_bar_domain_checks" in raw_nodes
    assert "raw_etf_mins_bar_domain_checks" in silver_nodes
