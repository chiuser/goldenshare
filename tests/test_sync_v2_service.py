from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.service import SyncV2Service


def _build_service(dataset_key: str) -> SyncV2Service:
    service = SyncV2Service(
        session=SimpleNamespace(),
        contract=get_sync_v2_contract(dataset_key),
        strict_contract=True,
    )
    service.execution_context = SimpleNamespace(is_cancel_requested=lambda execution_id: False)
    return service


def test_sync_v2_service_range_rebuild_accepts_run_profile_without_unknown_param_error() -> None:
    service = _build_service("margin")

    rows_fetched, rows_written, result_date, message = service.execute(
        run_type="FULL",
        execution_id=365,
        run_profile="range_rebuild",
        trigger_source="manual",
        source_key="tushare",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 4, 24),
        exchange_id=["SSE", "SZSE"],
        _plan_units=(),
    )

    assert rows_fetched == 0
    assert rows_written == 0
    assert result_date == date(2026, 4, 24)
    assert message == "units=0 done=0 failed=0"


def test_sync_v2_service_snapshot_refresh_accepts_run_profile_without_unknown_param_error() -> None:
    service = _build_service("stock_basic")

    rows_fetched, rows_written, result_date, message = service.execute(
        run_type="FULL",
        execution_id=366,
        run_profile="snapshot_refresh",
        trigger_source="manual",
        source_key="tushare",
        list_status=["L"],
        _plan_units=(),
    )

    assert rows_fetched == 0
    assert rows_written == 0
    assert result_date is None
    assert message == "units=0 done=0 failed=0"


def test_sync_v2_service_unknown_params_still_strict_without_leaking_run_profile() -> None:
    service = _build_service("margin")

    with pytest.raises(RuntimeError) as exc_info:
        service.execute(
            run_type="FULL",
            execution_id=367,
            run_profile="range_rebuild",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 4, 24),
            exchange_id=["SSE"],
            bad_flag="X",
            _plan_units=(),
        )

    message = str(exc_info.value)
    assert "[unknown_params]" in message
    assert "bad_flag" in message
    assert "run_profile" not in message
