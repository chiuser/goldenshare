"""Current native notification and sensor definition contracts; no private resume state."""

from uuid import uuid4

import dagster as dg
import pytest

from orchestrator.defs.run_contracts.stock_period_delivery import (
    delivery_completion,
    delivery_ref,
    validate_delivery_completion,
)
from orchestrator.defs.sensors.silver_stock_monthly_update_job_sensor import (
    silver_stock_monthly_update_job_sensor,
)
from orchestrator.defs.sensors.silver_stock_weekly_update_job_sensor import (
    silver_stock_weekly_update_job_sensor,
)


@pytest.mark.parametrize(
    "definition,job",
    [
        (silver_stock_weekly_update_job_sensor, "silver_stock_weekly_update_job"),
        (silver_stock_monthly_update_job_sensor, "silver_stock_monthly_update_job"),
    ],
)
def test_exact_definition_contract(definition, job):
    assert definition.name == job + "_sensor"
    assert definition.default_status == dg.DefaultSensorStatus.STOPPED
    assert definition.minimum_interval_seconds == 60
    assert definition.job_name == job
    assert definition.tags == {
        "goldenshare/sensor_domain": "quote_data",
        "goldenshare/sensor_target_layer": "silver",
        "goldenshare/sensor_role": "asset_update",
    }


@pytest.mark.parametrize("change", ["version", "freq", "count", "batch", "path"])
def test_native_notice_rejects_non_contract_inputs(change):
    ref = delivery_ref(str(uuid4()), "week", "daily", "2026-11-10", ["2026-11-13"])
    notice = delivery_completion(
        ref, kind="daily", business_date="2026-11-10", periods=["2026-11-13"]
    )
    assert validate_delivery_completion(notice, "week") == ref
    if change == "version":
        notice["version"] = "other"
    if change == "freq":
        notice["freq"] = "month"
    if change == "count":
        notice["file_count"] = True
    if change == "batch":
        notice["upstream_batch_id"] = "wrong"
    if change == "path":
        notice["path"] = "/arbitrary"
    with pytest.raises(ValueError):
        validate_delivery_completion(notice, "week")
