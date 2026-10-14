from dataclasses import dataclass

from src.foundation.clients.local_lake.major_index_mins_contract import MAX_INDEX_MINUTE_PARTITION_FILES
from src.foundation.clients.local_lake.major_index_mins_reader import MAX_INDEX_MINUTE_HISTORY_ROWS


@dataclass(frozen=True, slots=True)
class XxmRuntimeBudget:
    source_batch_rows: int = 1000
    max_source_rows: int = MAX_INDEX_MINUTE_HISTORY_ROWS
    max_source_partitions: int = MAX_INDEX_MINUTE_PARTITION_FILES
    response_default_day: int = 300
    response_default_minute: int = 500
    max_response_rows: int = 2000
    max_response_bytes: int = 1024 * 1024
    cache_max_bytes: int = 64 * 1024 * 1024
    cache_max_series: int = 16
    max_concurrent_requests: int = 2
    request_deadline_seconds: float = 4.0


BUDGET = XxmRuntimeBudget()
