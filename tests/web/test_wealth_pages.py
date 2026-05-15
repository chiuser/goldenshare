from __future__ import annotations


def test_root_redirects_to_wealth_login(app_client) -> None:
    response = app_client.get("/", follow_redirects=False)

    assert response.status_code in {307, 308}
    assert response.headers["location"] == "/wealth/login"


def test_wealth_routes_serve_independent_react_shell(app_client, monkeypatch, tmp_path) -> None:
    from src.app.web import app as web_app

    index_file = tmp_path / "index.html"
    index_file.write_text('<!doctype html><div id="root"></div><script src="/wealth/assets/app.js"></script>', encoding="utf-8")
    monkeypatch.setattr(web_app, "WEALTH_INDEX_FILE", index_file)

    response = app_client.get("/wealth/market/overview")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "/wealth/assets/app.js" in response.text
