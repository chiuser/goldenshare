"""正式周月线发布的单对象点查，无日线请求、文件写入或缓存。"""

from orchestrator.defs.io.index_period_writer import download_index_period_rows
from orchestrator.defs.run_contracts.index_period import INDEX_PERIOD_PROBE_CODE


def index_period_source_published(period, period_end) -> bool:
    return bool(download_index_period_rows(
        period, period_end, codes=(INDEX_PERIOD_PROBE_CODE,), required_codes=(),
    ))
