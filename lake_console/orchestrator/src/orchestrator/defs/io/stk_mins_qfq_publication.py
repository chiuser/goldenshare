"""Staged, resumable publication for stock-minute QFQ indicators and prices."""

import fcntl
import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.utils.dg_log_helper import DgStdoutLogger

LOGGER = DgStdoutLogger("stk_mins_qfq_publication")


def _digest(path: Path, *, on_read: Callable[[int], None] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if on_read is not None:
                on_read(len(chunk))
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> list[int] | None:
    if not path.exists():
        return None
    value = path.stat()
    return [
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    ]


def _no_symlinks(path: Path) -> None:
    for part in (path, *path.parents):
        if (
            part in (Path("/tmp"), Path("/var"))
            and part.resolve() == Path("/private") / part.name
        ):
            continue
        if part.is_symlink():
            raise ValueError(f"QFQ publication path contains a symlink: {path}")


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save(path: Path, value: dict) -> None:
    candidate = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with candidate.open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(candidate, path)
    _sync_directory(path.parent)


class StkMinsQfqPublication:
    """Keep candidates and per-file receipts outside the destination lake.

    A caller may reuse a publication_id only for identical frozen inputs and
    targets. Inputs may contain replacement rows or an execution input description.
    Dagster reexecution passes its root run ID; direct callers get an independent
    operation unless they explicitly request a previous one.
    """

    def __init__(
        self,
        *,
        lake_root: Path,
        family: str,
        freq: int,
        trade_dates: tuple[str, ...],
        publication_id: str | None = None,
    ) -> None:
        if family not in {"qfq", "macd_kdj", "nineturn"}:
            raise ValueError("Unsupported QFQ publication family")
        if lake_root.is_symlink():
            raise ValueError("QFQ destination root cannot be a symlink")
        _no_symlinks(lake_root.absolute())
        self.requested_root = lake_root.absolute()
        self.root = lake_root.resolve()
        formal = Path(DEFAULT_LAKE_ROOT)
        staging = Path(DEFAULT_LAKE_STAGING_ROOT)
        if self.root == formal or self.root.is_relative_to(staging):
            if not self.root.is_dir() or not staging.is_dir():
                raise ValueError("QFQ formal lake and staging must already exist")
            base = staging
        elif any(
            self.root.is_relative_to(p.resolve())
            for p in (
                Path("/private/tmp"),
                Path(gettempdir()),
            )
        ):
            base = self.root.parent / f"{self.root.name}_staging"
        else:
            raise ValueError(
                "QFQ requires the formal lake, staging, or isolated temporary root"
            )
        _no_symlinks(self.root)
        _no_symlinks(base)
        root_key = hashlib.sha256(str(self.root).encode()).hexdigest()
        scope = {
            "version": 1,
            "family": family,
            "freq": freq,
            "trade_dates": trade_dates,
        }
        self.scope = json.loads(json.dumps(scope))
        scope_key = hashlib.sha256(
            json.dumps(scope, sort_keys=True).encode()
        ).hexdigest()
        operation = publication_id if publication_id is not None else uuid4().hex
        if not operation:
            raise ValueError("QFQ publication identity cannot be empty")
        operation_key = hashlib.sha256(operation.encode()).hexdigest()
        self.namespace = (
            base / "stk_mins_qfq" / family / f"root={root_key}" / f"freq={freq}"
        )
        self.directory = (
            self.namespace / f"run_id={operation_key}" / f"scope={scope_key}"
        )
        self.targets: tuple[Path, ...] = ()
        self.descriptor: int | None = None
        self.validated_count = 0
        self.promoted_count = 0
        self.last_progress_at = time.monotonic()
        self.verified_files: dict[Path, dict] = {}
        self.unstarted_targets: dict[Path, list[int] | None] = {}
        self.building_receipts: dict[Path, dict] = {}
        self.bound_receipts: dict[Path, dict | None] = {}
        self.progress_bytes = {
            "existing_build_target_stat_bytes": 0,
            "frozen_input_stat_bytes": 0,
            "verified_candidate_stat_bytes": 0,
            "verified_formal_stat_bytes": 0,
            "input_sha256_read_bytes": 0,
            "candidate_sha256_read_bytes": 0,
            "formal_sha256_read_bytes": 0,
        }

    def _progress(
        self, stage: str, target: Path | None = None, *, force: bool = False
    ) -> None:
        current = time.monotonic()
        if force or current - self.last_progress_at >= 30:
            LOGGER.stdout(
                "stock_minute_file_publication_progress",
                stage=stage,
                validated_file_count=self.validated_count,
                promoted_file_count=self.promoted_count,
                total_file_count=len(self.targets),
                target=str(target) if target is not None else None,
                operation_directory=str(self.directory),
                **self.progress_bytes,
            )
            self.last_progress_at = current

    def __enter__(self):
        self.verified_files.clear()
        self.unstarted_targets.clear()
        self.building_receipts.clear()
        self.bound_receipts.clear()
        for name in self.progress_bytes:
            self.progress_bytes[name] = 0
        _no_symlinks(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        _no_symlinks(self.directory)
        descriptor = os.open(
            self.namespace / "writer.lock",
            os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            receipt_directory = self.directory / "files"
            _no_symlinks(receipt_directory)
            receipt_directory.mkdir(exist_ok=True)
        except BaseException:
            os.close(descriptor)
            raise
        self.descriptor = descriptor
        return self

    def __exit__(self, *_):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None
        self.verified_files.clear()
        self.unstarted_targets.clear()
        self.building_receipts.clear()
        self.bound_receipts.clear()

    def _target(self, target: Path) -> Path:
        absolute = target.absolute()
        try:
            relative = absolute.relative_to(self.requested_root)
        except ValueError:
            relative = absolute.relative_to(self.root)
        if ".." in relative.parts or relative.parts[0] != "gold":
            raise ValueError("QFQ publication target must remain in destination Gold")
        canonical = self.root / relative
        _no_symlinks(canonical)
        return canonical

    def _receipt_path(self, target: Path) -> Path:
        key = hashlib.sha256(str(target).encode()).hexdigest()
        return self.directory / "files" / f"{key}.json"

    def _receipt(self, target: Path) -> dict | None:
        path = self._receipt_path(target)
        _no_symlinks(path)
        if not path.exists():
            return None
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict) or receipt.get("target") != str(target):
            raise ValueError("QFQ file receipt target mismatch")
        if not isinstance(receipt.get("status"), str) or receipt["status"] not in {
            "building", "validated", "promoting", "promoted"
        }:
            raise ValueError("QFQ file receipt has an invalid status")
        self._candidate_path(target, receipt)
        if "before" not in receipt or not self._valid_identity(receipt["before"]):
            raise ValueError("QFQ file receipt has an invalid target identity")
        if receipt["status"] != "building":
            digest = receipt.get("sha256")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or type(receipt.get("row_count")) is not int
                or receipt["row_count"] < 0
                or receipt.get("candidate_identity") is None
                or not self._valid_identity(receipt["candidate_identity"])
            ):
                raise ValueError("QFQ file receipt has invalid validation fields")
        if (
            self.scope["family"] == "nineturn"
            and receipt["status"] == "promoted"
            and (
                receipt.get("promoted_identity") is None
                or not self._valid_identity(receipt["promoted_identity"])
            )
        ):
            raise ValueError("Nine-turn receipt has an invalid promoted identity")
        return receipt

    @staticmethod
    def _valid_identity(value) -> bool:
        return value is None or (
            isinstance(value, list)
            and len(value) == 5
            and all(type(component) is int for component in value)
        )

    def _candidate_path(self, target: Path, receipt: dict) -> Path:
        name = receipt.get("candidate")
        if not isinstance(name, str) or not name:
            raise ValueError("QFQ file receipt has no candidate path")
        candidate = Path(name)
        base = self.directory / "candidates"
        if (
            not candidate.is_absolute()
            or ".." in candidate.parts
            or not candidate.is_relative_to(base)
            or candidate.relative_to(base).parts[1:]
            != target.relative_to(self.root).parts
        ):
            raise ValueError("QFQ candidate escaped its operation directory or target")
        _no_symlinks(candidate)
        return candidate

    def _remember_file(
        self, target: Path, receipt: dict, path: Path, identity: list[int]
    ) -> None:
        previous = self.verified_files.get(target)
        if previous is not None:
            key = (
                "verified_formal_stat_bytes" if previous["path"] == target
                else "verified_candidate_stat_bytes"
            )
            self.progress_bytes[key] -= previous["identity"][2]
        key = (
            "verified_formal_stat_bytes" if path == target
            else "verified_candidate_stat_bytes"
        )
        self.progress_bytes[key] += identity[2]
        self.verified_files[target] = {
            "receipt": json.loads(json.dumps(receipt)),
            "path": path,
            "identity": identity,
        }

    def _check_bound_receipt(self, target: Path, receipt: dict | None) -> None:
        if receipt is None and self.bound_receipts.get(target) is not None:
            raise ValueError("QFQ file receipt missing after operation binding")
        if target not in self.bound_receipts or receipt != self.bound_receipts[target]:
            raise ValueError("QFQ file receipt changed after operation binding")

    def _save_receipt(self, target: Path, receipt: dict) -> None:
        self._check_bound_receipt(target, self._receipt(target))
        _save(self._receipt_path(target), receipt)
        self.bound_receipts[target] = json.loads(json.dumps(receipt))

    def _digest_file(self, path: Path, *, kind: str) -> str:
        def record_read(size: int) -> None:
            self.progress_bytes[f"{kind}_sha256_read_bytes"] += size

        return _digest(path, on_read=record_read)

    def _check_verified_file(self, target: Path, receipt: dict) -> dict:
        verified = self.verified_files.get(target)
        if verified is None or receipt != verified["receipt"]:
            raise ValueError("QFQ file receipt changed after validation")
        _no_symlinks(verified["path"])
        if _identity(verified["path"]) != verified["identity"]:
            raise ValueError("QFQ file identity changed after validation")
        return verified

    def _stable_digest(self, path: Path) -> tuple[str, list[int]]:
        _no_symlinks(path)
        before = _identity(path)
        if before is None or not path.is_file():
            raise ValueError("QFQ file changed or disappeared before digest")
        kind = "formal" if path in self.target_set else "candidate"
        digest = self._digest_file(path, kind=kind)
        _no_symlinks(path)
        if _identity(path) != before:
            raise ValueError("QFQ file identity changed during digest")
        return digest, before

    def _verify_file_once(self, target: Path, receipt: dict, path: Path) -> None:
        if target in self.verified_files:
            verified = self._check_verified_file(target, receipt)
            if verified["path"] != path:
                raise ValueError("QFQ verified file path changed")
            return
        digest, identity = self._stable_digest(path)
        if digest != receipt["sha256"]:
            raise ValueError("QFQ file content changed after validation")
        if self._receipt(target) != receipt:
            raise ValueError("QFQ file receipt changed during digest")
        self._remember_file(target, receipt, path, identity)

    def bind(
        self, connection, *, inputs: dict[str, str], targets: tuple[Path, ...]
    ) -> None:
        """Freeze replacement rows or an input description, never full price history."""
        self.targets = tuple(self._target(target) for target in targets)
        self.target_set = set(self.targets)
        self._progress("freeze_inputs", force=True)
        if not self.targets or len(set(self.targets)) != len(self.targets):
            raise ValueError("QFQ publication needs a nonempty unique target set")
        attempt = self.directory / "attempts" / uuid4().hex
        attempt.mkdir(parents=True)
        frozen = {}
        total_input_bytes = 0
        for name, sql in inputs.items():
            if not name.isidentifier():
                raise ValueError("Invalid QFQ replacement table name")
            path = attempt / f"{name}.parquet"
            connection.execute(copy_query_to_parquet(sql, path))
            frozen[name] = self._digest_file(path, kind="input")
            total_input_bytes += path.stat().st_size
        self.progress_bytes["frozen_input_stat_bytes"] = total_input_bytes
        value = {
            "scope": self.scope,
            "inputs": frozen,
            "targets": [str(target) for target in self.targets],
        }
        metadata = self.directory / "operation.json"
        _no_symlinks(metadata)
        existing_operation = metadata.exists()
        receipts = [self._receipt(target) for target in self.targets]
        if existing_operation:
            if json.loads(metadata.read_text()) != value:
                raise ValueError(
                    "QFQ publication inputs or targets changed; cannot resume"
                )
            known = [index for index, receipt in enumerate(receipts) if receipt]
            # Both writers build in frozen target order, before any promotion.
            # Only an uninterrupted suffix can therefore be safely unstarted.
            # A gap, an entirely missing set or missing commit records is ambiguous.
            if any(receipt is None for receipt in receipts) and (
                not known
                or any(
                    receipt is None for receipt in receipts[: max(known) + 1]
                )
                or any(
                    receipt and receipt["status"] in {"promoting", "promoted"}
                    for receipt in receipts
                )
            ):
                raise ValueError("QFQ file receipt missing; cannot safely resume")
        else:
            if any((self.directory / "files").iterdir()):
                raise ValueError("QFQ operation metadata missing for existing receipts")
            _save(metadata, value)
        self.unstarted_targets = {
            target: _identity(target)
            for target, receipt in zip(self.targets, receipts, strict=True)
            if receipt is None
        }
        self.bound_receipts = {
            target: json.loads(json.dumps(receipt))
            for target, receipt in zip(self.targets, receipts, strict=True)
        }
        # Existing validated candidates and promoted files need no second copy.
        expected_bytes = 0
        for target, receipt in zip(self.targets, receipts, strict=True):
            if (receipt is None or receipt["status"] == "building") and target.exists():
                expected_bytes += target.stat().st_size
        self.progress_bytes["existing_build_target_stat_bytes"] = expected_bytes
        required_bytes = (
            int(1.2 * (expected_bytes + total_input_bytes)) + 64 * 1024 * 1024
        )
        if shutil.disk_usage(self.directory).free < required_bytes:
            raise OSError(
                "Insufficient QFQ staging space for the complete candidate set"
            )

        self._progress("build_candidates", force=True)

    def candidate(self, target: Path, *, fail_if_target_exists: bool = False):
        """Return a new candidate, or the verified row count of an earlier one."""
        target = self._target(target)
        if target not in self.target_set:
            raise ValueError("QFQ target was not included in the frozen operation")
        target.parent.mkdir(parents=True, exist_ok=True)
        _no_symlinks(target)
        receipt = self._receipt(target)
        self._check_bound_receipt(target, receipt)
        if target in self.building_receipts and receipt != self.building_receipts[target]:
            raise ValueError("QFQ build receipt changed after candidate creation")
        if receipt is not None and receipt["status"] != "building":
            already_verified = target in self.verified_files
            self._verify_receipt_file(target, receipt)
            if not already_verified:
                self.validated_count += 1
            if receipt["status"] == "promoted" and not already_verified:
                self.promoted_count += 1
            self._progress("build_candidates", target)
            return None, int(receipt["row_count"])
        if receipt is None and (
            target not in self.unstarted_targets or target in self.verified_files
        ):
            raise ValueError("QFQ file receipt missing after operation binding")
        if receipt is None and _identity(target) != self.unstarted_targets[target]:
            raise ValueError("QFQ target changed before candidate build")
        if receipt is not None and _identity(target) != receipt["before"]:
            raise ValueError("QFQ target changed after an interrupted candidate build")
        if fail_if_target_exists and target.exists():
            raise FileExistsError(f"QFQ target already exists: {target}")
        if shutil.disk_usage(self.directory).free < 64 * 1024 * 1024:
            raise OSError("Insufficient QFQ staging space")
        relative = target.relative_to(self.root)
        path = self.directory / "candidates" / uuid4().hex / relative
        path.parent.mkdir(parents=True)
        if path.parent.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("QFQ candidate and target must be on the same filesystem")
        receipt = {
            "status": "building",
            "target": str(target),
            "candidate": str(path),
            "before": _identity(target),
        }
        self._save_receipt(target, receipt)
        self.building_receipts[target] = json.loads(json.dumps(receipt))
        self.unstarted_targets.pop(target, None)
        return path, None

    def validated(
        self, target: Path, candidate: Path, row_count: int,
        *, expected_identity: tuple[int, int, int, int, int] | None = None,
    ) -> None:
        target = self._target(target)
        receipt = self._receipt(target)
        self._check_bound_receipt(target, receipt)
        if receipt is None or receipt["status"] != "building":
            raise ValueError("QFQ candidate has no matching build receipt")
        if receipt != self.building_receipts.get(target):
            raise ValueError("QFQ build receipt changed after candidate creation")
        if receipt["candidate"] != str(candidate):
            raise ValueError("QFQ candidate differs from its receipt")
        _no_symlinks(candidate)
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        digest, identity = self._stable_digest(candidate)
        if expected_identity is not None and tuple(identity) != expected_identity:
            raise ValueError("QFQ candidate changed after business validation")
        if self._receipt(target) != receipt:
            raise ValueError("QFQ build receipt changed during digest")
        receipt.update(
            {
                "status": "validated",
                "sha256": digest,
                "row_count": int(row_count),
                "candidate_identity": identity,
            }
        )
        self._save_receipt(target, receipt)
        self.building_receipts.pop(target, None)
        self._remember_file(target, receipt, candidate, identity)

        self.validated_count += 1
        self._progress("build_candidates", target)

    def _verify_candidate(self, target: Path, receipt: dict) -> None:
        candidate = self._candidate_path(target, receipt)
        if not candidate.is_file() or _identity(candidate) != receipt["candidate_identity"]:
            raise ValueError("QFQ candidate changed or disappeared")
        if _identity(target) != receipt["before"]:
            raise ValueError("QFQ target changed before publication")
        if candidate.parent.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("QFQ candidate and target must be on the same filesystem")
        self._verify_file_once(target, receipt, candidate)
        if self.verified_files[target]["identity"] != receipt["candidate_identity"]:
            raise ValueError("QFQ candidate identity changed during validation")

    def _verify_receipt_file(self, target: Path, receipt: dict) -> None:
        if receipt["status"] == "promoted":
            try:
                if (
                    self.scope["family"] == "nineturn"
                    and _identity(target) != receipt["promoted_identity"]
                ):
                    raise ValueError("Nine-turn promoted file identity changed")
                self._verify_file_once(target, receipt, target)
                if (
                    self.scope["family"] == "nineturn"
                    and self.verified_files[target]["identity"] != receipt["promoted_identity"]
                ):
                    raise ValueError("Nine-turn promoted file identity changed during verification")
            except ValueError as error:
                raise ValueError("Completed QFQ target changed or disappeared") from error
            return
        if receipt["status"] == "promoting":
            candidate = self._candidate_path(target, receipt)
            target_identity = _identity(target)
            candidate_identity = _identity(candidate)
            if candidate_identity is None:
                if (
                    target_identity is None
                    or target_identity[:4] != receipt["candidate_identity"][:4]
                ):
                    raise ValueError("QFQ promoting paths conflict; cannot select a file")
                self._verify_file_once(target, receipt, target)
                identity = self.verified_files[target]["identity"]
                if identity[:4] != receipt["candidate_identity"][:4]:
                    raise ValueError("QFQ promoting paths conflict during validation")
                receipt["status"] = "promoted"
                if self.scope["family"] == "nineturn":
                    receipt["promoted_identity"] = identity
                self._save_receipt(target, receipt)
                self._remember_file(target, receipt, target, identity)
                return
            if target_identity != receipt["before"]:
                raise ValueError("QFQ promoting paths conflict; cannot select a file")
        self._verify_candidate(target, receipt)

    def promote(self) -> None:
        """Validate the entire set first; then commit files individually."""
        self._progress("validate_candidates", force=True)
        receipts = []
        for target in self.targets:
            receipt = self._receipt(target)
            self._check_bound_receipt(target, receipt)
            if receipt is None or receipt["status"] not in {
                "validated",
                "promoting",
                "promoted",
            }:
                raise ValueError("QFQ candidate set is not completely validated")
            receipts.append((target, receipt))
        for target, receipt in receipts:
            self._verify_receipt_file(target, receipt)
            self._progress("validate_candidates", target)
        self._progress("promote_files", force=True)
        for target, receipt in receipts:
            current_receipt = self._receipt(target)
            self._check_bound_receipt(target, current_receipt)
            self._check_verified_file(target, current_receipt)
            if receipt["status"] == "promoted":
                continue
            candidate = Path(receipt["candidate"])
            _no_symlinks(target)
            _no_symlinks(candidate)
            if (
                _identity(target) != receipt["before"]
                or _identity(candidate) != receipt["candidate_identity"]
            ):
                raise ValueError("QFQ file identity changed during publication")
            receipt["status"] = "promoting"
            self._save_receipt(target, receipt)
            self._remember_file(
                target, receipt, candidate, receipt["candidate_identity"]
            )
            os.replace(candidate, target)
            _sync_directory(target.parent)
            _no_symlinks(target)
            identity = _identity(target)
            if identity is None or identity[:4] != receipt["candidate_identity"][:4]:
                raise ValueError("QFQ published file identity mismatch")
            receipt["status"] = "promoted"
            if self.scope["family"] == "nineturn":
                receipt["promoted_identity"] = identity
            self._save_receipt(target, receipt)
            self._remember_file(target, receipt, target, identity)
            self.promoted_count += 1
            self._progress("promote_files", target)
        self._progress("completed", force=True)
