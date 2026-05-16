from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from lake_console.backend.app.services.duckdb_compute_plan_service import (
    _json_text,
    _relpath,
    _source_item,
    _utc_now_iso,
    _write_json_atomic,
    _write_parquet_manifest,
)
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.settings import LakeConsoleSettings


ProgressCallback = Callable[[dict[str, Any]], None]

AUDIT_LEDGER_COLUMNS = [
    "run_id",
    "partition_key",
    "issue_code",
    "severity",
    "candidate_part_path",
    "message",
    "expected_value",
    "actual_value",
    "observed_at",
]

EXPECTED_QFQ_CANDIDATE_COLUMNS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "exchange",
    "vwap",
)


class DuckDbComputeAuditService:
    """Audit staged DuckDB candidate parts without publishing formal Lake data."""

    def __init__(self, *, settings: LakeConsoleSettings) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root.resolve()

    def audit_stk_mins_qfq_candidates(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        manifest_root = self._manifest_root(run_id)
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        run_payload = _read_json(manifest_root / "run.json")
        if run_payload.get("job_type") != "stk_mins_qfq_clean_next":
            raise RuntimeError(f"不支持的 job_type：{run_payload.get('job_type')}")
        if run_payload.get("status") not in {"compute_completed", "audit_running", "blocked", "prewrite_backup"}:
            raise RuntimeError(f"当前 run 状态不能进入 M3-A candidate audit：{run_payload.get('status')}")

        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        lock_acquired: dict[str, Any] | None = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            run_payload = {
                **run_payload,
                "status": "audit_running",
                "m3a_started_at": _utc_now_iso(),
                "finished_at": None,
                "error": None,
            }
            _write_json_atomic(manifest_root / "run.json", run_payload)
            _append_audit_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "candidate_audit_started",
                    "level": "info",
                    "message": "M3-A 开始 candidate_part 汇总与审计；不发布正式分区，不写 formal gate。",
                },
            )

            units = _read_manifest_rows(manifest_root / "units.parquet")
            candidate_parts = _read_manifest_rows(manifest_root / "candidate_parts.parquet")
            publish_partitions = _read_manifest_rows(manifest_root / "publish_partitions.parquet")
            issues: list[dict[str, Any]] = []
            issues.extend(self._audit_input_snapshot(run_payload=run_payload))
            candidate_by_path = _candidate_rows_by_path(candidate_parts, issues=issues, run_id=run_id)
            units_by_partition = _units_by_partition(units)

            audited_publish_partitions: list[dict[str, Any]] = []
            for index, partition in enumerate(publish_partitions, start=1):
                partition_key = str(partition["partition_key"])
                _emit_progress(
                    progress_callback,
                    {
                        "event": "partition_audit_started",
                        "run_id": run_id,
                        "partition_index": index,
                        "partition_count": len(publish_partitions),
                        "partition_key": partition_key,
                    },
                )
                partition_issues = self._audit_publish_partition(
                    run_id=run_id,
                    partition=partition,
                    candidate_by_path=candidate_by_path,
                    units=units_by_partition.get(partition_key, []),
                )
                issues.extend(partition_issues)
                expected_paths = _json_array(partition.get("expected_candidate_part_paths_json"))
                audit_passed = not partition_issues and not any(issue["partition_key"] in {"__run__", partition_key} for issue in issues)
                audited_publish_partitions.append(
                    {
                        **partition,
                        "source_candidate_parts_json": _json_text(expected_paths if audit_passed else []),
                        "audit_status": "passed" if audit_passed else "failed",
                        "publish_status": "audit_passed" if audit_passed else "blocked",
                    }
                )
                _emit_progress(
                    progress_callback,
                    {
                        "event": "partition_audit_finished",
                        "run_id": run_id,
                        "partition_index": index,
                        "partition_count": len(publish_partitions),
                        "partition_key": partition_key,
                        "issue_count": len(partition_issues),
                    },
                )

            _write_audit_ledger(manifest_root / "audit_ledger.parquet", issues)
            _write_publish_partitions_manifest(manifest_root / "publish_partitions.parquet", audited_publish_partitions)

            status = "prewrite_backup" if not issues else "blocked"
            metrics = {
                "publish_partition_count": len(publish_partitions),
                "candidate_part_count": len(candidate_parts),
                "issue_count": len(issues),
                "passed_partition_count": len(
                    [row for row in audited_publish_partitions if row.get("audit_status") == "passed"]
                ),
                "blocked_partition_count": len(
                    [row for row in audited_publish_partitions if row.get("audit_status") != "passed"]
                ),
            }
            run_payload = {
                **run_payload,
                "status": status,
                "m3a_finished_at": _utc_now_iso(),
                "finished_at": None,
                "m3a_metrics": metrics,
            }
            if issues:
                run_payload["error"] = {
                    "error_code": "LC_COMPUTE_CANDIDATE_AUDIT_FAILED",
                    "stage": "candidate_audit",
                    "message_for_human": "candidate 审计未通过，正式数据未被修改。",
                    "technical_detail": f"issue_count={len(issues)}",
                }
            _write_json_atomic(manifest_root / "run.json", run_payload)
            _append_audit_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "candidate_audit_finished",
                    "level": "info" if not issues else "error",
                    "message": (
                        "M3-A candidate 审计通过，下一步可以进入 Kopia 写前备份。"
                        if not issues
                        else "M3-A candidate 审计未通过，正式数据未被修改。"
                    ),
                    "metrics": metrics,
                },
            )
            return {
                "run_id": run_id,
                "status": status,
                "manifest_root": _relpath(manifest_root, self.lake_root),
                "audit_ledger": _relpath(manifest_root / "audit_ledger.parquet", self.lake_root),
                "metrics": metrics,
                "formal_paths_touched": [],
                "lock_acquired": lock_acquired,
                "lock_after": None,
            }
        finally:
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)

    def _audit_input_snapshot(self, *, run_payload: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for source_item in run_payload.get("input_snapshot", {}).get("source_items") or []:
            source_role = str(source_item.get("source_role") or "")
            raw_path = str(source_item.get("path") or "")
            raw_files = source_item.get("files") or []
            if not raw_path:
                issues.append(_issue(run_id=str(run_payload["run_id"]), code="input_snapshot_missing_path", message="input snapshot 缺少 path。"))
                continue
            file_paths = [self.lake_root / str(file.get("path") or "") for file in raw_files]
            missing_files = [path for path in file_paths if not path.exists()]
            if missing_files:
                issues.append(
                    _issue(
                        run_id=str(run_payload["run_id"]),
                        code="input_snapshot_file_missing",
                        message="input snapshot 中的源文件已缺失。",
                        candidate_part_path=", ".join(_relpath(path, self.lake_root) for path in missing_files[:5]),
                    )
                )
                continue
            current = _source_item(source_role, self.lake_root / raw_path, file_paths, self.lake_root)
            if current.get("metadata_signature") != source_item.get("metadata_signature"):
                issues.append(
                    _issue(
                        run_id=str(run_payload["run_id"]),
                        code="input_snapshot_changed",
                        message=f"输入源已变化，本次 candidate 作废：source_role={source_role} path={raw_path}",
                        expected=source_item.get("metadata_signature"),
                        actual=current.get("metadata_signature"),
                    )
                )
        return issues

    def _audit_publish_partition(
        self,
        *,
        run_id: str,
        partition: dict[str, Any],
        candidate_by_path: dict[str, dict[str, Any]],
        units: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        partition_key = str(partition["partition_key"])
        issues: list[dict[str, Any]] = []
        expected_paths = _json_array(partition.get("expected_candidate_part_paths_json"))
        if not expected_paths:
            issues.append(_issue(run_id=run_id, partition_key=partition_key, code="missing_expected_candidate_paths", message="publish partition 缺少 expected candidate part 清单。"))
            return issues

        unit_statuses = {str(unit.get("status") or "") for unit in units}
        if unit_statuses != {"succeeded"}:
            issues.append(
                _issue(
                    run_id=run_id,
                    partition_key=partition_key,
                    code="compute_unit_not_succeeded",
                    message=f"该发布分区仍存在未成功的 compute unit：statuses={sorted(unit_statuses)}",
                )
            )

        candidate_paths: list[Path] = []
        candidate_row_total = 0
        for raw_path in expected_paths:
            candidate = candidate_by_path.get(raw_path)
            if candidate is None:
                issues.append(
                    _issue(
                        run_id=run_id,
                        partition_key=partition_key,
                        code="candidate_part_missing_from_manifest",
                        message="candidate_part manifest 缺少预期路径。",
                        candidate_part_path=raw_path,
                    )
                )
                continue
            if str(candidate.get("status") or "") != "staged":
                issues.append(
                    _issue(
                        run_id=run_id,
                        partition_key=partition_key,
                        code="candidate_part_not_staged",
                        message="candidate_part 状态不是 staged。",
                        candidate_part_path=raw_path,
                        actual=candidate.get("status"),
                    )
                )
                continue
            path = _resolve_candidate_part(self.lake_root, run_id, raw_path)
            if not path.exists():
                issues.append(
                    _issue(
                        run_id=run_id,
                        partition_key=partition_key,
                        code="candidate_part_file_missing",
                        message="candidate_part 文件不存在。",
                        candidate_part_path=raw_path,
                    )
                )
                continue
            file_audit = _audit_candidate_file(path=path, lake_root=self.lake_root, candidate=candidate, run_id=run_id, partition_key=partition_key)
            issues.extend(file_audit["issues"])
            candidate_row_total += int(file_audit["row_count"])
            candidate_paths.append(path)

        expected_source_rows = _expected_source_rows(units=units, lake_root=self.lake_root)
        if expected_source_rows is not None and candidate_row_total != expected_source_rows:
            issues.append(
                _issue(
                    run_id=run_id,
                    partition_key=partition_key,
                    code="candidate_row_count_mismatch",
                    message="candidate 行数与源 clean_next 分区行数不一致。",
                    expected=expected_source_rows,
                    actual=candidate_row_total,
                )
            )
        if candidate_paths:
            issues.extend(_audit_candidate_duplicates(run_id=run_id, partition_key=partition_key, paths=candidate_paths))
        return issues

    def _manifest_root(self, run_id: str) -> Path:
        return self.lake_root / "manifest" / "duckdb_compute" / "runs" / run_id


def _audit_candidate_file(*, path: Path, lake_root: Path, candidate: dict[str, Any], run_id: str, partition_key: str) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    metadata = _parquet_metadata(path)
    actual_columns = tuple(metadata["columns"])
    rel_path = _relpath(path, lake_root)
    if actual_columns != EXPECTED_QFQ_CANDIDATE_COLUMNS:
        issues.append(
            _issue(
                run_id=run_id,
                partition_key=partition_key,
                code="candidate_schema_mismatch",
                message="candidate_part schema 与 qfq clean_next 候选口径不一致。",
                candidate_part_path=rel_path,
                expected=list(EXPECTED_QFQ_CANDIDATE_COLUMNS),
                actual=list(actual_columns),
            )
        )
    actual_row_count = int(metadata["row_count"])
    expected_row_count = int(candidate.get("row_count") or 0)
    if actual_row_count != expected_row_count:
        issues.append(
            _issue(
                run_id=run_id,
                partition_key=partition_key,
                code="candidate_file_row_count_mismatch",
                message="candidate_part 文件行数与 manifest 不一致。",
                candidate_part_path=rel_path,
                expected=expected_row_count,
                actual=actual_row_count,
            )
        )
    actual_byte_count = path.stat().st_size
    expected_byte_count = int(candidate.get("byte_count") or 0)
    if actual_byte_count != expected_byte_count:
        issues.append(
            _issue(
                run_id=run_id,
                partition_key=partition_key,
                code="candidate_file_byte_count_mismatch",
                message="candidate_part 文件大小与 manifest 不一致。",
                candidate_part_path=rel_path,
                expected=expected_byte_count,
                actual=actual_byte_count,
            )
        )
    actual_checksum = _sha256_file(path)
    if actual_checksum != candidate.get("checksum"):
        issues.append(
            _issue(
                run_id=run_id,
                partition_key=partition_key,
                code="candidate_file_checksum_mismatch",
                message="candidate_part checksum 与 manifest 不一致。",
                candidate_part_path=rel_path,
                expected=candidate.get("checksum"),
                actual=actual_checksum,
            )
        )
    return {"issues": issues, "row_count": actual_row_count}


def _audit_candidate_duplicates(*, run_id: str, partition_key: str, paths: list[Path]) -> list[dict[str, Any]]:
    duckdb = _require_duckdb()
    connection = duckdb.connect(database=":memory:")
    try:
        duplicate_count = connection.execute(
            """
            select count(*) from (
                select ts_code, cast(freq as integer) as freq, cast(trade_time as timestamp) as trade_time, count(*) as row_count
                from read_parquet(?, hive_partitioning=false)
                group by 1, 2, 3
                having count(*) > 1
            )
            """,
            [[str(path) for path in paths]],
        ).fetchone()[0]
    finally:
        connection.close()
    if int(duplicate_count or 0) == 0:
        return []
    return [
        _issue(
            run_id=run_id,
            partition_key=partition_key,
            code="candidate_duplicate_key",
            message="candidate 分区存在重复 key：ts_code + freq + trade_time。",
            actual=int(duplicate_count),
        )
    ]


def _expected_source_rows(*, units: list[dict[str, Any]], lake_root: Path) -> int | None:
    if not units:
        return None
    input_paths = _json_object(units[0].get("input_paths_json"))
    clean_paths = input_paths.get("clean_next") or []
    if not clean_paths:
        return None
    return sum(_parquet_metadata(lake_root / str(path))["row_count"] for path in clean_paths)


def _candidate_rows_by_path(candidate_parts: list[dict[str, Any]], *, issues: list[dict[str, Any]], run_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    seen_units: set[str] = set()
    for row in candidate_parts:
        raw_path = str(row.get("candidate_part_path") or "")
        unit_key = str(row.get("unit_key") or "")
        if unit_key in seen_units:
            issues.append(_issue(run_id=run_id, code="duplicate_candidate_unit", message=f"candidate_part manifest 存在重复 unit_key：{unit_key}"))
        seen_units.add(unit_key)
        if not raw_path:
            issues.append(_issue(run_id=run_id, code="candidate_part_missing_path", message=f"candidate_part manifest 缺少路径：unit_key={unit_key}"))
            continue
        if raw_path in result:
            issues.append(_issue(run_id=run_id, code="duplicate_candidate_path", message=f"candidate_part manifest 存在重复路径：{raw_path}", candidate_part_path=raw_path))
        result[raw_path] = row
    return result


def _units_by_partition(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        result.setdefault(str(unit.get("publish_partition_key") or ""), []).append(unit)
    return result


def _resolve_candidate_part(lake_root: Path, run_id: str, raw_path: str) -> Path:
    path = (lake_root / raw_path).resolve()
    allowed_root = (lake_root / "_tmp" / "duckdb_compute" / run_id / "candidate_parts").resolve()
    if path != allowed_root and allowed_root not in path.parents:
        raise RuntimeError(f"candidate_part 路径越界，拒绝审计：{raw_path}")
    return path


def _write_audit_ledger(path: Path, issues: list[dict[str, Any]]) -> None:
    _write_parquet_manifest(path, [_project_issue(row) for row in issues], columns=AUDIT_LEDGER_COLUMNS)


def _write_publish_partitions_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_parquet_manifest(
        path,
        [_publish_partition_manifest_row(row) for row in rows],
        columns=[
            "run_id",
            "partition_key",
            "source_candidate_parts_json",
            "expected_candidate_part_paths_json",
            "expected_candidate_part_count",
            "target_path",
            "audit_status",
            "publish_status",
        ],
    )


def _publish_partition_manifest_row(partition: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": partition["run_id"],
        "partition_key": partition["partition_key"],
        "source_candidate_parts_json": _ensure_json_text(partition.get("source_candidate_parts_json") or []),
        "expected_candidate_part_paths_json": _ensure_json_text(partition.get("expected_candidate_part_paths_json") or []),
        "expected_candidate_part_count": int(partition.get("expected_candidate_part_count") or 0),
        "target_path": partition["target_path"],
        "audit_status": partition["audit_status"],
        "publish_status": partition["publish_status"],
    }


def _issue(
    *,
    run_id: str,
    code: str,
    message: str,
    partition_key: str = "__run__",
    candidate_part_path: str | None = None,
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "partition_key": partition_key,
        "issue_code": code,
        "severity": "block",
        "candidate_part_path": candidate_part_path,
        "message": message,
        "expected_value": _json_text(expected) if expected is not None else None,
        "actual_value": _json_text(actual) if actual is not None else None,
        "observed_at": _utc_now_iso(),
    }


def _project_issue(row: dict[str, Any]) -> dict[str, Any]:
    return {column: row.get(column) for column in AUDIT_LEDGER_COLUMNS}


def _parquet_metadata(path: Path) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 pyarrow 依赖，无法读取 Parquet metadata。") from exc
    parquet_file = pq.ParquetFile(path)
    return {
        "row_count": int(parquet_file.metadata.num_rows),
        "columns": [field.name for field in parquet_file.schema_arrow],
    }


def _read_manifest_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("缺少 Parquet 读取依赖，请先安装 lake_console/backend/requirements.txt。") from exc
    if not path.exists():
        raise FileNotFoundError(f"缺少 run manifest 文件：{path}")
    frame = pd.read_parquet(path, engine="pyarrow")
    return [dict(row) for row in frame.to_dict(orient="records")]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON manifest 格式非法：{path}")
    return payload


def _append_audit_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = 1
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    seq = max(seq, int(json.loads(line).get("seq", 0)) + 1)
    payload = {"seq": seq, "created_at": _utc_now_iso(), **event}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _json_array(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(item) for item in json.loads(str(value))]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    payload = json.loads(str(value))
    if not isinstance(payload, dict):
        return {}
    return payload


def _ensure_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return _json_text(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _emit_progress(progress_callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if progress_callback is not None:
        progress_callback(payload)


def _require_duckdb():  # type: ignore[no-untyped-def]
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 duckdb 依赖，请先安装 lake_console/backend/requirements.txt。") from exc
    return duckdb
