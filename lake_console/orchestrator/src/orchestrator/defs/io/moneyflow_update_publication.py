"""Shared moneyflow per-file intent, atomic publication and recovery protocol."""

import json
import os
import shutil
from pathlib import Path

from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_MIN_FREE_BYTES,
    MoneyflowContractError,
)


def assert_moneyflow_update_path(path: Path) -> None:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(p.is_symlink() for p in (path, *path.parents))
    ):
        raise MoneyflowContractError("update_path")


def assert_moneyflow_update_roots(lake_root: Path, staging_root: Path) -> None:
    for path in (lake_root, staging_root):
        assert_moneyflow_update_path(path)
        if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise MoneyflowContractError("update_root_unavailable")
    if (
        lake_root == staging_root
        or lake_root in staging_root.parents
        or staging_root in lake_root.parents
    ):
        raise MoneyflowContractError("update_root_overlap")
    if any(Path("/Volumes") in p.parents for p in (lake_root, staging_root)):
        if lake_root != Path(DEFAULT_LAKE_ROOT) or staging_root != Path(
            DEFAULT_LAKE_STAGING_ROOT
        ):
            raise MoneyflowContractError("update_volume_root")
        if not lake_root.parent.is_mount():
            raise MoneyflowContractError("update_mount")
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise MoneyflowContractError("update_device")
    if shutil.disk_usage(staging_root).free < MONEYFLOW_HISTORY_MIN_FREE_BYTES:
        raise MoneyflowContractError("update_free_space")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _checkpoint(path: Path, value: dict) -> None:
    assert_moneyflow_update_path(path)
    temporary = path.with_suffix(".json.tmp")
    assert_moneyflow_update_path(temporary)
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def read_moneyflow_update_control(path: Path) -> dict:
    assert_moneyflow_update_path(path)
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise MoneyflowContractError("update_control")
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as error:
        raise MoneyflowContractError("update_control") from error
    if not isinstance(value, dict):
        raise MoneyflowContractError("update_control")
    return value


def publish_moneyflow_update_file(
    connection,
    candidate: Path,
    target: Path,
    *,
    dataset: str,
    audit_file,
    day: str,
    layer: str,
    checkpoint: Path,
    raw_hash: str | None = None,
    check_cancel=lambda: None,
) -> dict:
    """Persist intent before replace; recover a moved file without recreating it."""
    assert_moneyflow_update_path(candidate)
    assert_moneyflow_update_path(target)
    identity = {
        "revision": f"{dataset}_daily_v1",
        "layer": layer,
        "trade_date": day,
        "candidate": str(candidate),
        "target": str(target),
        "raw_sha256": raw_hash,
    }
    silver = layer == "silver"
    if checkpoint.exists():
        state = read_moneyflow_update_control(checkpoint)
        if any(state.get(k) != v for k, v in identity.items()) or state.get(
            "stage"
        ) not in {"intent", "complete"}:
            raise MoneyflowContractError("update_intent")
    else:
        audit_file(connection, candidate, day, silver=silver)
        new_hash = candidate_file_hash(candidate)
        old_hash = None
        unchanged = False
        if target.exists():
            audit_file(connection, target, day, silver=silver)
            old_hash = candidate_file_hash(target)
            unchanged = (
                connection.execute(
                    "SELECT count(*) FROM ((SELECT * FROM read_parquet($a,hive_partitioning=false) EXCEPT "
                    "SELECT * FROM read_parquet($b,hive_partitioning=false)) UNION ALL "
                    "(SELECT * FROM read_parquet($b,hive_partitioning=false) EXCEPT "
                    "SELECT * FROM read_parquet($a,hive_partitioning=false)))",
                    {"a": str(candidate), "b": str(target)},
                ).fetchone()[0]
                == 0
            )
        state = {
            **identity,
            "candidate_sha256": new_hash,
            "prior_sha256": old_hash,
            "published_sha256": old_hash if unchanged else new_hash,
            "mode": "reuse" if unchanged else "replace",
            "stage": "intent",
        }
        _checkpoint(checkpoint, state)
    check_cancel()
    actual = candidate_file_hash(target) if target.is_file() else None
    if actual != state["published_sha256"]:
        if (
            state["stage"] == "complete"
            or state["mode"] != "replace"
            or actual != state["prior_sha256"]
        ):
            raise MoneyflowContractError("update_target_changed")
        if (
            not candidate.is_file()
            or candidate_file_hash(candidate) != state["candidate_sha256"]
        ):
            raise MoneyflowContractError("update_candidate_changed")
        audit_file(connection, candidate, day, silver=silver)
        target.parent.mkdir(parents=True, exist_ok=True)
        assert_moneyflow_update_path(target)
        if candidate.stat().st_dev != target.parent.stat().st_dev:
            raise MoneyflowContractError("update_device")
        check_cancel()
        # Recheck immediately before replacing. The namespace lock serializes writers.
        if (candidate_file_hash(target) if target.is_file() else None) != state[
            "prior_sha256"
        ]:
            raise MoneyflowContractError("update_target_changed")
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(candidate, target)
        _fsync_directory(target.parent)
    audit_file(connection, target, day, silver=silver)
    if candidate_file_hash(target) != state["published_sha256"]:
        raise MoneyflowContractError("update_readback")
    if state["stage"] != "complete":
        state = {**state, "stage": "complete"}
        _checkpoint(checkpoint, state)
    return state
