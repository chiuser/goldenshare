from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
)


def idx_factor_pro_row(
    ts_code: str,
    trade_date: str,
    *,
    null_column: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {}
    for index, column in enumerate(IDX_FACTOR_PRO_SOURCE_COLUMNS):
        if column == "ts_code":
            row[column] = ts_code
        elif column == "trade_date":
            row[column] = trade_date
        elif column == null_column:
            row[column] = None
        else:
            row[column] = float(index)
    return row


class FakeIdxFactorProTushare:
    def __init__(
        self,
        *,
        rows: Sequence[Mapping[str, object]],
        columns: Sequence[str] = IDX_FACTOR_PRO_SOURCE_COLUMNS,
    ) -> None:
        self.rows = [dict(row) for row in rows]
        self.columns = tuple(columns)
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields) -> TushareResult:
        request_params = dict(params)
        request_fields = tuple(fields)
        self.calls.append((api_name, request_params, request_fields))
        offset = int(request_params["offset"])
        rows = self.rows[offset : offset + int(request_params["limit"])]
        return TushareResult(
            rows=rows,
            columns=self.columns,
            metadata={},
        )


def write_idx_factor_pro_rows(
    *,
    path: Path,
    rows: Sequence[Mapping[str, object]],
    duckdb_resource: DuckDBResource,
    columns: Sequence[str] = IDX_FACTOR_PRO_SOURCE_COLUMNS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame.from_records(rows, columns=columns)
    with duckdb_resource.connect() as connection:
        connection.register("idx_factor_pro_test_rows", frame)
        try:
            connection.execute(
                copy_query_to_parquet(
                    "SELECT * FROM idx_factor_pro_test_rows",
                    path,
                )
            )
        finally:
            connection.unregister("idx_factor_pro_test_rows")
