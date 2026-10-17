"""C01/C02/C07: literal contracts from existing seven source definitions, not planner output."""

import copy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from orchestrator.moneyflow_continuation.contract import ContinuationError, digest
from orchestrator.moneyflow_continuation.plan import (
    make_plan,
    request_for,
    validate_plan,
    validate_scope,
)

AT = datetime(2026, 10, 17, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
DAY = "2026-10-08"
NAMES = (
    "moneyflow_mkt_dc",
    "moneyflow_ind_ths",
    "moneyflow_cnt_ths",
    "moneyflow_ind_dc",
    "moneyflow_dc",
    "moneyflow_ths",
    "moneyflow",
)


def plan_for(names=("moneyflow_mkt_dc",), days=(DAY,), at=AT, parent=None):
    entries = [{"dataset": n, "trade_date": d} for n in names for d in days]
    return make_plan(
        entries,
        set(days),
        at,
        {"path": "/private/tmp/proof.json", "sha256": "a" * 64},
        {},
        [],
        parent,
        digest(parent) if parent else None,
    )


def test_seven_literal_contracts_and_whole_jobs():
    plan = plan_for(NAMES)
    assert [u["dataset"] for u in plan["units"]] == list(NAMES)
    assert [len(u["raw"]["schema"]) for u in plan["units"]] == [
        15,
        12,
        12,
        18,
        15,
        13,
        20,
    ]
    for unit in plan["units"]:
        raw, silver = unit["raw"], unit["silver"]
        assert [c for c in raw["schema"] if c[0] == "trade_date"] == [
            ["trade_date", "VARCHAR"]
        ]
        assert [c for c in silver["schema"] if c[0] == "trade_date"] == [
            ["trade_date", "DATE"]
        ]
        for layer in ("raw", "silver"):
            body = request_for(unit, layer, "2026-10-17", "b" * 64)
            params = body["variables"]["executionParams"]
            assert set(params) == {"selector", "runConfigData", "executionMetadata"}
            assert params["runConfigData"] == {}
            assert params["selector"]["jobName"] == unit[layer]["job"]
            assert params["selector"]["repositoryLocationName"] == "orchestrator"
    raw = request_for(plan["units"][0], "raw", "2026-10-17")
    tags = {
        t["key"]: t["value"]
        for t in raw["variables"]["executionParams"]["executionMetadata"]["tags"]
    }
    assert tags == {
        "dagster/partition": DAY,
        "dagster/partition_set": "raw_tushare_moneyflow_mkt_dc_update_job_partition_set",
        "dagster/run_key": "raw_tushare_moneyflow_mkt_dc:2026-10-08:2026-10-17:1",
    }
    silver = request_for(plan["units"][0], "silver", "2026-10-17", "b" * 64)
    assert (
        next(
            t["value"]
            for t in silver["variables"]["executionParams"]["executionMetadata"]["tags"]
            if t["key"] == "dagster/run_key"
        )
        == "silver_moneyflow_mkt_dc:2026-10-08:" + "b" * 64
    )


@pytest.mark.parametrize(
    "entries,opened,at,reason",
    [
        ([], set(), AT, "scope_size"),
        ([{"dataset": "other", "trade_date": DAY}], {DAY}, AT, "unknown_dataset"),
        (
            [{"dataset": NAMES[0], "trade_date": "2026-09-30"}],
            {"2026-09-30"},
            AT,
            "history_out_of_scope",
        ),
        ([{"dataset": NAMES[0], "trade_date": DAY}], set(), AT, "not_sse_open"),
        (
            [{"dataset": NAMES[0], "trade_date": "2026-10-17"}],
            {"2026-10-17"},
            AT,
            "date_not_mature",
        ),
        (
            [{"dataset": NAMES[0], "trade_date": "2026-10-18"}],
            {"2026-10-18"},
            AT,
            "date_not_mature",
        ),
        (
            [{"dataset": NAMES[0], "trade_date": DAY, "job": "bad"}],
            {DAY},
            AT,
            "scope_fields",
        ),
        ([{"dataset": NAMES[0], "trade_date": DAY}] * 2, {DAY}, AT, "duplicate_unit"),
        (
            [{"dataset": NAMES[0], "trade_date": "20261008"}],
            {"20261008"},
            AT,
            "history_out_of_scope",
        ),
    ],
)
def test_invalid_scope(entries, opened, at, reason):
    with pytest.raises(ContinuationError, match=reason):
        validate_scope(entries, opened, at)


def test_child_preserves_root_but_cannot_expand():
    parent = plan_for(days=(DAY, "2026-10-09"))
    child = plan_for(days=("2026-10-09",), at=AT + timedelta(days=1), parent=parent)
    assert child["root_scope_digest"] == parent["root_scope_digest"]
    assert child["parent_sha256"] == digest(parent)
    with pytest.raises(ContinuationError, match="parent_scope_expanded"):
        plan_for(days=("2026-10-12",), parent=parent)


@pytest.mark.parametrize("field", ["schema", "job", "target", "asset", "check"])
def test_tampered_contract_refused(field):
    plan = copy.deepcopy(plan_for())
    plan["units"][0]["raw"][field] = "fake"
    with pytest.raises(ContinuationError, match="plan_contract"):
        validate_plan(plan)


def test_49_units_bounded_and_sorted():
    days = tuple(f"2026-10-{i:02d}" for i in range(8, 15))
    plan = plan_for(NAMES, days)
    assert len(plan["units"]) == 49
    with pytest.raises(ContinuationError, match="scope_size"):
        plan_for(NAMES, days + ("2026-10-15",))


def test_silver_placeholder_never_requested():
    with pytest.raises(ContinuationError, match="raw_hash_required"):
        request_for(plan_for()["units"][0], "silver", "2026-10-17")
