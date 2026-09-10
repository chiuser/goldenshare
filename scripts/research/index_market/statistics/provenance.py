"""Verify frozen source identity across the explicitly recorded directory move."""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
MIGRATION_MANIFEST = Path(__file__).resolve().parents[1] / "migration_20260909.json"


def verify_prior_source(source: Path, recorded_sha256: str) -> dict:
    """Accept exact bytes, or one audited old/new pair; all other changes fail."""
    source = source.resolve()
    current = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = {"recorded_sha256": recorded_sha256, "current_sha256": current}
    if current == recorded_sha256:
        return {**evidence, "mode": "exact"}
    relative = source.relative_to(REPO).as_posix()
    manifest_bytes = MIGRATION_MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    matches = [entry for entry in manifest["files"]
               if entry["role"] == "statistics" and entry["new_path"] == relative
               and entry["old_sha256"] == recorded_sha256
               and entry["new_sha256"] == current]
    if len(matches) != 1:
        raise ValueError(f"prior script changed outside audited directory migration: {relative}")
    return {**evidence, "mode": "directory_migration_20260909",
            "migration_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}
