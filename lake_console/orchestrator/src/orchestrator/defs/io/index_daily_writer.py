"""Staged single-file writes for index daily Raw/Silver and major-index Gold."""

import fcntl
import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_market_major_indices_daily_path,
    raw_index_daily_path,
    silver_index_daily_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    RAW_INDEX_DAILY_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
)

SCHEMAS = {
    "raw_index_daily": RAW_INDEX_DAILY_SCHEMA,
    "silver_index_daily": SILVER_INDEX_DAILY_SCHEMA,
    "gold_market_major_indices_daily": GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
}


def _check_path(path: Path) -> None:
    if ".." in path.parts:
        raise ValueError("Index daily path cannot contain parent traversal")
    for part in (path, *path.parents):
        if (
            part in (Path("/tmp"), Path("/var"))
            and part.resolve() == Path("/private") / part.name
        ):
            continue
        if part.is_symlink():
            raise ValueError(f"Index daily path contains a symlink: {path}")


def _identity(path: Path) -> list[int] | None:
    _check_path(path)
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


def _digest(path: Path) -> str:
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


def _save(path: Path, value: dict) -> None:
    candidate = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with candidate.open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(candidate, path)
    _sync_directory(path.parent)


def _staging_base(target: Path, dataset: str, day: str) -> Path:
    _check_path(target)
    formal = Path(DEFAULT_LAKE_ROOT)
    staging = Path(DEFAULT_LAKE_STAGING_ROOT)
    if target.is_relative_to(formal):
        expected = {
            "raw_index_daily": raw_index_daily_path,
            "silver_index_daily": silver_index_daily_path,
            "gold_market_major_indices_daily": gold_market_major_indices_daily_path,
        }[dataset](formal, day)
        if target != expected:
            raise ValueError(
                "Index daily formal target does not match its dataset and date"
            )
        if not formal.is_dir() or not staging.is_dir():
            raise ValueError("Index daily formal lake and staging must already exist")
        base = staging
    elif target.is_relative_to(staging):
        if not staging.is_dir():
            raise ValueError("Index daily staging must already exist")
        base = staging
    elif any(
        target.is_relative_to(path.resolve())
        for path in (Path("/private/tmp"), Path(gettempdir()))
    ):
        base = Path(gettempdir()).resolve() / "goldenshare_index_daily_staging"
    else:
        raise ValueError(
            "Index daily requires the formal lake, staging, or isolated temporary target"
        )
    _check_path(base)
    return base


@contextmanager
def _writer_lock(directory: Path):
    _check_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        directory / "writer.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def _validate_candidate(
    connection, candidate: Path, *, dataset: str, day: str, expected_rows: int
) -> int:
    source = read_parquet(candidate, hive_partitioning=False)
    columns = connection.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
    if [(row[0], row[1]) for row in columns] != [
        (col.name, col.type) for col in SCHEMAS[dataset]
    ]:
        raise ValueError(
            "Index daily candidate schema differs from the current contract"
        )
    expected_date = (
        duckdb_string(day.replace("-", ""))
        if dataset == "raw_index_daily"
        else f"DATE {duckdb_string(day)}"
    )
    count, outside = connection.execute(
        f"SELECT count(*), count(*) FILTER (WHERE trade_date IS NULL OR trade_date<>{expected_date}) FROM {source}"
    ).fetchone()
    if int(count) != expected_rows or expected_rows <= 0 or int(outside):
        raise ValueError("Index daily candidate row count or target date mismatch")
    return int(count)


def write_index_daily_partition(
    connection,
    select_sql: str,
    *,
    dataset: str,
    partition_key: str,
    target_path: Path,
    source_paths: tuple[Path, ...],
    expected_rows: int,
    publication_id: str | None = None,
    additional_identity=(),
    staging_directory: Path | None = None,
    candidate_validator=None,
) -> int:
    """Validate and commit one existing-contract date file; preserve failed work."""
    if dataset not in SCHEMAS:
        raise ValueError("Unsupported index daily dataset")
    if dataset == "raw_index_daily" and (
        not additional_identity or candidate_validator is None
    ):
        raise ValueError(
            "Raw index daily requires source identity and candidate validation"
        )
    _check_path(target_path.absolute())
    target = target_path.resolve()
    base = _staging_base(target, dataset, partition_key)
    target_key = hashlib.sha256(str(target).encode()).hexdigest()
    namespace = base / "index_daily" / dataset / f"target={target_key}"
    operation = publication_id if publication_id is not None else uuid4().hex
    if not operation:
        raise ValueError("Index daily publication identity cannot be empty")
    directory = namespace / f"run_id={hashlib.sha256(operation.encode()).hexdigest()}"
    if staging_directory is not None:
        _check_path(staging_directory.absolute())
        directory = staging_directory.resolve()
        if (
            dataset != "raw_index_daily"
            or directory.is_relative_to(Path(DEFAULT_LAKE_ROOT))
            or not (
                directory.is_relative_to(Path(DEFAULT_LAKE_STAGING_ROOT))
                or any(
                    directory.is_relative_to(p.resolve())
                    for p in (Path("/private/tmp"), Path(gettempdir()))
                )
            )
        ):
            raise ValueError("Raw index daily operation directory must be in staging")
    with _writer_lock(namespace):
        _check_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        sources = {
            str(path.resolve()): _identity(path.absolute()) for path in source_paths
        }
        if any(value is None for value in sources.values()) or (
            not sources
            and not (
                dataset == "raw_index_daily"
                and additional_identity
                and candidate_validator is not None
            )
        ):
            raise FileNotFoundError("Index daily publication source missing")
        inputs = json.loads(
            json.dumps(
                {
                    "version": 1,
                    "dataset": dataset,
                    "date": partition_key,
                    "sql": hashlib.sha256(select_sql.encode()).hexdigest(),
                    "sources": sources,
                    "expected_rows": expected_rows,
                    "additional": additional_identity,
                },
                default=str,
            )
        )
        receipt_path = directory / "receipt.json"
        _check_path(receipt_path)
        receipt = (
            json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        )
        if receipt is not None:
            if receipt.get("target") != str(target) or receipt.get("inputs") != inputs:
                raise ValueError("Index daily publication inputs or target changed")
            if (
                receipt["status"] in {"promoting", "promoted"}
                and target.is_file()
                and _digest(target) == receipt["sha256"]
            ):
                receipt["status"] = "promoted"
                _save(receipt_path, receipt)
                return int(receipt["row_count"])
            if (
                receipt["status"] == "promoted"
                or _identity(target) != receipt["before"]
            ):
                raise ValueError("Index daily target changed after publication started")
        target.parent.mkdir(parents=True, exist_ok=True)
        if receipt is None or receipt["status"] == "building":
            required = (
                int(
                    1.2
                    * (
                        sum(value[2] for value in sources.values())
                        + (target.stat().st_size if target.exists() else 0)
                    )
                )
                + 8 * 1024**2
            )
            if shutil.disk_usage(directory).free < required:
                raise OSError("Insufficient index daily staging space")
            candidate = directory / f"attempt={uuid4().hex}" / "part-000.parquet"
            candidate.parent.mkdir()
            receipt = {
                "target": str(target),
                "inputs": inputs,
                "before": _identity(target),
                "candidate": str(candidate),
                "status": "building",
            }
            _save(receipt_path, receipt)
            connection.execute(copy_query_to_parquet(select_sql, candidate))
            row_count = _validate_candidate(
                connection,
                candidate,
                dataset=dataset,
                day=partition_key,
                expected_rows=expected_rows,
            )
            if candidate_validator is not None:
                candidate_validator(connection, candidate)
            with candidate.open("rb") as stream:
                os.fsync(stream.fileno())
            receipt.update(
                status="validated", row_count=row_count, sha256=_digest(candidate)
            )
            _save(receipt_path, receipt)
        elif receipt["status"] not in {"validated", "promoting"}:
            raise ValueError("Unknown index daily publication receipt state")
        candidate = Path(receipt["candidate"])
        if not candidate.is_relative_to(directory):
            raise ValueError("Index daily candidate escaped its operation directory")
        _check_path(candidate)
        if not candidate.is_file() or _digest(candidate) != receipt["sha256"]:
            raise ValueError("Index daily candidate changed or disappeared")
        if sources != {
            str(path.resolve()): _identity(path.absolute()) for path in source_paths
        }:
            raise ValueError("Index daily source changed while building candidate")
        if _identity(target) != receipt["before"]:
            raise ValueError("Index daily target changed before publication")
        if candidate.parent.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("Index daily candidate and target must share a filesystem")
        receipt["status"] = "promoting"
        _save(receipt_path, receipt)
        os.replace(candidate, target)
        _sync_directory(target.parent)
        if _digest(target) != receipt["sha256"]:
            raise ValueError("Index daily publication readback mismatch")
        receipt["status"] = "promoted"
        _save(receipt_path, receipt)
        return int(receipt["row_count"])
