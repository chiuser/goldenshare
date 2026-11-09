"""Read DG inputs, run r4.1 in date order, and publish daily results."""

import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta, timezone
from itertools import groupby
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io.index_daily_writer import _writer_lock
from orchestrator.defs.paths import (
    gold_major_index_mins_path,
    gold_major_index_mins_technical_path,
    silver_index_factor_pro_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE_SCHEMA,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    expected_gold_minute_times,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    active_idx_factor_pro_daily_codes,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    effective_silver_codes_for_date,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import INDICATOR_VERSION
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_DATASET,
    STRUCTURE_FREQUENCIES,
    STRUCTURE_INDEX_CODES,
    STRUCTURE_PERIODS,
    STRUCTURE_START,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata

CN_OFFSET = timezone(timedelta(hours=8))
MINUTE_ENDPOINTS = {
    freq: tuple(time.fromisoformat(endpoint) for endpoint in expected_gold_minute_times("SSE", freq))
    for freq in STRUCTURE_FREQUENCIES
}
STRUCTURE_COLUMNS = tuple(column.name for column in GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE_SCHEMA)
STRUCTURE_RESULTS_TYPE = GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE_SCHEMA[-1].type


@dataclass(frozen=True)
class StructureDay:
    trade_date: date
    success: bool
    results: list[dict]
    input_bar_count: int


class StructureInputError(ValueError):
    def __init__(self, trade_date: date, reason: str, *, input_bar_count: int = 0):
        super().__init__(f"{trade_date}: {reason}")
        self.trade_date = trade_date
        self.input_bar_count = input_bar_count


def structure_algorithm_version() -> str:
    from goldenshare_technical_indicators.xxm import MAIN_SPEC

    return MAIN_SPEC.algorithm_version


def structure_trade_dates(
    connection, lake_root: Path, through: date, *, recent: int | None = None,
) -> tuple[date, ...]:
    if recent is not None:
        sql = "ORDER BY trade_date DESC LIMIT ?"
        params = [recent]
    else:
        sql = "ORDER BY trade_date"
        params = []
    rows = connection.execute(
        """
        SELECT trade_date
        FROM read_parquet(?, hive_partitioning=false)
        WHERE exchange='SSE' AND is_open AND trade_date BETWEEN ? AND ?
        """ + sql,
        [str(silver_trade_calendar_path(lake_root)), STRUCTURE_START, through, *params],
    ).fetchall()
    return tuple(sorted(row[0] for row in rows))


def structure_source_paths(lake_root: Path, trade_date: date) -> tuple[Path, ...]:
    day = trade_date.isoformat()
    return (
        silver_index_factor_pro_path(lake_root, day),
        *(gold_major_index_mins_path(lake_root, freq, day) for freq in STRUCTURE_FREQUENCIES),
        *(gold_major_index_mins_technical_path(lake_root, freq, day) for freq in STRUCTURE_FREQUENCIES),
    )


def expected_structure_keys(trade_date: date) -> set[tuple[str, int, time | None]]:
    daily_codes = STRUCTURE_INDEX_CODES.intersection(active_idx_factor_pro_daily_codes(trade_date))
    minute_codes = STRUCTURE_INDEX_CODES.intersection(effective_silver_codes_for_date(trade_date))
    return {(code, 0, None) for code in daily_codes} | {
        (code, freq, endpoint)
        for code in minute_codes
        for freq, endpoints in MINUTE_ENDPOINTS.items()
        for endpoint in endpoints
    }


_STRUCTURE_INPUT_SQL = """
WITH daily AS (
    SELECT regexp_extract(filename, 'trade_date=([^/]+)/', 1)::DATE AS partition_date,
           trade_date, ts_code, 0 AS freq, NULL::TIMESTAMP AS trade_time,
           close, macd_dif_bfq AS dif, macd_dea_bfq AS dea, macd_bfq AS hist
    FROM read_parquet(?, hive_partitioning=false, filename=true)
    WHERE ts_code IN (SELECT unnest(?))
), prices AS (
    SELECT regexp_extract(filename, 'trade_date=([^/]+)/', 1)::DATE AS partition_date,
           trade_date, ts_code, freq, trade_time, close
    FROM read_parquet(?, hive_partitioning=false, filename=true)
    WHERE ts_code IN (SELECT unnest(?))
), indicators AS (
    SELECT regexp_extract(filename, 'trade_date=([^/]+)/', 1)::DATE AS partition_date,
           trade_date, ts_code, freq, trade_time, macd_dif AS dif, macd_dea AS dea, macd AS hist
    FROM read_parquet(?, hive_partitioning=false, filename=true)
    WHERE ts_code IN (SELECT unnest(?))
)
SELECT * FROM daily
UNION ALL
SELECT partition_date, trade_date, ts_code, freq, trade_time, close, dif, dea, hist
FROM prices FULL OUTER JOIN indicators
USING (partition_date, trade_date, ts_code, freq, trade_time)
ORDER BY partition_date, ts_code, freq, trade_time
"""


def _read_structure_month(connection, lake_root: Path, days: Sequence[date]):
    daily_files, price_files, indicator_files = [], [], []
    missing_input = None
    price_file_end = 1 + len(STRUCTURE_FREQUENCIES)
    for day in days:
        files = structure_source_paths(lake_root, day)
        missing = next((path for path in files if not path.is_file()), None)
        if missing is not None:
            missing_input = (day, missing)
            break
        daily_files.append(str(files[0]))
        price_files.extend(map(str, files[1:price_file_end]))
        indicator_files.extend(map(str, files[price_file_end:]))
    codes = sorted(STRUCTURE_INDEX_CODES)
    rows = connection.execute(
        _STRUCTURE_INPUT_SQL, [daily_files, codes, price_files, codes, indicator_files, codes],
    ).fetchall() if daily_files else []
    return {key: list(group) for key, group in groupby(rows, key=lambda row: row[0])}, missing_input


def _align_structure_day(day: date, rows: Sequence[tuple]) -> dict:
    expected = expected_structure_keys(day)
    active_sequences = {(code, freq) for code, freq, _ in expected}
    aligned = {}
    for _, trade_date, code, freq, stamp, close, dif, dea, hist in rows:
        if (code, freq) not in active_sequences and freq in (0, *STRUCTURE_FREQUENCIES):
            continue
        endpoint = stamp.time() if stamp is not None else None
        key = (code, freq, endpoint)
        if (trade_date != day or (stamp is not None and stamp.date() != day)
                or key not in expected or key in aligned):
            raise StructureInputError(day, f"无效或重复的 K 线键 {key}")
        if None in (close, dif, dea, hist):
            raise StructureInputError(day, f"价格或指标缺失 {key}")
        aligned[key] = (stamp, close, dif, dea, hist)
    missing = expected.difference(aligned)
    if missing:
        raise StructureInputError(day, f"缺少 K 线键 {min(missing)}")
    return aligned


def calculate_structure_days(
    connection, lake_root: Path, days: Sequence[date], *, first_result_date: date,
    report_month: Callable[[date, int, float], None] | None = None,
) -> Iterator[StructureDay]:
    from goldenshare_technical_indicators.xxm import XxmBar, XxmCalculator
    from goldenshare_technical_indicators.xxm.event_display import event_display_flags

    calculators = {}
    total_input = 0
    for _, month in groupby(days, key=lambda day: (day.year, day.month)):
        started = perf_counter()
        month_days = tuple(month)
        month_rows, missing_input = _read_structure_month(connection, lake_root, month_days)
        for day in month_days:
            if missing_input is not None and day == missing_input[0]:
                raise StructureInputError(day, f"缺少输入文件 {missing_input[1]}")
            aligned = _align_structure_day(day, month_rows.pop(day, ()))
            total_input += len(aligned)
            events = []
            for input_count, ((code, freq, endpoint), (stamp, close, dif, dea, hist)) in enumerate(
                aligned.items(), start=1,
            ):
                period = f"m{freq}" if freq else "day"
                bar_time = (
                    stamp.replace(tzinfo=CN_OFFSET).isoformat() if stamp else day.isoformat()
                )
                series = (code, freq)
                if series not in calculators:
                    indicator_scope = INDICATOR_VERSION if freq else "bfq"
                    calculators[series] = XxmCalculator(
                        period=period, ts_code=code,
                        source_identity=f"{period}|{bar_time}|{indicator_scope}",
                    )
                try:
                    step = calculators[series].step(XxmBar(bar_time, close, dif, dea, hist))
                except ValueError as exc:
                    raise StructureInputError(
                        day, f"{code} {period} {bar_time}: {exc}", input_bar_count=input_count,
                    ) from exc
                if day >= first_result_date and step.events:
                    flags = event_display_flags(step.events)
                    events.extend({
                        "ts_code": code,
                        "period": period,
                        "bar_end_time": endpoint,
                        "event_type": event["type"],
                        "direction": event["direction"],
                        "display_on_chart": flags[event["id"]],
                    } for event in step.events)
            if day >= first_result_date:
                events.sort(key=lambda event: (
                    event["bar_end_time"] or time(15), event["ts_code"], event["period"],
                ))
                yield StructureDay(day, True, events, len(aligned))
        if report_month is not None:
            report_month(month_days[-1], total_input, perf_counter() - started)


def structure_result_contract_error(connection, path: Path, trade_date: date) -> str | None:
    if not path.is_file():
        return "结果文件不存在"
    columns = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(path)],
    ).fetchall()
    if [(row[0], row[1]) for row in columns] != [
        (column.name, column.type) for column in GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE_SCHEMA
    ]:
        return "Parquet 字段或类型不符合合同"
    rows = connection.execute(
        "SELECT trade_date, success, results FROM read_parquet(?, hive_partitioning=false)",
        [str(path)],
    ).fetchall()
    if len(rows) != 1:
        return "结果文件必须恰好一行"
    stored_date, success, events = rows[0]
    if stored_date != trade_date or success is None or events is None or (not success and events):
        return "日期、成功标志或空结果不符合合同"
    for event in events:
        if event is None:
            return "事件不能为空"
        period = event["period"]
        endpoint = event["bar_end_time"]
        if (
            event["ts_code"] not in STRUCTURE_INDEX_CODES
            or period not in STRUCTURE_PERIODS
            or (endpoint is not None if period == "day" else endpoint not in MINUTE_ENDPOINTS[int(period[1:])])
            or event["event_type"] not in ("DULL", "STRUCTURE", "CANCEL")
            or event["direction"] not in ("TOP", "BOTTOM")
            or event["display_on_chart"] is None
        ):
            return "事件字段不符合合同"
    return None


def write_structure_day(
    connection, structure_day: StructureDay, *, staging_dir: Path, target: Path,
) -> None:
    candidate = staging_dir / f"trade_date={structure_day.trade_date}" / "part-000.parquet"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    select = (
        "SELECT ?::DATE AS trade_date, ?::BOOLEAN AS success, "
        f"?::{STRUCTURE_RESULTS_TYPE} AS results"
    )
    connection.execute(copy_query_to_parquet(select, candidate), [
        structure_day.trade_date, structure_day.success, structure_day.results,
    ])
    error = structure_result_contract_error(connection, candidate, structure_day.trade_date)
    if error:
        raise ValueError(f"{candidate}: {error}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidate, target)


def structure_writer_lock(staging_root: Path):
    return _writer_lock(staging_root / STRUCTURE_DATASET)


def structure_materialization_metadata(
    path: Path, *, algorithm_version: str, input_bar_count: int, event_count: int,
) -> dict:
    return build_materialization_metadata(
        uri=path,
        row_count=1,
        observed_columns=STRUCTURE_COLUMNS,
        extra_metadata={
            "formula_version": algorithm_version,
            "source_row_count": input_bar_count,
            "event_count": event_count,
        },
    )
