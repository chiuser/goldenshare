from __future__ import annotations

from src.foundation.ingestion.codebook import INGESTION_CODEBOOK_UPDATED_AT, INGESTION_CODEBOOK_VERSION


def test_ops_ingestion_codebook_requires_admin(app_client, user_factory) -> None:
    user_factory(username="viewer", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "viewer", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/codebook/ingestion", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_ingestion_codebook_returns_backend_dictionary(app_client, user_factory) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/codebook/ingestion", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == INGESTION_CODEBOOK_VERSION
    assert payload["updated_at"] == INGESTION_CODEBOOK_UPDATED_AT
    assert any(item["code"] == "forbidden_sentinel" for item in payload["error_codes"])
    assert any(item["code"] == "all_rows_rejected" for item in payload["error_codes"])
    assert any(item["code"] == "normalize.required_field_missing" for item in payload["reason_codes"])
