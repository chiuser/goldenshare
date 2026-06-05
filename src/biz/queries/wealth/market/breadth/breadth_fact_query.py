from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.biz.queries.wealth.market.common.clickhouse_readonly_client import ClickHouseReadonlyClient


_BREADTH_FACT_TABLE = "share_fact_market_breadth_daily"
_BREADTH_COLUMNS = """
    trade_date,
    up_count,
    down_count,
    flat_count,
    total_count,
    red_rate,
    down_gt_7_count,
    down_5_7_count,
    down_3_5_count,
    down_0_3_count,
    up_0_3_count,
    up_3_5_count,
    up_5_7_count,
    up_gt_7_count
"""


@dataclass(frozen=True, slots=True)
class BreadthDistributionBuckets:
    down_gt_7_count: int
    down_5_7_count: int
    down_3_5_count: int
    down_0_3_count: int
    up_0_3_count: int
    up_3_5_count: int
    up_5_7_count: int
    up_gt_7_count: int


@dataclass(frozen=True, slots=True)
class BreadthFactRow:
    trade_date: date
    up_count: int
    down_count: int
    flat_count: int
    total_count: int
    red_rate: float
    distribution_buckets: BreadthDistributionBuckets


class BreadthFactDuplicatedError(RuntimeError):
    """Raised when the ClickHouse fact table violates one-row-per-trade-date."""

    def __init__(self, *, trade_date: date, row_count: int) -> None:
        super().__init__(f"duplicated breadth fact rows for {trade_date.isoformat()}: {row_count}")
        self.trade_date = trade_date
        self.row_count = row_count


class BreadthFactQuery:
    """Read precomputed breadth facts from ClickHouse."""

    def __init__(self, *, client: ClickHouseReadonlyClient | None = None) -> None:
        self._client = client or ClickHouseReadonlyClient()

    def load_observed_trade_date(self) -> date | None:
        rows = self._client.query_json(
            f"""
            SELECT trade_date AS observed_trade_date
            FROM {_BREADTH_FACT_TABLE}
            WHERE trade_date <= today()
            ORDER BY trade_date DESC
            LIMIT 1
            FORMAT JSON
            """
        )
        if not rows:
            return None
        value = rows[0].get("observed_trade_date")
        if not value:
            return None
        return date.fromisoformat(str(value))

    def load_one(self, *, trade_date: date) -> BreadthFactRow | None:
        rows = self._client.query_json(
            f"""
            SELECT {_BREADTH_COLUMNS}
            FROM {_BREADTH_FACT_TABLE}
            WHERE trade_date = toDate('{trade_date.isoformat()}')
            ORDER BY trade_date ASC
            LIMIT 2
            FORMAT JSON
            """
        )
        if len(rows) > 1:
            raise BreadthFactDuplicatedError(trade_date=trade_date, row_count=len(rows))
        if not rows:
            return None
        return _row_to_fact(rows[0])

    def load_many(self, *, trade_dates: list[date]) -> list[BreadthFactRow]:
        if not trade_dates:
            return []

        unique_trade_dates = sorted(set(trade_dates))
        date_literals = ", ".join(f"toDate('{trade_day.isoformat()}')" for trade_day in unique_trade_dates)
        rows = self._client.query_json(
            f"""
            SELECT {_BREADTH_COLUMNS}
            FROM {_BREADTH_FACT_TABLE}
            WHERE trade_date IN ({date_literals})
            ORDER BY trade_date ASC
            LIMIT 1000
            FORMAT JSON
            """
        )

        row_counts: dict[date, int] = {}
        facts: list[BreadthFactRow] = []
        for row in rows:
            fact = _row_to_fact(row)
            row_counts[fact.trade_date] = row_counts.get(fact.trade_date, 0) + 1
            facts.append(fact)
        for trade_day, row_count in row_counts.items():
            if row_count > 1:
                raise BreadthFactDuplicatedError(trade_date=trade_day, row_count=row_count)
        return facts


def _int_value(row: dict, key: str) -> int:
    return int(row.get(key) or 0)


def _float_value(row: dict, key: str) -> float:
    return float(row.get(key) or 0.0)


def _row_to_fact(row: dict) -> BreadthFactRow:
    trade_date_value = row.get("trade_date")
    if trade_date_value is None:
        raise RuntimeError("ClickHouse breadth fact row missing trade_date")
    return BreadthFactRow(
        trade_date=date.fromisoformat(str(trade_date_value)),
        up_count=_int_value(row, "up_count"),
        down_count=_int_value(row, "down_count"),
        flat_count=_int_value(row, "flat_count"),
        total_count=_int_value(row, "total_count"),
        red_rate=_float_value(row, "red_rate"),
        distribution_buckets=BreadthDistributionBuckets(
            down_gt_7_count=_int_value(row, "down_gt_7_count"),
            down_5_7_count=_int_value(row, "down_5_7_count"),
            down_3_5_count=_int_value(row, "down_3_5_count"),
            down_0_3_count=_int_value(row, "down_0_3_count"),
            up_0_3_count=_int_value(row, "up_0_3_count"),
            up_3_5_count=_int_value(row, "up_3_5_count"),
            up_5_7_count=_int_value(row, "up_5_7_count"),
            up_gt_7_count=_int_value(row, "up_gt_7_count"),
        ),
    )
