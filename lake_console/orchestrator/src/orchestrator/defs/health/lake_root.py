from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from orchestrator.defs.duckdb_connection import DEFAULT_DUCKDB_TEMP_DIRECTORY
from orchestrator.defs.paths import GOLD, RAW, SILVER


GIB = 1024**3
LAKE_ROOT_TMP_DIR = "_tmp"
LAKE_ROOT_HEALTH_DIR = "lake_root_health"
LAKE_ROOT_HEALTH_CANARY_PREFIX = "canary-"
LAKE_ROOT_MIN_FREE_GIB = 64
DUCKDB_TEMP_MIN_FREE_GIB = 64
LAKE_ROOT_MIN_FREE_BYTES = LAKE_ROOT_MIN_FREE_GIB * GIB
DUCKDB_TEMP_MIN_FREE_BYTES = DUCKDB_TEMP_MIN_FREE_GIB * GIB


@dataclass(frozen=True)
class CanaryCheckResult:
    passed: bool
    path: Path
    error: str | None = None


@dataclass(frozen=True)
class LakeRootHealthStatus:
    lake_root: Path
    duckdb_temp_directory: Path
    checked_at: str
    required_paths: tuple[Path, ...]
    missing_required_paths: tuple[Path, ...]
    non_directory_required_paths: tuple[Path, ...]
    lake_root_tmp_path: Path
    lake_root_canary_path: Path | None
    lake_root_canary_error: str | None
    lake_root_free_bytes: int | None
    duckdb_temp_free_bytes: int | None
    duckdb_temp_canary_path: Path | None
    duckdb_temp_canary_error: str | None
    duckdb_temp_directory_error: str | None
    min_lake_root_free_bytes: int
    min_duckdb_temp_free_bytes: int
    required_paths_ready: bool
    lake_root_read_write_ready: bool
    lake_root_disk_space_ready: bool
    duckdb_temp_directory_ready: bool
    check_disk_space: bool
    check_duckdb_temp: bool
    failure_reasons: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return (
            self.required_paths_ready
            and self.lake_root_read_write_ready
            and self.lake_root_disk_space_ready
            and self.duckdb_temp_directory_ready
        )

    @property
    def run_available(self) -> bool:
        return self.required_paths_ready and self.lake_root_read_write_ready

    def metadata(self) -> dict[str, Any]:
        return {
            "summary": _health_summary(self),
            "next_action": _health_next_action(self),
            "result_status": "healthy" if self.healthy else "failed",
            "component_status": _component_status(self),
            "diagnostic_ref": (
                "完整诊断看 missing_required_paths、non_directory_required_paths、"
                "lake_root_canary_error、free_gib 和 failure_reasons。"
            ),
            "health_status": "healthy" if self.healthy else "failed",
            "checked_at": self.checked_at,
            "lake_root": str(self.lake_root),
            "required_paths": [str(path) for path in self.required_paths],
            "missing_required_paths": [
                str(path) for path in self.missing_required_paths
            ],
            "non_directory_required_paths": [
                str(path) for path in self.non_directory_required_paths
            ],
            "lake_root_tmp_path": str(self.lake_root_tmp_path),
            "lake_root_canary_path": (
                str(self.lake_root_canary_path)
                if self.lake_root_canary_path is not None
                else ""
            ),
            "lake_root_canary_error": self.lake_root_canary_error or "",
            "lake_root_free_bytes": _metadata_int(self.lake_root_free_bytes),
            "lake_root_free_gib": _bytes_to_gib(self.lake_root_free_bytes),
            "lake_root_min_free_bytes": self.min_lake_root_free_bytes,
            "lake_root_min_free_gib": _bytes_to_gib(self.min_lake_root_free_bytes),
            "duckdb_temp_directory": str(self.duckdb_temp_directory),
            "duckdb_temp_directory_error": self.duckdb_temp_directory_error or "",
            "duckdb_temp_canary_path": (
                str(self.duckdb_temp_canary_path)
                if self.duckdb_temp_canary_path is not None
                else ""
            ),
            "duckdb_temp_canary_error": self.duckdb_temp_canary_error or "",
            "duckdb_temp_free_bytes": _metadata_int(self.duckdb_temp_free_bytes),
            "duckdb_temp_free_gib": _bytes_to_gib(self.duckdb_temp_free_bytes),
            "duckdb_temp_min_free_bytes": self.min_duckdb_temp_free_bytes,
            "duckdb_temp_min_free_gib": _bytes_to_gib(
                self.min_duckdb_temp_free_bytes
            ),
            "required_paths_ready": self.required_paths_ready,
            "lake_root_read_write_ready": self.lake_root_read_write_ready,
            "lake_root_disk_space_ready": self.lake_root_disk_space_ready,
            "duckdb_temp_directory_ready": self.duckdb_temp_directory_ready,
            "check_disk_space": self.check_disk_space,
            "check_duckdb_temp": self.check_duckdb_temp,
            "failure_reasons": list(self.failure_reasons),
        }


def _component_status(status: LakeRootHealthStatus) -> dict[str, bool]:
    return {
        "required_paths_ready": status.required_paths_ready,
        "lake_root_read_write_ready": status.lake_root_read_write_ready,
        "lake_root_disk_space_ready": status.lake_root_disk_space_ready,
        "duckdb_temp_directory_ready": status.duckdb_temp_directory_ready,
    }


def _health_summary(status: LakeRootHealthStatus) -> str:
    if status.healthy:
        return (
            "Lake root 平台健康检查通过：必要目录、读写 canary、磁盘空间和 "
            "DuckDB temp 均可用。"
        )
    failed_components = [
        label
        for reason, label in (
            ("required_paths_not_ready", "必要目录未就绪"),
            ("lake_root_tmp_not_ready", "临时目录未就绪"),
            ("lake_root_read_write_not_ready", "lake root 读写 canary 失败"),
            ("lake_root_disk_space_below_threshold", "lake root 磁盘空间不足"),
            ("duckdb_temp_directory_not_ready", "DuckDB temp 不可用"),
        )
        if reason in status.failure_reasons
    ]
    if not failed_components:
        return "Lake root 平台健康检查失败：存在未归类的健康问题。"
    return f"Lake root 平台健康检查失败：{', '.join(failed_components)}。"


def _health_next_action(status: LakeRootHealthStatus) -> str:
    if status.healthy:
        return "无需处理；可以继续依赖 lake_root_health_ready 作为平台健康门禁。"

    action_by_reason = {
        "required_paths_not_ready": (
            "先修复 missing_required_paths / non_directory_required_paths "
            "中列出的目录。"
        ),
        "lake_root_tmp_not_ready": (
            "先修复 lake_root_tmp_path，使健康检查可以创建临时目录。"
        ),
        "lake_root_read_write_not_ready": (
            "先修复 lake root canary 读写权限或挂载状态。"
        ),
        "lake_root_disk_space_below_threshold": (
            "先释放 lake root 磁盘空间或调整正式容量阈值。"
        ),
        "duckdb_temp_directory_not_ready": (
            "先修复 DuckDB temp 目录、权限或空间。"
        ),
    }
    for reason in status.failure_reasons:
        action = action_by_reason.get(reason)
        if action is not None:
            return action
    return "先查看 failure_reasons、canary_error 和路径字段定位平台健康问题。"


def evaluate_lake_root_health(
    *,
    lake_root: str | Path,
    duckdb_temp_directory: str | Path = DEFAULT_DUCKDB_TEMP_DIRECTORY,
    min_lake_root_free_bytes: int = LAKE_ROOT_MIN_FREE_BYTES,
    min_duckdb_temp_free_bytes: int = DUCKDB_TEMP_MIN_FREE_BYTES,
    check_disk_space: bool = True,
    check_duckdb_temp: bool = True,
) -> LakeRootHealthStatus:
    root = Path(lake_root)
    duckdb_temp = Path(duckdb_temp_directory)
    checked_at = datetime.now(UTC).isoformat()
    lake_root_tmp = root / LAKE_ROOT_TMP_DIR

    required_paths = (
        root,
        root / RAW,
        root / SILVER,
        root / GOLD,
        lake_root_tmp,
    )
    missing_paths: list[Path] = []
    non_directory_paths: list[Path] = []
    failure_reasons: list[str] = []

    for path in required_paths[:-1]:
        if not path.exists():
            missing_paths.append(path)
        elif not path.is_dir():
            non_directory_paths.append(path)

    tmp_error = _ensure_directory(lake_root_tmp) if root.is_dir() else "lake root is not a directory"
    if tmp_error is not None:
        failure_reasons.append("lake_root_tmp_not_ready")
        if lake_root_tmp.exists() and not lake_root_tmp.is_dir():
            non_directory_paths.append(lake_root_tmp)
        elif not lake_root_tmp.exists():
            missing_paths.append(lake_root_tmp)

    required_paths_ready = not missing_paths and not non_directory_paths
    if not required_paths_ready:
        failure_reasons.append("required_paths_not_ready")

    lake_root_canary = _failed_canary(lake_root_tmp / LAKE_ROOT_HEALTH_DIR)
    if required_paths_ready:
        lake_root_canary_dir = lake_root_tmp / LAKE_ROOT_HEALTH_DIR
        canary_dir_error = _ensure_directory(lake_root_canary_dir)
        if canary_dir_error is None:
            lake_root_canary = _run_canary_check(lake_root_canary_dir)
        else:
            lake_root_canary = CanaryCheckResult(
                passed=False,
                path=lake_root_canary_dir,
                error=canary_dir_error,
            )

    lake_root_read_write_ready = lake_root_canary.passed
    if not lake_root_read_write_ready:
        failure_reasons.append("lake_root_read_write_not_ready")

    lake_root_free_bytes = _disk_free_bytes(root) if check_disk_space and root.exists() else None
    lake_root_disk_space_ready = True
    if check_disk_space:
        lake_root_disk_space_ready = (
            lake_root_free_bytes is not None
            and lake_root_free_bytes >= min_lake_root_free_bytes
        )
        if not lake_root_disk_space_ready:
            failure_reasons.append("lake_root_disk_space_below_threshold")

    duckdb_temp_error = None
    duckdb_temp_canary = _failed_canary(duckdb_temp)
    duckdb_temp_free_bytes = None
    duckdb_temp_directory_ready = True
    if check_duckdb_temp:
        duckdb_temp_error = _ensure_directory(duckdb_temp)
        if duckdb_temp_error is None:
            duckdb_temp_canary = _run_canary_check(duckdb_temp)
            duckdb_temp_free_bytes = (
                _disk_free_bytes(duckdb_temp) if check_disk_space else None
            )
        duckdb_temp_directory_ready = (
            duckdb_temp_error is None
            and duckdb_temp_canary.passed
            and (
                not check_disk_space
                or (
                    duckdb_temp_free_bytes is not None
                    and duckdb_temp_free_bytes >= min_duckdb_temp_free_bytes
                )
            )
        )
        if not duckdb_temp_directory_ready:
            failure_reasons.append("duckdb_temp_directory_not_ready")

    return LakeRootHealthStatus(
        lake_root=root,
        duckdb_temp_directory=duckdb_temp,
        checked_at=checked_at,
        required_paths=required_paths,
        missing_required_paths=tuple(missing_paths),
        non_directory_required_paths=tuple(non_directory_paths),
        lake_root_tmp_path=lake_root_tmp,
        lake_root_canary_path=lake_root_canary.path,
        lake_root_canary_error=lake_root_canary.error,
        lake_root_free_bytes=lake_root_free_bytes,
        duckdb_temp_free_bytes=duckdb_temp_free_bytes,
        duckdb_temp_canary_path=duckdb_temp_canary.path,
        duckdb_temp_canary_error=duckdb_temp_canary.error,
        duckdb_temp_directory_error=duckdb_temp_error,
        min_lake_root_free_bytes=min_lake_root_free_bytes,
        min_duckdb_temp_free_bytes=min_duckdb_temp_free_bytes,
        required_paths_ready=required_paths_ready,
        lake_root_read_write_ready=lake_root_read_write_ready,
        lake_root_disk_space_ready=lake_root_disk_space_ready,
        duckdb_temp_directory_ready=duckdb_temp_directory_ready,
        check_disk_space=check_disk_space,
        check_duckdb_temp=check_duckdb_temp,
        failure_reasons=tuple(dict.fromkeys(failure_reasons)),
    )


def assert_lake_root_available_for_run(lake_root: str | Path) -> None:
    status = evaluate_lake_root_health(
        lake_root=lake_root,
        check_disk_space=False,
        check_duckdb_temp=False,
    )
    if status.run_available:
        return

    metadata = status.metadata()
    raise RuntimeError(
        "Lake root is not ready for this run. "
        f"failure_reasons={metadata['failure_reasons']} "
        f"missing_required_paths={metadata['missing_required_paths']} "
        f"non_directory_required_paths={metadata['non_directory_required_paths']} "
        f"lake_root_canary_error={metadata['lake_root_canary_error']}"
    )


def _ensure_directory(path: Path) -> str | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return str(error)
    if not path.is_dir():
        return f"{path} is not a directory"
    return None


def _run_canary_check(directory: Path) -> CanaryCheckResult:
    token = uuid4().hex
    path = directory / f"{LAKE_ROOT_HEALTH_CANARY_PREFIX}{token}.txt"
    content = f"goldenshare-lake-root-health:{token}\n"
    error_message: str | None = None

    try:
        _write_canary_file(path, content)
        observed = _read_canary_file(path)
        if observed != content:
            error_message = "canary read content mismatch"
    except OSError as error:
        error_message = str(error)
    finally:
        if path.exists():
            try:
                _delete_canary_file(path)
            except OSError as error:
                cleanup_error = f"canary cleanup failed: {error}"
                error_message = (
                    cleanup_error
                    if error_message is None
                    else f"{error_message}; {cleanup_error}"
                )

    return CanaryCheckResult(
        passed=error_message is None,
        path=path,
        error=error_message,
    )


def _failed_canary(path: Path) -> CanaryCheckResult:
    return CanaryCheckResult(passed=False, path=path, error="canary was not run")


def _write_canary_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _read_canary_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _delete_canary_file(path: Path) -> None:
    path.unlink()


def _disk_free_bytes(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _bytes_to_gib(value: int | None) -> float:
    if value is None:
        return -1.0
    return round(value / GIB, 3)


def _metadata_int(value: int | None) -> int:
    return -1 if value is None else value
