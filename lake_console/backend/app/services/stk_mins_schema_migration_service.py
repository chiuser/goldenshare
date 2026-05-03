from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.tushare_stk_mins import STK_MINS_FIELDS
from lake_console.backend.app.services.parquet_writer import replace_file_atomically
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


@dataclass(frozen=True)
class StkMinsSchemaMigrationFile:
    path: Path
    freq: int
    trade_date: date
    size_bytes: int


@dataclass(frozen=True)
class StkMinsSchemaMigrationResult:
    path: str
    action: str
    row_count: int | None
    size_bytes: int
    reason: str


class StkMinsSchemaMigrationService:
    """Migrate local stk_mins raw parquet files to the current Lake schema."""

    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or print

    def migrate(
        self,
        *,
        dry_run: bool,
        apply: bool,
        freq: int | None = None,
        trade_date: date | None = None,
    ) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("必须且只能指定 dry_run 或 apply。")

        started = time.monotonic()
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-stk-mins-schema"
        files = self._scan_files(freq=freq, trade_date=trade_date)
        self.progress(
            f"[stk_mins_schema] start mode={'apply' if apply else 'dry-run'} "
            f"files={len(files)} freq={freq or '-'} trade_date={trade_date.isoformat() if trade_date else '-'}"
        )

        results: list[StkMinsSchemaMigrationResult] = []
        for index, file in enumerate(files, start=1):
            if dry_run:
                result = self._inspect_file(file)
            else:
                result = self._migrate_file(run_id=run_id, file=file)
            results.append(result)
            if apply or result.action != "skip_current":
                self.progress(
                    f"[stk_mins_schema] {index}/{len(files)} action={result.action} "
                    f"freq={file.freq} trade_date={file.trade_date.isoformat()} rows={result.row_count or '-'}"
                )

        elapsed = round(time.monotonic() - started, 3)
        if apply:
            TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)

        action_counts: dict[str, int] = {}
        for result in results:
            action_counts[result.action] = action_counts.get(result.action, 0) + 1

        summary = {
            "dataset_key": "stk_mins",
            "operation": "migrate_stk_mins_schema",
            "mode": "apply" if apply else "dry_run",
            "run_id": run_id if apply else None,
            "filter": {
                "freq": freq,
                "trade_date": trade_date.isoformat() if trade_date else None,
            },
            "file_count": len(files),
            "total_bytes": sum(file.size_bytes for file in files),
            "action_counts": action_counts,
            "elapsed_seconds": elapsed,
            "results": [
                {
                    "path": result.path,
                    "action": result.action,
                    "row_count": result.row_count,
                    "size_bytes": result.size_bytes,
                    "reason": result.reason,
                }
                for result in results
            ],
        }
        self.progress(f"[stk_mins_schema] done files={len(files)} actions={action_counts} elapsed={elapsed}s")
        return summary

    def _scan_files(self, *, freq: int | None, trade_date: date | None) -> list[StkMinsSchemaMigrationFile]:
        root = self.lake_root / "raw_tushare" / "stk_mins_by_date"
        if not root.exists():
            return []
        files: list[StkMinsSchemaMigrationFile] = []
        freq_dirs = [root / f"freq={freq}"] if freq is not None else sorted(root.glob("freq=*"))
        for freq_dir in freq_dirs:
            parsed_freq = _parse_int_partition(freq_dir.name, "freq")
            if parsed_freq is None or not freq_dir.is_dir():
                continue
            date_dirs = [freq_dir / f"trade_date={trade_date.isoformat()}"] if trade_date else sorted(freq_dir.glob("trade_date=*"))
            for date_dir in date_dirs:
                parsed_date = _parse_date_partition(date_dir.name, "trade_date")
                if parsed_date is None or not date_dir.is_dir():
                    continue
                for parquet_file in sorted(date_dir.glob("*.parquet")):
                    files.append(
                        StkMinsSchemaMigrationFile(
                            path=parquet_file,
                            freq=parsed_freq,
                            trade_date=parsed_date,
                            size_bytes=parquet_file.stat().st_size,
                        )
                    )
        return files

    def _inspect_file(self, file: StkMinsSchemaMigrationFile) -> StkMinsSchemaMigrationResult:
        pq = _require_pyarrow_parquet()
        try:
            schema = pq.read_schema(file.path)
            names = list(schema.names)
            reasons = _schema_migration_reasons(schema)
            action = "would_migrate" if reasons else "skip_current"
            row_count = pq.ParquetFile(file.path).metadata.num_rows
            return StkMinsSchemaMigrationResult(
                path=str(file.path),
                action=action,
                row_count=row_count,
                size_bytes=file.size_bytes,
                reason=", ".join(reasons) if reasons else "schema_current",
            )
        except Exception as exc:  # noqa: BLE001
            return StkMinsSchemaMigrationResult(
                path=str(file.path),
                action="inspect_failed",
                row_count=None,
                size_bytes=file.size_bytes,
                reason=str(exc),
            )

    def _migrate_file(self, *, run_id: str, file: StkMinsSchemaMigrationFile) -> StkMinsSchemaMigrationResult:
        inspection = self._inspect_file(file)
        if inspection.action == "skip_current":
            return inspection
        if inspection.action == "inspect_failed":
            return inspection

        pd = _require_pandas()
        try:
            frame = pd.read_parquet(file.path, engine="pyarrow")
            original_count = len(frame)
            migrated = _normalize_frame(frame, freq=file.freq, trade_date=file.trade_date)
            if len(migrated) != original_count:
                raise ValueError(f"迁移前后行数不一致：before={original_count} after={len(migrated)}")
            tmp_file = self._tmp_file(run_id=run_id, file=file)
            backup_root = self._backup_root(run_id=run_id, file=file)
            tmp_file.parent.mkdir(parents=True, exist_ok=True)
            migrated.to_parquet(tmp_file, index=False, engine="pyarrow", compression="zstd")
            _validate_output_file(tmp_file, expected_rows=original_count)
            replace_file_atomically(tmp_file=tmp_file, final_file=file.path, backup_root=backup_root)
            return StkMinsSchemaMigrationResult(
                path=str(file.path),
                action="migrated",
                row_count=original_count,
                size_bytes=file.size_bytes,
                reason=inspection.reason,
            )
        except Exception as exc:  # noqa: BLE001
            return StkMinsSchemaMigrationResult(
                path=str(file.path),
                action="migrate_failed",
                row_count=None,
                size_bytes=file.size_bytes,
                reason=str(exc),
            )

    def _tmp_file(self, *, run_id: str, file: StkMinsSchemaMigrationFile) -> Path:
        return (
            self.lake_root
            / "_tmp"
            / run_id
            / "raw_tushare"
            / "stk_mins_by_date"
            / f"freq={file.freq}"
            / f"trade_date={file.trade_date.isoformat()}"
            / file.path.name
        )

    def _backup_root(self, *, run_id: str, file: StkMinsSchemaMigrationFile) -> Path:
        return (
            self.lake_root
            / "_tmp"
            / run_id
            / "_backup"
            / "stk_mins_schema"
            / f"freq={file.freq}"
            / f"trade_date={file.trade_date.isoformat()}"
        )


def _normalize_frame(frame, *, freq: int, trade_date: date):  # type: ignore[no-untyped-def]
    pd = _require_pandas()
    required = {"ts_code", "trade_time", "open", "close", "high", "low", "vol", "amount"}
    missing_required = sorted(required - set(frame.columns))
    if missing_required:
        raise ValueError(f"缺少必需字段：{missing_required}")

    normalized = pd.DataFrame()
    normalized["ts_code"] = frame["ts_code"].astype("string")
    if normalized["ts_code"].isna().any():
        raise ValueError("ts_code 存在空值。")

    normalized["freq"] = _normalize_freq_column(frame, expected_freq=freq)
    trade_time = pd.to_datetime(frame["trade_time"], errors="raise")
    if getattr(trade_time.dt, "tz", None) is not None:
        trade_time = trade_time.dt.tz_localize(None)
    if trade_time.isna().any():
        raise ValueError("trade_time 存在空值。")
    wrong_date = trade_time.dt.date != trade_date
    if wrong_date.any():
        raise ValueError(f"trade_time 存在不属于分区 trade_date={trade_date.isoformat()} 的记录。")
    normalized["trade_time"] = trade_time

    for field in ("open", "close", "high", "low", "amount", "vwap"):
        if field in frame.columns:
            normalized[field] = pd.to_numeric(frame[field], errors="raise").astype("float64")
        else:
            normalized[field] = pd.Series([None] * len(frame), dtype="float64")

    vol = pd.to_numeric(frame["vol"], errors="raise")
    vol_non_null = vol.dropna()
    if not ((vol_non_null % 1) == 0).all():
        raise ValueError("vol 存在非整数值。")
    normalized["vol"] = vol.astype("Int64")

    if "exchange" in frame.columns:
        exchange = frame["exchange"].astype("string").str.strip()
        normalized["exchange"] = exchange.mask(exchange.isin(["", "nan", "None", "null"]))
    else:
        normalized["exchange"] = pd.Series([None] * len(frame), dtype="string")

    return normalized[list(STK_MINS_FIELDS)]


def _normalize_freq_column(frame, *, expected_freq: int):  # type: ignore[no-untyped-def]
    pd = _require_pandas()
    if "freq" not in frame.columns:
        return pd.Series([expected_freq] * len(frame), dtype="int16")
    parsed = frame["freq"].map(_parse_freq_value)
    non_null = parsed.dropna()
    if not (non_null == expected_freq).all():
        raise ValueError(f"freq 字段与分区 freq={expected_freq} 不一致。")
    return pd.Series([expected_freq] * len(frame), dtype="int16")


def _parse_freq_value(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return None
    if text.endswith("min"):
        text = text[:-3]
    return int(float(text))


def _schema_migration_reasons(schema) -> list[str]:  # type: ignore[no-untyped-def]
    pa = _require_pyarrow()
    names = list(schema.names)
    reasons: list[str] = []
    if names != list(STK_MINS_FIELDS):
        reasons.append("columns")
    for field in ("exchange", "vwap"):
        if field not in names:
            reasons.append(f"missing_{field}")
    if "trade_time" in names and not pa.types.is_timestamp(schema.field("trade_time").type):
        reasons.append("trade_time_not_timestamp")
    if "freq" in names:
        freq_type = schema.field("freq").type
        if not pa.types.is_integer(freq_type):
            reasons.append("freq_not_integer")
    else:
        reasons.append("missing_freq")
    if "vol" in names:
        vol_type = schema.field("vol").type
        if not pa.types.is_integer(vol_type):
            reasons.append("vol_not_integer")
    return sorted(set(reasons))


def _validate_output_file(path: Path, *, expected_rows: int) -> None:
    pq = _require_pyarrow_parquet()
    schema = pq.read_schema(path)
    reasons = _schema_migration_reasons(schema)
    if reasons:
        raise ValueError(f"迁移后 schema 仍不符合目标：{reasons}")
    row_count = pq.ParquetFile(path).metadata.num_rows
    if row_count != expected_rows:
        raise ValueError(f"迁移后行数不一致：expected={expected_rows} actual={row_count}")


def _parse_int_partition(name: str, key: str) -> int | None:
    prefix = f"{key}="
    if not name.startswith(prefix):
        return None
    try:
        return int(name[len(prefix) :])
    except ValueError:
        return None


def _parse_date_partition(name: str, key: str) -> date | None:
    prefix = f"{key}="
    if not name.startswith(prefix):
        return None
    try:
        return date.fromisoformat(name[len(prefix) :])
    except ValueError:
        return None


def _require_pandas():  # type: ignore[no-untyped-def]
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少迁移依赖，请先安装 lake_console/backend/requirements.txt。") from exc
    return pd


def _require_pyarrow():  # type: ignore[no-untyped-def]
    try:
        import pyarrow as pa
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 pyarrow，请先安装 lake_console/backend/requirements.txt。") from exc
    return pa


def _require_pyarrow_parquet():  # type: ignore[no-untyped-def]
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 pyarrow，请先安装 lake_console/backend/requirements.txt。") from exc
    return pq
