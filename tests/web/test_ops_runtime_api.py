from __future__ import annotations

def test_ops_runtime_scheduler_tick_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/runtime/scheduler-tick",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 5},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_runtime_scheduler_tick_is_blocked_in_web_process(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/runtime/scheduler-tick",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 5},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "runtime_decoupled"


def test_ops_runtime_worker_run_is_blocked_in_web_process(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)

    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.post(
        "/api/v1/ops/runtime/worker-run",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 2},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "runtime_decoupled"
