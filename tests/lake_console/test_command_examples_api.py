from __future__ import annotations

from fastapi.testclient import TestClient

from lake_console.backend.app.main import create_app


def test_command_examples_api_returns_groups_and_examples():
    client = TestClient(create_app())

    response = client.get("/api/lake/command-examples")

    assert response.status_code == 200
    payload = response.json()
    groups = payload["groups"]
    assert groups

    items = [item for group in groups for item in group["items"]]
    item_by_key = {item["item_key"]: item for item in items}
    assert "daily" in item_by_key
    assert "lake_maintenance" in item_by_key
    assert item_by_key["daily"]["item_type"] == "dataset"
    assert item_by_key["lake_maintenance"]["item_type"] == "command_set"
    assert item_by_key["daily"]["examples"][0]["argv"][0] == "lake-console"
    assert item_by_key["daily"]["examples"][0]["command"].startswith("lake-console ")


def test_command_examples_api_filters_by_dataset_key():
    client = TestClient(create_app())

    response = client.get("/api/lake/command-examples", params={"dataset_key": "moneyflow"})

    assert response.status_code == 200
    payload = response.json()
    items = [item for group in payload["groups"] for item in group["items"]]
    assert [item["item_key"] for item in items] == ["moneyflow"]
    assert items[0]["examples"]


def test_command_examples_api_filters_by_group_key():
    client = TestClient(create_app())

    response = client.get("/api/lake/command-examples", params={"group_key": "maintenance"})

    assert response.status_code == 200
    payload = response.json()
    assert [group["group_key"] for group in payload["groups"]] == ["maintenance"]
    assert payload["groups"][0]["items"][0]["item_key"] == "lake_maintenance"
