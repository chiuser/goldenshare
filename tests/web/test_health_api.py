from __future__ import annotations

from src.web.settings import get_web_settings


def test_health_endpoints_return_ok(app_client) -> None:
    response = app_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "goldenshare-web"
    assert response.headers["X-Request-ID"]

    response_v1 = app_client.get("/api/v1/health")
    assert response_v1.status_code == 200
    assert response_v1.json()["env"] == get_web_settings().app_env
