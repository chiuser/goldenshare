"""Exact, bounded single-day material from the existing canonical Gold 1m files.

This reader does not decide trading sessions, coverage or rule outcomes. The
caller freezes the returned material before using it across execution batches.
The chart reader and its public cursor/float contract are unchanged.
"""
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
from threading import Timer
from time import monotonic
from zoneinfo import ZoneInfo

from .stock_mins_reader import build_stock_mins_qfq_paths, MinuteSourceContractError, MinuteQueryError


@dataclass(frozen=True, slots=True)
class RuleMinuteRow:
    checkpoint_at: datetime
    close_text: str | None
    volume_shares_text: str | None


@dataclass(frozen=True, slots=True)
class RuleMinuteMaterial:
    stock_code: str
    trade_date: date
    source_version: str
    rows: tuple[RuleMinuteRow, ...]
    scanned_files: int
    payload_bytes: int
    elapsed_ms: float


class StockRuleMinuteReader:
    def __init__(self, lake_root: Path):
        self.lake_root = lake_root

    def read_day(self, *, stock_code, trade_date, row_limit, byte_limit, remaining_ms):
        if type(row_limit) is not int or row_limit < 1 or type(byte_limit) is not int or byte_limit < 1:
            raise ValueError("Positive execution limits required")
        started = monotonic()
        remaining_ms()
        paths = build_stock_mins_qfq_paths(self.lake_root, "bars", stock_code, 1, [trade_date.year])
        if not paths:
            raise MinuteQueryError("尚未取得该股票的分钟行情文件")
        path = paths[0]
        before = path.stat()
        import duckdb
        connection = duckdb.connect(":memory:", config={"threads": "1", "memory_limit": "256MB", "temp_directory": ""})
        timer = None
        try:
            timer = Timer(remaining_ms() / 1000, connection.interrupt)
            timer.daemon = True
            timer.start()
            # VARCHAR preserves source numeric precision without passing through
            # the chart DTO's Python float or rounding to displayed cents.
            rows = connection.execute("""
                SELECT trade_time, CAST(close AS VARCHAR), CAST(vol AS VARCHAR)
                FROM read_parquet(?)
                WHERE ts_code = ? AND freq = 1 AND trade_date = ?
                ORDER BY trade_time LIMIT ?
            """, [str(path), stock_code, trade_date, row_limit + 1]).fetchall()
            remaining_ms()
        except Exception as error:
            remaining_ms()  # Preserve the caller's deadline exception.
            raise MinuteQueryError("分钟行情读取未完成") from error
        finally:
            if timer is not None:
                timer.cancel()
                if timer.ident is not None:
                    timer.join()
            connection.close()
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise MinuteQueryError("读取期间分钟行情版本发生变化")
        if len(rows) > row_limit:
            raise MinuteSourceContractError("单日分钟材料超过批次行数上限")
        result = []
        previous = None
        for at, price, volume in rows:
            remaining_ms()
            if not isinstance(at, datetime):
                raise MinuteSourceContractError("分钟时间类型不符合合同")
            at = at.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if at.tzinfo is None else at.astimezone(ZoneInfo("Asia/Shanghai"))
            if at.date() != trade_date or at.second or at.microsecond or (previous is not None and at <= previous):
                raise MinuteSourceContractError("分钟时间身份不完整或重复")
            previous = at
            result.append(RuleMinuteRow(at, price, volume))
        serialized = json.dumps(dict(stockCode=stock_code, tradeDate=trade_date.isoformat(),
            rows=[[r.checkpoint_at.isoformat(), r.close_text, r.volume_shares_text] for r in result]),
            sort_keys=True, separators=(",", ":")).encode()
        if len(serialized) > byte_limit:
            raise MinuteSourceContractError("分钟材料超过批次字节上限")
        remaining_ms()
        return RuleMinuteMaterial(stock_code, trade_date, sha256(serialized).hexdigest(),
            tuple(result), 1, len(serialized), (monotonic() - started) * 1000)
