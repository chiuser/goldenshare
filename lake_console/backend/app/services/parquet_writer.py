from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class ParquetDependencyError(RuntimeError):
    pass


def write_rows_to_parquet(
    rows: list[dict[str, Any]],
    output_path: Path,
    *,
    column_dtypes: Mapping[str, str] | None = None,
) -> int:
    if not rows:
        raise ValueError("没有可写入的行。")
    pd = _require_pandas()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    for column, dtype in (column_dtypes or {}).items():
        if column not in frame.columns:
            raise ValueError(f"Parquet dtype override 字段不存在：{column}")
        frame[column] = frame[column].astype(dtype)
    frame.to_parquet(output_path, index=False, engine="pyarrow", compression="zstd")
    return len(frame)


def read_parquet_row_count(path: Path) -> int:
    pd = _require_pandas()
    frame = pd.read_parquet(path, engine="pyarrow")
    return int(len(frame))


def read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    pd = _require_pandas()
    frame = pd.read_parquet(path, engine="pyarrow")
    return [dict(row) for row in frame.to_dict(orient="records")]


def read_parquet_files(paths: list[Path]) -> list[dict[str, Any]]:
    if not paths:
        return []
    pd = _require_pandas()
    frames = [pd.read_parquet(path, engine="pyarrow") for path in paths]
    if not frames:
        return []
    frame = pd.concat(frames, ignore_index=True)
    return [dict(row) for row in frame.to_dict(orient="records")]


def replace_file_atomically(*, tmp_file: Path, final_file: Path, backup_root: Path) -> None:
    final_file.parent.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_file = backup_root / final_file.name
    final_moved = False
    try:
        if final_file.exists():
            if backup_file.exists():
                backup_file.unlink()
            final_file.replace(backup_file)
            final_moved = True
        tmp_file.replace(final_file)
    except Exception:
        if final_moved and backup_file.exists() and not final_file.exists():
            backup_file.replace(final_file)
        raise
    else:
        if backup_file.exists():
            backup_file.unlink()


def replace_directory_atomically(*, tmp_dir: Path, final_dir: Path, backup_root: Path) -> None:
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / final_dir.name
    final_moved = False
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if final_dir.exists():
            final_dir.replace(backup_dir)
            final_moved = True
        tmp_dir.replace(final_dir)
    except Exception:
        if final_moved and backup_dir.exists() and not final_dir.exists():
            backup_dir.replace(final_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)


def _require_pandas():  # type: ignore[no-untyped-def]
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:
        raise ParquetDependencyError(
            "缺少 Parquet 写入依赖。请先安装：python3 -m pip install -r lake_console/backend/requirements.txt"
        ) from exc
    return pd
