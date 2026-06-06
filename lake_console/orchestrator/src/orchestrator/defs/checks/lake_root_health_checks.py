import dagster as dg

from orchestrator.defs.assets.lake_root_health import lake_root_health
from orchestrator.defs.duckdb_connection import DEFAULT_DUCKDB_TEMP_DIRECTORY
from orchestrator.defs.health.lake_root import LakeRootHealthStatus
from orchestrator.defs.health.lake_root import evaluate_lake_root_health
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _evaluate(lake_root: LakeRootResource) -> LakeRootHealthStatus:
    return evaluate_lake_root_health(
        lake_root=lake_root.root(),
        duckdb_temp_directory=DEFAULT_DUCKDB_TEMP_DIRECTORY,
    )


def _check_result(
    *,
    passed: bool,
    check_scope: CheckScope,
    status: LakeRootHealthStatus,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=check_scope,
            failed_row_count=0 if passed else 1,
            extra_metadata=status.metadata(),
        ),
    )


@dg.asset_check(
    asset=lake_root_health,
    blocking=True,
    name="lake_root_required_paths_ready",
)
def lake_root_required_paths_ready(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    status = _evaluate(lake_root)
    return _check_result(
        passed=status.required_paths_ready,
        check_scope=CheckScope.FILE_EXISTS,
        status=status,
    )


@dg.asset_check(
    asset=lake_root_health,
    blocking=True,
    name="lake_root_read_write_ready",
)
def lake_root_read_write_ready(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    status = _evaluate(lake_root)
    return _check_result(
        passed=status.lake_root_read_write_ready,
        check_scope=CheckScope.VALUE_SANITY,
        status=status,
    )


@dg.asset_check(
    asset=lake_root_health,
    blocking=True,
    name="lake_root_disk_space_ready",
)
def lake_root_disk_space_ready(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    status = _evaluate(lake_root)
    return _check_result(
        passed=status.lake_root_disk_space_ready,
        check_scope=CheckScope.VALUE_SANITY,
        status=status,
    )


@dg.asset_check(
    asset=lake_root_health,
    blocking=True,
    name="duckdb_temp_directory_ready",
)
def duckdb_temp_directory_ready(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    status = _evaluate(lake_root)
    return _check_result(
        passed=status.duckdb_temp_directory_ready,
        check_scope=CheckScope.VALUE_SANITY,
        status=status,
    )
