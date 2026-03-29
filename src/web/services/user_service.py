from __future__ import annotations

from src.web.domain.user import AuthenticatedUser


class UserService:
    def get_self_profile(self, user: AuthenticatedUser) -> AuthenticatedUser:
        return user
