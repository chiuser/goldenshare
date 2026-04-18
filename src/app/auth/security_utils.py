from __future__ import annotations

import hashlib
import secrets

from src.app.exceptions import WebAppError


def generate_raw_token() -> str:
    return secrets.token_urlsafe(48)


def hash_raw_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def normalize_username(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise WebAppError(status_code=422, code="validation_error", message="Username can not be empty")
    return normalized


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    normalized = email.strip().lower()
    return normalized or None
