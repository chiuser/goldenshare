"""Single-file publication and retained inputs for international-index jobs."""

import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_index_global_path,
    raw_index_global_staging_path,
    silver_index_global_path,
    silver_index_global_staging_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)


def _check_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Index global publication requires an absolute safe path")
    for part in (path, *path.parents):
        if (
            part in (Path("/tmp"), Path("/var"))
            and part.resolve() == Path("/private") / part.name
        ):
            continue
        if part.is_symlink():
            raise ValueError("Index global publication rejects symbolic links")


def _identity(path: Path) -> list[int] | None:
    _check_path(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Index global publication requires regular files")
    value = path.stat()
    return [
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    ]


def _digest(path: Path) -> str:
    _check_path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _encode(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _reject_constant(value: str) -> None:
    raise ValueError(f"Index global control JSON contains invalid {value}")


def _read_json(path: Path) -> dict:
    _check_path(path)
    if not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("Index global control file is absent or oversized")
    value = json.loads(path.read_text(), parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise TypeError("Index global control JSON must be an object")
    return value


def _save_json(path: Path, value: dict, *, exclusive: bool = False) -> None:
    _check_path(path)
    data = _encode(value)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    _check_path(temporary)
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if exclusive and path.exists():
        raise ValueError("Index global frozen input already exists")
    os.replace(temporary, path)
    _sync_directory(path.parent)


class IndexGlobalPublication:
    """Keep one file's validated work and recognize an interrupted rename.

    The caller owns the current business candidate validator. This class owns
    input retention, the target lock and filesystem/checkpoint consistency.
    """

    def __init__(
        self,
        *,
        lake_root_path: Path,
        target_path: Path,
        operation_directory: Path,
        asset_key: str,
        day: str,
        phase: str,
        operation_id: str,
        source_paths: tuple[Path, ...] = (),
    ):
        for path in (lake_root_path, target_path, operation_directory, *source_paths):
            _check_path(Path(path).absolute())
        self.root = Path(lake_root_path).resolve()
        self.target = Path(target_path).resolve()
        self.directory = Path(operation_directory).resolve()
        self.asset_key, self.day, self.phase = asset_key, day, phase
        self.operation_id = operation_id
        self.sources = tuple(Path(path).resolve() for path in source_paths)
        if asset_key == "raw_index_global":
            expected_target = raw_index_global_path(self.root, day)
            expected_directory = raw_index_global_staging_path(
                self.root, operation_id, day, phase
            ).parent
            schema = RAW_INDEX_GLOBAL_SCHEMA
            if self.sources:
                raise ValueError("Index global Raw input must be a frozen phase")
        elif asset_key == "silver_index_global" and phase == "silver":
            expected_target = silver_index_global_path(self.root, day)
            expected_directory = silver_index_global_staging_path(
                self.root, operation_id, day
            ).parent
            schema = SILVER_INDEX_GLOBAL_SCHEMA
            if self.sources != (raw_index_global_path(self.root, day),):
                raise ValueError("Index global Silver must bind its same-day Raw")
        else:
            raise ValueError("Unsupported index global publication asset/phase")
        if self.target != expected_target or self.directory != expected_directory.resolve():
            raise ValueError("Index global target or operation directory differs from scope")
        self.namespace = self.directory.parent.parent
        self.control = self.directory / "operation.json"
        self.input_path = self.directory / "phase_rows.json"
        self.scope = {
            "version": 1,
            "asset_key": asset_key,
            "day": day,
            "phase": phase,
            "operation_id": operation_id,
            "lake_root": str(self.root),
            "target": str(self.target),
            "operation_directory": str(self.directory),
            "schema": [[column.name, column.type] for column in schema],
        }
        self.state: dict = {}
        self._lock: int | None = None

    def __enter__(self):
        if not self.root.is_dir():
            raise ValueError("Index global Lake root must already exist")
        if self.root == Path(DEFAULT_LAKE_ROOT):
            staging_root = Path(DEFAULT_LAKE_STAGING_ROOT)
            if not staging_root.is_dir() or not self.root.parent.is_mount():
                raise ValueError("Index global formal Lake/staging mount unavailable")
            if staging_root.stat().st_dev != self.root.stat().st_dev:
                raise ValueError("Index global Lake and staging must share a filesystem")
        _check_path(self.namespace)
        self.namespace.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.namespace / "writer.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock = descriptor
            self.directory.mkdir(parents=True, exist_ok=True)
            _check_path(self.directory)
            if self.directory.stat().st_dev != self.root.stat().st_dev:
                raise ValueError("Index global candidate and target must share a filesystem")
            current_sources = self._source_identities()
            if self.control.exists():
                self.state = _read_json(self.control)
                if self.state.get("scope") != self.scope:
                    raise ValueError("Index global operation scope changed")
                if self.state.get("sources") != current_sources:
                    raise ValueError("Index global source changed after operation started")
                if self.state.get("status") not in {
                    "prepared", "input_ready", "building", "validated",
                    "promoting", "promoted", "reused",
                }:
                    raise ValueError("Unknown index global operation status")
            else:
                if any(self.directory.iterdir()):
                    raise ValueError("Index global orphan operation files must be retained")
                self.state = {
                    "scope": self.scope,
                    "sources": current_sources,
                    "before": _identity(self.target),
                    "status": "prepared",
                    "input": None,
                }
                self._save()
            self.read_input()
            return self
        except BaseException:
            os.close(descriptor)
            self._lock = None
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None

    def _require_lock(self) -> None:
        if self._lock is None:
            raise RuntimeError("Index global publication requires its writer context")

    def _save(self) -> None:
        self._require_lock()
        _save_json(self.control, self.state)

    def _source_identities(self) -> dict:
        values = {str(path): _identity(path) for path in self.sources}
        if any(identity is None for identity in values.values()):
            raise FileNotFoundError("Index global publication source missing")
        return values

    def _assert_sources(self) -> None:
        if self._source_identities() != self.state["sources"]:
            raise ValueError("Index global source changed during publication")

    def _assert_before(self) -> None:
        if _identity(self.target) != self.state["before"]:
            raise ValueError("Index global target changed after operation started")

    def _candidate(self) -> Path:
        relative = Path(self.state.get("candidate", ""))
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or relative.name != "part-000.parquet"
            or not relative.parent.name.startswith("attempt=")
            or len(relative.parent.name.removeprefix("attempt=")) != 32
            or any(c not in "0123456789abcdef" for c in relative.parent.name[8:])
        ):
            raise ValueError("Index global checkpoint candidate escaped its operation")
        candidate = self.directory / relative
        _check_path(candidate)
        return candidate

    def read_input(self) -> dict | None:
        self._require_lock()
        metadata = self.state.get("input")
        if metadata is None:
            if self.input_path.exists() or any(self.directory.glob(".phase_rows.json.*.tmp")):
                raise ValueError("Index global frozen input is incomplete or unconfirmed")
            return None
        if not isinstance(metadata, dict) or not self.input_path.is_file():
            raise ValueError("Index global frozen input is missing")
        if (
            self.input_path.stat().st_size != metadata.get("bytes")
            or _digest(self.input_path) != metadata.get("sha256")
            or metadata.get("complete") is not True
        ):
            raise ValueError("Index global frozen input changed or is incomplete")
        return _read_json(self.input_path)

    def freeze_input(self, data: dict) -> None:
        self._require_lock()
        self._assert_sources()
        self._assert_before()
        existing = self.read_input()
        if existing is not None:
            if _encode(existing) != _encode(data):
                raise ValueError("Index global frozen input differs from this attempt")
            return
        if self.state["status"] != "prepared":
            raise ValueError("Index global cannot replace an operation input")
        _save_json(self.input_path, data, exclusive=True)
        self.state.update(
            input={
                "bytes": self.input_path.stat().st_size,
                "sha256": _digest(self.input_path),
                "complete": True,
            },
            status="input_ready",
        )
        self._save()

    def new_candidate(self) -> Path:
        self._require_lock()
        self._assert_sources()
        self._assert_before()
        if self.state["status"] not in {"prepared", "input_ready", "building"}:
            raise ValueError("Index global validated publication must be completed first")
        if self.asset_key == "raw_index_global" and self.read_input() is None:
            raise ValueError("Index global Raw requires its frozen input before building")
        source_size = sum(value[2] for value in self.state["sources"].values())
        prior_size = (self.state["before"] or [0, 0, 0])[2]
        if shutil.disk_usage(self.directory).free < 4 * (source_size + prior_size + 64 * 1024):
            raise OSError("Insufficient index global staging space")
        relative = Path(f"attempt={uuid4().hex}") / "part-000.parquet"
        candidate = self.directory / relative
        candidate.parent.mkdir()
        self.state.update(status="building", candidate=str(relative))
        self._save()
        return candidate

    def publish(
        self,
        candidate: Path,
        *,
        result: dict,
        validator: Callable[[Path], object],
    ) -> dict:
        self._require_lock()
        self._assert_sources()
        self._assert_before()
        if self.state["status"] != "building" or Path(candidate) != self._candidate():
            raise ValueError("Index global candidate is not the current building attempt")
        candidate_before = _identity(candidate)
        if candidate_before is None:
            raise FileNotFoundError("Index global validated candidate missing")
        validator(candidate)
        if _identity(candidate) != candidate_before:
            raise ValueError("Index global candidate changed during validation")
        result = json.loads(_encode(result))
        digest = _digest(candidate)
        if _identity(candidate) != candidate_before:
            raise ValueError("Index global candidate changed during digest")
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        self.state.update(
            status="validated", sha256=digest,
            candidate_identity=candidate_before, result=result,
        )
        self._save()
        return self.completed()

    def reuse(self, *, result: dict) -> dict:
        self._require_lock()
        self._assert_sources()
        self._assert_before()
        if self.state["status"] not in {"prepared", "input_ready", "building"}:
            raise ValueError("Index global operation already has a completed result")
        if self.asset_key == "raw_index_global" and self.read_input() is None:
            raise ValueError("Index global reuse requires its frozen input")
        identity = _identity(self.target)
        if identity is None:
            raise ValueError("Index global cannot reuse a missing target")
        self.state.update(
            status="reused", result=json.loads(_encode(result)),
            sha256=_digest(self.target), published_identity=identity,
        )
        self._save()
        return self.state["result"]

    def completed(self) -> dict | None:
        self._require_lock()
        self._assert_sources()
        self.read_input()
        status = self.state["status"]
        if status in {"prepared", "input_ready", "building"}:
            self._assert_before()
            return None
        if not isinstance(self.state.get("result"), dict):
            raise TypeError("Index global publication has no saved business result")
        if status in {"promoted", "reused"}:
            if (
                _identity(self.target) != self.state.get("published_identity")
                or _digest(self.target) != self.state.get("sha256")
            ):
                raise ValueError("Index global published target changed")
            return dict(self.state["result"])
        candidate = self._candidate()
        target_identity = _identity(self.target)
        if status == "promoting" and target_identity != self.state["before"]:
            if (
                target_identity is None
                or target_identity[:4] != self.state["candidate_identity"][:4]
                or _digest(self.target) != self.state["sha256"]
            ):
                raise ValueError("Index global target changed during interrupted promotion")
        else:
            self._assert_before()
            if (
                _identity(candidate) != self.state.get("candidate_identity")
                or _digest(candidate) != self.state.get("sha256")
            ):
                raise ValueError("Index global validated candidate changed or disappeared")
            self.target.parent.mkdir(parents=True, exist_ok=True)
            _check_path(self.target.parent)
            if candidate.stat().st_dev != self.target.parent.stat().st_dev:
                raise ValueError("Index global candidate and target must share a filesystem")
            self._assert_sources()
            self._assert_before()
            self.state["status"] = "promoting"
            self._save()
            if _identity(candidate) != self.state["candidate_identity"]:
                raise ValueError("Index global candidate changed before replacement")
            self._assert_sources()
            self._assert_before()
            os.replace(candidate, self.target)
            _sync_directory(self.target.parent)
            target_identity = _identity(self.target)
            if (
                target_identity[:4] != self.state["candidate_identity"][:4]
                or _digest(self.target) != self.state["sha256"]
            ):
                raise ValueError("Index global promoted target differs from its candidate")
        self.state.update(status="promoted", published_identity=target_identity)
        self._save()
        return dict(self.state["result"])
