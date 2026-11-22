"""指数周月线 Raw：完整 unit 下载、列式合并及单文件原子提升。"""

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.checks.index_period_checks import (
    IndexPeriodContractError,
    IndexPeriodFileCheck,
    check_index_period_coverage,
    check_index_period_file,
    check_index_period_raw_file,
    index_period_schema_matches,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    index_period_candidate_path,
    raw_index_monthly_path,
    raw_index_weekly_path,
    silver_index_basic_path,
    silver_index_daily_path,
    silver_index_monthly_path,
    silver_index_weekly_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_WEEKLY_SCHEMA,
    SILVER_INDEX_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.index_period import (
    INDEX_PERIOD_EMPTY_SOURCE_CODE,
    INDEX_PERIOD_TIMEZONE,
    INDEX_WEEKLY,
    index_period_bounds,
    index_period_codes,
)
from orchestrator.tushare_download import (
    DownloadMode,
    DownloadStatus,
    DownloadTask,
    TushareDownloader,
)

RAW_COLUMNS = tuple(column.name for column in RAW_INDEX_WEEKLY_SCHEMA)


def _file_version(path):
    try:
        return file_version(path)
    except OSError:
        return None


@contextmanager
def _observe_inputs(inputs, asset_key, files):
    if inputs is None:
        yield
        return
    versions = [_file_version(path) for path, _ in files]
    yield
    for (path, scope), before in zip(files, versions, strict=True):
        after = _file_version(path)
        inputs.append(
            {
                "asset_key": asset_key,
                "scope": scope,
                "target_version": json.dumps(after, separators=(",", ":"))
                if after is not None and before == after
                else None,
            }
        )


def index_period_end(connection, calendar_path, period, partition_key):
    start, end = index_period_bounds(period, partition_key)
    first, last, trading_end, day_count = connection.execute(
        f"""SELECT min(trade_date), max(trade_date),
                   max(trade_date) FILTER (WHERE is_open), count(*)
            FROM {read_parquet(calendar_path)} WHERE exchange = 'SSE'
              AND trade_date BETWEEN DATE {duckdb_string(start)} AND DATE {duckdb_string(end)}"""
    ).fetchone()
    if (first, last, day_count) != (start, end, (end - start).days + 1):
        raise ValueError("交易日历未覆盖所选完整周／月")
    if trading_end is None:
        raise ValueError("所选周期没有交易日")
    if period == INDEX_WEEKLY and trading_end.isoformat() != partition_key:
        raise ValueError("周分区不是该周最后交易日")
    return trading_end


def download_index_period_rows(period, period_end, *, codes, required_codes):
    """在调用线程创建并关闭组件会话；业务只验证本次完整 unit 合同。"""
    task = DownloadTask(
        contract_name=period.dataset_id,
        mode=DownloadMode.BY_OBJECT_POINT,
        objects=codes,
        points=(period_end.isoformat(),),
    )
    rows, delivered = [], []
    downloader = TushareDownloader.load()
    with downloader.download(task) as session:
        for result in session:
            code = result.unit.object_code
            if (
                code not in codes
                or code in delivered
                or result.unit.point != period_end.isoformat()
            ):
                raise ValueError("源 unit 代码或期末不符")
            delivered.append(code)
            if len(result.records) > 1 or (
                not result.records and code in required_codes
            ):
                raise ValueError(f"{code} 在 {period_end} 缺记录或返回重复记录")
            if any(
                set(fields) != set(RAW_COLUMNS) for fields in result.observed_field_sets
            ):
                raise ValueError(f"{code} 源业务字段不完整")
            for record in result.records:
                values = record.as_mapping()
                if set(values) != set(RAW_COLUMNS):
                    raise ValueError(f"{code} 源业务字段不完整")
                if (values["ts_code"], values["trade_date"]) != (
                    code,
                    period_end.strftime("%Y%m%d"),
                ):
                    raise ValueError(f"{code} 源记录代码或期末不符")
                rows.append(tuple(values[name] for name in RAW_COLUMNS))
    summary = session.summary
    if (
        set(delivered) != set(codes)
        or summary.status != DownloadStatus.SUCCEEDED
        or not summary.download_complete
        or summary.row_count != len(rows)
    ):
        raise ValueError("指数周期下载未完整完成")
    return rows


@dataclass(frozen=True)
class IndexPeriodRawWrite:
    path: Path
    period_end: date
    partition_row_count: int
    check: IndexPeriodFileCheck


def write_index_period_raw(
    connection,
    *,
    lake_root: Path,
    period,
    partition_key: str,
    run_id: str,
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
) -> IndexPeriodRawWrite:
    period_end = index_period_end(
        connection,
        silver_trade_calendar_path(lake_root),
        period,
        partition_key,
    )
    codes = index_period_codes()
    rows = download_index_period_rows(
        period,
        period_end,
        codes=codes,
        required_codes=tuple(
            code for code in codes if code != INDEX_PERIOD_EMPTY_SOURCE_CODE
        ),
    )
    # 单期最多11行；历史合并、排序与 Parquet 写入均在 DuckDB 内完成。
    projection = ", ".join(
        f'CAST("{c.name}" AS {c.type}) AS "{c.name}"' for c in RAW_INDEX_WEEKLY_SCHEMA
    )
    values = ", ".join("(" + ",".join("?" for _ in RAW_COLUMNS) + ")" for _ in rows)
    names = ", ".join(f'"{name}"' for name in RAW_COLUMNS)
    connection.execute(
        f"CREATE TEMP TABLE index_period_delta AS SELECT {projection} FROM (VALUES {values}) AS source({names})",
        [value for row in rows for value in row],
    )
    prepared = prepare_index_period_file(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        run_id=run_id,
        period=period,
        layer="raw",
        source_relation="index_period_delta",
        partition_key=partition_key,
        period_end=period_end,
    )
    promote_index_period_file(prepared)
    return IndexPeriodRawWrite(
        prepared.path, period_end, prepared.partition_row_count, prepared.check
    )


@dataclass(frozen=True)
class IndexPeriodPreparedFile:
    path: Path
    candidate: Path
    check: IndexPeriodFileCheck
    partition_row_count: int


def index_period_path(root, period, layer):
    function = (
        (raw_index_weekly_path if period == INDEX_WEEKLY else raw_index_monthly_path)
        if layer == "raw"
        else (
            silver_index_weekly_path
            if period == INDEX_WEEKLY
            else silver_index_monthly_path
        )
    )
    return function(root)


def prepare_index_period_file(
    connection,
    *,
    lake_root,
    staging_root,
    run_id,
    period,
    layer,
    source_relation,
    partition_key=None,
    period_start=None,
    period_end=None,
    history_relation=None,
    as_of=None,
    expected_codes=None,
):
    """共享的列式写入；bootstrap传完整来源，日常仅按本次主键替换。"""
    target = index_period_path(lake_root, period, layer)
    candidate = index_period_candidate_path(
        staging_root, run_id, layer, period.dataset_id
    )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if candidate.parent.stat().st_dev != target.parent.stat().st_dev:
        raise ValueError("候选与正式文件必须位于同一文件系统")
    previous_count = replaced_count = 0
    schema = RAW_INDEX_WEEKLY_SCHEMA if layer == "raw" else SILVER_INDEX_WEEKLY_SCHEMA
    names = ", ".join(f'"{column.name}"' for column in schema)
    key_date = "trade_date" if layer == "raw" else "period_start_date"
    source_count = connection.execute(
        f"SELECT count(*) FROM {source_relation}"
    ).fetchone()[0]
    if target.exists() and partition_key is not None:
        history = history_relation or read_parquet(target)
        if not index_period_schema_matches(connection, history, layer):
            raise ValueError("已有指数周期文件 schema 不符")
        previous_count = connection.execute(
            f"SELECT count(*) FROM {history}"
        ).fetchone()[0]
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE index_period_history AS SELECT {names} FROM {history}"
        )
        replaced_count = connection.execute(
            f"SELECT count(*) FROM index_period_history h SEMI JOIN {source_relation} d USING (ts_code, {key_date})"
        ).fetchone()[0]
        merge = f"""SELECT {names} FROM index_period_history h
            WHERE NOT EXISTS (SELECT 1 FROM {source_relation} d
                              WHERE h.ts_code=d.ts_code AND h.{key_date}=d.{key_date})
            UNION ALL SELECT {names} FROM {source_relation}"""
    else:
        merge = f"SELECT {names} FROM {source_relation}"
    connection.execute(f"CREATE OR REPLACE TEMP TABLE index_period_merged AS {merge}")
    connection.execute(
        copy_query_to_parquet(
            "SELECT * FROM index_period_merged ORDER BY ts_code, trade_date",
            candidate,
        )
    )
    arguments = {
        "path": candidate,
        "delta_relation": source_relation,
        "source_row_count": source_count,
        "expected_file_row_count": previous_count - replaced_count + source_count,
        "codes": index_period_codes(),
    }
    if layer == "raw" and partition_key is not None:
        check = check_index_period_raw_file(
            connection, **arguments, period_end=period_end
        )
    else:
        check = check_index_period_file(
            connection,
            **arguments,
            layer=layer,
            period_start=period_start,
            period_end=period_end,
        )
    partition_count = source_count
    if expected_codes is not None:
        rows = connection.execute(
            "SELECT ts_code, trade_date FROM index_period_merged "
            "WHERE period_start_date = ? ORDER BY ts_code, trade_date",
            [period_start],
        ).fetchall()
        check = check_index_period_coverage(
            check, rows, as_of=as_of, expected_codes=expected_codes
        )
        partition_count = len(rows)
    elif partition_key is not None and check.passed:
        predicate = (
            "trade_date = ?"
            if period == INDEX_WEEKLY
            else "substr(trade_date, 1, 6) = ?"
        )
        key = partition_key.replace("-", "")
        if layer == "silver":
            predicate, key = "period_start_date = ?", period_start
        partition_count = connection.execute(
            f"SELECT count(*) FROM index_period_merged WHERE {predicate}", [key]
        ).fetchone()[0]
    if not check.passed:
        raise IndexPeriodContractError(check, period_end, as_of=as_of)
    return IndexPeriodPreparedFile(target, candidate, check, partition_count)


def promote_index_period_file(prepared):
    os.replace(prepared.candidate, prepared.path)


def load_index_period_calendar(connection, root, start, end):
    connection.execute(f"""CREATE OR REPLACE TEMP TABLE index_period_calendar AS
        SELECT trade_date,is_open FROM {read_parquet(silver_trade_calendar_path(root))}
        WHERE exchange='SSE' AND trade_date BETWEEN DATE {duckdb_string(start)} AND DATE {duckdb_string(end)}""")
    for frequency in ("week", "month"):
        connection.execute(f"""CREATE OR REPLACE TEMP TABLE index_period_cycles_{frequency} AS
            SELECT date_trunc('{frequency}',trade_date)::DATE cycle_date,
                min(trade_date) period_start_date,max(trade_date) period_end
            FROM index_period_calendar WHERE is_open GROUP BY 1""")


def load_index_period_listings(connection, root):
    codes = ",".join(duckdb_string(code) for code in index_period_codes())
    connection.execute(f"""CREATE OR REPLACE TEMP TABLE index_period_listings AS
        SELECT ts_code,list_date FROM {read_parquet(silver_index_basic_path(root))}
        WHERE ts_code IN ({codes})""")
    rows = connection.execute(
        "SELECT ts_code,list_date FROM index_period_listings"
    ).fetchall()
    if (
        len(rows) != len(index_period_codes())
        or len(dict(rows)) != len(rows)
        or any(day is None for _, day in rows)
    ):
        raise ValueError("11个主要指数的发布日期缺失或重复")
    return dict(rows)


def index_period_projection(schema):
    return ",".join(
        f'CAST("{column.name}" AS {column.type}) AS "{column.name}"'
        for column in schema
    )


def index_period_silver_from_source_sql(relation, *, raw, period):
    """仅作单位转换；不重算或裁剪已接受的源行情。"""
    day = "strptime(s.trade_date,'%Y%m%d')::DATE" if raw else "s.trade_date"
    start = "c.period_start_date" if raw else "s.period_start_date"
    change = 's."change"' if raw else "s.change_amount"
    return f"""SELECT s.ts_code,{start} period_start_date,{day} trade_date,
        s.open,s.high,s.low,s.close,s.pre_close,{change} change_amount,
        s.pct_chg * 100 pct_chg,
        s.vol * 0.01::DECIMAL(3,2) vol,s.amount * 0.001::DECIMAL(4,3) amount
        FROM {relation} s JOIN index_period_cycles_{period.frequency} c
        ON date_trunc('{period.frequency}',{day})::DATE=c.cycle_date"""


def synthesize_index_period(
    connection,
    *,
    root,
    period,
    period_start,
    as_of,
    codes,
    output_relation,
    inputs=None,
):
    allowed = ",".join(duckdb_string(code) for code in codes)
    connection.execute(f"""CREATE OR REPLACE TEMP TABLE index_period_expected AS
        SELECT b.ts_code,c.trade_date FROM index_period_listings b CROSS JOIN index_period_calendar c
        WHERE b.ts_code IN ({allowed}) AND c.is_open
          AND c.trade_date BETWEEN greatest(b.list_date,DATE {duckdb_string(period_start)}) AND DATE {duckdb_string(as_of)}""")
    days = [
        r[0]
        for r in connection.execute(
            "SELECT DISTINCT trade_date FROM index_period_expected ORDER BY trade_date"
        ).fetchall()
    ]
    paths = [silver_index_daily_path(root, day.isoformat()) for day in days]
    missing = [
        day.isoformat()
        for day, path in zip(days, paths, strict=True)
        if not path.is_file()
    ]
    if missing:
        raise ValueError(f"DG指数日线缺文件：{missing}；先补齐上游，再人工重跑")
    files = ",".join(duckdb_string(path) for path in paths)
    prices = ",".join(
        f'CAST(d."{name}" AS DECIMAL(18,4)) AS "{name}"'
        for name in ("open", "high", "low", "close", "pre_close")
    )
    day_files = (
        [
            (path, {"partition_key": day.isoformat()})
            for day, path in zip(days, paths, strict=True)
        ]
        if inputs is not None
        else ()
    )
    with _observe_inputs(inputs, "silver_index_daily", day_files):
        connection.execute(f"""CREATE OR REPLACE TEMP TABLE index_period_daily AS
            SELECT d.ts_code,d.trade_date,{prices},CAST(d.vol AS DECIMAL(20,4)) vol,CAST(d.amount AS DECIMAL(20,4)) amount
            FROM read_parquet([{files}],hive_partitioning=false) d
            JOIN index_period_expected e USING(ts_code,trade_date)""")
    missing_keys = connection.execute("""SELECT e.ts_code,e.trade_date FROM index_period_expected e
        ANTI JOIN index_period_daily d USING(ts_code,trade_date) LIMIT 11""").fetchall()
    invalid = connection.execute("""SELECT count(*) FROM index_period_daily
        WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR pre_close IS NULL OR vol IS NULL OR amount IS NULL""").fetchone()[
        0
    ]
    input_count, duplicates = connection.execute(
        "SELECT count(*),count(*)-count(DISTINCT(ts_code,trade_date)) FROM index_period_daily"
    ).fetchone()
    if missing_keys or invalid or duplicates:
        raise ValueError(
            f"DG指数日线输入不完整：缺少{missing_keys}，空值{invalid}，重复{duplicates}"
        )
    connection.execute("""CREATE OR REPLACE TEMP TABLE index_period_aggregated AS
        SELECT ts_code,first(open ORDER BY trade_date) open,max(high) high,min(low) low,
          last(close ORDER BY trade_date) AS "close",first(pre_close ORDER BY trade_date) pre_close,
          sum(vol) vol,sum(amount) amount
        FROM index_period_daily GROUP BY ts_code""")
    if connection.execute(
        "SELECT count(*) FROM index_period_aggregated WHERE pre_close=0"
    ).fetchone()[0]:
        raise ValueError("DG指数日线窗口首日前收盘为零")
    # 定点价格转整数，分子分母均精确；整除实现正负ROUND_HALF_UP，不经过DOUBLE除法。
    selection = f"""WITH units AS (
        SELECT *,CAST(close*10000 AS HUGEINT)-CAST(pre_close*10000 AS HUGEINT) delta_units,
                 CAST(pre_close*10000 AS HUGEINT) pre_units FROM index_period_aggregated)
        SELECT ts_code,DATE {duckdb_string(period_start)} period_start_date,DATE {duckdb_string(as_of)} trade_date,
          open,high,low,close,pre_close,close-pre_close change_amount,
          sign(delta_units)*((abs(delta_units)*20000+pre_units)//(2*pre_units))*0.01::DECIMAL(3,2) pct_chg,
          vol,amount FROM units"""
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {output_relation} AS SELECT {index_period_projection(SILVER_INDEX_WEEKLY_SCHEMA)} FROM ({selection})"
    )
    return {
        "window_start": days[0].isoformat(),
        "window_end": as_of.isoformat(),
        "file_count": len(paths),
        "target_code_count": len(codes),
        "row_count": input_count,
    }


@dataclass(frozen=True)
class IndexPeriodSilverWrite:
    path: Path
    period_end: date
    partition_row_count: int
    check: IndexPeriodFileCheck
    input_row_count: int
    source_assets: tuple[str, ...]
    daily_input: dict | None
    file_version: list[int] | None
    inputs: list[dict]


def write_index_period_silver(
    connection,
    *,
    lake_root,
    period,
    partition_key,
    run_id,
    config,
    staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
):
    start, end = index_period_bounds(period, partition_key)
    inputs = []
    with _observe_inputs(
        inputs,
        "silver_trade_calendar",
        [
            (
                silver_trade_calendar_path(lake_root),
                {"start_date": start.isoformat(), "end_date": end.isoformat()},
            ),
        ],
    ):
        load_index_period_calendar(connection, lake_root, start, end)
    opens = [
        r[0]
        for r in connection.execute(
            "SELECT trade_date FROM index_period_calendar WHERE is_open ORDER BY trade_date"
        ).fetchall()
    ]
    count = connection.execute("SELECT count(*) FROM index_period_calendar").fetchone()[
        0
    ]
    if (
        count != (end - start).days + 1
        or not opens
        or (period == INDEX_WEEKLY and opens[-1].isoformat() != partition_key)
    ):
        raise ValueError("所选周期无交易日、日历不全或周分区不是实际期末")
    first, last = opens[0], opens[-1]
    if (
        config.mode == "repair"
        and last > datetime.now(ZoneInfo(INDEX_PERIOD_TIMEZONE)).date()
    ):
        raise ValueError("repair只允许选择已结束周期")
    as_of = date.fromisoformat(config.trade_date) if config.mode == "daily" else last
    if as_of not in opens:
        raise ValueError("实际截至日不属于所选周期的交易日")
    with _observe_inputs(
        inputs,
        "silver_index_basic",
        [
            (silver_index_basic_path(lake_root), {"business_date": as_of.isoformat()}),
        ],
    ):
        listings = load_index_period_listings(connection, lake_root)
    inputs.append(
        {
            "asset_key": "major_indices.cn_a.csv",
            "scope": {},
            "target_version": sha256(
                json.dumps(sorted(listings), separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
    )
    active = tuple(code for code, listed in listings.items() if listed <= as_of)
    schema = SILVER_INDEX_WEEKLY_SCHEMA
    empty = ",".join(f'CAST(NULL AS {c.type}) AS "{c.name}"' for c in schema)
    current_path = index_period_path(lake_root, period, "silver")
    current_exists = current_path.exists()
    previous_inputs = []
    if current_exists:
        with _observe_inputs(
            previous_inputs,
            period.silver_asset,
            [(current_path, {"partition_key": partition_key})],
        ):
            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE index_period_existing_silver AS SELECT * FROM {read_parquet(current_path)}"
            )
    current_sql = (
        f"SELECT * FROM index_period_existing_silver WHERE period_start_date=DATE {duckdb_string(first)}"
        if current_exists
        else f"SELECT {empty} WHERE false"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE index_period_current AS {current_sql}"
    )
    current = dict(
        connection.execute(
            "SELECT ts_code,trade_date FROM index_period_current"
        ).fetchall()
    )
    raw_path = index_period_path(lake_root, period, "raw")
    raw_empty = ",".join(
        f'CAST(NULL AS {c.type}) AS "{c.name}"' for c in RAW_INDEX_WEEKLY_SCHEMA
    )
    raw_exists = raw_path.exists()
    raw_sql = (
        f"SELECT * FROM {read_parquet(raw_path)} WHERE trade_date={duckdb_string(last.strftime('%Y%m%d'))}"
        if raw_exists
        else f"SELECT {raw_empty} WHERE false"
    )
    raw_inputs = []
    raw_files = (
        [(raw_path, {"partition_key": partition_key, "as_of_date": last.isoformat()})]
        if raw_exists
        else []
    )
    with _observe_inputs(raw_inputs, period.raw_asset, raw_files):
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE index_period_raw_current AS {raw_sql}"
        )
    raw_codes = {
        r[0]
        for r in connection.execute(
            "SELECT ts_code FROM index_period_raw_current"
        ).fetchall()
    }
    keep = tuple(
        code
        for code in active
        if current.get(code) == last
        and (
            config.mode == "repair"
            or (config.mode == "period" and code not in raw_codes)
        )
    )
    formal = tuple(code for code in active if code in raw_codes and code not in keep)
    synth = tuple(code for code in active if code not in keep and code not in formal)
    if keep or (config.mode == "daily" and synth):
        inputs.extend(previous_inputs)
    if formal:
        inputs.extend(raw_inputs)
    if config.mode == "period" and synth:
        raise ValueError(f"期末Raw缺失且无完整Silver：{synth}")
    if config.mode == "daily":
        for code in synth:
            expected = [day for day in opens if listings[code] <= day <= as_of]
            if current.get(code) is not None and current[code] > as_of:
                raise ValueError(f"{code} 禁止将实际截至日倒退")
            if len(expected) > 1 and current.get(code) not in (expected[-2], as_of):
                raise ValueError(f"{code} 周月线未接续上一应有交易日；先补齐后人工重跑")
    selections = []
    if keep:
        selections.append(
            "SELECT * FROM index_period_current WHERE ts_code IN ("
            + ",".join(duckdb_string(c) for c in keep)
            + ")"
        )
    if formal:
        selections.append(
            index_period_silver_from_source_sql(
                "index_period_raw_current", raw=True, period=period
            )
            + " WHERE s.ts_code IN ("
            + ",".join(duckdb_string(c) for c in formal)
            + ")"
        )
    daily_input = None
    if synth:
        daily_input = synthesize_index_period(
            connection,
            root=lake_root,
            period=period,
            period_start=first,
            as_of=as_of,
            codes=synth,
            output_relation="index_period_synthesized",
            inputs=inputs,
        )
        selections.append("SELECT * FROM index_period_synthesized")
    if not selections:
        raise ValueError("所选周期尚无已发布的目标指数")
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE index_period_silver_delta AS SELECT {index_period_projection(schema)} FROM ({' UNION ALL '.join(selections)})"
    )
    prepared = prepare_index_period_file(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        run_id=run_id,
        period=period,
        layer="silver",
        source_relation="index_period_silver_delta",
        history_relation="index_period_existing_silver" if current_exists else None,
        partition_key=partition_key,
        period_start=first,
        period_end=last,
        as_of=as_of,
        expected_codes=active,
    )
    if prepared.check.source_row_count != len(active):
        raise ValueError("本次周期标准行情目标代码不完整")
    promote_index_period_file(prepared)
    sources = tuple(
        (["silver_index_daily"] if synth else [])
        + ([period.raw_asset] if formal else [])
        + ([period.silver_asset] if keep else [])
    )
    return IndexPeriodSilverWrite(
        prepared.path,
        as_of,
        prepared.partition_row_count,
        prepared.check,
        len(formal) + len(keep) + (daily_input["row_count"] if daily_input else 0),
        sources,
        daily_input,
        _file_version(prepared.path),
        sorted(
            inputs,
            key=lambda item: (
                item["asset_key"],
                item["scope"].get("partition_key", ""),
            ),
        ),
    )
