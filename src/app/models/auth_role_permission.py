from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class AuthRolePermission(TimestampMixin, Base):
    __tablename__ = "auth_role_permission"
    __table_args__ = (
        Index("idx_auth_role_permission_role_key", "role_key"),
        Index("idx_auth_role_permission_permission_key", "permission_key"),
        Index("uq_auth_role_permission_role_permission", "role_key", "permission_key", unique=True),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_by_user_id: Mapped[int | None] = mapped_column(Integer)

