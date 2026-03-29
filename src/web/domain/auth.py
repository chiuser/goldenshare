from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenPayload:
    sub: int
    username: str
    is_admin: bool
