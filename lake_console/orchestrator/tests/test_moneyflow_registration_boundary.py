"""All seven registrars exclude bootstrap source gaps and keep the 22:00 gate."""

import importlib
from datetime import datetime
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts import moneyflow_automation as automation
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

CONTRACTS = tuple(
    v
    for v in vars(automation).values()
    if isinstance(v, automation.MoneyflowAutomationContract)
)


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.dataset)
@pytest.mark.parametrize("hour", (21, 22))
def test_registrar_boundary_holes_and_replay(tmp_path, monkeypatch, contract, hour):
    import orchestrator.defs.sensors.cn_a_trade_day_sensor as registration

    now = datetime(2026, 10, 13, hour, 1, tzinfo=CN_A_SENSOR_TIMEZONE)
    monkeypatch.setattr(
        registration,
        "datetime",
        type("Clock", (), {"now": staticmethod(lambda tz=None: now)}),
    )

    class Lake(LakeRootResource):
        def ensure_available_for_run(self):
            assert self.root().is_dir()

    settings = DuckDBConnectionSettings(
        temp_directory=tmp_path, memory_limit="512MB", threads=1
    )
    path = silver_trade_calendar_path(tmp_path / "lake")
    path.parent.mkdir(parents=True)
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as db:
        db.execute(
            "COPY (SELECT 'SSE' AS exchange, col0::DATE AS trade_date,col1 AS is_open FROM (VALUES ('2024-11-04',true),('2025-01-20',true),('2026-07-09',true),('2026-09-30',true),('2026-10-01',false),('2026-10-08',true),('2026-10-09',true),('2026-10-10',false),('2026-10-12',true),('2026-10-13',true))) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    sensor = getattr(
        importlib.import_module(
            "orchestrator.defs.sensors." + contract.dataset + "_sensor"
        ),
        "cn_a_" + contract.dataset + "_trade_day_sensor",
    )
    (tmp_path / "instance").mkdir()
    with (
        dg.DagsterInstance.local_temp(
            str(tmp_path / "instance"), overrides={"telemetry": {"enabled": False}}
        ) as instance,
        dg.build_sensor_context(
            instance=instance,
            resources={
                "lake_root": Lake(root_path=str(tmp_path / "lake")),
                "duckdb": SimpleNamespace(
                    connect=lambda: connect_configured_duckdb(
                        settings, temp_policy="existing_no_spill"
                    )
                ),
            },
        ) as ctx,
    ):
        first = sensor.evaluate_tick(ctx)
        keys = first.dynamic_partitions_requests[0].partition_keys
        assert keys == (
            ["2026-10-08", "2026-10-09"] if hour == 21 else ["2026-10-13", "2026-10-08"]
        )
        assert (
            len(keys) <= 2
            and len(first.cursor.encode()) <= 8192
            and not first.run_requests
        )
        for _ in range(4):
            result = sensor.evaluate_tick(ctx)
            for request in result.dynamic_partitions_requests:
                instance.add_dynamic_partitions(
                    contract.partition_set, request.partition_keys
                )
        registered = instance.get_dynamic_partitions(contract.partition_set)
        assert set(registered) == (
            {"2026-10-08", "2026-10-09", "2026-10-12"}
            | ({"2026-10-13"} if hour == 22 else set())
        )
        assert not sensor.evaluate_tick(ctx).dynamic_partitions_requests
        assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
