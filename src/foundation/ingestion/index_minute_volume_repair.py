"""Plan and apply exact-key updates to index minute volume."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import file_digest, sha256
from itertools import groupby, islice
import json
from os import fsync
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from sqlalchemy import column, select, update, values
from sqlalchemy.orm import Session

from src.foundation.models.raw.raw_index_mins import RawIndexMins


PILOT = ("000001.SH", "30min", date(2026, 11, 24))
REPAIR_DAYS = frozenset(date(2026, 11, day) for day in (10, 11, 12, 13, 16, 17, 18, 19, 20, 23, 24))
NATIVE_FREQS = ("1min", "5min", "15min", "30min", "60min")
SCOPE_TOTALS = {"pilot": (1, 9), "first-batch": (10_395, 667_359)}
MAX_GROUP_ROWS = 241
# SHA-256 of the 189 distinct sorted codes in the stage 1 verified preview.
_FIRST_BATCH_CODES_SHA256 = "353136bf0983545a1ffc4388f1acd0005838b41ec919cbbe1575f60b17edcd35"
_TABLE = RawIndexMins.__table__
_NON_VOLUME = tuple(field.name for field in _TABLE.c if field.name != "vol")


@dataclass(frozen=True, slots=True)
class VolumeRepairGroup:
    ts_code: str
    freq: str
    trade_date: date
    rows: tuple[tuple[datetime, float, float], ...]
    non_volume_digest: str = ""

    @property
    def key(self) -> tuple[str, str, date]:
        return self.ts_code, self.freq, self.trade_date

    @property
    def label(self) -> str:
        return f"{self.ts_code} {self.freq} {self.trade_date}"

    def encode(self, digest: str) -> bytes:
        return (json.dumps({
            "ts_code": self.ts_code, "freq": self.freq, "trade_date": self.trade_date.isoformat(),
            "rows": [[stamp.isoformat(), old, target] for stamp, old, target in self.rows],
            "non_volume_digest": digest,
        }, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _non_volume_digest(records) -> str:
    fields = [
        [row[name].isoformat() if name == "trade_time" else row[name] for name in _NON_VOLUME]
        for row in records
    ]
    return sha256(json.dumps(fields, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _read_group(session: Session, group: VolumeRepairGroup, *, lock: bool = False):
    fields = _TABLE.c
    begin = datetime.combine(group.trade_date, time.min)
    query = (
        select(_TABLE)
        .where(fields.ts_code == group.ts_code, fields.freq == group.freq,
               fields.trade_time >= begin, fields.trade_time < begin + timedelta(days=1))
        .order_by(fields.trade_time)
        .limit(len(group.rows) + 1)
    )
    return session.execute(query.with_for_update() if lock else query).mappings().all()


def _check_scope(group: VolumeRepairGroup, scope: str) -> None:
    if not group.ts_code.endswith(".SH") or group.freq not in NATIVE_FREQS or group.trade_date not in REPAIR_DAYS:
        raise ValueError(f"清单超出本次修复范围：{group.label}")
    if scope == "pilot" and group.key != PILOT:
        raise ValueError(f"清单超出试点范围：{group.label}")
    if not 0 < len(group.rows) <= MAX_GROUP_ROWS:
        raise ValueError(f"清单组根数无效：{group.label}")
    timestamps = [stamp for stamp, _, _ in group.rows]
    if timestamps != sorted(set(timestamps)) or any(
        stamp.date() != group.trade_date for stamp in timestamps
    ):
        raise ValueError(f"清单时间键重复、无序或超出当前日期：{group.label}")
    if any(target != old * 100 for _, old, target in group.rows):
        raise ValueError(f"清单成交量应按手转股：{group.label}")


def _classify(group: VolumeRepairGroup, records) -> list[tuple[datetime, float, float]]:
    if [record["trade_time"] for record in records] != [stamp for stamp, _, _ in group.rows]:
        raise ValueError(f"行情键与清单不一致：{group.label}")

    changes = []
    for record, (stamp, old, target) in zip(records, group.rows, strict=True):
        if record["vol"] == target:
            continue
        if record["vol"] != old:
            raise ValueError(f"成交量与清单旧值、目标值均不一致：{group.label} {stamp:%H:%M}")
        changes.append((stamp, old, target))
    return changes


def apply_volume_repair_group(session: Session, group: VolumeRepairGroup) -> int:
    """Update the locked group. The caller controls its transaction."""

    fields = _TABLE.c
    records = _read_group(session, group, lock=True)
    changes = _classify(group, records)
    if _non_volume_digest(records) != group.non_volume_digest:
        raise ValueError(f"非成交量字段与冻结清单不一致：{group.label}")
    if not changes:
        return 0

    repair_rows = values(
        column("trade_time", fields.trade_time.type),
        column("old_vol", fields.vol.type),
        column("target_vol", fields.vol.type),
        name="repair_rows",
    ).data(changes)
    statement = (
        update(_TABLE)
        .where(
            fields.ts_code == group.ts_code, fields.freq == group.freq,
            fields.trade_time == repair_rows.c.trade_time,
            fields.vol.is_not_distinct_from(repair_rows.c.old_vol),
            fields.vol.is_distinct_from(repair_rows.c.target_vol),
        )
        .values(vol=repair_rows.c.target_vol)
        .returning(fields.trade_time, fields.vol)
    )
    updated = set(session.execute(statement).tuples())
    if updated != {(stamp, target) for stamp, _, target in changes}:
        raise ValueError(f"更新结果与清单不一致：{group.label}")

    readback = _read_group(session, group)
    if _classify(group, readback) or _non_volume_digest(readback) != group.non_volume_digest:
        raise ValueError(f"行情读回与冻结清单不一致：{group.label}")
    return len(updated)


def _preview_rows(preview: Path, scope: str) -> Iterator[VolumeRepairGroup]:
    import duckdb

    sql = """
        SELECT ts_code, freq, trade_date, trade_time, old_vol, target_vol
        FROM read_parquet(?, hive_partitioning = false)
    """
    params = [str(preview)]
    if scope == "pilot":
        sql += " WHERE ts_code = ? AND freq = ? AND trade_date = ?"
        params.extend(PILOT)
    totals = SCOPE_TOTALS[scope]
    sql += " ORDER BY ts_code, freq, trade_date, trade_time LIMIT ?"
    params.append(totals[1] + 1)

    def rows(cursor):
        while batch := cursor.fetchmany(MAX_GROUP_ROWS):
            yield from batch

    with duckdb.connect(config={"memory_limit": "256MB", "threads": "1", "temp_directory": ""}) as db:
        cursor = db.execute(sql, params)
        for key, group in groupby(rows(cursor), key=lambda row: row[:3]):
            yield VolumeRepairGroup(*key, tuple(tuple(row[3:]) for row in islice(group, MAX_GROUP_ROWS + 1)))


def _check_scope_totals(scope: str, units: int, rows: int, codes: set[str]) -> None:
    if (units, rows) != SCOPE_TOTALS[scope]:
        raise ValueError("清单分组或根数与已确认的范围不一致")
    if scope == "first-batch":
        fingerprint = sha256("\n".join(sorted(codes)).encode()).hexdigest()
        if fingerprint != _FIRST_BATCH_CODES_SHA256:
            raise ValueError("清单指数代码与已确认的首批范围不一致")


def freeze_volume_repair(session_factory, *, preview: Path, target: Path, scope: str) -> str:
    group_total, row_total = SCOPE_TOTALS[scope]
    units = rows = 0
    codes: set[str] = set()
    pending: Path | None = None
    try:
        with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            pending = Path(stream.name)
            stream.write((json.dumps({"scope": scope, "unit_total": group_total, "row_total": row_total}) + "\n").encode())
            for group in _preview_rows(preview, scope):
                _check_scope(group, scope)
                with session_factory() as session:
                    records = _read_group(session, group)
                    _classify(group, records)
                stream.write(group.encode(_non_volume_digest(records)))
                units += 1
                rows += len(group.rows)
                codes.add(group.ts_code)
            _check_scope_totals(scope, units, rows, codes)
            stream.flush()
            fsync(stream.fileno())
        with pending.open("rb") as frozen:
            fingerprint = file_digest(frozen, "sha256").hexdigest()
        pending.replace(target)
        return fingerprint
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def verify_frozen_volume_repair(stream: BinaryIO, expected_sha256: str) -> dict:
    if file_digest(stream, "sha256").hexdigest() != expected_sha256:
        raise ValueError("历史成交量清单与已提交的 SHA-256 不一致")
    stream.seek(0)
    header = json.loads(stream.readline())
    totals = header["unit_total"], header["row_total"]
    scope = header["scope"]
    if totals != SCOPE_TOTALS.get(scope):
        raise ValueError("冻结清单范围不符合阶段 2")
    start = stream.tell()
    units = rows = 0
    codes: set[str] = set()
    for group in iter_frozen_volume_repair(stream, scope):
        units += 1
        rows += len(group.rows)
        codes.add(group.ts_code)
    _check_scope_totals(scope, units, rows, codes)
    stream.seek(start)
    return header


def iter_frozen_volume_repair(stream: Iterable[bytes], scope: str) -> Iterator[VolumeRepairGroup]:
    previous = None
    for line in stream:
        record = json.loads(line)
        group = VolumeRepairGroup(
            record["ts_code"], record["freq"], date.fromisoformat(record["trade_date"]),
            tuple((datetime.fromisoformat(stamp), old, target) for stamp, old, target in record["rows"]),
            record["non_volume_digest"],
        )
        _check_scope(group, scope)
        if previous is not None and group.key <= previous:
            raise ValueError("冻结清单分组重复或无序")
        previous = group.key
        yield group
