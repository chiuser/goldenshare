"""不可变的计算配置，不读取环境或数据文件。"""

from __future__ import annotations

from dataclasses import dataclass, fields

from ..contracts import _MAX_OUTPUT_ROWS


@dataclass(frozen=True, slots=True)
class KernelConfig:
    """一次运行实例的配置。"""

    goldenshare_lake_root: str
    max_concurrent_requests: int
    max_waiting_requests: int
    max_wait_ms: int
    sql_threads: int
    batch_rows: int
    query_memory_bytes: int
    request_memory_bytes: int
    deployment_reserve_bytes: int
    total_target_ms: int
    cleanup_reserve_ms: int
    max_input_rows: int
    max_source_files: int
    max_output_rows: int
    max_indicator_instances: int
    max_projected_row_group_bytes: int
    control_poll_ms: int
    monitor_join_target_ms: int

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name == "goldenshare_lake_root":
                continue
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field.name} must be an integer, not bool")
            minimum = 0 if field.name == "max_waiting_requests" else 1
            if value < minimum:
                raise ValueError(f"{field.name} must be >= {minimum}")
        if self.cleanup_reserve_ms >= self.total_target_ms:
            raise ValueError("cleanup_reserve_ms must be smaller than total_target_ms")
        if self.control_poll_ms >= self.cleanup_reserve_ms:
            raise ValueError("control_poll_ms must be smaller than cleanup_reserve_ms")
        if self.max_output_rows > _MAX_OUTPUT_ROWS:
            raise ValueError(f"max_output_rows must be <= {_MAX_OUTPUT_ROWS}")
