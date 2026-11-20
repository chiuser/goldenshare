"""Stage and publish the two index basic snapshots with per-file recovery."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.io.stock_period_raw import (
    atomic_json,
    file_digest,
    file_version,
    read_json,
    safe_path,
    sync_directory,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_index_basic_path,
    silver_index_basic_path,
)

INDEX_BASIC_COVERAGE_METADATA_KEY = "goldenshare/index_basic_coverage"


def _version(path: Path) -> list[int] | None:
    return file_version(path) if safe_path(path).exists() else None


@contextmanager
def index_basic_publication(root: Path, run_id: str):
    root = root.resolve()
    staging_root = root.parent / Path(DEFAULT_LAKE_STAGING_ROOT).name
    if root == Path(DEFAULT_LAKE_ROOT) and not root.parent.is_mount():
        raise RuntimeError("Index basic requires the mounted formal Lake")
    safe_path(staging_root)
    if not staging_root.is_dir() or root.stat().st_dev != staging_root.stat().st_dev:
        raise RuntimeError(
            "Index basic Lake and staging must share an available filesystem"
        )
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("Invalid index basic run ID")
    directory = safe_path(staging_root / "index_basic")
    directory.mkdir(exist_ok=True)
    with safe_path(directory / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield IndexBasicPublication(root, directory / f"run_id={run_id}", run_id)


class IndexBasicPublication:
    def __init__(self, root: Path, directory: Path, run_id: str) -> None:
        self.directory = safe_path(directory)
        self.record = safe_path(directory / "publication.json")
        self.targets = {
            "raw": raw_index_basic_path(root),
            "silver": silver_index_basic_path(root),
        }
        self.batch_id = run_id
        self.state = read_json(self.record) if self.record.is_file() else None
        if self.state is not None and (
            self.state["batch_id"] != run_id
            or self.state["targets"]
            != {layer: str(path) for layer, path in self.targets.items()}
        ):
            raise ValueError(
                "Index basic publication record refers to a different batch or Lake"
            )

    def new_attempt(self) -> Path:
        path = self.directory / f"attempt={uuid4().hex}"
        path.mkdir(parents=True)
        return path

    def freeze(
        self,
        *,
        candidates: dict[str, Path],
        coverage: dict[str, dict],
        previous: dict[str, list[int] | None],
        ready_date: str | None,
        raw_input: dict | None = None,
    ) -> None:
        artifacts = {}
        for layer, path in candidates.items():
            target = self.targets[layer]
            if _version(target) != previous[layer]:
                raise ValueError(
                    f"Index basic {layer} target changed during preparation"
                )
            safe_path(target.parent).mkdir(parents=True, exist_ok=True)
            identity = file_version(path)
            if identity[0] != target.parent.stat().st_dev:
                raise ValueError(
                    f"Index basic {layer} candidate is on another filesystem"
                )
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            artifacts[layer] = {
                "candidate": str(path.relative_to(self.directory)),
                "before": previous[layer],
                "candidate_version": identity,
                "sha256": file_digest(path),
                "status": "validated",
                "coverage": coverage[layer],
            }
        self.state = {
            "batch_id": self.batch_id,
            "targets": {layer: str(path) for layer, path in self.targets.items()},
            "ready_date": ready_date,
            "raw_input": raw_input,
            "artifacts": artifacts,
        }
        atomic_json(self.record, self.state)

    def target_versions(self, layers: tuple[str, ...]) -> dict[str, list[int] | None]:
        return {layer: _version(self.targets[layer]) for layer in layers}

    def _assert_raw_input(self) -> None:
        source = self.state["artifacts"].get("raw") or self.state["raw_input"]
        expected = source.get("published_version")
        target = self.targets["raw"]
        if (
            expected is None
            or _version(target) != expected
            or file_digest(target) != source["sha256"]
        ):
            raise ValueError(
                "Index basic Silver input no longer matches this batch's Raw"
            )

    def promote(self, layer: str) -> dict:
        if layer == "silver":
            self._assert_raw_input()
        record = self.state["artifacts"][layer]
        target = self.targets[layer]
        current_version = _version(target)
        if record["status"] == "published":
            if (
                current_version != record["published_version"]
                or file_digest(target) != record["sha256"]
            ):
                raise ValueError(f"Index basic published {layer} changed")
            return record["coverage"]

        candidate = self.directory / record["candidate"]
        if current_version == record["before"]:
            if layer == "raw" and "silver" in self.state["artifacts"]:
                silver = self.state["artifacts"]["silver"]
                if _version(self.targets["silver"]) != silver["before"]:
                    raise ValueError(
                        "Index basic Silver target changed before Raw publication"
                    )
                self._assert_candidate("silver", silver)
            self._assert_candidate(layer, record)
            record["status"] = "promoting"
            atomic_json(self.record, self.state)
            os.replace(candidate, target)
            current_version = file_version(target)

        if (
            record["status"] != "promoting"
            or current_version is None
            or current_version[:4] != record["candidate_version"][:4]
            or candidate.exists()
            or file_digest(target) != record["sha256"]
        ):
            raise ValueError(
                f"Index basic {layer} target differs from the validated candidate"
            )
        sync_directory(target.parent)
        record.update(status="published", published_version=current_version)
        atomic_json(self.record, self.state)
        return record["coverage"]

    def _assert_candidate(self, layer: str, record: dict) -> None:
        candidate = self.directory / record["candidate"]
        if (
            _version(candidate) != record["candidate_version"]
            or file_digest(candidate) != record["sha256"]
        ):
            raise ValueError(f"Index basic {layer} candidate changed after validation")

    def delivery_metadata(self, layer: str) -> dict:
        record = self.state["artifacts"][layer]
        return {
            "batch_id": self.batch_id,
            "sha256": record["sha256"],
            "file_version": record["published_version"],
            **record["coverage"],
        }
