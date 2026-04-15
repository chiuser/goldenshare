from __future__ import annotations

from datetime import date, datetime, timezone

from src.ops.models.ops.dataset_layer_snapshot_current import DatasetLayerSnapshotCurrent


def test_ops_layer_snapshot_requires_admin(app_client, user_factory) -> None:
    user_factory(username="user", password="secret", is_admin=False)
    login = app_client.post("/api/v1/auth/login", json={"username": "user", "password": "secret"})
    token = login.json()["token"]

    response = app_client.get("/api/v1/ops/layer-snapshots/latest", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_ops_layer_snapshot_history_and_latest_queries(
    app_client,
    user_factory,
    dataset_layer_snapshot_history_factory,
    db_session,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    dataset_layer_snapshot_history_factory(
        snapshot_date=date(2026, 4, 13),
        dataset_key="equity_daily",
        source_key="tushare",
        stage="serving",
        status="stale",
        rows_out=100,
        lag_seconds=7200,
        calculated_at=datetime(2026, 4, 13, 16, 0, tzinfo=timezone.utc),
    )
    db_session.add_all(
        [
            DatasetLayerSnapshotCurrent(
                dataset_key="equity_daily",
                source_key="tushare",
                stage="serving",
                status="healthy",
                rows_out=120,
                lag_seconds=120,
                calculated_at=datetime(2026, 4, 14, 16, 0, tzinfo=timezone.utc),
            ),
            DatasetLayerSnapshotCurrent(
                dataset_key="etf_daily",
                source_key="biying",
                stage="std",
                status="failed",
                rows_in=80,
                error_count=3,
                calculated_at=datetime(2026, 4, 14, 16, 5, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    history = app_client.get(
        "/api/v1/ops/layer-snapshots/history?dataset_key=equity_daily&stage=serving",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history.status_code == 200
    history_payload = history.json()
    assert history_payload["total"] == 1
    assert history_payload["items"][0]["snapshot_date"] == "2026-04-13"
    assert history_payload["items"][0]["status"] == "stale"

    latest = app_client.get(
        "/api/v1/ops/layer-snapshots/latest",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert latest.status_code == 200
    latest_payload = latest.json()
    assert latest_payload["total"] == 2
    latest_by_key = {(item["dataset_key"], item["source_key"], item["stage"]): item for item in latest_payload["items"]}
    assert latest_by_key[("equity_daily", "tushare", "serving")]["status"] == "healthy"
    assert latest_by_key[("etf_daily", "biying", "std")]["status"] == "failed"


def test_ops_layer_snapshot_latest_source_filter_includes_all_scope(
    app_client,
    user_factory,
    db_session,
) -> None:
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    token = login.json()["token"]

    db_session.add_all(
        [
            DatasetLayerSnapshotCurrent(
                dataset_key="stock_basic",
                source_key="__all__",
                stage="raw",
                status="healthy",
                rows_out=2000,
                calculated_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            ),
            DatasetLayerSnapshotCurrent(
                dataset_key="etf_daily",
                source_key="tushare",
                stage="raw",
                status="healthy",
                rows_out=500,
                calculated_at=datetime(2026, 4, 15, 10, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    latest = app_client.get(
        "/api/v1/ops/layer-snapshots/latest?source_key=biying&stage=raw",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert latest.status_code == 200
    payload = latest.json()
    keys = {(item["dataset_key"], item["source_key"], item["stage"]) for item in payload["items"]}
    assert ("stock_basic", "__all__", "raw") in keys
    assert ("etf_daily", "tushare", "raw") not in keys
