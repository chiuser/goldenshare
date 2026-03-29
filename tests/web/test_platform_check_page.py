from __future__ import annotations


def test_platform_check_page_is_available(app_client) -> None:
    response = app_client.get("/platform-check")

    assert response.status_code == 200
    assert "Goldenshare Platform Check" in response.text


def test_platform_check_static_js_is_available(app_client) -> None:
    response = app_client.get("/static/platform-check.js")

    assert response.status_code == 200
    assert "btn-health" in response.text
