"""Single blocking contract check for the manual DC industry hierarchy snapshot."""

from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.dc_industry_hierarchy import (
    _reference_industry_level_sql,
    _reference_select_sql,
    _snapshot_validation_failures,
    audit_dc_industry_hierarchy_reference,
    load_dc_industry_hierarchy_reference,
    silver_dc_industry_hierarchy,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    silver_dc_index_path,
    silver_dc_industry_hierarchy_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


_OUTPUT_COLUMN_PROJECTION = ", ".join(
    column.name for column in SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA
)


def _metadata_scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _latest_materialization_metadata(
    context: dg.AssetCheckExecutionContext,
) -> dict[str, Any] | None:
    event = context.instance.get_latest_materialization_event(
        silver_dc_industry_hierarchy.key
    )
    if event is None or event.dagster_event is None:
        return None
    materialization = event.dagster_event.event_specific_data.materialization
    return {
        key: _metadata_scalar(value)
        for key, value in materialization.metadata.items()
    }


def _output_reference_differences(
    *,
    connection: Any,
    target_path: Path,
    reference_path: Path,
) -> tuple[int, int, list[dict[str, str]]]:
    output_relation = read_parquet(target_path, hive_partitioning=False)
    reference_sql = _reference_select_sql(reference_path)
    missing_rows = connection.execute(
        f"""
        WITH output AS (SELECT {_OUTPUT_COLUMN_PROJECTION} FROM {output_relation}), reference AS ({reference_sql})
        SELECT reference.level, reference.name
        FROM reference
        LEFT JOIN output
          ON output.ts_code = reference.ts_code
         AND output.name = reference.name
         AND output.industry_level = {_reference_industry_level_sql('reference.level')}
        WHERE output.ts_code IS NULL
        ORDER BY reference.level, reference.name
        LIMIT 20
        """
    ).fetchall()
    extra_rows = connection.execute(
        f"""
        WITH output AS (SELECT {_OUTPUT_COLUMN_PROJECTION} FROM {output_relation}), reference AS ({reference_sql})
        SELECT output.industry_level, output.name, output.ts_code
        FROM output
        LEFT JOIN reference
          ON output.ts_code = reference.ts_code
         AND output.name = reference.name
         AND output.industry_level = {_reference_industry_level_sql('reference.level')}
        WHERE reference.ts_code IS NULL
        ORDER BY output.industry_level, output.name, output.ts_code
        LIMIT 20
        """
    ).fetchall()
    missing_count = int(
        connection.execute(
            f"""
            WITH output AS (SELECT {_OUTPUT_COLUMN_PROJECTION} FROM {output_relation}), reference AS ({reference_sql})
            SELECT count(*)
            FROM reference
            LEFT JOIN output
              ON output.ts_code = reference.ts_code
             AND output.name = reference.name
             AND output.industry_level = {_reference_industry_level_sql('reference.level')}
            WHERE output.ts_code IS NULL
            """
        ).fetchone()[0]
    )
    extra_count = int(
        connection.execute(
            f"""
            WITH output AS (SELECT {_OUTPUT_COLUMN_PROJECTION} FROM {output_relation}), reference AS ({reference_sql})
            SELECT count(*)
            FROM output
            LEFT JOIN reference
              ON output.ts_code = reference.ts_code
             AND output.name = reference.name
             AND output.industry_level = {_reference_industry_level_sql('reference.level')}
            WHERE reference.ts_code IS NULL
            """
        ).fetchone()[0]
    )
    samples = [
        {"kind": "missing_output", "level": str(level), "name": str(name)}
        for level, name in missing_rows
    ] + [
        {
            "kind": "extra_output",
            "industry_level": str(level),
            "name": str(name),
            "ts_code": str(ts_code),
        }
        for level, name, ts_code in extra_rows
    ]
    return missing_count, extra_count, samples[:20]


@dg.asset_check(asset=silver_dc_industry_hierarchy, blocking=True)
def silver_dc_industry_hierarchy_core_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    target_path = silver_dc_industry_hierarchy_path(lake_root.root())
    failed_rule_names: list[str] = []
    failure_samples: list[dict[str, str]] = []
    failure_counts: dict[str, int] = {}
    metadata = _latest_materialization_metadata(context)

    if not target_path.is_file():
        failed_rule_names.append("file_exists")
        failure_counts["file_exists"] = 1
    if metadata is None:
        failed_rule_names.append("materialization_reference_metadata")
        failure_counts["materialization_reference_metadata"] = 1

    reference = None
    if metadata is not None:
        reference_trade_date = str(
            metadata.get("goldenshare/code_reference_trade_date", "")
        ).strip()
        reference_path = str(
            metadata.get("goldenshare/code_reference_file_path", "")
        ).strip()
        if not reference_trade_date:
            failed_rule_names.append("materialization_reference_metadata")
            failure_counts["materialization_reference_metadata"] = 1
        else:
            expected_reference_path = silver_dc_index_path(
                lake_root.root(), reference_trade_date
            )
            if reference_path != str(expected_reference_path):
                failed_rule_names.append("materialization_reference_metadata")
                failure_counts["materialization_reference_metadata"] = 1
            try:
                reference = load_dc_industry_hierarchy_reference(
                    lake_root_path=lake_root.root(),
                    duckdb_resource=duckdb,
                    reference_trade_date=reference_trade_date,
                )
                audit = audit_dc_industry_hierarchy_reference(
                    duckdb_resource=duckdb,
                    reference=reference,
                )
                if (
                    audit.missing_seed_node_count
                    or audit.extra_reference_node_count
                ):
                    failed_rule_names.append("seed_reference_two_way_mapping")
                    failure_counts["seed_reference_two_way_mapping"] = (
                        audit.missing_seed_node_count
                        + audit.extra_reference_node_count
                    )
                    failure_samples.extend(
                        {
                            "kind": "missing_seed_reference",
                            "industry_level": str(level),
                            "name": name,
                        }
                        for level, name in audit.missing_seed_node_samples[:20]
                    )
                    failure_samples.extend(
                        {
                            "kind": "extra_reference",
                            "level": level,
                            "name": name,
                        }
                        for level, name in audit.extra_reference_node_samples[:20]
                    )
            except Exception as error:  # noqa: BLE001 - a broken reference must fail closed.
                failed_rule_names.append("reference_file_contract")
                failure_counts["reference_file_contract"] = 1
                failure_samples.append({"error_type": type(error).__name__})

    checked_row_count = 0
    if target_path.is_file() and reference is not None:
        try:
            with connect_configured_duckdb() as connection:
                failures = _snapshot_validation_failures(
                    connection=connection,
                    path=target_path,
                    reference=reference,
                )
                checked_row_count = int(
                    connection.execute(
                        f"SELECT count(*) FROM {read_parquet(target_path, hive_partitioning=False)}"
                    ).fetchone()[0]
                )
                failed_snapshot_rules = [
                    rule_name for rule_name, count in failures.items() if count
                ]
                if failed_snapshot_rules:
                    failed_rule_names.append("snapshot_contract")
                    failure_counts["snapshot_contract"] = sum(
                        failures[rule_name] for rule_name in failed_snapshot_rules
                    )
                missing_count, extra_count, output_samples = _output_reference_differences(
                    connection=connection,
                    target_path=target_path,
                    reference_path=reference.path,
                )
                if missing_count or extra_count:
                    failed_rule_names.append("output_reference_two_way_mapping")
                    failure_counts["output_reference_two_way_mapping"] = (
                        missing_count + extra_count
                    )
                    failure_samples.extend(output_samples)
        except Exception as error:  # noqa: BLE001 - corrupt files must report a failed check.
            failed_rule_names.append("snapshot_readable")
            failure_counts["snapshot_readable"] = 1
            failure_samples.append({"error_type": type(error).__name__})

    deduplicated_rules = list(dict.fromkeys(failed_rule_names))
    failed_row_count = sum(failure_counts.values())
    return dg.AssetCheckResult(
        passed=not deduplicated_rules,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            file_path=target_path,
            missing_file_paths=[target_path] if not target_path.is_file() else [],
            extra_metadata={
                "summary": (
                    "东方财富行业层级快照通过核心契约检查。"
                    if not deduplicated_rules
                    else "东方财富行业层级快照未通过核心契约检查，请先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，快照可供板块行业层级分析使用。"
                    if not deduplicated_rules
                    else "修复 seed、指定日期的 dc_index 目录或快照文件后，重新运行手动更新 job。"
                ),
                "rule_summary": [
                    "file_exists",
                    "materialization_reference_metadata",
                    "reference_file_contract",
                    "seed_reference_two_way_mapping",
                    "snapshot_contract",
                    "output_reference_two_way_mapping",
                ],
                "failed_rule_names": deduplicated_rules,
                "failure_counts": failure_counts,
                "failure_samples": failure_samples[:20],
            },
        ),
    )


__all__ = ["silver_dc_industry_hierarchy_core_check"]
