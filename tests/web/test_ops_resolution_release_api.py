from __future__ import annotations


def test_ops_resolution_release_list_rejects_non_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/releases", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_resolution_release_create_list_and_update_status(app_client, user_factory, db_session) -> None:
    from sqlalchemy import select

    from src.ops.models.ops.config_revision import ConfigRevision

    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    created = app_client.post(
        "/api/v1/ops/releases",
        headers={"Authorization": f"Bearer {token}"},
        json={"dataset_key": "security_master", "target_policy_version": 3, "status": "previewing"},
    )
    assert created.status_code == 200
    created_payload = created.json()
    release_id = created_payload["id"]
    assert created_payload["dataset_key"] == "security_master"
    assert created_payload["target_policy_version"] == 3
    assert created_payload["status"] == "previewing"
    assert created_payload["triggered_by_username"] == "admin"

    listed = app_client.get("/api/v1/ops/releases?dataset_key=security_master", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 1
    assert listed_payload["items"][0]["id"] == release_id

    updated = app_client.patch(
        f"/api/v1/ops/releases/{release_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "running"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "running"

    completed = app_client.patch(
        f"/api/v1/ops/releases/{release_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["finished_at"] is not None

    revisions = list(
        db_session.scalars(
            select(ConfigRevision)
            .where(ConfigRevision.object_type == "resolution_release")
            .where(ConfigRevision.object_id == str(release_id))
            .order_by(ConfigRevision.id.asc())
        )
    )
    assert [item.action for item in revisions] == ["created", "status_updated", "status_updated"]


def test_ops_resolution_release_stage_status_upsert_and_query(
    app_client,
    user_factory,
    resolution_release_factory,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    release = resolution_release_factory(dataset_key="security_master", target_policy_version=2, status="running")

    upsert = app_client.put(
        f"/api/v1/ops/releases/{release.id}/stages",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "items": [
                {
                    "dataset_key": "security_master",
                    "source_key": "tushare",
                    "stage": "std",
                    "status": "success",
                    "rows_in": 100,
                    "rows_out": 98,
                    "message": "ok",
                },
                {
                    "dataset_key": "security_master",
                    "source_key": "biying",
                    "stage": "std",
                    "status": "failed",
                    "rows_in": 80,
                    "rows_out": 0,
                    "message": "schema mismatch",
                },
            ]
        },
    )
    assert upsert.status_code == 200
    payload = upsert.json()
    assert payload["total"] == 2
    statuses = {item["source_key"]: item["status"] for item in payload["items"]}
    assert statuses == {"tushare": "success", "biying": "failed"}

    filtered = app_client.get(
        f"/api/v1/ops/releases/{release.id}/stages?source_key=biying",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 1
    assert filtered_payload["items"][0]["source_key"] == "biying"
    assert filtered_payload["items"][0]["stage"] == "std"
