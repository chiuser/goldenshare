from __future__ import annotations

from src.platform.auth.domain import AuthenticatedUser


class UserService:
    def get_self_profile(self, user: AuthenticatedUser) -> AuthenticatedUser:
        return user


__all__ = ["UserService"]
