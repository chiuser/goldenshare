"""Actual isolated monthly jobs with three blocking checks and correct partitions."""

import dagster as dg
import pytest
from pydantic import ValidationError

from orchestrator.defs.assets import stock_monthly as assets
from orchestrator.defs.checks import stock_monthly_checks as checks
from orchestrator.defs.jobs import stock_monthly as jobs
from orchestrator.defs.partitions import cn_a_stock_months
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.configs import StockMonthlyRawConfig
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_asset_key,
    monthly_check_names,
    monthly_job_name,
)
from orchestrator.defs.stock_monthly_point import deliver_month_intent
from orchestrator.defs.stock_monthly_update_state import monthly_period_status

from .test_stock_monthly_update import frame_for, setup_reference


@pytest.mark.parametrize("source", tuple(StockMonthlySource))
def test_actual_job_check_events_and_partition(tmp_path, monkeypatch, source):
    lake, staging, _ = setup_reference(tmp_path)
    calls = []

    def fetch(worker, params, *args):
        calls.append(params)
        return frame_for(source)

    def deliver(*args, **kwargs):
        kwargs["staging_root"] = staging
        kwargs["fetch"] = fetch
        return deliver_month_intent(*args, **kwargs)

    monkeypatch.setattr(assets, "deliver_month_intent", deliver)
    monkeypatch.setattr(
        assets, "monthly_upstream_bindings", lambda instance, days: {"ids": list(days)}
    )
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    asset = getattr(assets, monthly_asset_key(source))
    check_defs = [getattr(checks, name) for name in monthly_check_names(source)]
    definitions = dg.Definitions(
        assets=[asset],
        asset_checks=check_defs,
        jobs=[getattr(jobs, monthly_job_name(source))],
        resources={
            "lake_root": LakeRootResource(root_path=str(lake)),
            "tushare": TushareResource(token="offline-test"),
        },
    )
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(cn_a_stock_months.name, ["2020-02"])
        job = definitions.resolve_job_def(monthly_job_name(source))
        result = job.execute_in_process(instance=instance, partition_key="2020-02")
        assert result.success
        evaluations = [
            e.event_specific_data
            for e in result.all_events
            if e.event_type_value == "ASSET_CHECK_EVALUATION"
        ]
        assert len(evaluations) == 3 and all(
            e.passed and e.blocking and e.partition == "2020-02" for e in evaluations
        )
        for name in monthly_check_names(source):
            history = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(asset.key, name), limit=1
            )
            assert history[0].partition == "2020-02"
        assert all(c.partitions_def == cn_a_stock_months for c in check_defs)
        assert job.asset_layer.executable_asset_keys == {asset.key}
        assert monthly_period_status(instance, lake, source, "2020-02") == "ready"
    assert calls == [
        {"freq": "month", "trade_date": "20200228", "limit": 6000, "offset": 0}
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"write_mode": "overwrite"},
        {"code_list_path": "/tmp/codes.csv"},
        {"fallback": True},
        {"source": "weekly"},
    ],
)
def test_forbidden_config_rejected(kwargs):
    with pytest.raises(ValidationError):
        StockMonthlyRawConfig(**kwargs)


@pytest.mark.parametrize("source", tuple(StockMonthlySource))
def test_bootstrap_delivery_retains_null_cutoff_without_daily_reconstruction(
    tmp_path, source
):
    import json

    from orchestrator.defs.bootstrap.stock_monthly_delivery import (
        read_month_bootstrap_delivery,
    )
    from orchestrator.defs.bootstrap.stock_monthly_promote import (
        promote_month_candidates,
    )

    from .test_stock_monthly_bootstrap import prepared

    store, lake, _, path, digest = prepared(tmp_path, source=source)
    promote_month_candidates(store, path, digest)
    audit = json.loads(path.read_text())
    month = "2020-02"
    item = next(r for r in audit["records"] if r["month"] == month)
    from orchestrator.defs.paths import raw_stock_monthly_path

    delivery = {
        "delivery_method": "prod_month_bootstrap",
        "audit_path": str(path),
        "audit_hash": digest,
        "source": source.value,
        "month": month,
        "path": str(raw_stock_monthly_path(lake, source, month)),
        "rows": item["rows"],
    }
    with store.connection() as con:
        proof = read_month_bootstrap_delivery(
            delivery, lake, source, month, connection=con
        )
        assert (
            proof["annual_captured_rows"] == 6
            and proof["annual_excluded_rows"] == 2
            and proof["rows"] == 2
        )
        assert (
            con.execute(
                "SELECT count(*) FROM monthly_candidate WHERE end_date IS NULL"
            ).fetchone()[0]
            == 2
        )
    path.write_text(path.read_text() + "changed")
    with pytest.raises(ValueError, match="monthly_bootstrap_audit_changed"):
        read_month_bootstrap_delivery(delivery, lake, source, month)
