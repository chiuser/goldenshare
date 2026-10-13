"""Real isolated baselines, candidate retention, and all six Raw job consumers."""

import importlib
import json

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.moneyflow_row_count import (
    moneyflow_row_count_baseline,
    moneyflow_row_count_decision,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

from . import test_moneyflow_dc_definitions as support
from .moneyflow_baseline_support import seed_moneyflow_baseline

env = support.env


def rows(n, day=support.DAY):
    return [support.row(f"{i:06d}.SZ", day=day) for i in range(n)]


def baseline(env, day="2026-10-13"):
    with moneyflow_candidate_connection(env.staging) as db:
        return moneyflow_row_count_baseline(
            instance=env.instance,
            connection=db,
            lake_root=env.lake,
            dataset="moneyflow_dc",
            trade_date=day,
        )


def test_verified_fallback_and_strict_prior_date(env):
    b = baseline(env)
    assert b["mode"] == "bootstrap_cutoff" and [r["date"] for r in b["references"]] == [
        "2026-09-30"
    ]
    with pytest.raises(MoneyflowContractError, match="row_count_baseline_missing"):
        baseline(env, "2026-09-30")


def test_previous_five_median_and_future_exclusion(env):
    for day, n in [
        ("2026-10-01", 2),
        ("2026-10-02", 10),
        ("2026-10-05", 5),
        ("2026-10-06", 9),
        ("2026-10-07", 3),
        ("2026-10-14", 100),
    ]:
        seed_moneyflow_baseline(
            instance=env.instance,
            lake=env.lake,
            staging=env.staging,
            dataset="moneyflow_dc",
            rows=rows(n),
            day=day,
        )
    b = baseline(env)
    assert b["mode"] == "previous_five" and b["baseline_scope_counts"] == {"all": 5}
    assert [r["date"] for r in b["references"]] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
    ]
    assert moneyflow_row_count_decision(b, {"all": 4})["passed"]
    assert not moneyflow_row_count_decision(b, {"all": 3})["passed"]
    assert moneyflow_row_count_decision(b, {"all": 100})["passed"]


def test_damaged_baseline_fails_closed(env):
    target = raw_moneyflow_path(env.lake, "moneyflow_dc", "2026-09-30")
    target.write_bytes(b"damaged")
    with pytest.raises(
        MoneyflowContractError, match="row_count_baseline_not_ready:file_changed"
    ):
        baseline(env)


def test_missing_baseline_no_file_only_success(env):
    with (
        dg.DagsterInstance.ephemeral() as instance,
        moneyflow_candidate_connection(env.staging) as db,
        pytest.raises(
            MoneyflowContractError,
            match="row_count_baseline_not_ready:file_without_materialization",
        ),
    ):
        moneyflow_row_count_baseline(
            instance=instance,
            connection=db,
            lake_root=env.lake,
            dataset="moneyflow_dc",
            trade_date=support.DAY,
        )


@pytest.mark.parametrize(
    "dataset",
    (
        "moneyflow_ind_ths",
        "moneyflow_cnt_ths",
        "moneyflow_ind_dc",
        "moneyflow_dc",
        "moneyflow_ths",
        "moneyflow",
    ),
)
def test_all_six_jobs_stable_drop_retains_candidates_without_success(
    tmp_path, monkeypatch, dataset
):
    module = importlib.import_module("tests.test_" + dataset + "_definitions")
    with_context = module.env.__wrapped__(tmp_path, monkeypatch)
    e = next(with_context)
    try:
        base = module.sample() if hasattr(module, "sample") else [module.row()]
        if dataset == "moneyflow_ind_dc":
            reference = [
                dict(r, name=r["name"] + str(i)) for r in base for i in range(5)
            ]
            target_rows = base
        else:
            reference = [dict(base[0], ts_code=f"{i:06d}.SZ") for i in range(5)]
            target_rows = [base[0]]
        seed_moneyflow_baseline(
            instance=e.instance,
            lake=e.lake,
            staging=e.staging,
            dataset=dataset,
            rows=reference,
        )
        if hasattr(module, "set_rows"):
            module.set_rows(e, target_rows)
        else:
            e.source.responses = iter([target_rows, list(reversed(target_rows))])
        result = module.run(
            e, "raw_tushare_" + dataset + "_update_job", raise_on_error=False
        )
        assert not result.success and not result.get_asset_materialization_events()
        assert not raw_moneyflow_path(e.lake, dataset, module.DAY).exists()
        receipts = list(
            e.staging.glob(
                "moneyflow/*/" + dataset + "/" + module.DAY + "/receipt.json"
            )
        )
        assert len(receipts) == 1
        receipt = json.loads(receipts[0].read_text())
        assert receipt["row_count_guard"]["passed"] is False
        assert receipt["row_count_guard"]["reason_code"] == "row_count_drop"
        assert (receipts[0].parent / "raw.parquet").is_file()
        failures = [
            event
            for event in result.all_events
            if event.event_type == dg.DagsterEventType.STEP_FAILURE
        ]
        metadata = failures[0].step_failure_data.user_failure_data.metadata
        assert metadata["goldenshare/retryable"].value is False
    finally:
        with_context.close()


def test_per_class_drop_even_when_total_grows():
    b = {
        "mode": "previous_five",
        "references": [],
        "baseline_scope_counts": {"行业": 5, "概念": 5, "地域": 5},
    }
    result = moneyflow_row_count_decision(b, {"行业": 3, "概念": 5, "地域": 100})
    assert result["declined_scopes"] == ["行业"] and not result["passed"]
    assert moneyflow_row_count_decision(b, {"行业": 4, "概念": 4, "地域": 4})["passed"]


def test_wrong_scope_and_zero_rejected():
    b = {"baseline_scope_counts": {"all": 5}}
    for counts in ({"bad": 5}, {"all": 0}, {"all": True}):
        with pytest.raises(MoneyflowContractError, match="row_count_candidate_scopes"):
            moneyflow_row_count_decision(b, counts)


def test_stale_baseline_check_is_not_skipped(env):
    from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
    from orchestrator.defs.run_contracts.moneyflow_automation import (
        STOCK_DC_MONEYFLOW_AUTOMATION,
    )

    path = raw_moneyflow_path(env.lake, "moneyflow_dc", "2026-09-30")
    env.instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=STOCK_DC_MONEYFLOW_AUTOMATION.raw_asset,
            partition="2026-09-30",
            metadata={
                "goldenshare/file_sha256": candidate_file_hash(path),
                "dagster/row_count": 1,
            },
        )
    )
    with pytest.raises(
        MoneyflowContractError,
        match="row_count_baseline_not_ready:check_failed_or_stale",
    ):
        baseline(env)


def test_baseline_file_budget_and_date_fact_budget(env, monkeypatch):
    from datetime import date, timedelta

    from orchestrator.defs.run_contracts.moneyflow import (
        MONEYFLOW_DC_READINESS_FILE_MAX_BYTES,
    )

    path = raw_moneyflow_path(env.lake, "moneyflow_dc", "2026-09-30")
    with path.open("r+b") as stream:
        stream.truncate(MONEYFLOW_DC_READINESS_FILE_MAX_BYTES + 1)
    with pytest.raises(
        MoneyflowContractError, match="row_count_baseline_not_ready:file_hash_budget"
    ):
        baseline(env)
    dates = {(date(1970, 1, 1) + timedelta(days=i)).isoformat() for i in range(20001)}
    monkeypatch.setattr(env.instance, "get_materialized_partitions", lambda _: dates)
    with pytest.raises(MoneyflowContractError, match="row_count_baseline_date_budget"):
        baseline(env)


def test_latest_five_bad_reference_never_uses_older_or_fallback(env):
    for day in (
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
        "2026-10-08",
    ):
        seed_moneyflow_baseline(
            instance=env.instance,
            lake=env.lake,
            staging=env.staging,
            dataset="moneyflow_dc",
            rows=rows(5),
            day=day,
        )
    raw_moneyflow_path(env.lake, "moneyflow_dc", "2026-10-08").write_bytes(
        b"corrupt newest"
    )
    with pytest.raises(
        MoneyflowContractError, match="row_count_baseline_not_ready:file_changed"
    ):
        baseline(env)


def test_five_files_twenty_queries_and_cancellation(env):
    for day in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"):
        seed_moneyflow_baseline(
            instance=env.instance,
            lake=env.lake,
            staging=env.staging,
            dataset="moneyflow_dc",
            rows=rows(5),
            day=day,
        )
    with moneyflow_candidate_connection(env.staging) as db:
        queries = []

        class Connection:
            def execute(self, *args):
                queries.append(args)
                return db.execute(*args)

        def cancel_after_three_sql():
            if len(queries) == 3:
                raise MoneyflowContractError("user_cancel")

        with pytest.raises(MoneyflowContractError, match="user_cancel"):
            moneyflow_row_count_baseline(
                instance=env.instance,
                connection=Connection(),
                lake_root=env.lake,
                dataset="moneyflow_dc",
                trade_date="2026-10-13",
                check=cancel_after_three_sql,
            )
        assert len(queries) == 3
        queries.clear()
        b = moneyflow_row_count_baseline(
            instance=env.instance,
            connection=Connection(),
            lake_root=env.lake,
            dataset="moneyflow_dc",
            trade_date="2026-10-13",
        )
        assert len(b["references"]) == 5 and len(queries) == 20
        assert len({args[1][-1] for args in queries}) == 5


@pytest.mark.parametrize("n", (4, 6))
def test_exact_twenty_percent_and_growth_publish_guard_evidence(env, n):
    seed_moneyflow_baseline(
        instance=env.instance,
        lake=env.lake,
        staging=env.staging,
        dataset="moneyflow_dc",
        rows=rows(5),
    )
    support.set_rows(env, rows(n))
    result = support.run(env, "raw_tushare_moneyflow_dc_update_job")
    assert result.success
    guard = (
        result.get_asset_materialization_events()[0]
        .event_specific_data.materialization.metadata["goldenshare/row_count_guard"]
        .value
    )
    assert (
        guard["passed"]
        and guard["baseline_scope_counts"] == {"all": 5}
        and guard["candidate_scope_counts"] == {"all": n}
    )


def test_decline_preserves_existing_target_and_rechecks_receipt_on_resume(env):
    from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
    from orchestrator.defs.io.moneyflow_daily_update import update_daily_moneyflow_raw

    assert support.run(env, "raw_tushare_moneyflow_dc_update_job").success
    target = raw_moneyflow_path(env.lake, "moneyflow_dc", support.DAY)
    digest = candidate_file_hash(target)
    seed_moneyflow_baseline(
        instance=env.instance,
        lake=env.lake,
        staging=env.staging,
        dataset="moneyflow_dc",
        rows=rows(10),
    )
    support.set_rows(env, rows(1))
    kwargs = {
        "instance": env.instance,
        "dataset": "moneyflow_dc",
        "tushare": env.source,
        "lake_root": env.lake,
        "staging_root": env.staging,
        "operation_id": "drop-resume",
        "trade_date": support.DAY,
    }
    with pytest.raises(MoneyflowContractError, match="row_count_drop:all"):
        update_daily_moneyflow_raw(**kwargs)
    receipt = (
        env.staging
        / "moneyflow/drop-resume/moneyflow_dc"
        / support.DAY
        / "receipt.json"
    )
    data = json.loads(receipt.read_text())
    data["row_count_guard"] = {"passed": True}
    receipt.write_text(json.dumps(data))
    request_count = len(env.source.calls)
    with pytest.raises(MoneyflowContractError, match="row_count_drop:all"):
        update_daily_moneyflow_raw(**kwargs)
    assert (
        len(env.source.calls) == request_count and candidate_file_hash(target) == digest
    )
    assert json.loads(receipt.read_text())["row_count_guard"]["passed"] is False
    assert (receipt.parent / "raw.parquet").is_file() and not (
        receipt.parent / "promotion-raw.json"
    ).exists()


@pytest.mark.parametrize("recorded", (None, True, 2, 1.0))
def test_native_count_must_match_physical_integer(env, recorded):
    seed_moneyflow_baseline(
        instance=env.instance,
        lake=env.lake,
        staging=env.staging,
        dataset="moneyflow_dc",
        rows=rows(1),
        metadata={"dagster/row_count": recorded},
    )
    with pytest.raises(MoneyflowContractError, match="row_count_baseline_count"):
        baseline(env)


def test_dc_native_scope_counts_must_match_each_physical_class(tmp_path, monkeypatch):
    from . import test_moneyflow_ind_dc_definitions as board

    with_context = board.env.__wrapped__(tmp_path, monkeypatch)
    e = next(with_context)
    try:
        seed_moneyflow_baseline(
            instance=e.instance,
            lake=e.lake,
            staging=e.staging,
            dataset="moneyflow_ind_dc",
            rows=board.sample(),
            metadata={
                "goldenshare/scope_row_counts": {"行业": 2, "概念": 1, "地域": 1}
            },
        )
        with (
            moneyflow_candidate_connection(e.staging) as db,
            pytest.raises(MoneyflowContractError, match="row_count_baseline_scopes"),
        ):
            moneyflow_row_count_baseline(
                instance=e.instance,
                connection=db,
                lake_root=e.lake,
                dataset="moneyflow_ind_dc",
                trade_date=board.DAY,
            )
    finally:
        with_context.close()
