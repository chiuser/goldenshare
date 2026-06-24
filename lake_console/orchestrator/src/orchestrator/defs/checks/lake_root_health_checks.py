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


def _combined_health_check_result(status: LakeRootHealthStatus) -> dg.AssetCheckResult:
    rule_passed = {
        "lake_root_required_paths_ready": status.required_paths_ready,
        "lake_root_read_write_ready": status.lake_root_read_write_ready,
        "lake_root_disk_space_ready": status.lake_root_disk_space_ready,
        "duckdb_temp_directory_ready": status.duckdb_temp_directory_ready,
    }
    failed_rule_names = [
        rule_name for rule_name, passed in rule_passed.items() if not passed
    ]
    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=len(failed_rule_names),
            extra_metadata={
                **status.metadata(),
                "rule_passed": rule_passed,
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


@dg.asset_check(
    asset=lake_root_health,
    blocking=True,
    name="lake_root_health_ready",
)
def lake_root_health_ready(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    return _combined_health_check_result(_evaluate(lake_root))


def lake_root_required_paths_ready(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    status = _evaluate(lake_root)
    return _check_result(
        passed=status.required_paths_ready,
        check_scope=CheckScope.FILE_EXISTS,
        status=status,
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


def lake_root_disk_space_ready(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    status = _evaluate(lake_root)
    return _check_result(
        passed=status.lake_root_disk_space_ready,
        check_scope=CheckScope.VALUE_SANITY,
        status=status,
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
