from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.parquet_writer import read_parquet_rows, replace_file_atomically, write_rows_to_parquet
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


CLEAN_NEXT_GATE_SCHEMA_VERSION = 1
CLEAN_NEXT_GATE_RELATIVE_PATH = Path("manifest") / "stk_mins_quality" / "clean_next_partition_gate.parquet"
CLEAN_NEXT_GATE_FIELDS = (
    "gate_schema_version",
    "dataset_key",
    "source_key",
    "freq",
    "trade_date",
    "partition_key",
    "clean_partition_path",
    "source_run_id",
    "clean_run_id",
    "write_revision",
    "status",
    "issue_count",
    "raw_rows",
    "clean_rows",
    "checked_at",
    "ledger_path",
    "message",
)


@dataclass(frozen=True)
class CleanNextGateStatus:
    freq: int
    trade_date: date
    clean_partition_path: str
    source_run_id: str
    clean_run_id: str
    write_revision: str
    status: str
    issue_count: int
    raw_rows: int
    clean_rows: int
    ledger_path: str
    message: str
    checked_at: datetime | None = None

    @property
    def partition_key(self) -> str:
        return clean_next_partition_key(freq=self.freq, trade_date=self.trade_date)

    def to_dict(self) -> dict[str, object]:
        checked_at = self.checked_at or datetime.now(timezone.utc)
        return {
            "gate_schema_version": CLEAN_NEXT_GATE_SCHEMA_VERSION,
            "dataset_key": "stk_mins",
            "source_key": "tushare",
            "freq": self.freq,
            "trade_date": self.trade_date,
            "partition_key": self.partition_key,
            "clean_partition_path": self.clean_partition_path,
            "source_run_id": self.source_run_id,
            "clean_run_id": self.clean_run_id,
            "write_revision": self.write_revision,
            "status": self.status,
            "issue_count": self.issue_count,
            "raw_rows": self.raw_rows,
            "clean_rows": self.clean_rows,
            "checked_at": checked_at,
            "ledger_path": self.ledger_path,
            "message": self.message,
        }


class CleanNextGateBlockedError(RuntimeError):
    pass


class CleanNextPartitionGateService:
    def __init__(self, *, lake_root: Path) -> None:
        self.lake_root = lake_root

    @property
    def gate_file(self) -> Path:
        return self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH

    def write_statuses(self, statuses: list[CleanNextGateStatus], *, run_id: str) -> dict[str, object]:
        if not statuses:
            return {
                "run_id": run_id,
                "path": str(self.gate_file),
                "updated_partitions": 0,
                "written_rows": len(self._read_rows()),
            }

        LakeRootService(self.lake_root).require_ready_for_write()
        existing_by_key = {str(row.get("partition_key") or ""): _project_gate_row(row) for row in self._read_rows()}
        for status in statuses:
            existing_by_key[status.partition_key] = _project_gate_row(status.to_dict())

        gate_rows = sorted(existing_by_key.values(), key=lambda row: str(row["partition_key"]))
        tmp_file = self.lake_root / "_tmp" / run_id / CLEAN_NEXT_GATE_RELATIVE_PATH
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / CLEAN_NEXT_GATE_RELATIVE_PATH.parent
        written = write_rows_to_parquet(gate_rows, tmp_file)
        replace_file_atomically(tmp_file=tmp_file, final_file=self.gate_file, backup_root=backup_root)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        return {
            "run_id": run_id,
            "path": str(self.gate_file),
            "updated_partitions": len(statuses),
            "written_rows": written,
        }

    def read_statuses(self) -> list[dict[str, Any]]:
        return self._read_rows()

    def require_passed(self, *, freq: int, trade_date: date) -> dict[str, Any]:
        partition_key = clean_next_partition_key(freq=freq, trade_date=trade_date)
        row = next((item for item in self._read_rows() if str(item.get("partition_key") or "") == partition_key), None)
        if not row:
            raise CleanNextGateBlockedError(f"clean_next gate 缺少分区状态：{partition_key}")
        if str(row.get("status") or "") != "passed":
            ledger_path = row.get("ledger_path") or "-"
            raise CleanNextGateBlockedError(f"clean_next gate 未通过：{partition_key} status={row.get('status')} ledger={ledger_path}")
        return row

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.gate_file.exists():
            return []
        return read_parquet_rows(self.gate_file)


def clean_next_partition_key(*, freq: int, trade_date: date) -> str:
    return f"freq={freq}/trade_date={trade_date.isoformat()}"


def _project_gate_row(row: dict[str, Any]) -> dict[str, Any]:
    projected = {field: row.get(field) for field in CLEAN_NEXT_GATE_FIELDS}
    projected["gate_schema_version"] = CLEAN_NEXT_GATE_SCHEMA_VERSION
    projected["dataset_key"] = projected.get("dataset_key") or "stk_mins"
    projected["source_key"] = projected.get("source_key") or "tushare"
    projected["freq"] = int(projected.get("freq") or 0)
    projected["trade_date"] = _parse_date(projected.get("trade_date"))
    projected["partition_key"] = projected.get("partition_key") or clean_next_partition_key(
        freq=int(projected["freq"]),
        trade_date=projected["trade_date"],
    )
    projected["status"] = projected.get("status") or "failed"
    projected["issue_count"] = int(projected.get("issue_count") or 0)
    projected["raw_rows"] = int(projected.get("raw_rows") or 0)
    projected["clean_rows"] = int(projected.get("clean_rows") or 0)
    return projected


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
