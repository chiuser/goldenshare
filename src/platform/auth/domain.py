from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenPayload:
    sub: int
    username: str
    is_admin: bool


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: int
    username: str
    display_name: str | None
    email: str | None
    account_state: str
    is_admin: bool
    is_active: bool
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
