from __future__ import annotations

from src.platform.models.app.app_user import AppUser


def test_login_success_updates_last_login(app_client, db_session, user_factory) -> None:
    user = user_factory(username="admin", password="secret", is_admin=True)

    response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})

    assert response.status_code == 200
    body = response.json()
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


def test_login_rejects_inactive_user(app_client, user_factory) -> None:
    user_factory(username="inactive", password="secret", is_active=False)

    response = app_client.post("/api/v1/auth/login", json={"username": "inactive", "password": "secret"})

    assert response.status_code == 401
    assert response.json()["message"] == "User is inactive"


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
