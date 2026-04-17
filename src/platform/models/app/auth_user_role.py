from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class AuthUserRole(TimestampMixin, Base):
    __tablename__ = "auth_user_role"
    __table_args__ = (
        Index("idx_auth_user_role_user_id", "user_id"),
        Index("idx_auth_user_role_role_key", "role_key"),
        Index("uq_auth_user_role_user_role", "user_id", "role_key", unique=True),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_by_user_id: Mapped[int | None] = mapped_column(Integer)

