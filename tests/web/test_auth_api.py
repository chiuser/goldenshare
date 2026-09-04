from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, select
from starlette.requests import Request

from src.app.exceptions.web import install_exception_handlers
from src.app.models.app_user import AppUser
from src.app.models.auth_audit_log import AuthAuditLog
from src.app.models.auth_refresh_token import AuthRefreshToken


def _assert_token_contract(body: dict) -> None:
    assert set(body) == {"token", "refresh_token", "access_token_expires_at", "username", "is_admin", "display_name"}
    assert isinstance(body["token"], str) and body["token"]
    assert isinstance(body["refresh_token"], str) and body["refresh_token"]
    assert isinstance(body["access_token_expires_at"], str) and body["access_token_expires_at"]
    assert isinstance(body["username"], str)
    assert isinstance(body["is_admin"], bool)
    assert body["display_name"] is None or isinstance(body["display_name"], str)


def test_login_success_updates_last_login(app_client, db_session, user_factory) -> None:
    user = user_factory(username="admin", password="secret", is_admin=True)

    response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})

    assert response.status_code == 200
    body = response.json()
    _assert_token_contract(body)
    assert body["username"] == "admin"
    assert body["is_admin"] is True
    assert body["token"]

    refreshed = db_session.get(AppUser, user.id)
    assert refreshed is not None
    assert refreshed.last_login_at is not None


def test_login_rejects_wrong_password(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret")

    response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert response.json()["request_id"]
    assert response.json()["message"] == "用户名或密码不正确"
    assert set(response.json()) == {"code", "message", "request_id"}
    assert app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200


def test_login_rejects_inactive_user(app_client, user_factory) -> None:
    user_factory(username="inactive", password="secret", is_active=False)

    response = app_client.post("/api/v1/auth/login", json={"username": "inactive", "password": "secret"})

    assert response.status_code == 401
    assert response.json()["message"] == "用户已停用"
    assert response.json()["code"] == "unauthorized"
    assert set(response.json()) == {"code", "message", "request_id"}


def test_auth_me_requires_token(app_client) -> None:
    response = app_client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert response.json()["request_id"]


def test_auth_me_returns_current_user(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["username"] == "admin"
    assert response.json()["is_admin"] is True


def test_users_me_returns_current_user(app_client, user_factory) -> None:
    user_factory(username="alice", password="secret", display_name="Alice")
    login = app_client.post("/api/v1/auth/login", json={"username": "alice", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["display_name"] == "Alice"


def test_logout_requires_authentication(app_client) -> None:
    response = app_client.post("/api/v1/auth/logout")

    assert response.status_code == 401


def test_logout_returns_ok(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret")
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_login_nullable_display_name_contract(app_client, user_factory) -> None:
    user_factory(username="nullable", password="secret", display_name=None)
    response = app_client.post("/api/v1/auth/login", json={"username": "nullable", "password": "secret"})
    assert response.status_code == 200
    _assert_token_contract(response.json())
    assert response.json()["display_name"] is None


@pytest.mark.parametrize("body", [
    {}, {"username": "admin"}, {"password": "synthetic-secret"},
    {"username": "", "password": "synthetic-secret"}, {"username": "admin", "password": ""},
    {"username": "u" * 65, "password": "synthetic-secret"},
    {"username": "admin", "password": "synthetic-secret-" * 20},
    {"username": ["synthetic-user"], "password": {"secret": "synthetic-secret"}},
    {"username": None, "password": None}, ["synthetic-secret"],
], ids=["missing-both", "missing-password", "missing-user", "empty-user", "empty-password",
        "long-user", "long-password", "wrong-types", "nulls", "non-object"])
def test_login_validation_never_returns_inputs_or_creates_sessions(app_client, db_session, user_factory, body) -> None:
    user = user_factory(username="admin", password="secret")
    response = app_client.post("/api/v1/auth/login?audit=1", json=body)
    assert response.status_code == 422
    assert response.json() == {
        "code": "validation_error", "message": "登录参数校验失败，请检查用户名和密码",
        "request_id": response.headers["x-request-id"],
    }
    assert "synthetic" not in response.text
    assert db_session.scalar(select(func.count()).select_from(AuthRefreshToken)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuthAuditLog)) == 0
    db_session.refresh(user)
    assert user.last_login_at is None
    assert user.failed_login_count == 0
    assert app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200


def test_login_malformed_json_never_returns_body(app_client) -> None:
    response = app_client.post("/api/v1/auth/login", content='{"password":"synthetic-secret",',
                               headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json() == {
        "code": "validation_error", "message": "登录参数校验失败，请检查用户名和密码",
        "request_id": response.headers["x-request-id"],
    }
    assert "synthetic-secret" not in response.text


@pytest.mark.parametrize("path,method,operator", [
    ("/api/v1/auth/login-extra", "POST", False),
    ("/api/v1/auth/login", "GET", False),
    ("/api/v1/ops/probe", "POST", True),
])
def test_login_redaction_does_not_change_other_validation_contracts(path, method, operator) -> None:
    app = FastAPI()
    install_exception_handlers(app)
    errors = [{"type": "probe.operator_forbidden" if operator else "value_error",
               "msg": "运营端不能提交该字段" if operator else "ordinary validation",
               "loc": ("body", "probe"), "input": "non-sensitive-probe"}]
    request = Request({"type": "http", "method": method, "path": path, "headers": [],
                       "route": SimpleNamespace(path=path), "state": {"request_id": "scope-test"}})
    response = asyncio.run(app.exception_handlers[RequestValidationError](request, RequestValidationError(errors)))
    assert response.status_code == 422
    assert json.loads(response.body) == {
        "code": "probe.operator_forbidden" if operator else "validation_error",
        "message": "运营端不能提交该字段" if operator else str(errors), "request_id": "scope-test",
    }


def test_real_login_refresh_rotation_and_logout_revocation(app_client, user_factory) -> None:
    user_factory(username="rotation", password="secret", display_name="Rotation")
    login = app_client.post("/api/v1/auth/login", json={"username": "rotation", "password": "secret"})
    assert login.status_code == 200
    original = login.json()
    _assert_token_contract(original)
    response = app_client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert response.status_code == 200
    refreshed = response.json()
    _assert_token_contract(refreshed)
    assert refreshed["refresh_token"] != original["refresh_token"]
    assert (refreshed["username"], refreshed["display_name"], refreshed["is_admin"]) == ("rotation", "Rotation", False)
    headers = {"Authorization": f"Bearer {refreshed['token']}"}
    assert app_client.get("/api/v1/auth/me", headers=headers).status_code == 200
    replay = app_client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["code"] == "unauthorized"
    logout = app_client.post("/api/v1/auth/logout", headers=headers, json={"refresh_token": refreshed["refresh_token"]})
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}
    revoked = app_client.post("/api/v1/auth/refresh", json={"refresh_token": refreshed["refresh_token"]})
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "unauthorized"
