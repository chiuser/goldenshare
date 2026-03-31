from __future__ import annotations


def test_legacy_ops_routes_redirect_to_new_frontend(app_client) -> None:
    for path, expected in (
        ("/ops", "/app/ops"),
        ("/ops/overview", "/app/ops/overview"),
        ("/ops/freshness", "/app/ops/freshness"),
        ("/ops/schedules", "/app/ops/schedules"),
        ("/ops/executions", "/app/ops/executions"),
        ("/ops/catalog", "/app/ops/catalog"),
    ):
        response = app_client.get(path, follow_redirects=False)
        assert response.status_code in {307, 308}
        assert response.headers["location"] == expected


def test_frontend_app_entry_serves_react_shell(app_client) -> None:
    response = app_client.get("/app")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
