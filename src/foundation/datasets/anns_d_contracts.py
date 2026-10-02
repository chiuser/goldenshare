"""Deterministic announcement identity and information coverage contract."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any

FIELDS = ('ann_date', 'ts_code', 'name', 'title', 'url', 'rec_time')
ATTRIBUTES = ('name', 'url', 'rec_time')


class AnnouncementPersistenceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class AnnouncementContractError(ValueError):
    pass


def content(row: dict[str, Any]) -> tuple:
    day = row['ann_date']
    if not isinstance(day, date) or isinstance(day, datetime):
        raise AnnouncementContractError('ann_date must be a date')
    recorded = row.get('rec_time')
    if recorded is not None:
        if not isinstance(recorded, datetime) or recorded.tzinfo is None:
            raise AnnouncementContractError('rec_time must be timezone aware')
        recorded = recorded.astimezone(timezone.utc).isoformat()
    return (day.isoformat(), row['ts_code'], row.get('name'), row['title'], row.get('url'), recorded)


def digest(values: tuple | list) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(row: dict[str, Any]) -> tuple[str, str]:
    values = content(row)
    return digest(('anns_d', values[0], values[1], values[3])), digest(('anns_d', *values))


def covers(complete: dict, partial: dict) -> bool:
    a, b = content(partial), content(complete)
    if (a[0], a[1], a[3]) != (b[0], b[1], b[3]):
        return False
    va, vb = (a[2], a[4], a[5]), (b[2], b[4], b[5])
    return all(x is None or x == y for x, y in zip(va, vb)) and sum(x is not None for x in vb) > sum(x is not None for x in va)


def maximal(rows: list[dict]) -> list[dict]:
    """Return actual source rows, never a synthetic union of their attributes."""
    unique: dict[str, dict] = {}
    for row in rows:
        group, key = identity(row)
        if row.get('group_key', group) != group or row.get('row_key_hash', key) != key:
            raise AnnouncementContractError('identity does not match actual fields')
        prior = unique.get(key)
        if prior is not None and content(prior) != content(row):
            raise AnnouncementContractError('content hash collision')
        if prior is None:
            unique[key] = row
    return [row for key, row in sorted(unique.items()) if not any(covers(other, row) for other in unique.values())]
