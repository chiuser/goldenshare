from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AffectedPartition:
    dataset_key: str
    source_key: str
    layer: str
    partition_grain: str
    partition_values: dict[str, str]
    partition_path: str
    source_run_id: str
    write_revision: str
    rows_written: int
    bytes_written: int

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_key": self.dataset_key,
            "source_key": self.source_key,
            "layer": self.layer,
            "partition_grain": self.partition_grain,
            "partition_values": dict(self.partition_values),
            "partition_path": self.partition_path,
            "source_run_id": self.source_run_id,
            "write_revision": self.write_revision,
            "rows_written": self.rows_written,
            "bytes_written": self.bytes_written,
        }
