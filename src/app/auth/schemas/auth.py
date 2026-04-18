from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    token: str
    refresh_token: str | None = None
    access_token_expires_at: datetime | None = None
    username: str
    is_admin: bool
    display_name: str | None = None


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    account_state: str
    is_admin: bool
    is_active: bool
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    invite_code: str | None = Field(default=None, min_length=4, max_length=128)


class RegisterResponse(BaseModel):
    user_id: int
    username: str
    account_state: str
    requires_email_verification: bool
    token: str | None = None
    refresh_token: str | None = None
    verification_token_debug: str | None = None


class VerifyActionTokenRequest(BaseModel):
    token: str = Field(min_length=8, max_length=512)


class LookupAccountRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=255)


class LookupAccountResponse(BaseModel):
    ok: bool = True
    message: str
    token_debug: str | None = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=8, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=8, max_length=512)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    new_password: str = Field(min_length=1, max_length=256)


class SessionItem(BaseModel):
    id: int
    status: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


class SessionListResponse(BaseModel):
    total: int
    items: list[SessionItem]


__all__ = [
    "CurrentUserResponse",
    "LoginRequest",
    "LookupAccountRequest",
    "LookupAccountResponse",
    "LogoutRequest",
    "RefreshTokenRequest",
    "RegisterRequest",
    "RegisterResponse",
    "ResetPasswordRequest",
    "SessionItem",
    "SessionListResponse",
    "TokenResponse",
    "VerifyActionTokenRequest",
]
