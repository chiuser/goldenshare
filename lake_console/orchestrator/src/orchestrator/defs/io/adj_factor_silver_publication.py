"""Publish one audited factor partition and recover the same execution."""

import fcntl
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    silver_adj_factor_publication_root,
)


class AdjFactorPublicationError(ValueError):
    """The factor publication cannot safely continue."""


def file_identity(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    s = path.stat()
    return {"device": s.st_dev, "inode": s.st_ino, "bytes": s.st_size,
            "mtime_ns": s.st_mtime_ns, "ctime_ns": s.st_ctime_ns}


def _stable_identity(value: dict | None) -> dict | None:
    return None if value is None else {k: value[k] for k in (
        "device", "inode", "bytes", "mtime_ns",
    )}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_path(path: Path) -> None:
    if (not path.is_absolute() or ".." in path.parts
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise AdjFactorPublicationError("adj_factor_publication_path")


def _check_roots(lake_root: Path, staging_root: Path) -> None:
    for root in (lake_root, staging_root):
        _check_path(root)
        if not root.is_dir() or not os.access(root, os.R_OK | os.W_OK | os.X_OK):
            raise AdjFactorPublicationError("adj_factor_publication_root_unavailable")
    if (lake_root == staging_root or lake_root in staging_root.parents
            or staging_root in lake_root.parents):
        raise AdjFactorPublicationError("adj_factor_publication_roots_overlap")
    if (any(Path("/Volumes") in p.parents for p in (lake_root, staging_root))
            and (lake_root != Path(DEFAULT_LAKE_ROOT)
                 or staging_root != Path(DEFAULT_LAKE_STAGING_ROOT)
                 or not lake_root.parent.is_mount())):
        raise AdjFactorPublicationError("adj_factor_publication_formal_root")
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise AdjFactorPublicationError("adj_factor_publication_device")


def _checkpoint(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    _check_path(temporary)
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_sources(inputs: Mapping[str, dict | None]) -> None:
    if any(file_identity(Path(path)) != identity for path, identity in inputs.items()):
        raise AdjFactorPublicationError("adj_factor_publication_source_changed")


def _recover(state: dict, control: Path, target: Path) -> dict | None:
    """Recognize a completed rename before testing the original target input."""
    phase = state["phase"]
    if phase not in {"prepared", "committed"}:
        return None
    actual = file_identity(target)
    expected = state["published_identity"]
    if _stable_identity(actual) != _stable_identity(expected):
        if phase == "prepared" and actual == state["prior_target_identity"]:
            return None
        raise AdjFactorPublicationError("adj_factor_publication_target_changed")
    if phase == "prepared":
        if _sha256(target) != state["candidate_sha256"]:
            raise AdjFactorPublicationError("adj_factor_publication_target_digest")
        state["phase"] = "committed"
        _checkpoint(control, state)
    # A later source change never rolls back an already published file.
    _assert_sources(state["source_identities"])
    return state["result"]


def _publish_locked(
    *, control: Path, target: Path, sources: tuple[Path, ...], binding: dict,
    build_candidate: Callable[[Path], dict],
) -> dict:
    if control.exists():
        if control.stat().st_size > 256 * 1024:
            raise AdjFactorPublicationError("adj_factor_publication_control_size")
        state = json.loads(control.read_text())
        if (state.get("binding") != binding
                or state.get("phase") not in {"planned", "prepared", "committed"}):
            raise AdjFactorPublicationError("adj_factor_publication_binding")
        recovered = _recover(state, control, target)
        if recovered is not None:
            return recovered
        _assert_sources(state["source_identities"])
        if file_identity(target) != state["prior_target_identity"]:
            raise AdjFactorPublicationError("adj_factor_publication_target_changed")
    else:
        state = {"binding": binding, "phase": "planned",
                 "source_identities": {str(p): file_identity(p) for p in sources},
                 "prior_target_identity": file_identity(target), "attempts": []}
        _checkpoint(control, state)

    if state["phase"] == "planned":
        # Preserve any incomplete candidate from an interrupted attempt.
        candidate = control.parent / f"candidate-{len(state['attempts'])}.parquet"
        _check_path(candidate)
        if candidate.exists():
            raise AdjFactorPublicationError("adj_factor_publication_candidate_conflict")
        state["attempts"].append(str(candidate))
        state["candidate"] = str(candidate)
        _checkpoint(control, state)
        result = build_candidate(candidate)
        _assert_sources(state["source_identities"])
        if file_identity(target) != state["prior_target_identity"]:
            raise AdjFactorPublicationError("adj_factor_publication_target_changed")
        state["result"] = result
        if result["unchanged"]:
            state.update(phase="committed", published_identity=file_identity(target))
            _checkpoint(control, state)
            _assert_sources(state["source_identities"])
            return result
        if not candidate.is_file():
            raise AdjFactorPublicationError("adj_factor_publication_candidate_missing")
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        state.update(phase="prepared", published_identity=file_identity(candidate),
                     candidate_sha256=_sha256(candidate))
        _checkpoint(control, state)

    candidate = Path(state["candidate"])
    _check_path(candidate)
    if (candidate.parent != control.parent
            or file_identity(candidate) != state["published_identity"]):
        raise AdjFactorPublicationError("adj_factor_publication_candidate_changed")
    _assert_sources(state["source_identities"])
    if file_identity(target) != state["prior_target_identity"]:
        raise AdjFactorPublicationError("adj_factor_publication_target_changed")
    if candidate.stat().st_dev != target.parent.stat().st_dev:
        raise AdjFactorPublicationError("adj_factor_publication_device")
    os.replace(candidate, target)
    if _stable_identity(file_identity(target)) != _stable_identity(state["published_identity"]):
        raise AdjFactorPublicationError("adj_factor_publication_committed_identity")
    state["phase"] = "committed"
    _checkpoint(control, state)
    _assert_sources(state["source_identities"])
    return state["result"]


def publish_silver_adj_factor(
    *, lake_root: Path, staging_root: Path, publication_id: str, trade_date: str,
    target: Path, sources: tuple[Path, ...], restore_keys: tuple[tuple[str, str], ...],
    build_candidate: Callable[[Path], dict],
) -> dict:
    _check_roots(lake_root, staging_root)
    for path in (target, *sources):
        _check_path(path)
    if not target.is_relative_to(lake_root / "silver"):
        raise AdjFactorPublicationError("adj_factor_publication_target_layer")
    run_root = silver_adj_factor_publication_root(staging_root, publication_id, trade_date)
    _check_path(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_dir = staging_root / "adj_factor" / "silver" / "locks"
    _check_path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"trade_date={trade_date}.lock"
    _check_path(lock_path)
    binding = {"revision": "adj_factor_retired_retention_v1", "trade_date": trade_date,
               "target": str(target), "sources": [str(p) for p in sources],
               "restore_keys": [list(key) for key in restore_keys]}
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AdjFactorPublicationError("adj_factor_publication_writer_busy") from error
        return _publish_locked(control=run_root / "publication.json", target=target,
                               sources=sources, binding=binding,
                               build_candidate=build_candidate)
