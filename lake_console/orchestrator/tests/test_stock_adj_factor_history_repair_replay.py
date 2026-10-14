"""Seven-frequency replay and complete monthly blocking evidence in isolation."""

import json
from itertools import pairwise
from pathlib import Path

import pytest

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    RepairBudget,
    file_identity,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_indicators import (
    audit_indicator_batch,
    build_indicator_target_candidate,
    indicator_replay_tasks,
    read_indicator_task,
    replay_indicator_task,
    seal_indicator_batch,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import read_parquet

from . import test_stock_adj_factor_history_repair_execution as execution_tests
from . import test_stock_adj_factor_history_repair_indicators as samples

scope = samples.scope
repair_endpoints = samples.repair_endpoints
freeze_case = samples.freeze_case
price_plan = samples.price_plan
indicator_plan = samples.indicator_plan


def test_all_seven_frequencies_share_literals_and_carry_across_years(
    indicator_plan, tmp_path
):
    plan = indicator_plan
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        for freq in (1, 5, 15, 30, 60, 90, 120):
            task = samples._task(plan, f"gold_stk_mins_qfq_macd_kdj_{freq}m")
            samples._prepare_price(c, plan, task)
            replay_indicator_task(c, plan, task)
            fragments = read_indicator_task(plan, task)
            output = next(
                Path(f["outputs"]["result"]["path"])
                for f in fragments
                if "2026-06-29" in f["dates"]
            )
            row = c.execute(
                "SELECT macd_dif_qfq,macd_dea_qfq,macd_qfq,kdj_k_qfq,kdj_d_qfq,kdj_qfq FROM "
                + read_parquet(output, hive_partitioning=False)
                + " WHERE trade_date=DATE '2026-06-29' ORDER BY trade_time LIMIT 1"
            ).fetchone()
            assert row == pytest.approx(
                (
                    0.19943019943019943,
                    0.039886039886039886,
                    0.3190883190883191,
                    60.0,
                    53.33333333333333,
                    73.33333333333333,
                )
            )
            # Carry rows keep the last actual bar and remain one state per expected day.
            state = Path(fragments[0]["outputs"]["state"]["path"])
            values = c.execute(
                "SELECT trade_date,last_trade_time FROM "
                + read_parquet(state, hive_partitioning=False)
                + " ORDER BY trade_date"
            ).fetchall()
            assert all(t.date() <= d for d, t in values)
            assert len(values) == len(fragments[0]["dates"])
        # An earlier fixed stock crosses 2023 -> 2024 -> 2025 -> 2026 using candidate state.
        task = samples._task(plan, "gold_stk_mins_qfq_macd_kdj_120m", "600016.SH")
        replay_indicator_task(c, plan, task)
        fragments = read_indicator_task(plan, task)
        assert {d[:4] for f in fragments for d in f["dates"]} == {
            "2023",
            "2024",
            "2025",
            "2026",
        }
        for first, second in pairwise(fragments):
            assert second["binding"]["previous_record_hash"] == first["record_hash"]
        replay_indicator_task(c, plan, task, audit=True)


def test_real_indicator_child_reports_only_sealed_files_and_sample_status(
    indicator_plan, tmp_path
):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_execution as execution,
    )

    plan = indicator_plan
    task = samples._task(plan)
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        samples._prepare_price(c, plan, task)
    target = paths.gold_stk_mins_qfq_macd_kdj_path(
        Path(plan["lake_root"]), 1, "688689.SH", "2026"
    )
    original = file_identity(target)
    updates = []
    args = {
        "plan_path": Path(plan["run_root"]) / "plan.json",
        "expected_hash": plan["plan_hash"],
        "phase": "indicator",
        "selected_targets": [str(target)],
        "worker_command": execution_tests.launcher(plan, tmp_path),
        "progress": updates.append,
    }
    result = execution.execute_repair_candidates(**args)
    assert (
        result["completed"] == 1 and result["sample"] and not result["all_chain_ready"]
    )
    assert result["replay_completed"] == result["replay_total"] == 1
    assert result["status"] == "INDICATOR_CANDIDATES_VERIFIED"
    assert all(u["completed"] in (0, 1) for u in updates)
    assert result["peak_rss_bytes"] < RepairBudget().max_rss
    candidate = (
        Path(plan["run_root"])
        / "candidates"
        / target.relative_to(Path(plan["lake_root"]))
    )
    identity = file_identity(candidate)
    audited = execution.execute_repair_candidates(**args, audit=True)
    assert audited["audited"] and file_identity(candidate) == identity
    assert file_identity(target) == original
    print(
        json.dumps(
            {
                "isolated_R2_child": True,
                "completed": 1,
                "replay_tasks": 1,
                "peak_rss_bytes": max(
                    result["peak_rss_bytes"], audited["peak_rss_bytes"]
                ),
                "elapsed_seconds": result["elapsed_seconds"],
                "candidate_bytes": result["candidate_bytes"],
                "spill_bytes": result["spill_bytes"],
                "all_chain_ready": result["all_chain_ready"],
            }
        )
    )


def test_shared_daily_batch_runs_original_rules_and_detects_unapproved_stock_damage(
    indicator_plan, tmp_path
):
    from orchestrator.defs.duckdb_sql import copy_query_to_parquet

    plan = indicator_plan
    root = Path(plan["lake_root"])
    day = "2021-01-27"
    unit = samples.prices.unit_for(plan, "gold_stock_daily_trend_channel")
    task = samples._task(plan, unit["asset_key"])
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        samples._prepare_price(c, plan, task)
        replay_indicator_task(c, plan, task)
        target = paths.gold_stock_daily_trend_channel_path(root, day)
        record = build_indicator_target_candidate(c, plan, unit, target)
        proof = audit_indicator_batch(
            c, plan, unit, [str(target)], pending={str(target): record}
        )
        assert proof["checked_dates"] == 1
        # An unrelated retained stock is included in the complete file blocking check.
        candidate = (
            target
            if record["no_op"]
            else Path(plan["run_root"]) / record["candidate_relative_path"]
        )
        broken = Path(plan["run_root"]) / "candidates" / target.relative_to(root)
        broken.parent.mkdir(parents=True, exist_ok=True)
        c.execute(
            copy_query_to_parquet(
                "SELECT * REPLACE('INVALID' AS short_state) FROM "
                + read_parquet(candidate, hive_partitioning=False)
                + " WHERE ts_code='000001.SZ' UNION ALL SELECT * FROM "
                + read_parquet(candidate, hive_partitioning=False)
                + " WHERE ts_code!='000001.SZ'",
                broken,
            )
        )
        corrupt = dict(
            record,
            no_op=False,
            candidate_relative_path=broken.relative_to(
                Path(plan["run_root"])
            ).as_posix(),
            candidate_sha256=file_identity(broken).sha256,
        )
        with pytest.raises(FactorRepairError, match="trend_result_check_failed"):
            audit_indicator_batch(
                c, plan, unit, [str(target)], pending={str(target): corrupt}
            )
        broken.unlink()
        seal_indicator_batch(plan, {str(target): record}, proof)
        assert record["validated"]


def test_daily_state_and_nineturn_batches_share_complete_blocking_semantics(
    indicator_plan, tmp_path
):
    plan = indicator_plan
    root = Path(plan["lake_root"])
    day = "2021-01-27"
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        samples._prepare_price(
            c, plan, samples._task(plan, "gold_stock_daily_trend_channel")
        )
        for asset, helper in (
            (
                "gold_stock_daily_trend_channel_state",
                paths.gold_stock_daily_trend_channel_state_path,
            ),
            ("gold_stock_daily_qfq_nineturn", paths.gold_stock_daily_qfq_nineturn_path),
        ):
            task = samples._task(plan, asset.removesuffix("_state"))
            replay_indicator_task(c, plan, task)
            target = helper(root, day)
            before = file_identity(target)
            unit = samples.prices.unit_for(plan, asset)
            record = build_indicator_target_candidate(c, plan, unit, target)
            proof = audit_indicator_batch(
                c, plan, unit, [str(target)], pending={str(target): record}
            )
            seal_indicator_batch(plan, {str(target): record}, proof)
            assert record["validated"] and file_identity(target) == before
            build_indicator_target_candidate(c, plan, unit, target, audit=True)


def test_minute_nineturn_and_macd_state_check_complete_files(indicator_plan, tmp_path):
    plan = indicator_plan
    root = Path(plan["lake_root"])
    day = "2026-06-29"
    freq = 120
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        for asset in (
            f"gold_stk_mins_qfq_nineturn_{freq}m",
            f"gold_stk_mins_qfq_macd_kdj_state_{freq}m",
        ):
            result_asset = asset.replace("_state_", "_")
            tasks = [
                t
                for t in indicator_replay_tasks(plan)
                if t["asset_key"] == result_asset
                and day in (t["state_profile"] or t["profile"])["target_dates"]
            ]
            samples._prepare_price(c, plan, tasks[0])
            for task in tasks:
                replay_indicator_task(c, plan, task)
            unit = samples.prices.unit_for(plan, asset)
            target = (
                paths.gold_stk_mins_qfq_nineturn_path(root, freq, day)
                if "nineturn" in asset
                else paths.gold_stk_mins_qfq_macd_kdj_state_path(root, freq, day)
            )
            if "_state_" in asset:
                result_unit = samples.prices.unit_for(plan, result_asset)
                candidates = {
                    str(
                        paths.gold_stk_mins_qfq_macd_kdj_path(
                            root, freq, t["profile"]["ts_code"], "2026"
                        )
                    )
                    for t in tasks
                }
                pending = {
                    p: build_indicator_target_candidate(c, plan, result_unit, Path(p))
                    for p in sorted(candidates)
                }
                proof = audit_indicator_batch(
                    c, plan, result_unit, sorted(candidates), pending=pending
                )
                seal_indicator_batch(plan, pending, proof)
            record = build_indicator_target_candidate(c, plan, unit, target)
            proof = audit_indicator_batch(
                c, plan, unit, [str(target)], pending={str(target): record}
            )
            seal_indicator_batch(plan, {str(target): record}, proof)
            assert record["validated"]
            build_indicator_target_candidate(c, plan, unit, target, audit=True)


def test_indicator_cancel_preserves_complete_segments_and_reuses_them(
    indicator_plan, tmp_path, monkeypatch
):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_indicators as replay,
    )

    plan = indicator_plan
    task = samples._task(plan, "gold_stk_mins_qfq_nineturn_120m")
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        samples._prepare_price(c, plan, task)
        monkeypatch.setattr(
            replay,
            "plan_repair_calculation_windows",
            lambda rows, **kw: tuple(
                tuple(d for d, n in rows[i : i + 2]) for i in range(0, len(rows), 2)
            ),
        )
        canceled = []

        def progress(data):
            if data["replay_completed_rows"] > 0:
                canceled.append(True)

        with pytest.raises(FactorRepairError, match="canceled"):
            replay_indicator_task(
                c, plan, task, progress=progress, cancel=lambda: bool(canceled)
            )
        directory = Path(plan["run_root"]) / "inputs/indicator_replay" / task["task_id"]
        owned = {str(p): file_identity(p) for p in directory.glob("*")}
        assert (
            directory.joinpath("segment-1.json").exists()
            and not directory.joinpath("task.json").exists()
        )
        replay_indicator_task(c, plan, task)
        assert all(file_identity(Path(p)) == identity for p, identity in owned.items())
        replay_indicator_task(c, plan, task, audit=True)


def test_nineturn_inspection_counts_stop_at_each_stock_endpoint(tmp_path):
    import duckdb

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli import (
        _history_input_counts,
    )
    from orchestrator.defs.duckdb_sql import copy_query_to_parquet

    source = tmp_path / "source.parquet"
    with duckdb.connect() as c:
        c.execute(
            copy_query_to_parquet(
                "SELECT code::VARCHAR ts_code,day::DATE trade_date,time::TIMESTAMP trade_time FROM (VALUES ('688689.SH','2026-06-29','2026-06-29 09:30:00'),('688689.SH','2026-06-29','2026-06-29 15:00:00'),('688689.SH','2026-06-30','2026-06-30 09:30:00'),('001331.SZ','2026-06-30','2026-06-30 09:30:00')) rows(code,day,time)",
                source,
            )
        )
        daily = [
            {"ts_code": "688689.SH", "end_time": "2026-06-29"},
            {"ts_code": "001331.SZ", "end_time": "2026-06-30"},
        ]
        minute = [
            {"ts_code": "688689.SH", "end_time": "2026-06-29 09:30:00"},
            {"ts_code": "001331.SZ", "end_time": "2026-06-30 15:00:00"},
        ]
        stats = {}
        assert _history_input_counts(
            c, daily, [source], freq=None, input_stats=stats
        ) == {"688689.SH": 2, "001331.SZ": 1}
        assert _history_input_counts(
            c, minute, [source], freq=120, input_stats=stats
        ) == {"688689.SH": 1, "001331.SZ": 1}
        stats[str(source)] = (0, 0)
        with pytest.raises(FactorRepairError, match="input_drift"):
            _history_input_counts(c, minute, [source], freq=120, input_stats=stats)


def test_result_and_state_tails_are_independent_without_new_state_coverage(
    indicator_plan, tmp_path
):
    from copy import deepcopy
    from uuid import uuid4

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        AssetRepairEndpoint,
        FactorRepairScope,
        freeze_stock_factor_repair,
        plan_repair_calculation_windows,
    )
    from orchestrator.defs.duckdb_sql import copy_query_to_parquet

    old = indicator_plan
    units = deepcopy(old["units"])
    endpoints = deepcopy(old["endpoints"])
    root = Path(old["lake_root"])
    asset = "gold_stk_mins_qfq_macd_kdj_state_1m"
    unit = next(u for u in units if u["asset_key"] == asset)
    p = next(p for p in unit["calculation_windows"] if p["ts_code"] == "688689.SH")
    cut = p["target_dates"][-2]
    p["trade_date_rows"] = [r for r in p["trade_date_rows"] if r[0] <= cut]
    p["end_time"] = cut
    p["observed_dates"] = p["target_dates"] = [d for d, n in p["trade_date_rows"]]
    p["windows"] = [
        list(w)
        for w in plan_repair_calculation_windows(p["trade_date_rows"], max_rows=99992)
    ]
    e = next(
        e for e in endpoints if e["asset_key"] == asset and e["ts_code"] == "688689.SH"
    )
    e.update(
        end_time=cut,
        expected_dates=p["target_dates"],
        calculation_rows=len(p["target_dates"]),
    )
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        for name in unit["target_paths"]:
            target = Path(name)
            if target.parent.name.removeprefix("trade_date=") <= cut:
                continue
            c.execute(
                "CREATE OR REPLACE TEMP TABLE initial_state AS SELECT * FROM "
                + read_parquet(target, hive_partitioning=False)
            )
            c.execute(
                copy_query_to_parquet(
                    "SELECT * FROM initial_state WHERE ts_code!='688689.SH'", target
                )
            )
    plan = freeze_stock_factor_repair(
        lake_root=root,
        run_root=Path(old["run_root"]).parent / f"run_id={uuid4()}",
        scopes=[
            FactorRepairScope(
                **{**s, "factor_ranges": tuple(tuple(r) for r in s["factor_ranges"])}
            )
            for s in old["scopes"]
        ],
        source_rows=old["source_rows"],
        anchors=old["anchors"],
        units=units,
        endpoints=[
            AssetRepairEndpoint(
                **{
                    k: tuple(v) if k in ("expected_dates", "context_times") else v
                    for k, v in e.items()
                }
            )
            for e in endpoints
        ],
        target_paths=[p for u in units for p in u["target_paths"]],
        input_stats=[
            (
                i["path"],
                Path(i["path"]).stat().st_size,
                Path(i["path"]).stat().st_mtime_ns,
            )
            for i in old["source_fingerprints"]
        ],
        partition_validation=old["partition_validation"],
        writer_guard=lambda: None,
    )
    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        task = samples._task(plan)
        samples._prepare_price(c, plan, task)
        replay_indicator_task(c, plan, task)
        fragments = read_indicator_task(plan, task)
        result_last = max(
            c.execute(
                "SELECT max(trade_date) FROM "
                + read_parquet(
                    Path(f["outputs"]["result"]["path"]), hive_partitioning=False
                )
            ).fetchone()[0]
            for f in fragments
        )
        state_last = max(
            c.execute(
                "SELECT max(trade_date) FROM "
                + read_parquet(
                    Path(f["outputs"]["state"]["path"]), hive_partitioning=False
                )
            ).fetchone()[0]
            for f in fragments
        )
        assert str(result_last) == "2026-10-12" and str(state_last) == cut


def test_macd_reports_1024_bar_progress_and_stops_before_next_segment(
    indicator_plan, tmp_path
):
    plan = indicator_plan
    task = samples._task(plan)
    updates = []
    canceled = []

    def progress(data):
        updates.append(data)
        if data.get("replay_calculated_rows", 0) >= 1024:
            canceled.append(True)

    with connect_configured_duckdb(
        RepairBudget().connection_settings(tmp_path), temp_policy="existing_no_spill"
    ) as c:
        samples._prepare_price(c, plan, task)
        with pytest.raises(FactorRepairError, match="canceled"):
            replay_indicator_task(
                c, plan, task, progress=progress, cancel=lambda: bool(canceled)
            )
        assert updates[-1]["replay_calculated_rows"] == 1024
        assert (
            updates[-1]["replay_completed_rows"] == 0
            and updates[-1]["replay_completed_windows"] == 0
        )
        directory = Path(plan["run_root"]) / "inputs/indicator_replay" / task["task_id"]
        assert (directory / "segment-0.json").exists() and not (
            directory / "result-1.parquet"
        ).exists()
        saved = {str(p): file_identity(p) for p in directory.glob("*")}
        successful = []
        replay_indicator_task(c, plan, task, progress=successful.append)
        assert all(file_identity(Path(p)) == identity for p, identity in saved.items())
        values = [d["replay_calculated_rows"] for d in successful]
        assert (
            values == sorted(values)
            and values[-1] == successful[-1]["replay_total_rows"]
        )
        assert (
            successful[-1]["replay_completed_windows"]
            == successful[-1]["replay_total_windows"]
        )
