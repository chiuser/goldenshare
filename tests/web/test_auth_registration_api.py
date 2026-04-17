from __future__ import annotations

from sqlalchemy import select

from src.foundation.config.settings import get_settings
from src.platform.auth.security_utils import hash_raw_token
from src.platform.models.app.auth_refresh_token import AuthRefreshToken


def _set_auth_mode(monkeypatch, *, mode: str, require_email_verification: bool = True) -> None:
    monkeypatch.setenv("AUTH_REGISTER_MODE", mode)
    monkeypatch.setenv("AUTH_REQUIRE_EMAIL_VERIFICATION", "true" if require_email_verification else "false")
    get_settings.cache_clear()


def test_register_public_verify_and_refresh_flow(app_client, monkeypatch) -> None:
    _set_auth_mode(monkeypatch, mode="public", require_email_verification=True)

    register = app_client.post(
        "/api/v1/auth/register",
        json={"username": "new_user", "password": "secret123", "email": "new@example.com"},
    )
    assert register.status_code == 200
    register_payload = register.json()
    assert register_payload["account_state"] == "pending_verification"
    assert register_payload["verification_token_debug"]

    verify = app_client.post(
        "/api/v1/auth/register/verify",
        json={"token": register_payload["verification_token_debug"]},
    )
    assert verify.status_code == 200
    verify_payload = verify.json()
    assert verify_payload["token"]
    assert verify_payload["refresh_token"]

    me = app_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {verify_payload['token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "new_user"
    assert me.json()["account_state"] == "active"

    refresh = app_client.post("/api/v1/auth/refresh", json={"refresh_token": verify_payload["refresh_token"]})
    assert refresh.status_code == 200
    refresh_payload = refresh.json()
    assert refresh_payload["token"]
    assert refresh_payload["refresh_token"]
    assert refresh_payload["refresh_token"] != verify_payload["refresh_token"]

    old_refresh = app_client.post("/api/v1/auth/refresh", json={"refresh_token": verify_payload["refresh_token"]})
    assert old_refresh.status_code == 401


def test_register_invite_only_requires_valid_invite(app_client, user_factory, monkeypatch) -> None:
    _set_auth_mode(monkeypatch, mode="invite_only", require_email_verification=True)
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    no_invite = app_client.post(
        "/api/v1/auth/register",
        json={"username": "invite_user", "password": "secret123", "email": "invite@example.com"},
    )
    assert no_invite.status_code == 422

    invite_create = app_client.post(
        "/api/v1/admin/invites",
        headers={"Authorization": f"Bearer {token}"},
        json={"role_key": "viewer", "max_uses": 1},
    )
    assert invite_create.status_code == 200
    code = invite_create.json()["code"]

    register = app_client.post(
        "/api/v1/auth/register",
        json={
            "username": "invite_user",
            "password": "secret123",
            "email": "invite@example.com",
            "invite_code": code,
        },
    )
    assert register.status_code == 200
    payload = register.json()
    assert payload["username"] == "invite_user"
    assert payload["verification_token_debug"]


def test_forgot_and_reset_password_revoke_old_sessions(app_client, user_factory, db_session, monkeypatch) -> None:
    _set_auth_mode(monkeypatch, mode="public", require_email_verification=False)
    user_factory(username="alice", password="oldsecret", is_admin=False)

    old_login = app_client.post("/api/v1/auth/login", json={"username": "alice", "password": "oldsecret"})
    assert old_login.status_code == 200
    old_refresh_token = old_login.json()["refresh_token"]
    old_refresh_hash = hash_raw_token(old_refresh_token)

    forgot = app_client.post("/api/v1/auth/forgot-password", json={"username_or_email": "alice"})
    assert forgot.status_code == 200
    token_debug = forgot.json()["token_debug"]
    assert token_debug

    reset = app_client.post("/api/v1/auth/reset-password", json={"token": token_debug, "new_password": "newsecret123"})
    assert reset.status_code == 200
    assert reset.json()["token"]

    old_token_refresh = app_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert old_token_refresh.status_code == 401

    old_login_again = app_client.post("/api/v1/auth/login", json={"username": "alice", "password": "oldsecret"})
    assert old_login_again.status_code == 401

    new_login = app_client.post("/api/v1/auth/login", json={"username": "alice", "password": "newsecret123"})
    assert new_login.status_code == 200

    old_refresh_row = db_session.scalar(
        select(AuthRefreshToken).where(AuthRefreshToken.token_hash == old_refresh_hash)
    )
    assert old_refresh_row is not None
    assert old_refresh_row.revoked_at is not None
