from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.web.auth.jwt_service import JWTService
from src.web.auth.password_service import PasswordService
from src.web.domain.user import AuthenticatedUser
from src.web.exceptions import WebAppError
from src.web.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self) -> None:
        self.user_repository = UserRepository()
        self.password_service = PasswordService()
        self.jwt_service = JWTService()

    def login(self, session: Session, *, username: str, password: str) -> tuple[str, AuthenticatedUser]:
        user = self.user_repository.get_by_username(session, username.strip())
        if user is None or not self.password_service.verify_password(password, user.password_hash):
            raise WebAppError(status_code=401, code="unauthorized", message="Username or password is incorrect")
        if not user.is_active:
            raise WebAppError(status_code=401, code="unauthorized", message="User is inactive")

        self.user_repository.update_last_login(session, user, datetime.now(timezone.utc))
        session.commit()
        token = self.jwt_service.encode(user_id=user.id, username=user.username, is_admin=user.is_admin)
        return token, AuthenticatedUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            is_admin=user.is_admin,
            is_active=user.is_active,
        )
