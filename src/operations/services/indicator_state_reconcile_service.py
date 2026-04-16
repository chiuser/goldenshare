from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.indicator_state import IndicatorState
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor


IssueType = Literal["missing_state", "stale_state", "bar_count_mismatch", "adj_factor_mismatch"]


@dataclass(frozen=True)
class IndicatorStateIssueSample:
    ts_code: str
    adjustment: str
    indicator_name: str
    issue_type: IssueType
    detail: str


@dataclass(frozen=True)
class IndicatorStateReconcileReport:
    total_codes: int
    expected_states: int
    existing_states: int
    missing_state: int
    stale_state: int
    bar_count_mismatch: int
    adj_factor_mismatch: int
    samples: dict[IssueType, list[IndicatorStateIssueSample]]

    @property
    def has_issue(self) -> bool:
        return any(
            value > 0
            for value in (
                self.missing_state,
                self.stale_state,
                self.bar_count_mismatch,
                self.adj_factor_mismatch,
            )
        )


class IndicatorStateReconcileService:
    ADJUSTMENTS = ("forward", "backward")
    INDICATORS = ("macd", "kdj", "rsi")
    ADJ_FACTOR_EPSILON = 1e-8

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    def run(
        self,
        session: Session,
        *,
        source_key: str = "tushare",
        version: int = 1,
        sample_limit: int = 20,
    ) -> IndicatorStateReconcileReport:
        latest_rows = session.execute(
            select(
                EquityDailyBar.ts_code,
                func.max(EquityDailyBar.trade_date).label("latest_trade_date"),
                func.count().label("bar_count"),
            )
            .group_by(EquityDailyBar.ts_code)
            .order_by(EquityDailyBar.ts_code.asc())
        ).all()
        if not latest_rows:
            return IndicatorStateReconcileReport(
                total_codes=0,
                expected_states=0,
                existing_states=0,
                missing_state=0,
                stale_state=0,
                bar_count_mismatch=0,
                adj_factor_mismatch=0,
                samples={
                    "missing_state": [],
                    "stale_state": [],
                    "bar_count_mismatch": [],
                    "adj_factor_mismatch": [],
                },
            )

        latest_by_code = {row.ts_code: row.latest_trade_date for row in latest_rows}
        bar_count_by_code = {row.ts_code: int(row.bar_count or 0) for row in latest_rows}
        ts_codes = sorted(latest_by_code)

        states = list(
            session.scalars(
                select(IndicatorState).where(
                    IndicatorState.ts_code.in_(ts_codes),
                    IndicatorState.source_key == source_key,
                    IndicatorState.version == version,
                    IndicatorState.indicator_name.in_(self.INDICATORS),
                    IndicatorState.adjustment.in_(self.ADJUSTMENTS),
                )
            )
        )
        state_by_key: dict[tuple[str, str, str], IndicatorState] = {
            (row.ts_code, row.adjustment, row.indicator_name): row for row in states
        }

        latest_subquery = (
            select(
                EquityDailyBar.ts_code.label("ts_code"),
                func.max(EquityDailyBar.trade_date).label("latest_trade_date"),
            )
            .group_by(EquityDailyBar.ts_code)
            .subquery()
        )
        factor_rows = session.execute(
            select(EquityAdjFactor.ts_code, EquityAdjFactor.adj_factor)
            .join(
                latest_subquery,
                and_(
                    EquityAdjFactor.ts_code == latest_subquery.c.ts_code,
                    EquityAdjFactor.trade_date == latest_subquery.c.latest_trade_date,
                ),
            )
        ).all()
        latest_adj_factor_by_code = {row.ts_code: self._as_float(row.adj_factor) for row in factor_rows}

        samples: dict[IssueType, list[IndicatorStateIssueSample]] = {
            "missing_state": [],
            "stale_state": [],
            "bar_count_mismatch": [],
            "adj_factor_mismatch": [],
        }

        missing_state = 0
        stale_state = 0
        bar_count_mismatch = 0
        adj_factor_mismatch = 0

        for ts_code in ts_codes:
            latest_trade_date = latest_by_code[ts_code]
            latest_bar_count = bar_count_by_code[ts_code]
            for adjustment in self.ADJUSTMENTS:
                for indicator_name in self.INDICATORS:
                    key = (ts_code, adjustment, indicator_name)
                    state = state_by_key.get(key)
                    if state is None:
                        missing_state += 1
                        if len(samples["missing_state"]) < sample_limit:
                            samples["missing_state"].append(
                                IndicatorStateIssueSample(
                                    ts_code=ts_code,
                                    adjustment=adjustment,
                                    indicator_name=indicator_name,
                                    issue_type="missing_state",
                                    detail="状态缺失",
                                )
                            )
                        continue

                    if state.last_trade_date != latest_trade_date:
                        stale_state += 1
                        if len(samples["stale_state"]) < sample_limit:
                            samples["stale_state"].append(
                                IndicatorStateIssueSample(
                                    ts_code=ts_code,
                                    adjustment=adjustment,
                                    indicator_name=indicator_name,
                                    issue_type="stale_state",
                                    detail=f"last_trade_date={state.last_trade_date.isoformat()} latest={latest_trade_date.isoformat()}",
                                )
                            )
                        continue

                    state_bar_count = self._as_int(state.state_json.get("bar_count"))
                    if state_bar_count is None or state_bar_count != latest_bar_count:
                        bar_count_mismatch += 1
                        if len(samples["bar_count_mismatch"]) < sample_limit:
                            samples["bar_count_mismatch"].append(
                                IndicatorStateIssueSample(
                                    ts_code=ts_code,
                                    adjustment=adjustment,
                                    indicator_name=indicator_name,
                                    issue_type="bar_count_mismatch",
                                    detail=f"state={state_bar_count} expected={latest_bar_count}",
                                )
                            )

                    if indicator_name != "macd":
                        continue

                    state_factor = self._as_float(state.state_json.get("last_adj_factor"))
                    latest_factor = latest_adj_factor_by_code.get(ts_code)
                    mismatch = False
                    if state_factor is None and latest_factor is not None:
                        mismatch = True
                    elif state_factor is not None and latest_factor is None:
                        mismatch = True
                    elif state_factor is not None and latest_factor is not None:
                        mismatch = abs(state_factor - latest_factor) > self.ADJ_FACTOR_EPSILON
                    if mismatch:
                        adj_factor_mismatch += 1
                        if len(samples["adj_factor_mismatch"]) < sample_limit:
                            samples["adj_factor_mismatch"].append(
                                IndicatorStateIssueSample(
                                    ts_code=ts_code,
                                    adjustment=adjustment,
                                    indicator_name=indicator_name,
                                    issue_type="adj_factor_mismatch",
                                    detail=f"state={state_factor} latest={latest_factor}",
                                )
                            )

        expected_states = len(ts_codes) * len(self.ADJUSTMENTS) * len(self.INDICATORS)
        return IndicatorStateReconcileReport(
            total_codes=len(ts_codes),
            expected_states=expected_states,
            existing_states=len(states),
            missing_state=missing_state,
            stale_state=stale_state,
            bar_count_mismatch=bar_count_mismatch,
            adj_factor_mismatch=adj_factor_mismatch,
            samples=samples,
        )
