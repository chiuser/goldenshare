from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from lake_console.backend.app.services.security_universe_filter import load_security_universe_rows


@dataclass(frozen=True)
class MissingStateClassification:
    bootstrap_ts_codes: frozenset[str]
    rejected_reasons: dict[str, str]

    @property
    def rejected(self) -> bool:
        return bool(self.rejected_reasons)


def classify_missing_macd_states(
    *,
    lake_root: Path,
    missing_ts_codes: list[str],
    window_start_date: date,
    trade_date: date,
) -> MissingStateClassification:
    if not missing_ts_codes:
        return MissingStateClassification(bootstrap_ts_codes=frozenset(), rejected_reasons={})
    if trade_date < window_start_date:
        raise ValueError("trade_date 不能早于 window_start_date。")

    rows_by_code = {row.ts_code: row for row in load_security_universe_rows(lake_root=lake_root)}
    bootstrap_codes: set[str] = set()
    rejected_reasons: dict[str, str] = {}
    for ts_code in sorted(set(missing_ts_codes)):
        universe_row = rows_by_code.get(ts_code)
        if universe_row is None:
            rejected_reasons[ts_code] = "stock_basic 缺少该 ts_code，无法判断是否为新股"
            continue
        if universe_row.delist_date is not None and universe_row.delist_date < trade_date:
            rejected_reasons[ts_code] = (
                "源分钟线日期晚于 stock_basic.delist_date，疑似源数据或股票池不一致，"
                f"list_date={universe_row.list_date.isoformat()} delist_date={universe_row.delist_date.isoformat()}"
            )
            continue
        if universe_row.list_date > trade_date:
            rejected_reasons[ts_code] = (
                "源分钟线日期早于 stock_basic.list_date，疑似源数据或股票池不一致，"
                f"list_date={universe_row.list_date.isoformat()} trade_date={trade_date.isoformat()}"
            )
            continue
        if universe_row.list_date < window_start_date:
            rejected_reasons[ts_code] = (
                "老股票缺少 MACD state，不能从本次增量窗口中途初始化，"
                f"list_date={universe_row.list_date.isoformat()} window_start={window_start_date.isoformat()}"
            )
            continue
        bootstrap_codes.add(ts_code)

    return MissingStateClassification(
        bootstrap_ts_codes=frozenset(bootstrap_codes),
        rejected_reasons=rejected_reasons,
    )
