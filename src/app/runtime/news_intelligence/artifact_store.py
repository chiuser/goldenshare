from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid


REQUIRED_ARTIFACTS = frozenset(
    {
        "manifest.json",
        "source_snapshot.jsonl",
        "candidate_results.jsonl",
        "event_results.jsonl",
        "analysis_results.jsonl",
        "annotation_import.jsonl",
        "annotation_export.jsonl",
        "classification_metrics.json",
        "clustering_metrics.json",
        "summary_audit.json",
        "ranking_metrics.json",
        "resource_samples.jsonl",
        "report.md",
    }
)


class ArtifactContractError(RuntimeError):
    pass


class AtomicArtifactWriter(AbstractContextManager["AtomicArtifactWriter"]):
    """Write one immutable experiment directory and atomically publish it."""

    def __init__(self, output_root: Path, experiment_id: str) -> None:
        if not experiment_id or "/" in experiment_id or experiment_id in {".", ".."}:
            raise ValueError("experiment_id must be a single safe path component")
        self.output_root = output_root.expanduser().resolve()
        self.final_path = self.output_root / experiment_id
        self.staging_path = (
            self.output_root / f".{experiment_id}.staging-{uuid.uuid4().hex}"
        )
        self._committed = False

    def __enter__(self) -> "AtomicArtifactWriter":
        self.output_root.mkdir(parents=True, exist_ok=True)
        if self.output_root.is_symlink():
            raise ArtifactContractError("output root must not be a symbolic link")
        if self.final_path.exists():
            raise FileExistsError(
                f"experiment is immutable and already exists: {self.final_path}"
            )
        self.staging_path.mkdir(mode=0o750)
        return self

    def write_json(self, name: str, value: object) -> None:
        path = self._path(name)
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def write_jsonl(self, name: str, records: Iterable[object]) -> None:
        path = self._path(name)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")

    def write_text(self, name: str, value: str) -> None:
        self._path(name).write_text(value, encoding="utf-8")

    def commit(self) -> Path:
        present = {path.name for path in self.staging_path.iterdir() if path.is_file()}
        missing = sorted(REQUIRED_ARTIFACTS - present)
        if missing:
            raise ArtifactContractError(
                f"experiment artifact set is incomplete: {missing}"
            )
        checksums = []
        for path in sorted(self.staging_path.iterdir(), key=lambda item: item.name):
            if path.name == "SHA256SUMS" or not path.is_file():
                continue
            checksums.append(f"{_sha256(path)}  {path.name}")
            _fsync_file(path)
        checksum_path = self.staging_path / "SHA256SUMS"
        checksum_path.write_text("\n".join(checksums) + "\n", encoding="utf-8")
        _fsync_file(checksum_path)
        _fsync_directory(self.staging_path)
        os.replace(self.staging_path, self.final_path)
        _fsync_directory(self.output_root)
        self._committed = True
        return self.final_path

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if not self._committed and self.staging_path.exists():
            shutil.rmtree(self.staging_path)
        return False

    def _path(self, name: str) -> Path:
        if not name or Path(name).name != name or name in {".", "..", "SHA256SUMS"}:
            raise ValueError("artifact name must be a safe file name")
        if not self.staging_path.exists():
            raise ArtifactContractError("artifact writer is not active")
        return self.staging_path / name


def verify_artifact_directory(path: Path) -> None:
    root = path.expanduser().resolve()
    checksum_path = root / "SHA256SUMS"
    if not checksum_path.is_file():
        raise ArtifactContractError("SHA256SUMS is missing")
    expected_names = REQUIRED_ARTIFACTS | {"SHA256SUMS"}
    actual_names = {item.name for item in root.iterdir() if item.is_file()}
    if actual_names != expected_names:
        raise ArtifactContractError(
            f"artifact file set differs: {sorted(actual_names ^ expected_names)}"
        )
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", maxsplit=1)
        if _sha256(root / name) != digest:
            raise ArtifactContractError(f"checksum mismatch: {name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
