from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.app.auth.dependencies import require_quote_access
from src.foundation.config.settings import get_settings


@pytest.mark.skipif(os.environ.get("WEALTH_REAL_DB_CHECK") != "1", reason="set WEALTH_REAL_DB_CHECK=1 to run real-db check")
def test_streak_ladder_real_db_check(monkeypatch) -> None:
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", ".env.web.local")
    get_settings.cache_clear()

    from src.app.web.app import app

    app.dependency_overrides[require_quote_access] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/wealth/market/streak-ladder",
                params={"market": "CN_A", "debug": 1},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["tradingDay"]["market"] == "CN_A"
        assert "streakLadderV5" in payload
        output_path = Path("reports/wealth/streak_ladder_real_db_sample.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
