from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.parquet_writer import (
    read_parquet_files,
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)


@dataclass(frozen=True)
class IndexMinsPartitionKey:
    freq: str
    trade_date: date


class IndexMinsPartitionWriter:
    def __init__(self, *, lake_root: Path, run_id: str, progress=None) -> None:
        self.lake_root = lake_root
        self.run_id = run_id
        self.progress = progress or print
        self._chunk_index_by_key: dict[IndexMinsPartitionKey, int] = {}

    def stage_rows(self, *, freq: str, trade_date: date, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        key = IndexMinsPartitionKey(freq=freq, trade_date=trade_date)
        chunk_index = self._chunk_index_by_key.get(key, 0) + 1
        self._chunk_index_by_key[key] = chunk_index
        chunk_file = self._chunk_file(key=key, chunk_index=chunk_index)
        write_rows_to_parquet(rows, chunk_file)

    def finalize_partition(
        self,
        *,
        freq: str,
        trade_date: date,
        skip_reason: str | None,
    ) -> dict[str, Any]:
        key = IndexMinsPartitionKey(freq=freq, trade_date=trade_date)
        chunk_files = self._chunk_files(key=key)
        if not chunk_files:
            return {
                "freq": freq,
                "trade_date": trade_date.isoformat(),
                "written_rows": 0,
                "skipped_replace": True,
                "skip_reason": skip_reason or "no_data",
                "output": None,
            }

        rows = read_parquet_files(chunk_files)
        rows.sort(key=lambda item: (str(item.get("ts_code") or ""), item.get("trade_time")))
        _assert_no_duplicate_rows(freq=freq, rows=rows)

        tmp_dir = self._final_tmp_dir(key=key)
        tmp_file = tmp_dir / "part-000.parquet"
        final_dir = self._final_dir(key=key)
        final_file = final_dir / "part-000.parquet"
        backup_root = self._backup_root(key=key)

        written = _write_and_validate(rows=rows, tmp_file=tmp_file)
        replace_directory_atomically(tmp_dir=tmp_dir, final_dir=final_dir, backup_root=backup_root)
        self.progress(
            f"[index_mins] finalized freq={freq} trade_date={trade_date.isoformat()} written={written} output={final_file}"
        )
        return {
            "freq": freq,
            "trade_date": trade_date.isoformat(),
            "written_rows": written,
            "skipped_replace": False,
            "skip_reason": None,
            "output": str(final_file),
        }

    def _chunk_file(self, *, key: IndexMinsPartitionKey, chunk_index: int) -> Path:
        return (
            self.lake_root
            / "_tmp"
            / self.run_id
            / "_stage"
            / "index_mins"
            / f"freq={key.freq}"
            / f"trade_date={key.trade_date.isoformat()}"
            / "chunks"
            / f"part-{chunk_index:05d}.parquet"
        )

    def _chunk_files(self, *, key: IndexMinsPartitionKey) -> list[Path]:
        chunk_dir = self._chunk_file(key=key, chunk_index=1).parent
        if not chunk_dir.exists():
            return []
        return sorted(path for path in chunk_dir.iterdir() if path.suffix == ".parquet")

    def _final_tmp_dir(self, *, key: IndexMinsPartitionKey) -> Path:
        return (
            self.lake_root
            / "_tmp"
            / self.run_id
            / "raw_tushare"
            / "index_mins_by_date"
            / f"freq={key.freq}"
            / f"trade_date={key.trade_date.isoformat()}"
        )

    def _final_dir(self, *, key: IndexMinsPartitionKey) -> Path:
        return (
            self.lake_root
            / "raw_tushare"
            / "index_mins_by_date"
            / f"freq={key.freq}"
            / f"trade_date={key.trade_date.isoformat()}"
        )

    def _backup_root(self, *, key: IndexMinsPartitionKey) -> Path:
        return (
            self.lake_root
            / "_tmp"
            / self.run_id
            / "_backup"
            / "index_mins_by_date"
            / f"freq={key.freq}"
            / f"trade_date={key.trade_date.isoformat()}"
        )


def _assert_no_duplicate_rows(*, freq: str, rows: list[dict[str, Any]]) -> None:
    seen_keys: set[tuple[str, str, Any]] = set()
    for row in rows:
        key = (
            str(row.get("ts_code") or ""),
            freq,
            row.get("trade_time"),
        )
        if key in seen_keys:
            raise RuntimeError(
                f"index_mins 分区出现重复主键：freq={freq} ts_code={key[0]} trade_time={key[2]!r}"
            )
        seen_keys.add(key)


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(
            f"index_mins Parquet 校验失败：written={written} validated={validated} file={tmp_file}"
        )
    return written
