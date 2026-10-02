"""Announcement identity: equality of the complete original source object."""
from __future__ import annotations

import hashlib
import json
from typing import Any


class AnnouncementPersistenceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def digest(values: Any) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def canonical_payload(payload: str) -> str:
    source = json.loads(payload)
    if not isinstance(source, dict):
        raise ValueError('announcement source payload must be an object')
    return json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(payload: str) -> str:
    return digest(('anns_d', json.loads(canonical_payload(payload))))
