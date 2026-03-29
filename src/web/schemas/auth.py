from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    token: str
    username: str
    is_admin: bool
    display_name: str | None = None


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    is_admin: bool
    is_active: bool
