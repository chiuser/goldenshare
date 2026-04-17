from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class AuthInviteCode(TimestampMixin, Base):
    __tablename__ = "auth_invite_code"
    __table_args__ = (
        Index("idx_auth_invite_code_role_key", "role_key"),
        Index("idx_auth_invite_code_expires_at", "expires_at"),
        Index("idx_auth_invite_code_disabled_at", "disabled_at"),
        Index("uq_auth_invite_code_hash", "code_hash", unique=True),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    code_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False, default="viewer", server_default="viewer")
    assigned_email: Mapped[str | None] = mapped_column(String(255))
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(255))

