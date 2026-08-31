from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from orchestrator.defs.sensors.etf_basic_sensor import (
    evaluate_raw_etf_basic_sensor,
    evaluate_silver_etf_basic_sensor,
)
from tests.test_etf_basic_readiness import (
    FakeInstance,
    TestDuckDBResource,
    _ready_fixture,
)

NOW = datetime(2026, 8, 30, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _context(instance, lake_root):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        instance=instance,
        resources=SimpleNamespace(
            duckdb=TestDuckDBResource(),
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: lake_root,
            ),
        ),
    )


def test_basic_raw_missing_requests_one_run_and_silver_waits(tmp_path) -> None:  # type: ignore[no-untyped-def]
    lake_root = tmp_path / "data_lake"
    lake_root.mkdir()
    instance = FakeInstance(records_by_asset={}, check_records={})
    context = _context(instance, lake_root)

    raw_result = evaluate_raw_etf_basic_sensor(context, evaluated_at=NOW)
    silver_result = evaluate_silver_etf_basic_sensor(context, evaluated_at=NOW)

    assert len(raw_result.run_requests or []) == 1
    assert not silver_result.run_requests
    assert "等待当天 Raw" in str(silver_result.skip_reason)
    assert len(raw_result.cursor.encode("utf-8")) < 2048


def test_basic_ready_latest_versions_are_not_retriggered(tmp_path) -> None:  # type: ignore[no-untyped-def]
    instance, lake_root, _ = _ready_fixture(tmp_path)
    context = _context(instance, lake_root)

    raw_result = evaluate_raw_etf_basic_sensor(context, evaluated_at=NOW)
    silver_result = evaluate_silver_etf_basic_sensor(context, evaluated_at=NOW)

    assert not raw_result.run_requests
    assert not silver_result.run_requests
    assert "ready" in str(raw_result.skip_reason)
    assert "ready" in str(silver_result.skip_reason)
