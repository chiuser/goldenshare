"""Actual retained jobs and blocking checks against only temporary files/instances."""

import json

import dagster as dg
import pytest

from orchestrator.defs.io.stock_period_raw import atomic_json, connection
from orchestrator.defs.run_contracts.stock_period import FIELDS


@pytest.mark.parametrize(
    "freq,partition,today,prior,days",
    [
        (
            "month",
            "2020-02",
            "2020-02-28",
            "2020-01",
            ["2020-02-27", "2020-02-28", "2020-03-02"],
        ),
        (
            "week",
            "2026-10-16",
            "2026-10-16",
            "2026-10-09",
            ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"],
        ),
    ],
)
def test_actual_job_check_events_and_partition(
    tmp_path, monkeypatch, freq, partition, today, prior, days
):
    from orchestrator.defs import paths
    from orchestrator.defs.assets import stock_monthly, stock_weekly
    from orchestrator.defs.bootstrap import stock_period_history
    from orchestrator.defs.checks import stock_monthly_checks, stock_weekly_checks
    from orchestrator.defs.jobs import stock_monthly as monthly_jobs
    from orchestrator.defs.jobs import stock_weekly as weekly_jobs
    from orchestrator.defs.resources import LakeRootResource
    from orchestrator.defs.run_contracts.configs import build_stock_period_run_config

    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    with connection(tmp_path / "fixtures") as con:
        for p, sql, args in [
            (
                paths.silver_stock_basic_path(root),
                "SELECT '000001.SZ' ts_code,'L' list_status,'CNY' curr_type",
                [],
            ),
            (
                paths.silver_stock_identity_map_path(root),
                "SELECT '000001.SZ' source_ts_code,'000001.SZ' latest_ts_code,'confirmed' confidence",
                [],
            ),
            (
                paths.silver_trade_calendar_path(root),
                # Actual Silver schema; Raw cal_date is not a Silver field.
                (
                    "SELECT 'SSE' exchange,unnest(?)::DATE trade_date,"
                    "true is_open,NULL::DATE pretrade_date"
                ),
                [days],
            ),
        ]:
            p.parent.mkdir(parents=True, exist_ok=True)
            con.sql(sql, params=args).write_parquet(str(p))
    atomic_json(
        staging / "stock_period" / "baseline.json",
        {"status": "ready", "listed": ["000001.SZ"]},
    )
    atomic_json(
        staging / "stock_period" / "daily.json",
        {
            # Real handoff persists both frequencies, even when this job only
            # exercises one. Independent prior closed-period fixture values.
            "completed_through": {
                "week": prior if freq == "week" else "2020-02-21",
                "month": prior if freq == "month" else "2026-09",
            },
            "last_refresh": {},
            "factor_through": today,
        },
    )
    calls = []

    def transport(params):
        calls.append(params)
        dates = ["20200228", "20200229"] if freq == "month" else ["20261016"]
        return json.dumps(
            {
                "code": 0,
                "data": {
                    "fields": list(FIELDS),
                    "items": [
                        ["000001.SZ", d, today.replace("-", ""), freq] + [1.25] * 17
                        for d in dates
                    ],
                },
            }
        ).encode()

    monkeypatch.setattr(stock_period_history, "HttpPage", lambda **_: transport)
    asset = getattr(
        stock_weekly if freq == "week" else stock_monthly,
        "raw_tushare_stk_period_bar_adj_" + freq,
    )
    cm = stock_weekly_checks if freq == "week" else stock_monthly_checks
    check_defs = [
        getattr(cm, asset.key.path[0] + "_" + s + "_check")
        for s in ("file_contract", "key_partition", "delivery_reconciliation")
    ]
    job = getattr(
        weekly_jobs if freq == "week" else monthly_jobs,
        "raw_stk_period_bar_adj_" + freq + "_update_job",
    )
    definitions = dg.Definitions(
        assets=[asset],
        asset_checks=check_defs,
        jobs=[job],
        resources={"lake_root": LakeRootResource(root_path=str(root))},
    )
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    monkeypatch.setenv("DAGSTER_HOME", str(instance_dir))
    (instance_dir / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(instance_dir)) as instance:
        instance.add_dynamic_partitions(
            "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months",
            [partition],
        )
        result = definitions.resolve_job_def(job.name).execute_in_process(
            instance=instance,
            partition_key=partition,
            run_config=build_stock_period_run_config(freq, today),
        )
        assert result.success
        checks = [
            e.event_specific_data
            for e in result.all_events
            if e.event_type_value == "ASSET_CHECK_EVALUATION"
        ]
        assert len(checks) == 3 and all(
            c.passed and c.blocking and c.partition == partition for c in checks
        )
    assert len(calls) == 1
