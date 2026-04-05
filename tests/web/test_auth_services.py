from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.platform.auth.jwt_service import JWTService
from src.platform.auth.password_service import PasswordService
from src.platform.exceptions.web import WebAppError


def test_password_service_hash_and_verify() -> None:
    service = PasswordService()
    password_hash = service.hash_password("secret")

    assert password_hash != "secret"
    assert service.verify_password("secret", password_hash) is True
    assert service.verify_password("other", password_hash) is False


def test_jwt_service_encode_and_decode() -> None:
    service = JWTService()

    token = service.encode(user_id=1, username="admin", is_admin=True)
    payload = service.decode(token)

    assert payload.sub == 1
    assert payload.username == "admin"
    assert payload.is_admin is True


def test_jwt_service_rejects_expired_token() -> None:
    service = JWTService()
    expired = jwt.encode(
        {
            "sub": "1",
            "username": "admin",
            "is_admin": True,
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        service.secret,
        algorithm=service.algorithm,
    )

    with pytest.raises(WebAppError) as exc_info:
        service.decode(expired)

    assert exc_info.value.code == "unauthorized"
