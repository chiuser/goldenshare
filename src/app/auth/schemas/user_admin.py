from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdminUserListItem(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    account_state: str
    is_admin: bool
    is_active: bool
    roles: list[str] = Field(default_factory=list)
    email_verified_at: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AdminUserListResponse(BaseModel):
    total: int
    items: list[AdminUserListItem]


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    is_admin: bool = False
    is_active: bool = True
    account_state: str = "active"
    roles: list[str] = Field(default_factory=list)


class AdminUpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    is_admin: bool | None = None
    is_active: bool | None = None
    account_state: str | None = None


class AdminSetUserRolesRequest(BaseModel):
    roles: list[str] = Field(default_factory=list, min_length=1)


class AdminResetPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AdminInviteCreateRequest(BaseModel):
    role_key: str = Field(default="viewer", min_length=1, max_length=64)
    assigned_email: str | None = Field(default=None, max_length=255)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_at: datetime | None = None
    note: str | None = Field(default=None, max_length=255)
    code: str | None = Field(default=None, min_length=4, max_length=128)


class AdminInviteCreateResponse(BaseModel):
    id: int
    code: str
    role_key: str
    assigned_email: str | None = None
    max_uses: int
    used_count: int
    expires_at: datetime | None = None
    disabled_at: datetime | None = None
    note: str | None = None
    created_at: datetime


class AdminInviteItem(BaseModel):
    id: int
    code_hint: str
    role_key: str
    assigned_email: str | None = None
    max_uses: int
    used_count: int
    expires_at: datetime | None = None
    disabled_at: datetime | None = None
    last_used_at: datetime | None = None
    created_by_user_id: int | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminInviteListResponse(BaseModel):
    total: int
    items: list[AdminInviteItem]


class AuthAuditItem(BaseModel):
    id: int
    user_id: int | None = None
    username_snapshot: str | None = None
    event_type: str
    event_status: str
    ip_address: str | None = None
    user_agent: str | None = None
    detail_json: dict
    occurred_at: datetime


class AuthAuditListResponse(BaseModel):
    total: int
    items: list[AuthAuditItem]

