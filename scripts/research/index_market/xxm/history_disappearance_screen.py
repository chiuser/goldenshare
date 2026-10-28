"""P2 pure in-memory observation of the unique formal r4 calculator."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import resource
import sys
import time

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar, XxmStep


def observe_rows(bars, *, period, source_identity, check) -> tuple[XxmStep, ...]:
    """P2 single formal r4 observation; no source reads or result persistence.

    This function executes only the formal calculator.
    """
    deadline = time.perf_counter() + 20.0

    def guard():
        check()
        if time.perf_counter() >= deadline:
            raise TimeoutError("离线观察超过20秒")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
        if peak > 256 * 1024 * 1024:
            raise ValueError("离线观察超过256MiB内存")

    guard()
    calculator = XxmCalculator(period=period, source_identity=source_identity, record_decisions=True)
    results, result_bytes = [], 0
    for index, bar in enumerate(bars):
        guard()
        if index >= 1000 or not isinstance(bar, XxmBar):
            raise ValueError("离线观察只接受最多1000根标准XxmBar")
        step = calculator.step(bar)
        guard()
        result_bytes += len(json.dumps(asdict(step), ensure_ascii=False, allow_nan=False,
                                       separators=(',', ':')).encode('utf-8'))
        if result_bytes > 16 * 1024 * 1024:
            raise ValueError("离线观察结果超过16MiB")
        results.append(step)
    guard()
    result = deepcopy(tuple(results))
    guard()
    return result
