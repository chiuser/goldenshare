"""Read one bounded window of an identity-checked, already sorted minute CSV.

The accepted SHA is the caller's frozen-source evidence. Binary seeking does
not establish the ordering of unvisited rows in an arbitrary CSV. SHA reads
all bytes without parsing them; only bounded probes, neighbours and the
requested window are decoded. No indicator or product state is calculated.
"""
from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
import time


COLUMNS = (
    "ts_code", "freq", "trade_date", "trade_time", "close", "macd_dif",
    "macd_dea", "macd", "params_key", "indicator_version", "observation_count",
)
PARAMS = "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3"
SLOTS = ("11:00:00", "14:00:00", "15:00:00")
MAX_LINE_BYTES = 1024
MAX_SEEK_ROWS = 128
MAX_SEEK_BYTES = 65536
MAX_SOURCE_BYTES = 3 * 1024 * 1024
NUMBER_FIELDS = ("close", "macd_dif", "macd_dea", "macd")


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        raise ValueError("Use the original YYYY-MM-DD HH:MM:SS timestamp")
    try:
        result = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("Invalid minute timestamp") from exc
    if value[-8:] not in SLOTS:
        raise ValueError("Invalid completed 90-minute endpoint")
    return result


def _parse_row(raw: bytes) -> dict[str, str]:
    if not raw or len(raw) > MAX_LINE_BYTES or b"\x00" in raw:
        raise ValueError("Empty, oversized or malformed CSV record")
    try:
        fields = next(csv.reader([raw.decode("utf-8")], strict=True))
    except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise ValueError("Malformed single-line CSV record") from exc
    if len(fields) != len(COLUMNS) or any(not field for field in fields):
        raise ValueError("CSV record does not match the eleven-column contract")
    row = dict(zip(COLUMNS, fields, strict=True))
    if (row["ts_code"] != "000001.SH" or row["freq"] != "90"
            or row["params_key"] != PARAMS or row["indicator_version"] != "1"):
        raise ValueError("Changed object, frequency or indicator identity")
    stamp = _timestamp(row["trade_time"])
    if stamp.date().isoformat() != row["trade_date"]:
        raise ValueError("Minute time and trade date disagree")
    if not re.fullmatch(r"[1-9]\d*", row["observation_count"]):
        raise ValueError("Invalid observation count")
    values = {}
    try:
        for name in NUMBER_FIELDS:
            values[name] = Decimal(row[name])
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric field") from exc
    if any(not value.is_finite() for value in values.values()) or values["close"] <= 0:
        raise ValueError("Nonfinite value or nonpositive close")
    if abs(values["macd"] - 2 * (values["macd_dif"] - values["macd_dea"])) > Decimal("1e-10"):
        raise ValueError("Broken H=2*(DIF-DEA)")
    return row


def read_window(source, *, start, end, expected_sha, max_rows=150, max_bytes=65536) -> dict:
    """Return original field strings after source, window and neighbour checks.

    ``max_rows``/``max_bytes`` bound the returned window. Positioning and
    neighbour reads have separate fixed bounds and are reported separately.
    Missing whole trading dates cannot be checked without a calendar; source
    identity and its pre-existing calendar evidence remain prerequisites.
    """
    begun = time.perf_counter()
    _timestamp(start)
    _timestamp(end)
    if start > end:
        raise ValueError("Window start is after its end")
    if (type(max_rows) is not int or not 0 < max_rows <= 150
            or type(max_bytes) is not int or not 0 < max_bytes <= 65536):
        raise ValueError("Window budget must be positive and within the approved bounds")
    if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        raise ValueError("An explicit frozen-source SHA256 is required")

    metrics = dict(window_rows=0, window_bytes=0, seek_rows=0, seek_bytes=0,
                   seek_calls=0, sha_bytes=0, header_bytes=0)
    with Path(source).open("rb") as stream:
        original = stream.fileno()
        import os
        before = os.fstat(original)
        if not 0 < before.st_size <= MAX_SOURCE_BYTES:
            raise ValueError("Source file is empty or exceeds the frozen-source byte bound")
        sha_started = time.perf_counter()
        digest = hashlib.sha256()
        while block := stream.read(65536):
            digest.update(block)
            metrics["sha_bytes"] += len(block)
        actual_sha = digest.hexdigest()
        metrics["sha_seconds"] = time.perf_counter() - sha_started
        if actual_sha != expected_sha:
            raise ValueError("Frozen source SHA256 does not match")

        stream.seek(0)
        header = stream.readline(MAX_LINE_BYTES + 1)
        metrics["header_bytes"] = len(header)
        try:
            names = next(csv.reader([header.decode("utf-8")], strict=True))
        except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
            raise ValueError("Malformed CSV header") from exc
        if len(header) > MAX_LINE_BYTES or tuple(names) != COLUMNS:
            raise ValueError("Changed eleven-column CSV header")
        first = stream.tell()
        size = before.st_size
        if first >= size:
            raise ValueError("CSV has no minute records")

        def account(raw: bytes) -> bytes:
            metrics["seek_bytes"] += len(raw)
            if metrics["seek_bytes"] > MAX_SEEK_BYTES:
                raise ValueError("Positioning byte budget exceeded")
            return raw

        def probe(position: int):
            metrics["seek_calls"] += 1
            stream.seek(position)
            if position > first:
                stream.seek(position - 1)
                previous_byte = account(stream.read(1))
                if previous_byte != b"\n":
                    fragment = account(stream.readline(MAX_LINE_BYTES + 1))
                    if len(fragment) > MAX_LINE_BYTES:
                        raise ValueError("Oversized CSV line while positioning")
            offset = stream.tell()
            raw = account(stream.readline(MAX_LINE_BYTES + 1))
            if not raw:
                return None
            metrics["seek_rows"] += 1
            if metrics["seek_rows"] > MAX_SEEK_ROWS:
                raise ValueError("Positioning row budget exceeded")
            return offset, _parse_row(raw), stream.tell()

        def lower_bound(target: str) -> int:
            low, high, found = first, size, size
            while low < high:
                middle = (low + high) // 2
                point = probe(middle)
                if point is None:
                    high = middle
                elif point[1]["trade_time"] >= target:
                    found = min(found, point[0])
                    high = middle
                else:
                    low = point[2]
            return found

        position = lower_bound(start)
        if position >= size:
            raise ValueError("Requested window start was not found")
        # Read at most one preceding line; do not scan backward to old history.
        left = None
        if position > first:
            offset = max(first, position - MAX_LINE_BYTES - 1)
            stream.seek(offset)
            fragment = account(stream.read(position - offset))
            cut = fragment.rfind(b"\n", 0, len(fragment) - 1)
            if cut < 0 and offset != first:
                raise ValueError("Preceding CSV line exceeds its byte bound")
            prior = probe(offset + cut + 1)
            if prior is None or prior[2] != position:
                raise ValueError("Invalid preceding window boundary")
            left = prior[1]

        rows = []
        next_row = None
        stream.seek(position)
        while raw := stream.readline(MAX_LINE_BYTES + 1):
            row = _parse_row(raw)
            key = row["trade_time"]
            if key > end:
                account(raw)
                metrics["seek_rows"] += 1
                if metrics["seek_rows"] > MAX_SEEK_ROWS:
                    raise ValueError("Positioning row budget exceeded")
                next_row = row
                break
            metrics["window_rows"] += 1
            metrics["window_bytes"] += len(raw)
            if metrics["window_rows"] > max_rows or metrics["window_bytes"] > max_bytes:
                raise ValueError("Requested window exceeds its row or byte budget")
            if key < start or (rows and key <= rows[-1]["trade_time"]):
                raise ValueError("Window timestamps are duplicate, unordered or outside its start")
            rows.append(row)

        if not rows or rows[0]["trade_time"] != start or rows[-1]["trade_time"] != end:
            raise ValueError("Requested start or end endpoint was not found")
        if left is not None and left["trade_time"] >= start:
            raise ValueError("Preceding row does not precede the requested window")
        if next_row is not None and next_row["trade_time"] <= end:
            raise ValueError("Following row does not follow the requested window")
        dates = {}
        for row in rows:
            dates.setdefault(row["trade_date"], []).append(row["trade_time"][-8:])
        for day, slots in dates.items():
            expected = [slot for slot in SLOTS if start <= f"{day} {slot}" <= end]
            if slots != expected:
                raise ValueError("Missing or duplicate completed endpoints within a trading date")
        after = os.fstat(original)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("Frozen source changed during window reading")

    metrics.update(seconds=time.perf_counter() - begun,
                   window_start=start, window_end=end,
                   preceding_time=left["trade_time"] if left else None,
                   following_time=next_row["trade_time"] if next_row else None,
                   global_order_verified=False, trading_calendar_rechecked=False)
    return dict(rows=rows, source_sha256=actual_sha, metrics=metrics)
