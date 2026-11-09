"""Plan, build and register the historical quantitative structure dataset."""

import argparse
import hashlib
import json
import os
import shutil
from datetime import date, datetime
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.scheduler.instigation import InstigatorType
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.checks.major_index_quantitative_structure_checks import (
    structure_check_metadata,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.health.lake_root import assert_lake_root_available_for_run
from orchestrator.defs.io.major_index_quantitative_structure import (
    calculate_structure_days,
    expected_structure_keys,
    structure_algorithm_version,
    structure_materialization_metadata,
    structure_source_paths,
    structure_trade_dates,
    structure_writer_lock,
    write_structure_day,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_major_index_quantitative_structure_path,
    gold_major_index_quantitative_structure_staging_dir,
    quantitative_structure_staging_root,
)
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_ASSET,
    STRUCTURE_CHECKS,
    STRUCTURE_DATASET,
    STRUCTURE_PARTITIONS,
    STRUCTURE_START,
)
from orchestrator.defs.run_contracts.metadata import CheckScope
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

ASSET_KEY = dg.AssetKey(STRUCTURE_ASSET)
CHECK_KEYS = [dg.AssetCheckKey(ASSET_KEY, check) for check in STRUCTURE_CHECKS]
SENSOR_NAMES = (
    f"{STRUCTURE_DATASET}_trade_day_sensor",
    f"{STRUCTURE_ASSET}_update_job_sensor",
)


def _plan_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_suffix(".tmp")
    candidate.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(candidate, path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_plan(path: Path, approved_id: str | None = None) -> dict:
    payload = _read_json(path)
    plan_id = payload.pop("plan_id")
    if _plan_digest(payload) != plan_id or (approved_id is not None and approved_id != plan_id):
        raise ValueError("报告内容与计划标识不一致")
    return {**payload, "plan_id": plan_id}


def _batches(rows):
    for _, month in groupby(rows, key=lambda row: row["trade_date"][:7]):
        yield list(month)


def _existing_targets(lake_root: Path) -> set[str]:
    root = gold_major_index_quantitative_structure_path(lake_root, STRUCTURE_START.isoformat())
    return {str(path) for path in root.parent.parent.glob("trade_date=*/part-000.parquet")}


def plan_structure_history(connection, lake_root: Path, through: date, *, replace_all: bool) -> dict:
    days = structure_trade_dates(connection, lake_root, through)
    if not days or days[-1] != through:
        raise ValueError("历史截止日必须是计算范围内的 SSE 开市日")
    existing = _existing_targets(lake_root)
    partitions = []
    first_missing = None
    source_bytes = 0
    for day in days:
        day_paths = structure_source_paths(lake_root, day)
        for path in day_paths:
            if path.is_file():
                source_bytes += path.stat().st_size
            elif first_missing is None:
                first_missing = {"trade_date": day.isoformat(), "path": str(path)}
        partitions.append({
            "trade_date": day.isoformat(),
            "inputs": [str(path) for path in day_paths],
            "target": str(gold_major_index_quantitative_structure_path(lake_root, day.isoformat())),
            "input_bar_count": len(expected_structure_keys(day)),
        })
    expected_targets = {row["target"] for row in partitions}
    if replace_all and existing - expected_targets:
        raise ValueError("全量换版的截止日必须覆盖所有已有 Gold 文件")
    payload = {
        "start_date": STRUCTURE_START.isoformat(), "through": through.isoformat(),
        "algorithm_version": structure_algorithm_version(), "replace_all": replace_all,
        "partitions": partitions, "existing_targets": sorted(existing),
        "first_missing_input": first_missing,
        "source_file_count": sum(len(row["inputs"]) for row in partitions),
        "source_file_bytes": source_bytes,
        "input_bar_count": sum(row["input_bar_count"] for row in partitions),
        "output_file_count": len(partitions),
        "free_bytes": shutil.disk_usage(lake_root).free,
    }
    return {**payload, "plan_id": _plan_digest(payload)}


def _require_buildable_plan(plan: dict) -> None:
    if plan["first_missing_input"]:
        raise ValueError(f"历史输入缺失：{plan['first_missing_input']}")
    if plan["existing_targets"] and not plan["replace_all"]:
        raise ValueError("首次初始化计划发现已有正式文件")


def _require_sensors_stopped(instance: dg.DagsterInstance) -> None:
    states = instance.all_instigator_state(instigator_type=InstigatorType.SENSOR)
    running = [state.name for state in states if state.name in SENSOR_NAMES and state.is_running]
    if running:
        raise ValueError(f"历史写入前需停用量化结构 sensor：{running}")


def register_structure_history(instance: dg.DagsterInstance, plan: dict) -> int:
    _require_buildable_plan(plan)
    _require_sensors_stopped(instance)
    expected = {row["trade_date"] for row in plan["partitions"]}
    missing = sorted(expected - set(instance.get_dynamic_partitions(STRUCTURE_PARTITIONS)))
    if missing:
        instance.add_dynamic_partitions(STRUCTURE_PARTITIONS, missing)
    if expected - set(instance.get_dynamic_partitions(STRUCTURE_PARTITIONS)):
        raise ValueError("历史分区登记读回不完整")
    return len(missing)


def _history_progress_path(lake_root: Path, plan: dict) -> Path:
    return gold_major_index_quantitative_structure_staging_dir(
        quantitative_structure_staging_root(lake_root), plan["plan_id"],
    ) / "latest.json"


def build_structure_history(connection, lake_root: Path, plan: dict) -> dict:
    _require_buildable_plan(plan)
    if structure_algorithm_version() != plan["algorithm_version"]:
        raise ValueError("当前算法版本与历史计划不一致")
    progress_path = _history_progress_path(lake_root, plan)
    with structure_writer_lock(quantitative_structure_staging_root(lake_root)):
        if progress_path.exists():
            progress = _read_json(progress_path)
            if (progress["plan_id"], progress["algorithm_version"]) != (
                plan["plan_id"], plan["algorithm_version"],
            ):
                raise ValueError("历史进度与当前计划不一致")
        else:
            if _existing_targets(lake_root) != set(plan["existing_targets"]):
                raise ValueError("正式目标文件集合与历史计划不一致")
            progress = {
                "plan_id": plan["plan_id"], "algorithm_version": plan["algorithm_version"],
                "last_trade_date": None, "row_count": 0, "event_count": 0,
            }
            _write_json(progress_path, progress)
        partitions = plan["partitions"]
        pending = [
            row for row in partitions
            if progress["last_trade_date"] is None or row["trade_date"] > progress["last_trade_date"]
        ]
        if pending:
            days = [date.fromisoformat(row["trade_date"]) for row in partitions]
            computed = calculate_structure_days(
                connection, lake_root, days, first_result_date=date.fromisoformat(pending[0]["trade_date"]),
            )
            for row, structure_day in zip(pending, computed, strict=True):
                target = Path(row["target"])
                write_structure_day(connection, structure_day, staging_dir=progress_path.parent, target=target)
                progress["last_trade_date"] = row["trade_date"]
                progress["row_count"] += 1
                progress["event_count"] += len(structure_day.results)
                _write_json(progress_path, progress)
                print(
                    f"{row['trade_date']} 已写 {progress['row_count']}/{len(partitions)} 日，"
                    f"当日输入 {structure_day.input_bar_count} 根，累计 {progress['event_count']} 个事件",
                    flush=True,
                )
    return progress


def audit_structure_history(connection, lake_root: Path, plan: dict) -> dict:
    progress = _read_json(_history_progress_path(lake_root, plan))
    partitions = plan["partitions"]
    if (progress["plan_id"], progress["algorithm_version"], progress["last_trade_date"]) != (
        plan["plan_id"], plan["algorithm_version"], plan["through"],
    ):
        raise ValueError("历史文件尚未写到批准的截止日")
    if _existing_targets(lake_root) != {row["target"] for row in partitions}:
        raise ValueError("实际历史文件集合与计划不一致")
    audited = []
    for batch in _batches(partitions):
        results = connection.execute(
            """
            SELECT filename, count(*), count(*) FILTER (WHERE success AND results IS NOT NULL),
                   min(trade_date), sum(len(results))
            FROM read_parquet(?, hive_partitioning=false, filename=true)
            GROUP BY filename
            """,
            [[row["target"] for row in batch]],
        ).fetchall()
        files = {path: (count, successes, day.isoformat(), events)
                 for path, count, successes, day, events in results}
        for row in batch:
            count, successes, day, events = files.get(row["target"], (0, 0, None, 0))
            if (count, successes, day) != (1, 1, row["trade_date"]):
                raise ValueError(f"{row['trade_date']} 文件验收失败")
            audited.append({
                "trade_date": day, "target": row["target"], "input_bar_count": row["input_bar_count"],
                "row_count": count, "event_count": events,
            })
    if (len(audited), sum(row["event_count"] for row in audited)) != (
        progress["row_count"], progress["event_count"],
    ):
        raise ValueError("实际历史结果数量与写入进度不一致")
    return {
        "plan_id": plan["plan_id"], "algorithm_version": plan["algorithm_version"],
        "partitions": audited,
    }


def _structure_event_records(instance, rows):
    days = [row["trade_date"] for row in rows]
    ids = instance.event_log_storage.get_latest_storage_id_by_partition(
        ASSET_KEY, dg.DagsterEventType.ASSET_MATERIALIZATION, partitions=set(days),
    )
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=ASSET_KEY, storage_ids=list(ids.values())),
        limit=len(ids),
    ).records if ids else ()
    checks = instance.event_log_storage.get_asset_check_partition_info(CHECK_KEYS, partition_keys=days)
    return {record.partition_key: record for record in records}, {
        (check.partition_key, check.check_key.name): check for check in checks
    }


def _event_actions(rows, plan, records, checks):
    for row in rows:
        day = row["trade_date"]
        current = records.get(day)
        if current:
            metadata = current.asset_materialization.metadata
            expected = structure_materialization_metadata(
                Path(row["target"]), algorithm_version=plan["algorithm_version"],
                input_bar_count=row["input_bar_count"], event_count=row["event_count"],
            )
            mismatches = {
                name for name, value in expected.items()
                if getattr(metadata.get(name), "value", None) != value
            }
            if mismatches:
                if plan["replace_all"] and "goldenshare/formula_version" in mismatches:
                    current = None
                else:
                    raise ValueError(f"{day} 现有 DG 产出与文件验收报告不一致：{sorted(mismatches)}")
        missing = []
        for name in STRUCTURE_CHECKS:
            check = checks.get((day, name))
            if not current or not check or check.latest_target_materialization_storage_id != current.storage_id:
                missing.append(name)
            elif check.latest_execution_status != AssetCheckExecutionRecordStatus.SUCCEEDED:
                raise ValueError(f"{day} 现有检查未通过：{name}")
        yield row, current, missing


def plan_structure_events(instance, plan: dict, audit: dict) -> dict:
    if (audit["plan_id"], audit["algorithm_version"]) != (plan["plan_id"], plan["algorithm_version"]):
        raise ValueError("文件验收报告与历史计划不一致")
    if [row["trade_date"] for row in audit["partitions"]] != [
        row["trade_date"] for row in plan["partitions"]
    ]:
        raise ValueError("文件验收日期与历史计划不一致")
    rows = audit["partitions"]
    materialization_count = check_count = 0
    for batch in _batches(rows):
        records, checks = _structure_event_records(instance, batch)
        for _, materialization, missing in _event_actions(batch, plan, records, checks):
            materialization_count += materialization is None
            check_count += len(missing)
    payload = {
        "history_plan_id": plan["plan_id"], "algorithm_version": plan["algorithm_version"],
        "replace_all": plan["replace_all"], "partitions": rows,
        "materialization_count": materialization_count, "check_count": check_count,
    }
    return {**payload, "plan_id": _plan_digest(payload)}


def _report_structure_checks(instance, row, record, names):
    for name in names:
        scope = CheckScope.SCHEMA if name == STRUCTURE_CHECKS[0] else CheckScope.VALUE_SANITY
        evaluation = dg.AssetCheckEvaluation(
            asset_key=ASSET_KEY, check_name=name, passed=True, blocking=True,
            partition=row["trade_date"],
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id, run_id=record.run_id, timestamp=record.timestamp,
            ),
            metadata=structure_check_metadata(Path(row["target"]), row["trade_date"], scope=scope),
        )
        instance.report_dagster_event(
            run_id=f"{STRUCTURE_DATASET}-history-{record.storage_id}",
            dagster_event=dg.DagsterEvent(
                event_type_value=dg.DagsterEventType.ASSET_CHECK_EVALUATION.value,
                event_specific_data=evaluation, job_name=f"{STRUCTURE_DATASET}_history",
            ),
        )


def report_structure_events(instance, lake_root: Path, plan: dict, *, trade_date: str | None) -> dict:
    _require_sensors_stopped(instance)
    rows = plan["partitions"]
    if trade_date is not None:
        rows = [row for row in rows if row["trade_date"] == trade_date]
        if not rows:
            raise ValueError("补录样本日期不在批准计划中")
    result = {"materialization_count": 0, "check_count": 0}
    with structure_writer_lock(quantitative_structure_staging_root(lake_root)):
        for batch in _batches(rows):
            records, checks = _structure_event_records(instance, batch)
            actions = list(_event_actions(batch, plan, records, checks))
            new_rows = []
            for row, record, _ in actions:
                if record is None:
                    instance.report_runless_asset_event(dg.AssetMaterialization(
                        asset_key=ASSET_KEY, partition=row["trade_date"],
                        metadata=structure_materialization_metadata(
                            Path(row["target"]), algorithm_version=plan["algorithm_version"],
                            input_bar_count=row["input_bar_count"], event_count=row["event_count"],
                        ),
                    ))
                    new_rows.append(row)
            if new_rows:
                latest, _ = _structure_event_records(instance, new_rows)
                records.update(latest)
            for row, _, names in actions:
                if names:
                    _report_structure_checks(instance, row, records[row["trade_date"]], names)
                    result["check_count"] += len(names)
            result["materialization_count"] += len(new_rows)
            audit_structure_events(instance, {**plan, "partitions": batch})
            print(f"DG 事件已核对至 {batch[-1]['trade_date']}，本次累计 {result}", flush=True)
    return result


def audit_structure_events(instance, plan: dict) -> dict:
    for batch in _batches(plan["partitions"]):
        records, checks = _structure_event_records(instance, batch)
        for row, record, missing in _event_actions(batch, plan, records, checks):
            if not record or missing:
                raise ValueError(f"{row['trade_date']} 缺少当前产出或检查：{missing}")
    return {"completed_partition_count": len(plan["partitions"])}


def _sample(connection, lake_root: Path, output_dir: Path) -> dict:
    days = structure_trade_dates(connection, lake_root, datetime.now(CN_A_SENSOR_TIMEZONE).date())[:2]
    rows = []
    for structure_day in calculate_structure_days(connection, lake_root, days, first_result_date=days[0]):
        key = structure_day.trade_date.isoformat()
        target = output_dir / f"trade_date={key}" / "part-000.parquet"
        write_structure_day(connection, structure_day, staging_dir=output_dir / "staging", target=target)
        rows.append({
            "trade_date": key, "input_bar_count": structure_day.input_bar_count,
            "row_count": 1, "event_count": len(structure_day.results), "target": str(target),
        })
    return {"partitions": rows}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample")
    sample.add_argument("--output-dir", type=Path, required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--through", type=date.fromisoformat, required=True)
    plan.add_argument("--replace-all", action="store_true")
    plan.add_argument("--output", type=Path, required=True)
    for name in ("register", "build", "post-audit", "events-plan", "events-apply", "events-audit"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        if name in ("register", "build", "events-apply"):
            command.add_argument("--plan-id", required=True)
            command.add_argument("--apply", action="store_true", required=True)
        if name in ("post-audit", "events-plan"):
            command.add_argument("--output", type=Path, required=True)
        if name == "events-plan":
            command.add_argument("--file-audit", type=Path, required=True)
        if name == "events-apply":
            command.add_argument("--trade-date", type=date.fromisoformat)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    lake_root = Path(DEFAULT_LAKE_ROOT)
    report_path = getattr(args, "output", None)
    if report_path is not None and not report_path.resolve().is_relative_to(Path("/private/tmp")):
        parser.error("--output 必须位于 /private/tmp")
    plan = _load_plan(args.plan, getattr(args, "plan_id", None)) if hasattr(args, "plan") else None
    if args.command == "sample":
        output = args.output_dir.resolve()
        if not output.is_relative_to(Path("/private/tmp")):
            parser.error("sample --output-dir 必须位于 /private/tmp")
        output.mkdir(parents=True, exist_ok=True)
        with connect_configured_duckdb(
            DuckDBConnectionSettings(temp_directory=output), temp_policy="existing_no_spill",
        ) as connection:
            result = _sample(connection, lake_root, output)
    elif args.command == "build":
        assert_lake_root_available_for_run(lake_root)
        with dg.DagsterInstance.get() as instance:
            _require_sensors_stopped(instance)
            registered = set(instance.get_dynamic_partitions(STRUCTURE_PARTITIONS))
            if any(row["trade_date"] not in registered for row in plan["partitions"]):
                raise ValueError("历史计划分区尚未登记")
        with connect_configured_duckdb() as connection:
            result = build_structure_history(connection, lake_root, plan)
    elif args.command in ("plan", "post-audit"):
        with TemporaryDirectory(dir="/private/tmp") as directory, connect_configured_duckdb(
            DuckDBConnectionSettings(temp_directory=Path(directory)), temp_policy="existing_no_spill",
        ) as connection:
            if args.command == "plan":
                result = plan_structure_history(connection, lake_root, args.through, replace_all=args.replace_all)
            else:
                result = audit_structure_history(connection, lake_root, plan)
    else:
        with dg.DagsterInstance.get() as instance:
            if args.command == "register":
                result = {"registered_partition_count": register_structure_history(instance, plan)}
            elif args.command == "events-plan":
                result = plan_structure_events(instance, plan, _read_json(args.file_audit))
            elif args.command == "events-apply":
                trade_date = args.trade_date.isoformat() if args.trade_date else None
                result = report_structure_events(instance, lake_root, plan, trade_date=trade_date)
            else:
                result = audit_structure_events(instance, plan)
    if report_path is not None:
        _write_json(report_path, result)
        result = {
            **{key: value for key, value in result.items() if key not in ("partitions", "existing_targets")},
            "partition_count": len(result["partitions"]),
            "report_path": str(report_path),
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
