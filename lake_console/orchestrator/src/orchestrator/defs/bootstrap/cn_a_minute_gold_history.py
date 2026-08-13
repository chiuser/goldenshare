"""Bounded candidate-first Bootstrap for canonical CN A-share index Gold bars."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from orchestrator.defs.io.cn_a_gold_minute_bars import (
    CANONICAL_GOLD_MINUTE_COLUMN_TYPES,
)
from orchestrator.defs.io.cn_a_gold_minute_writer import (
    write_canonical_gold_minute_partition,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_index_mins_path,
    gold_major_index_mins_path,
    silver_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
    expected_gold_minute_times,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    effective_silver_codes_for_date,
)

FORMAL_LAKE_ROOT = Path(DEFAULT_LAKE_ROOT)
STAGING_ROOT = Path(DEFAULT_LAKE_STAGING_ROOT) / "cn_a_minute_gold_p6"
REPORT_ROOT = Path("/private/tmp/cn_a_minute_gold_p6")
CHECKPOINT_INTERVAL = 20
SUPPORTED_DATASETS = ("index_mins", "major_index_mins")
MAJOR_INDEX_EQUIVALENCE_FREQS = (1, 90, 120)
AMOUNT_ABS_TOLERANCE = 1e-6


class CnAMinuteGoldHistoryError(RuntimeError):
    """Raised when a frozen Gold history build cannot continue safely."""


@dataclass(frozen=True, slots=True)
class _DatasetSpec:
    name: str
    source_path: Callable[[Path, int | str, str], Path]
    target_path: Callable[[Path, int | str, str], Path]
    expected_codes: Callable[[str], Sequence[str]] | None

    def source(self, root: Path, source_freq: int, trade_date: str) -> Path:
        return self.source_path(root, f"{source_freq}min", trade_date)

    def target(self, root: Path, target_freq: int, trade_date: str) -> Path:
        return self.target_path(root, target_freq, trade_date)

    def dataset_root(self, root: Path) -> Path:
        return self.target(root, 1, "2000-01-01").parents[2]


_SPECS = {
    "index_mins": _DatasetSpec(
        name="index_mins",
        source_path=silver_index_mins_path,
        target_path=gold_index_mins_path,
        expected_codes=None,
    ),
    "major_index_mins": _DatasetSpec(
        name="major_index_mins",
        source_path=silver_major_index_mins_path,
        target_path=gold_major_index_mins_path,
        expected_codes=effective_silver_codes_for_date,
    ),
}


class _BorrowedDuckDBResource:
    def __init__(self, connection) -> None:
        self._connection = connection

    @contextmanager
    def connect(self):
        yield self._connection


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json(path: Path, *, label: str) -> dict[str, object]:
    if not path.is_file():
        raise CnAMinuteGoldHistoryError(f"{label} is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CnAMinuteGoldHistoryError(f"{label} must contain a JSON object")
    return payload


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _spec(dataset: str) -> _DatasetSpec:
    try:
        return _SPECS[str(dataset).strip()]
    except KeyError as error:
        raise CnAMinuteGoldHistoryError(
            f"dataset must be one of {SUPPORTED_DATASETS!r}; got {dataset!r}"
        ) from error


def _source_dates(spec: _DatasetSpec, root: Path, source_freq: int) -> tuple[str, ...]:
    sample = spec.source(root, source_freq, "2000-01-01")
    freq_root = sample.parents[1]
    return tuple(
        sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in freq_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
    )


def _source_manifest(
    *, spec: _DatasetSpec, root: Path, trade_dates: Sequence[str]
) -> tuple[dict[str, object], ...]:
    entries: list[dict[str, object]] = []
    for source_freq in sorted(set(CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET.values())):
        for trade_date in trade_dates:
            path = spec.source(root, source_freq, trade_date)
            if not path.is_file():
                raise CnAMinuteGoldHistoryError(
                    f"required Silver source is missing: {path}"
                )
            stat = path.stat()
            entries.append(
                {
                    "source_freq": source_freq,
                    "trade_date": trade_date,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    return tuple(entries)


def _validate_source_manifest(plan: Mapping[str, object]) -> None:
    entries = plan.get("source_manifest")
    if not isinstance(entries, list):
        raise CnAMinuteGoldHistoryError("frozen plan has no source manifest")
    current: list[dict[str, object]] = []
    for value in entries:
        if not isinstance(value, Mapping):
            raise CnAMinuteGoldHistoryError("source manifest entry is invalid")
        path = Path(str(value["path"]))
        if not path.is_file():
            raise CnAMinuteGoldHistoryError(f"frozen Silver source disappeared: {path}")
        stat = path.stat()
        current.append(
            {
                "source_freq": int(value["source_freq"]),
                "trade_date": str(value["trade_date"]),
                "path": str(path),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    if _hash_payload(current) != str(plan.get("source_manifest_hash")):
        raise CnAMinuteGoldHistoryError(
            "Silver source manifest changed after the frozen P6 plan"
        )


def build_cn_a_minute_gold_history_plan(
    *,
    dataset: str,
    formal_lake_root: Path = FORMAL_LAKE_ROOT,
    staging_root: Path = STAGING_ROOT,
    report_root: Path = REPORT_ROOT,
) -> Path:
    """Freeze the physical Silver source and one-time Gold target scope."""

    spec = _spec(dataset)
    source_freqs = tuple(
        sorted(set(CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET.values()))
    )
    dates_by_freq = {
        source_freq: _source_dates(spec, formal_lake_root, source_freq)
        for source_freq in source_freqs
    }
    if any(not dates for dates in dates_by_freq.values()):
        raise CnAMinuteGoldHistoryError("Silver source date scope must not be empty")
    first_dates = dates_by_freq[source_freqs[0]]
    if any(dates != first_dates for dates in dates_by_freq.values()):
        raise CnAMinuteGoldHistoryError(
            "Silver source frequencies do not have one exact date scope"
        )
    target_root = spec.dataset_root(formal_lake_root)
    if target_root.exists():
        raise CnAMinuteGoldHistoryError(
            f"formal Gold dataset root already exists: {target_root}"
        )
    source_manifest = _source_manifest(
        spec=spec,
        root=formal_lake_root,
        trade_dates=first_dates,
    )
    source_manifest_hash = _hash_payload(source_manifest)
    hash_payload = {
        "dataset": spec.name,
        "formal_lake_root": str(formal_lake_root),
        "trade_dates": first_dates,
        "target_freqs": CN_A_GOLD_MINUTE_FREQS,
        "source_manifest_hash": source_manifest_hash,
        "contract": "cn_a_gold_minute_v1",
    }
    plan_hash = _hash_payload(hash_payload)
    phase_root = staging_root / spec.name / plan_hash
    candidate_lake_root = phase_root / "candidate_lake"
    staging_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    staging_device = (
        phase_root.stat().st_dev
        if phase_root.exists()
        else staging_root.stat().st_dev
    )
    if staging_device != formal_lake_root.stat().st_dev:
        raise CnAMinuteGoldHistoryError(
            "P6 staging and formal Lake must share one filesystem"
        )
    payload = {
        "schema_version": 1,
        "report_type": "cn_a_minute_gold_history_plan",
        "generated_at": datetime.now(UTC).isoformat(),
        **hash_payload,
        "plan_hash": plan_hash,
        "source_manifest": list(source_manifest),
        "source_manifest_hash": source_manifest_hash,
        "phase_root": str(phase_root),
        "candidate_lake_root": str(candidate_lake_root),
        "candidate_dataset_root": str(spec.dataset_root(candidate_lake_root)),
        "formal_dataset_root": str(target_root),
        "expected_file_count": len(first_dates) * len(CN_A_GOLD_MINUTE_FREQS),
        "writes": {"formal_lake": 0, "dagster_events": 0},
    }
    report_path = report_root / f"{spec.name}_gold_plan_{plan_hash}.json"
    _atomic_write_json(report_path, payload)
    return report_path


def _load_plan(path: Path, *, expected_plan_hash: str) -> dict[str, object]:
    plan = _load_json(path, label="P6 Gold plan")
    if plan.get("report_type") != "cn_a_minute_gold_history_plan":
        raise CnAMinuteGoldHistoryError("unsupported P6 Gold plan report type")
    if plan.get("plan_hash") != expected_plan_hash:
        raise CnAMinuteGoldHistoryError("expected P6 Gold plan hash mismatch")
    return plan


def _checkpoint_path(plan: Mapping[str, object]) -> Path:
    return Path(str(plan["phase_root"])) / "candidate-checkpoint.json"


def _load_checkpoint(plan: Mapping[str, object]) -> tuple[list[str], list[dict[str, object]]]:
    path = _checkpoint_path(plan)
    if not path.exists():
        return [], []
    payload = _load_json(path, label="P6 Gold candidate checkpoint")
    if payload.get("plan_hash") != plan.get("plan_hash"):
        raise CnAMinuteGoldHistoryError("candidate checkpoint plan hash mismatch")
    completed = payload.get("completed_keys")
    files = payload.get("files")
    if not isinstance(completed, list) or not isinstance(files, list):
        raise CnAMinuteGoldHistoryError("candidate checkpoint payload is incomplete")
    return [str(value) for value in completed], [dict(value) for value in files]


def _write_checkpoint(
    plan: Mapping[str, object],
    *,
    completed: Sequence[str],
    files: Sequence[Mapping[str, object]],
) -> None:
    _atomic_write_json(
        _checkpoint_path(plan),
        {
            "schema_version": 1,
            "plan_hash": plan["plan_hash"],
            "completed_keys": list(completed),
            "files": list(files),
        },
    )


def build_cn_a_minute_gold_history_candidates(
    *,
    plan_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
) -> Path:
    """Build every target file under staging; never expose a formal partition."""

    if not apply:
        raise CnAMinuteGoldHistoryError("candidate build requires apply=True")
    started_at = perf_counter()
    plan = _load_plan(plan_report_path, expected_plan_hash=expected_plan_hash)
    _validate_source_manifest(plan)
    spec = _spec(str(plan["dataset"]))
    trade_dates = tuple(str(value) for value in plan["trade_dates"])
    candidate_lake_root = Path(str(plan["candidate_lake_root"]))
    formal_dataset_root = Path(str(plan["formal_dataset_root"]))
    if formal_dataset_root.exists():
        raise CnAMinuteGoldHistoryError(
            f"formal Gold dataset appeared before promotion: {formal_dataset_root}"
        )
    completed, manifest = _load_checkpoint(plan)
    completed_set = set(completed)
    manifest_by_key = {str(value["key"]): value for value in manifest}
    for key in completed:
        entry = manifest_by_key.get(key)
        if entry is None:
            raise CnAMinuteGoldHistoryError(f"checkpoint manifest is missing {key}")
        path = Path(str(entry["path"]))
        if not path.is_file() or _sha256_file(path) != entry.get("sha256"):
            raise CnAMinuteGoldHistoryError(
                f"checkpointed candidate is missing or changed: {path}"
            )
    resource_value = duckdb_resource or DuckDBResource()
    for target_freq in CN_A_GOLD_MINUTE_FREQS:
        source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[target_freq]
        for batch_start in range(0, len(trade_dates), CHECKPOINT_INTERVAL):
            batch_dates = trade_dates[
                batch_start : batch_start + CHECKPOINT_INTERVAL
            ]
            with resource_value.connect() as connection:
                borrowed = _BorrowedDuckDBResource(connection)
                for trade_date in batch_dates:
                    key = f"{target_freq}:{trade_date}"
                    candidate = spec.target(
                        candidate_lake_root, target_freq, trade_date
                    )
                    if key in completed_set:
                        continue
                    if candidate.exists():
                        candidate.unlink()
                    result = write_canonical_gold_minute_partition(
                        duckdb_resource=borrowed,
                        source_path=spec.source(
                            Path(str(plan["formal_lake_root"])),
                            source_freq,
                            trade_date,
                        ),
                        target_path=candidate,
                        staging_path=candidate.with_name(
                            f".{candidate.name}.{os.getpid()}.staging"
                        ),
                        target_freq=target_freq,
                        partition_key=trade_date,
                        expected_codes=(
                            spec.expected_codes(trade_date)
                            if spec.expected_codes is not None
                            else None
                        ),
                    )
                    entry = {
                        "key": key,
                        "freq": target_freq,
                        "trade_date": trade_date,
                        "path": str(candidate),
                        "sha256": _sha256_file(candidate),
                        "size_bytes": candidate.stat().st_size,
                        "row_count": result.output_row_count,
                        "expected_code_count": result.expected_code_count,
                        "elapsed_ms": round(result.elapsed_ms, 3),
                    }
                    completed.append(key)
                    completed_set.add(key)
                    manifest.append(entry)
                    manifest_by_key[key] = entry
            _write_checkpoint(plan, completed=completed, files=manifest)
    expected_count = int(plan["expected_file_count"])
    if len(completed) != expected_count or len(manifest) != expected_count:
        raise CnAMinuteGoldHistoryError("candidate checkpoint count mismatch")
    report = {
        "schema_version": 1,
        "report_type": "cn_a_minute_gold_history_candidates",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_hash": plan["plan_hash"],
        "dataset": plan["dataset"],
        "candidate_lake_root": str(candidate_lake_root),
        "file_count": len(manifest),
        "row_count": sum(int(value["row_count"]) for value in manifest),
        "size_bytes": sum(int(value["size_bytes"]) for value in manifest),
        "peak_rss_bytes": _peak_rss_bytes(),
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        "files": manifest,
        "should_stop": False,
        "writes": {"candidate_files": len(manifest), "formal_lake": 0, "dagster_events": 0},
    }
    report_path = Path(str(plan_report_path)).with_name(
        f"{plan['dataset']}_gold_candidates_{plan['plan_hash']}.json"
    )
    _atomic_write_json(report_path, report)
    return report_path


def _relation_schema(connection, path: Path) -> dict[str, str]:
    return {
        str(row[0]): str(row[1]).upper()
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [str(path)],
        ).fetchall()
    }


def _audit_paths(
    *,
    connection,
    paths: Sequence[Path],
    target_freq: int,
    expected_row_count: int,
) -> dict[str, object]:
    if not paths:
        raise CnAMinuteGoldHistoryError("candidate audit path scope is empty")
    expected_schema = {
        name: type_name.upper()
        for name, type_name in CANONICAL_GOLD_MINUTE_COLUMN_TYPES.items()
    }
    observed_schema = _relation_schema(connection, paths[0])
    target_times = expected_gold_minute_times("SSE", target_freq)
    first_time = target_times[0]
    rows = connection.execute(
        """
        WITH actual AS MATERIALIZED (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(freq AS INTEGER) AS freq,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount,
            upper(trim(CAST(exchange AS VARCHAR))) AS exchange
          FROM read_parquet(?, hive_partitioning=false, union_by_name=false)
        ), grouped AS (
          SELECT
            trade_date,
            ts_code,
            count(*) AS row_count,
            min(strftime(trade_time, '%H:%M:%S')) AS first_time,
            max(strftime(trade_time, '%H:%M:%S')) AS last_time
          FROM actual
          GROUP BY trade_date, ts_code
        )
        SELECT
          (SELECT count(*) FROM actual),
          (SELECT count(*) - count(DISTINCT (trade_date, ts_code, trade_time)) FROM actual),
          (SELECT count(*) FROM actual WHERE freq != ?),
          (SELECT count(*) FROM actual WHERE CAST(trade_time AS DATE) != trade_date),
          (SELECT count(*) FROM actual WHERE strftime(trade_time, '%H:%M:%S') > '15:00:00'),
          (SELECT count(*) FROM actual WHERE ? != 1 AND strftime(trade_time, '%H:%M:%S') = '09:30:00'),
          (SELECT count(*) FROM actual WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR vol IS NULL OR amount IS NULL OR NOT isfinite(open) OR NOT isfinite(high) OR NOT isfinite(low) OR NOT isfinite(close) OR NOT isfinite(vol) OR NOT isfinite(amount) OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR high < low OR open < low OR open > high OR close < low OR close > high OR vol < 0 OR amount < 0),
          (SELECT count(*) FROM actual WHERE exchange NOT IN ('SSE', 'SZSE', 'BSE', 'XSHG', 'XSHE')),
          (SELECT count(*) FROM grouped WHERE row_count != ? OR first_time != ? OR last_time != '15:00:00')
        """,
        [[str(path) for path in paths], target_freq, target_freq, len(target_times), first_time],
    ).fetchone()
    metrics = tuple(int(value) for value in rows)
    ready = (
        observed_schema == expected_schema
        and metrics[0] == expected_row_count
        and not any(metrics[1:])
    )
    return {
        "freq": target_freq,
        "file_count": len(paths),
        "row_count": metrics[0],
        "expected_row_count": expected_row_count,
        "duplicate_key_count": metrics[1],
        "invalid_frequency_count": metrics[2],
        "invalid_partition_count": metrics[3],
        "post_close_row_count": metrics[4],
        "non_1m_0930_row_count": metrics[5],
        "invalid_value_count": metrics[6],
        "invalid_exchange_count": metrics[7],
        "invalid_code_day_shape_count": metrics[8],
        "schema_matches": observed_schema == expected_schema,
        "ready": ready,
    }


def audit_cn_a_minute_gold_history_candidates(
    *,
    plan_report_path: Path,
    candidate_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
) -> Path:
    started_at = perf_counter()
    plan = _load_plan(plan_report_path, expected_plan_hash=expected_plan_hash)
    _validate_source_manifest(plan)
    candidate_report = _load_json(candidate_report_path, label="P6 candidate report")
    if (
        candidate_report.get("report_type") != "cn_a_minute_gold_history_candidates"
        or candidate_report.get("plan_hash") != plan["plan_hash"]
        or candidate_report.get("should_stop") is not False
    ):
        raise CnAMinuteGoldHistoryError("candidate report is not green for this plan")
    files = candidate_report.get("files")
    if not isinstance(files, list) or len(files) != int(plan["expected_file_count"]):
        raise CnAMinuteGoldHistoryError("candidate report file manifest mismatch")
    by_freq: dict[int, list[dict[str, object]]] = {
        freq: [] for freq in CN_A_GOLD_MINUTE_FREQS
    }
    fingerprint_entries: list[dict[str, object]] = []
    for value in files:
        if not isinstance(value, Mapping):
            raise CnAMinuteGoldHistoryError("candidate manifest entry is invalid")
        entry = dict(value)
        path = Path(str(entry["path"]))
        observed_hash = _sha256_file(path) if path.is_file() else "missing"
        if observed_hash != entry.get("sha256"):
            raise CnAMinuteGoldHistoryError(f"candidate is missing or changed: {path}")
        by_freq[int(entry["freq"])].append(entry)
        fingerprint_entries.append(
            {
                "key": entry["key"],
                "sha256": observed_hash,
                "size_bytes": path.stat().st_size,
                "row_count": int(entry["row_count"]),
            }
        )
    resource_value = duckdb_resource or DuckDBResource()
    with resource_value.connect() as connection:
        audits = tuple(
            _audit_paths(
                connection=connection,
                paths=tuple(Path(str(value["path"])) for value in by_freq[freq]),
                target_freq=freq,
                expected_row_count=sum(
                    int(value["row_count"]) for value in by_freq[freq]
                ),
            )
            for freq in CN_A_GOLD_MINUTE_FREQS
        )
    ready = all(bool(value["ready"]) for value in audits)
    report = {
        "schema_version": 1,
        "report_type": "cn_a_minute_gold_history_candidate_audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_hash": plan["plan_hash"],
        "dataset": plan["dataset"],
        "candidate_report_path": str(candidate_report_path),
        "candidate_fingerprint": _hash_payload(fingerprint_entries),
        "audits": list(audits),
        "ready": ready,
        "should_stop": not ready,
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        "writes": {"formal_lake": 0, "dagster_events": 0},
    }
    report_path = Path(str(plan_report_path)).with_name(
        f"{plan['dataset']}_gold_candidate_audit_{plan['plan_hash']}.json"
    )
    _atomic_write_json(report_path, report)
    return report_path


def promote_cn_a_minute_gold_history(
    *,
    plan_report_path: Path,
    candidate_report_path: Path,
    audit_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
) -> Path:
    """Atomically publish one complete dataset directory after a green audit."""

    if not apply:
        raise CnAMinuteGoldHistoryError("formal promotion requires apply=True")
    started_at = perf_counter()
    plan = _load_plan(plan_report_path, expected_plan_hash=expected_plan_hash)
    _validate_source_manifest(plan)
    candidate_report = _load_json(candidate_report_path, label="P6 candidate report")
    audit_report = _load_json(audit_report_path, label="P6 candidate audit")
    if (
        candidate_report.get("plan_hash") != plan["plan_hash"]
        or audit_report.get("plan_hash") != plan["plan_hash"]
        or audit_report.get("ready") is not True
        or audit_report.get("should_stop") is not False
    ):
        raise CnAMinuteGoldHistoryError("P6 candidate is not promotion eligible")
    files = candidate_report.get("files")
    if not isinstance(files, list):
        raise CnAMinuteGoldHistoryError("candidate report file manifest is missing")
    fingerprint_entries: list[dict[str, object]] = []
    for value in files:
        if not isinstance(value, Mapping):
            raise CnAMinuteGoldHistoryError("candidate manifest entry is invalid")
        path = Path(str(value["path"]))
        observed_hash = _sha256_file(path) if path.is_file() else "missing"
        fingerprint_entries.append(
            {
                "key": value["key"],
                "sha256": observed_hash,
                "size_bytes": path.stat().st_size if path.is_file() else -1,
                "row_count": int(value["row_count"]),
            }
        )
    if _hash_payload(fingerprint_entries) != audit_report.get("candidate_fingerprint"):
        raise CnAMinuteGoldHistoryError("candidate changed after its green audit")
    candidate_dataset_root = Path(str(plan["candidate_dataset_root"]))
    formal_dataset_root = Path(str(plan["formal_dataset_root"]))
    if formal_dataset_root.exists():
        raise CnAMinuteGoldHistoryError(
            f"formal Gold dataset root already exists: {formal_dataset_root}"
        )
    formal_dataset_root.parent.mkdir(parents=True, exist_ok=True)
    if candidate_dataset_root.stat().st_dev != formal_dataset_root.parent.stat().st_dev:
        raise CnAMinuteGoldHistoryError(
            "candidate and formal Gold roots must share one filesystem"
        )
    os.replace(candidate_dataset_root, formal_dataset_root)
    spec = _spec(str(plan["dataset"]))
    formal_files = tuple(
        spec.target(formal_dataset_root.parents[2], freq, str(trade_date))
        for freq in CN_A_GOLD_MINUTE_FREQS
        for trade_date in plan["trade_dates"]
    )
    if any(not path.is_file() for path in formal_files):
        raise CnAMinuteGoldHistoryError(
            "formal Gold dataset is incomplete after atomic directory promotion"
        )
    report = {
        "schema_version": 1,
        "report_type": "cn_a_minute_gold_history_promote",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_hash": plan["plan_hash"],
        "dataset": plan["dataset"],
        "formal_dataset_root": str(formal_dataset_root),
        "promoted_file_count": len(formal_files),
        "candidate_fingerprint": audit_report["candidate_fingerprint"],
        "should_stop": False,
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        "writes": {"formal_lake": len(formal_files), "dagster_events": 0},
    }
    report_path = Path(str(plan_report_path)).with_name(
        f"{plan['dataset']}_gold_promote_{plan['plan_hash']}.json"
    )
    _atomic_write_json(report_path, report)
    return report_path


def audit_cn_a_minute_gold_history_formal(
    *,
    plan_report_path: Path,
    candidate_report_path: Path,
    audit_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
) -> Path:
    """Re-run the aggregate core audit against the atomically promoted directory."""

    started_at = perf_counter()
    plan = _load_plan(plan_report_path, expected_plan_hash=expected_plan_hash)
    candidate_report = _load_json(candidate_report_path, label="P6 candidate report")
    candidate_audit = _load_json(audit_report_path, label="P6 candidate audit")
    if (
        candidate_report.get("plan_hash") != plan["plan_hash"]
        or candidate_audit.get("plan_hash") != plan["plan_hash"]
        or candidate_audit.get("ready") is not True
    ):
        raise CnAMinuteGoldHistoryError(
            "formal audit requires the matching green candidate audit"
        )
    files = candidate_report.get("files")
    if not isinstance(files, list):
        raise CnAMinuteGoldHistoryError("candidate report file manifest is missing")
    spec = _spec(str(plan["dataset"]))
    formal_root = Path(str(plan["formal_lake_root"]))
    by_freq: dict[int, list[dict[str, object]]] = {
        freq: [] for freq in CN_A_GOLD_MINUTE_FREQS
    }
    fingerprint_entries: list[dict[str, object]] = []
    for value in files:
        if not isinstance(value, Mapping):
            raise CnAMinuteGoldHistoryError("candidate manifest entry is invalid")
        freq = int(value["freq"])
        trade_date = str(value["trade_date"])
        formal = spec.target(formal_root, freq, trade_date)
        observed_hash = _sha256_file(formal) if formal.is_file() else "missing"
        if observed_hash != value.get("sha256"):
            raise CnAMinuteGoldHistoryError(
                f"formal Gold file differs from promoted candidate: {formal}"
            )
        entry = {**dict(value), "path": str(formal)}
        by_freq[freq].append(entry)
        fingerprint_entries.append(
            {
                "key": value["key"],
                "sha256": observed_hash,
                "size_bytes": formal.stat().st_size,
                "row_count": int(value["row_count"]),
            }
        )
    formal_fingerprint = _hash_payload(fingerprint_entries)
    if formal_fingerprint != candidate_audit.get("candidate_fingerprint"):
        raise CnAMinuteGoldHistoryError(
            "formal Gold dataset fingerprint differs from candidate audit"
        )
    resource_value = duckdb_resource or DuckDBResource()
    with resource_value.connect() as connection:
        audits = tuple(
            _audit_paths(
                connection=connection,
                paths=tuple(Path(str(value["path"])) for value in by_freq[freq]),
                target_freq=freq,
                expected_row_count=sum(
                    int(value["row_count"]) for value in by_freq[freq]
                ),
            )
            for freq in CN_A_GOLD_MINUTE_FREQS
        )
    ready = all(bool(value["ready"]) for value in audits)
    report = {
        "schema_version": 1,
        "report_type": "cn_a_minute_gold_history_formal_audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_hash": plan["plan_hash"],
        "dataset": plan["dataset"],
        "formal_dataset_root": plan["formal_dataset_root"],
        "formal_fingerprint": formal_fingerprint,
        "file_count": len(files),
        "row_count": sum(int(value["row_count"]) for value in files),
        "audits": list(audits),
        "ready": ready,
        "should_stop": not ready,
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        "writes": {"formal_lake": 0, "dagster_events": 0},
    }
    report_path = Path(str(plan_report_path)).with_name(
        f"{plan['dataset']}_gold_formal_audit_{plan['plan_hash']}.json"
    )
    _atomic_write_json(report_path, report)
    return report_path


def _equivalence_year_audit(
    *,
    connection,
    gold_paths: Sequence[Path],
    silver_paths: Sequence[Path],
    freq: int,
    year: int,
) -> dict[str, object]:
    if not gold_paths or len(gold_paths) != len(silver_paths):
        raise CnAMinuteGoldHistoryError(
            f"equivalence scope is incomplete: freq={freq}, year={year}"
        )
    row = connection.execute(
        """
        WITH gold AS MATERIALIZED (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(freq AS INTEGER) AS freq,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount,
            CASE upper(trim(CAST(exchange AS VARCHAR)))
              WHEN 'XSHG' THEN 'SSE'
              WHEN 'XSHE' THEN 'SZSE'
              ELSE upper(trim(CAST(exchange AS VARCHAR)))
            END AS exchange,
            CAST(vwap AS DOUBLE) AS vwap
          FROM read_parquet(?, hive_partitioning=false, union_by_name=false)
        ), silver AS MATERIALIZED (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_time AS DATE) AS trade_date,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(regexp_extract(CAST(freq AS VARCHAR), '^[0-9]+') AS INTEGER) AS freq,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount,
            CASE upper(trim(CAST(exchange AS VARCHAR)))
              WHEN 'XSHG' THEN 'SSE'
              WHEN 'XSHE' THEN 'SZSE'
              ELSE upper(trim(CAST(exchange AS VARCHAR)))
            END AS exchange,
            CAST(vwap AS DOUBLE) AS vwap
          FROM read_parquet(?, hive_partitioning=false, union_by_name=false)
        ), compared AS (
          SELECT
            g.ts_code AS gold_code,
            s.ts_code AS silver_code,
            g.open IS DISTINCT FROM s.open
              OR g.high IS DISTINCT FROM s.high
              OR g.low IS DISTINCT FROM s.low
              OR g.close IS DISTINCT FROM s.close
              OR g.vol IS DISTINCT FROM s.vol
              OR NOT (
                (g.amount IS NULL AND s.amount IS NULL)
                OR (
                  g.amount IS NOT NULL
                  AND s.amount IS NOT NULL
                  AND abs(g.amount - s.amount) <= ?
                )
              )
              OR g.exchange IS DISTINCT FROM s.exchange
              OR g.vwap IS DISTINCT FROM s.vwap
              OR g.freq IS DISTINCT FROM s.freq AS value_mismatch
          FROM gold AS g
          FULL OUTER JOIN silver AS s
            ON g.ts_code = s.ts_code
           AND g.trade_date = s.trade_date
           AND g.trade_time = s.trade_time
        )
        SELECT
          (SELECT count(*) FROM gold) AS gold_rows,
          (SELECT count(*) FROM silver) AS silver_rows,
          (SELECT count(*) FROM compared WHERE gold_code IS NULL) AS missing_in_gold,
          (SELECT count(*) FROM compared WHERE silver_code IS NULL) AS missing_in_silver,
          (SELECT count(*) FROM compared WHERE gold_code IS NOT NULL AND silver_code IS NOT NULL AND value_mismatch) AS value_mismatch_count,
          (SELECT bit_xor(hash(ts_code, trade_date, trade_time)) FROM gold) AS gold_key_hash,
          (SELECT bit_xor(hash(ts_code, trade_date, trade_time)) FROM silver) AS silver_key_hash,
          (SELECT bit_xor(hash(open, high, low, close, vol, round(amount, 6), exchange, vwap, freq)) FROM gold) AS gold_value_hash,
          (SELECT bit_xor(hash(open, high, low, close, vol, round(amount, 6), exchange, vwap, freq)) FROM silver) AS silver_value_hash
        """,
        [
            [str(path) for path in gold_paths],
            [str(path) for path in silver_paths],
            AMOUNT_ABS_TOLERANCE,
        ],
    ).fetchone()
    metrics = {
        "freq": freq,
        "year": year,
        "file_count": len(gold_paths),
        "gold_row_count": int(row[0]),
        "silver_row_count": int(row[1]),
        "missing_in_gold_count": int(row[2]),
        "missing_in_silver_count": int(row[3]),
        "value_mismatch_count": int(row[4]),
        "gold_key_hash": str(row[5]),
        "silver_key_hash": str(row[6]),
        "gold_value_hash": str(row[7]),
        "silver_value_hash": str(row[8]),
    }
    metrics["ready"] = (
        metrics["gold_row_count"] == metrics["silver_row_count"]
        and metrics["missing_in_gold_count"] == 0
        and metrics["missing_in_silver_count"] == 0
        and metrics["value_mismatch_count"] == 0
        and metrics["gold_key_hash"] == metrics["silver_key_hash"]
        and metrics["gold_value_hash"] == metrics["silver_value_hash"]
    )
    return metrics


def audit_major_index_gold_silver_equivalence(
    *,
    plan_report_path: Path,
    expected_plan_hash: str,
    frequencies: Sequence[int] = MAJOR_INDEX_EQUIVALENCE_FREQS,
    duckdb_resource: DuckDBResource | None = None,
) -> Path:
    """Prove unchanged major-index frequencies do not require indicator rebuild."""

    started_at = perf_counter()
    plan = _load_plan(plan_report_path, expected_plan_hash=expected_plan_hash)
    if plan.get("dataset") != "major_index_mins":
        raise CnAMinuteGoldHistoryError(
            "Gold/Silver equivalence is only defined for major_index_mins"
        )
    normalized_frequencies = tuple(dict.fromkeys(int(value) for value in frequencies))
    if not normalized_frequencies or any(
        value not in MAJOR_INDEX_EQUIVALENCE_FREQS
        for value in normalized_frequencies
    ):
        raise CnAMinuteGoldHistoryError(
            "equivalence frequencies must be a non-empty subset of (1, 90, 120)"
        )
    trade_dates = tuple(str(value) for value in plan["trade_dates"])
    formal_root = Path(str(plan["formal_lake_root"]))
    dates_by_year: dict[int, list[str]] = {}
    for trade_date in trade_dates:
        dates_by_year.setdefault(int(trade_date[:4]), []).append(trade_date)
    audits: list[dict[str, object]] = []
    resource_value = duckdb_resource or DuckDBResource()
    with resource_value.connect() as connection:
        for freq in normalized_frequencies:
            for year, year_dates in sorted(dates_by_year.items()):
                gold_paths = tuple(
                    gold_major_index_mins_path(formal_root, freq, trade_date)
                    for trade_date in year_dates
                )
                silver_paths = tuple(
                    silver_major_index_mins_path(
                        formal_root, f"{freq}min", trade_date
                    )
                    for trade_date in year_dates
                )
                missing = tuple(
                    str(path)
                    for path in (*gold_paths, *silver_paths)
                    if not path.is_file()
                )
                if missing:
                    raise CnAMinuteGoldHistoryError(
                        "equivalence input file is missing: "
                        f"freq={freq}, year={year}, samples={missing[:10]!r}"
                    )
                audits.append(
                    _equivalence_year_audit(
                        connection=connection,
                        gold_paths=gold_paths,
                        silver_paths=silver_paths,
                        freq=freq,
                        year=year,
                    )
                )
    ready = all(bool(value["ready"]) for value in audits)
    report = {
        "schema_version": 1,
        "report_type": "major_index_gold_silver_equivalence",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_hash": plan["plan_hash"],
        "dataset": plan["dataset"],
        "frequencies": list(normalized_frequencies),
        "date_count": len(trade_dates),
        "amount_abs_tolerance": AMOUNT_ABS_TOLERANCE,
        "audits": audits,
        "ready": ready,
        "should_stop": not ready,
        "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
        "writes": {"formal_lake": 0, "dagster_events": 0},
    }
    report_path = Path(str(plan_report_path)).with_name(
        f"major_index_mins_gold_silver_equivalence_{plan['plan_hash']}.json"
    )
    _atomic_write_json(report_path, report)
    return report_path


__all__ = [
    "CnAMinuteGoldHistoryError",
    "audit_cn_a_minute_gold_history_candidates",
    "audit_cn_a_minute_gold_history_formal",
    "audit_major_index_gold_silver_equivalence",
    "build_cn_a_minute_gold_history_candidates",
    "build_cn_a_minute_gold_history_plan",
    "promote_cn_a_minute_gold_history",
]
