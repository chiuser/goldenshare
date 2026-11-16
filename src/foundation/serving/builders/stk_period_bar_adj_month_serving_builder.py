from __future__ import annotations

from src.foundation.datasets.stock_period_adj_contracts import SOURCE_FIELDS, StockPeriodAdjExecutionPolicy, normalize_rows, select_serving
from src.foundation.serving.builders.base import ServingBuildResult
from src.foundation.serving.builders.resolution_serving_builder import ResolutionServingBuilder


class StkPeriodBarAdjMonthServingBuilder(ResolutionServingBuilder):
    dataset_key = "stk_period_bar_adj_month"
    business_key_fields = ("ts_code", "trade_date", "freq")

    def build_rows(self, *, std_rows_by_source, policy, active_sources, target_columns):
        candidates = [{field: row[field] for field in SOURCE_FIELDS}
            for rows in std_rows_by_source.values() for row in rows]
        selected = select_serving(normalize_rows(candidates, freq='month', policy=StockPeriodAdjExecutionPolicy()), 'month')
        values = [{('change_amount' if key == 'change' else key): value for key, value in row.items()}
            for row in selected]
        return ServingBuildResult(rows=[{key: row[key] for key in target_columns} for row in values], resolved_count=len(values))
