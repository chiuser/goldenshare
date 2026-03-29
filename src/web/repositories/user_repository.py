from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.app.app_user import AppUser


class UserRepository:
    def get_by_id(self, session: Session, user_id: int) -> AppUser | None:
        stmt = select(AppUser).where(AppUser.id == user_id)
        return session.scalar(stmt)

    def get_by_username(self, session: Session, username: str) -> AppUser | None:
        stmt = select(AppUser).where(AppUser.username == username)
        return session.scalar(stmt)

    def create_user(
        self,
        session: Session,
        *,
        username: str,
        password_hash: str,
        display_name: str | None = None,
        email: str | None = None,
        is_admin: bool = False,
        is_active: bool = True,
    ) -> AppUser:
        user = AppUser(
            username=username,
            password_hash=password_hash,
            display_name=display_name,
            email=email,
            is_admin=is_admin,
            is_active=is_active,
        )
        session.add(user)
        session.flush()
        return user

    def update_last_login(self, session: Session, user: AppUser, ts: datetime) -> AppUser:
        user.last_login_at = ts
        session.flush()
        return user
