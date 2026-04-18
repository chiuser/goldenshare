from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from src.app.auth.domain import TokenPayload
from src.app.exceptions import WebAppError
from src.platform.web.settings import get_web_settings


class JWTService:
    algorithm = "HS256"

    def __init__(self) -> None:
        self.settings = get_web_settings()

    @property
    def secret(self) -> str:
        secret = self.settings.jwt_secret.strip()
        if not secret:
            raise WebAppError(status_code=500, code="config_error", message="JWT secret is not configured")
        return secret

    def encode(self, *, user_id: int, username: str, is_admin: bool) -> str:
        expire_at = datetime.now(timezone.utc) + timedelta(minutes=self.settings.jwt_expire_minutes)
        payload = {
            "sub": str(user_id),
            "username": username,
            "is_admin": is_admin,
            "exp": expire_at,
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def decode(self, token: str) -> TokenPayload:
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise WebAppError(status_code=401, code="unauthorized", message="Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise WebAppError(status_code=401, code="unauthorized", message="Token is invalid") from exc
        return TokenPayload(
            sub=int(payload["sub"]),
            username=str(payload.get("username", "")),
            is_admin=bool(payload.get("is_admin", False)),
        )

