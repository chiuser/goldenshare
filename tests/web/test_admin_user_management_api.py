from __future__ import annotations


def test_admin_user_management_flow(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = app_client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={
            "username": "managed_user",
            "password": "secret123",
            "display_name": "Managed",
            "email": "managed@example.com",
            "roles": ["viewer"],
        },
    )
    assert create.status_code == 200
    payload = create.json()
    assert payload["username"] == "managed_user"
    user_id = payload["id"]

    listed = app_client.get("/api/v1/admin/users", headers=headers)
    assert listed.status_code == 200
    assert any(item["username"] == "managed_user" for item in listed.json()["items"])

    role_update = app_client.post(
        f"/api/v1/admin/users/{user_id}/roles",
        headers=headers,
        json={"roles": ["operator"]},
    )
    assert role_update.status_code == 200
    assert role_update.json()["roles"] == ["operator"]

    suspend = app_client.post(f"/api/v1/admin/users/{user_id}/suspend", headers=headers)
    assert suspend.status_code == 200
    assert suspend.json()["account_state"] == "suspended"

    managed_login = app_client.post("/api/v1/auth/login", json={"username": "managed_user", "password": "secret123"})
    assert managed_login.status_code == 401

    activate = app_client.post(f"/api/v1/admin/users/{user_id}/activate", headers=headers)
    assert activate.status_code == 200
    assert activate.json()["account_state"] == "active"

    reset = app_client.post(
        f"/api/v1/admin/users/{user_id}/reset-password",
        headers=headers,
        json={"password": "newsecret123"},
    )
    assert reset.status_code == 200

    managed_login_new = app_client.post("/api/v1/auth/login", json={"username": "managed_user", "password": "newsecret123"})
    assert managed_login_new.status_code == 200

    delete_resp = app_client.delete(f"/api/v1/admin/users/{user_id}", headers=headers)
    assert delete_resp.status_code == 200

    listed_after_delete = app_client.get("/api/v1/admin/users", headers=headers)
    assert listed_after_delete.status_code == 200
    assert all(item["username"] != "managed_user" for item in listed_after_delete.json()["items"])

    managed_login_deleted = app_client.post("/api/v1/auth/login", json={"username": "managed_user", "password": "newsecret123"})
    assert managed_login_deleted.status_code == 401

    audit = app_client.get("/api/v1/admin/auth-audit", headers=headers)
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1


def test_admin_can_not_delete_self(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    users = app_client.get("/api/v1/admin/users", headers=headers)
    admin_user = next(item for item in users.json()["items"] if item["username"] == "admin")

    delete_self = app_client.delete(f"/api/v1/admin/users/{admin_user['id']}", headers=headers)
    assert delete_self.status_code == 422


def test_admin_invite_list_returns_full_code(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_invite = app_client.post(
        "/api/v1/admin/invites",
        headers=headers,
        json={"role_key": "viewer", "max_uses": 1},
    )
    assert create_invite.status_code == 200
    created_code = create_invite.json()["code"]

    invite_list = app_client.get("/api/v1/admin/invites?include_disabled=true&limit=50&offset=0", headers=headers)
    assert invite_list.status_code == 200
    created_row = next(item for item in invite_list.json()["items"] if item["id"] == create_invite.json()["id"])
    assert created_row["code_hint"] == created_code


def test_admin_can_hard_delete_invite(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_invite = app_client.post(
        "/api/v1/admin/invites",
        headers=headers,
        json={"role_key": "viewer", "max_uses": 1},
    )
    assert create_invite.status_code == 200
    invite_id = create_invite.json()["id"]

    hard_delete = app_client.delete(f"/api/v1/admin/invites/{invite_id}/hard-delete", headers=headers)
    assert hard_delete.status_code == 200

    invite_list = app_client.get("/api/v1/admin/invites?include_disabled=true&limit=50&offset=0", headers=headers)
    assert invite_list.status_code == 200
    assert all(item["id"] != invite_id for item in invite_list.json()["items"])
