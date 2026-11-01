"""Publish the four approved Raw/Silver minute families one file at a time."""

import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_index_mins_path,
    raw_stk_mins_path,
    silver_index_mins_path,
    silver_stk_mins_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
    RAW_STK_MINS_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)

CONTRACTS = {
    "raw_index_mins": (raw_index_mins_path, RAW_INDEX_MINS_SCHEMA, (1, 5, 15, 30, 60)),
    "silver_index_mins": (
        silver_index_mins_path,
        SILVER_INDEX_MINS_SCHEMA,
        (1, 5, 15, 30, 60, 90, 120),
    ),
    "raw_stk_mins": (raw_stk_mins_path, RAW_STK_MINS_SCHEMA, (1, 5, 15, 30, 60)),
    "silver_stk_mins": (
        silver_stk_mins_path,
        SILVER_STK_MINS_SCHEMA,
        (1, 5, 15, 30, 60),
    ),
}


def _safe(path: Path) -> None:
    if ".." in path.parts:
        raise ValueError("Minute publication rejects parent traversal")
    for component in (path, *path.parents):
        if (
            component in (Path("/tmp"), Path("/var"))
            and component.resolve() == Path("/private") / component.name
        ):
            continue
        if component.is_symlink():
            raise ValueError("Minute publication rejects symbolic links")


def _stat(path: Path):
    _safe(path)
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


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save(path: Path, value: dict) -> None:
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temp.open("x") as stream:
        json.dump(value, stream, sort_keys=True, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    _sync(path.parent)


class MinutePartitionPublication:
    """Run one existing candidate builder, or continue its validated file."""

    def __init__(
        self,
        *,
        dataset: str,
        target: Path,
        day: str,
        freq: int,
        publication_id: str | None = None,
        source_paths=(),
        source_identity=(),
        overwrite: bool = False,
    ):
        from datetime import date

        if dataset not in CONTRACTS or freq not in CONTRACTS[dataset][2]:
            raise ValueError("Unsupported minute dataset/frequency")
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Minute date must use YYYY-MM-DD")
        _safe(target.absolute())
        self.target = target.resolve()
        self.dataset, self.day, self.freq = dataset, day, freq
        formal, staging = Path(DEFAULT_LAKE_ROOT), Path(DEFAULT_LAKE_STAGING_ROOT)
        if self.target.is_relative_to(formal):
            path_fn = CONTRACTS[dataset][0]
            frequency = f"{freq}min" if "index" in dataset else freq
            if self.target != path_fn(formal, frequency, day):
                raise ValueError("Minute target does not match dataset/date/frequency")
            if not formal.is_dir() or not staging.is_dir():
                raise ValueError("Formal Lake and staging must already exist")
            base = staging
        elif self.target.is_relative_to(staging):
            if not staging.is_dir():
                raise ValueError("Formal staging must already exist")
            base = staging
        elif any(
            self.target.is_relative_to(p.resolve())
            for p in (Path("/private/tmp"), Path(gettempdir()))
        ):
            base = Path(gettempdir()).resolve() / "goldenshare_minute_staging"
        else:
            raise ValueError(
                "Minute writer requires approved Lake, staging or temporary root"
            )
        _safe(base)
        key = hashlib.sha256(str(self.target).encode()).hexdigest()
        self.namespace = base / "minute_partitions" / dataset / f"target={key}"
        operation = publication_id if publication_id is not None else uuid4().hex
        if not operation:
            raise ValueError("Minute publication identity cannot be empty")
        self.directory = (
            self.namespace / f"run_id={hashlib.sha256(operation.encode()).hexdigest()}"
        )
        self.sources = tuple(Path(p).absolute() for p in source_paths)
        self.source_identity = source_identity
        if not self.sources and not source_identity:
            raise ValueError("Minute publication needs file inputs or source identity")
        self.overwrite, self.reused = overwrite, False

    def _inputs(self):
        return json.loads(
            json.dumps(
                {
                    "version": 1,
                    "dataset": self.dataset,
                    "date": self.day,
                    "freq": self.freq,
                    "schema": [
                        (column.name, column.type)
                        for column in CONTRACTS[self.dataset][1]
                    ],
                    "sources": {str(p): _stat(p) for p in self.sources},
                    "source_identity": self.source_identity,
                    "overwrite": self.overwrite,
                },
                default=str,
            )
        )

    def _validate(self, candidate: Path, result: dict) -> None:
        source = read_parquet(candidate, hive_partitioning=False)
        with connect_configured_duckdb() as connection:
            observed = connection.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
            if [(r[0], r[1]) for r in observed] != [
                (c.name, c.type) for c in CONTRACTS[self.dataset][1]
            ]:
                raise ValueError("Minute candidate schema mismatch")
            frequency = (
                duckdb_string(f"{self.freq}min")
                if "index" in self.dataset
                else str(self.freq)
            )
            date_check = (
                f"OR trade_date IS NULL OR trade_date<>DATE {duckdb_string(self.day)}"
                if self.dataset == "silver_stk_mins"
                else ""
            )
            count, invalid, unique = connection.execute(f"""
                SELECT count(*), count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code)=''
                  OR trade_time IS NULL OR CAST(trade_time AS DATE)<>DATE {duckdb_string(self.day)}
                  OR freq IS NULL OR freq<>{frequency} {date_check}), count(DISTINCT (ts_code,trade_time))
                FROM {source}
            """).fetchone()
            expected = result.get("row_count", result.get("written_row_count"))
            if expected is None or count != expected or invalid or unique != count:
                raise ValueError("Minute candidate row/key/date/frequency mismatch")

    def run(self, build) -> dict:
        _safe(self.namespace)
        self.namespace.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            self.namespace / "writer.lock",
            os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._run_locked(build)
        finally:
            os.close(fd)

    def _run_locked(self, build) -> dict:
        _safe(self.directory)
        self.directory.mkdir(exist_ok=True)
        inputs = self._inputs()
        path = self.directory / "receipt.json"
        _safe(path)
        receipt = json.loads(path.read_text()) if path.exists() else None
        if receipt is not None:
            if (
                receipt.get("target") != str(self.target)
                or receipt.get("inputs") != inputs
            ):
                raise ValueError("Minute publication inputs changed")
            if (
                receipt["status"] in {"promoting", "promoted"}
                and self.target.is_file()
                and _sha(self.target) == receipt["sha256"]
            ):
                receipt["status"] = "promoted"
                _save(path, receipt)
                self.reused = True
                return receipt["result"]
            if (
                receipt["status"] == "promoted"
                or _stat(self.target) != receipt["before"]
            ):
                raise ValueError("Minute publication target changed")
        elif self.target.exists() and not self.overwrite:
            raise FileExistsError(f"Minute target exists: {self.target}")
        if receipt is None or receipt["status"] == "building":
            needed = 8 * 1024**2 + int(
                1.2 * sum(v[2] for v in inputs["sources"].values() if v)
            )
            if shutil.disk_usage(self.directory).free < needed:
                raise OSError("Insufficient minute staging space")
            candidate = self.directory / f"attempt={uuid4().hex}" / "part-000.parquet"
            candidate.parent.mkdir()
            _safe(self.target)
            self.target.parent.mkdir(parents=True, exist_ok=True)
            if candidate.parent.stat().st_dev != self.target.parent.stat().st_dev:
                raise ValueError("Minute candidate and target must share a filesystem")
            receipt = {
                "target": str(self.target),
                "inputs": inputs,
                "before": _stat(self.target),
                "candidate": str(candidate),
                "status": "building",
            }
            _save(path, receipt)
            result = json.loads(json.dumps(build(candidate), default=str))
            self._validate(candidate, result)
            with candidate.open("rb") as stream:
                os.fsync(stream.fileno())
            if self._inputs() != inputs:
                raise ValueError("Minute source changed during candidate generation")
            receipt.update(status="validated", sha256=_sha(candidate), result=result)
            _save(path, receipt)
        elif receipt["status"] not in {"validated", "promoting"}:
            raise ValueError("Unknown minute receipt status")
        else:
            self.reused = True
        candidate = Path(receipt["candidate"])
        if not candidate.is_relative_to(self.directory):
            raise ValueError("Minute candidate escaped staging operation")
        _safe(candidate)
        if not candidate.is_file() or _sha(candidate) != receipt["sha256"]:
            raise ValueError("Minute candidate changed or disappeared")
        if self._inputs() != inputs or _stat(self.target) != receipt["before"]:
            raise ValueError("Minute inputs or target changed before publication")
        _safe(self.target)
        self.target.parent.mkdir(parents=True, exist_ok=True)
        if candidate.stat().st_dev != self.target.parent.stat().st_dev:
            raise ValueError("Minute candidate and target must share a filesystem")
        receipt["status"] = "promoting"
        _save(path, receipt)
        os.replace(candidate, self.target)
        _sync(self.target.parent)
        if _sha(self.target) != receipt["sha256"]:
            raise ValueError("Minute target readback mismatch")
        receipt["status"] = "promoted"
        _save(path, receipt)
        return receipt["result"]
