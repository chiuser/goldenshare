"""Read the published daily files for one requested index and period."""
from datetime import date
from pathlib import Path

from .index_daily_reader import _read


_DIRECTORY = Path("gold/indicator/major_index_quantitative_structure")
_SCHEMA = (
    ("trade_date", "DATE"),
    ("success", "BOOLEAN"),
    ("results", "STRUCT(ts_code VARCHAR, period VARCHAR, bar_end_time TIME, "
                "event_type VARCHAR, direction VARCHAR, display_on_chart BOOLEAN)[]"),
    ("filename", "VARCHAR"),
)


def read_structure_days(root: Path, *, days: tuple[date, ...], ts_code: str, period: str, remaining):
    paths = {
        str(root / _DIRECTORY / f"trade_date={day.isoformat()}" / "part-000.parquet"): day
        for day in days
    }
    existing = {path: day for path, day in paths.items() if Path(path).is_file()}
    if not existing:
        return {}
    rows = _read(
        """
        SELECT trade_date, success, list_filter(results, event -> event.ts_code = ? AND event.period = ?) AS results,
               filename
        FROM read_parquet(?, hive_partitioning=false, filename=true)
        """,
        [ts_code, period, list(existing)], _SCHEMA, timeout_seconds=remaining(),
    )
    records = {}
    for day, success, events, filename in rows:
        if existing.get(filename) != day or day in records or success is None or events is None:
            raise ValueError("主要指数量化结构文件的日期或行数不符合合同。")
        records[day] = (success, events)
    if len(records) != len(existing):
        raise ValueError("主要指数量化结构文件的日期或行数不符合合同。")
    return records
