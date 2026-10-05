"""More than twenty trade days bind every check to the correct materialization."""

from types import SimpleNamespace as NS

import pytest

from orchestrator.defs import stock_monthly_update_state as module


def record(sid, passed=True, status="SUCCEEDED", blocking=True, check_id=None):
    return NS(
        id=check_id or sid,
        status=NS(value=status),
        event=NS(
            dagster_event=NS(
                event_specific_data=NS(
                    target_materialization_data=NS(storage_id=sid),
                    blocking=blocking,
                    passed=passed,
                )
            )
        ),
    )


def instance(monkeypatch, mutation=None):
    days = tuple(f"2026-09-{n:02}" for n in range(1, 23))
    mats = [NS(storage_id=n, partition_key=day) for n, day in enumerate(days, 1)]
    monkeypatch.setattr(
        module, "weekly_event_binding", lambda *args: (NS(storage_id=100), True)
    )
    limits = []

    def history(key, *, limit):
        limits.append(limit)
        records = [record(n) for n in range(22, 0, -1)]
        if mutation == "missing":
            records = records[:20]
        if mutation == "failed":
            records[0] = record(22, False, "FAILED")
        if mutation == "wrong_target":
            records[0] = record(999)
        if mutation == "nonblocking":
            records[0] = record(22, blocking=False)
        if mutation == "planned":
            records[0] = record(22, status="PLANNED")
        return records

    obj = NS(
        fetch_materializations=lambda *args, **kwargs: NS(records=mats),
        event_log_storage=NS(get_asset_check_execution_history=history),
    )
    return obj, days, limits


def test_all_twenty_two_dates_verified(monkeypatch):
    obj, days, limits = instance(monkeypatch)
    result = module.monthly_upstream_bindings(obj, days)
    assert (
        result
        and len(result["daily_materialization_ids"]) == 22
        and len(result["checks"]) == 22
    )
    assert limits == [320] * 4


@pytest.mark.parametrize(
    "mutation", ["missing", "failed", "wrong_target", "nonblocking", "planned"]
)
def test_incomplete_or_unbound_history_blocks(monkeypatch, mutation):
    obj, days, _ = instance(monkeypatch, mutation)
    assert module.monthly_upstream_bindings(obj, days) is None
