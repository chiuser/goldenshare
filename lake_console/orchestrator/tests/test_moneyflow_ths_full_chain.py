"""One-date HTTP precheck, original Raw job and native Silver success handoff.

Inputs: doc348's complete 13 fields, current producer schemas and stage-five
literal expectations. Only the upstream data, clock-of-day, token and remote
server are synthetic; collection uses the real worker and real stability wait.
"""

import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg

import orchestrator.defs.assets.moneyflow_ths as assets
import orchestrator.defs.checks.moneyflow_ths as checks
import orchestrator.defs.io.moneyflow_candidates as candidates
import orchestrator.defs.sensors.moneyflow_ths_sensor as sensors
from orchestrator.defs.paths import (
    raw_moneyflow_path,
    silver_moneyflow_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_THS_SCHEMA,
)
from orchestrator.defs.source_readiness import moneyflow_daily, moneyflow_ths
from orchestrator.defs.source_readiness.moneyflow_transport import call_moneyflow_source
from tests import test_moneyflow_ths_source_readiness as precheck
from tests.moneyflow_ths_upstream_support import seed_market
from tests.test_moneyflow_ths_http_worker import (
    TOKEN,
    Reply,
    localhost_source,
    source_body,
)

pytest_plugins = ("tests.test_moneyflow_ths_http_worker",)
market = precheck.market
DAY = "2026-11-10"
FIELDS = (
    "trade_date", "ts_code", "name", "pct_change", "latest", "net_amount",
    "net_d5_amount", "buy_lg_amount", "buy_lg_amount_rate", "buy_md_amount",
    "buy_md_amount_rate", "buy_sm_amount", "buy_sm_amount_rate",
)


def test_http_precheck_raw_merge_and_native_silver(market, monkeypatch, ths_probe, record_property):
    lake, instance = market.root, market.instance
    staging = market.tmp / "staging"
    staging.mkdir()
    monkeypatch.setattr(assets, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    seed_market(instance, lake, staging, [DAY], codes=("000001.SZ", "600000.SH", "000002.SZ"))
    assert FIELDS == tuple(c.name for c in RAW_TUSHARE_MONEYFLOW_THS_SCHEMA)
    raw = raw_moneyflow_path(lake, "moneyflow_ths", DAY)
    raw.parent.mkdir(parents=True, exist_ok=True)
    calendar = silver_trade_calendar_path(lake)
    calendar.parent.mkdir(parents=True, exist_ok=True)
    with candidates.moneyflow_candidate_connection(staging) as connection:
        connection.execute("COPY (SELECT 'SSE' exchange,DATE '2026-11-10' trade_date,true is_open) TO $p (FORMAT PARQUET)", {"p": str(calendar)})
    assert not raw.exists()
    assert not instance.fetch_materializations(assets.raw_tushare_moneyflow_ths.key, limit=1).records
    resource = SimpleNamespace(token=TOKEN)
    definitions = dg.Definitions(
        assets=[assets.raw_tushare_moneyflow_ths, assets.silver_moneyflow_ths],
        asset_checks=precheck.definitions.CHECKS,
        jobs=[precheck.definitions.raw_tushare_moneyflow_ths_update_job, precheck.definitions.silver_moneyflow_ths_update_job],
        sensors=[sensors.raw_tushare_moneyflow_ths_update_job_sensor, sensors.silver_moneyflow_ths_update_job_sensor],
        resources={"lake_root": market.resources.lake_root, "tushare": dg.ResourceDefinition.hardcoded_resource(resource), "duckdb": dg.ResourceDefinition.hardcoded_resource(SimpleNamespace())},
    )
    instance.add_dynamic_partitions(sensors.PARTITIONS, [DAY])

    def silver_tick(cursor=None):
        with dg.partition_loading_context(dynamic_partitions_store=instance), dg.build_sensor_context(instance=instance, repository_def=definitions.get_repository_def(), cursor=cursor, resources={"lake_root": market.resources.lake_root}) as context:
            return sensors.silver_moneyflow_ths_update_job_sensor.evaluate_tick(context)

    initialized = silver_tick()
    assert initialized.cursor and not initialized.run_requests
    # Independent literal values follow doc348 and the approved two-cycle example.
    requests = [
        dict(zip(FIELDS, ("20261110", "000001.SZ", None, Decimal(0), Decimal(10), Decimal(100), Decimal(-2), Decimal(3), Decimal(4), Decimal(5), Decimal(6), Decimal(-7), Decimal(8)), strict=True)),
        dict(zip(FIELDS, ("20261110", "600000.SH", "旧B", Decimal(0), Decimal(11), Decimal(200), Decimal(-3), Decimal(4), Decimal(5), Decimal(6), Decimal(7), Decimal(-8), Decimal(9)), strict=True)),
    ]

    def reply(payload, _):
        assert payload["params"] == {"trade_date": "20261110", "limit": 2000, "offset": 0}
        fields = tuple(payload["fields"].split(","))
        assert fields in (("ts_code", "trade_date"), FIELDS)
        return Reply(200, source_body(fields, requests))

    def request(*args, **kwargs):
        return call_moneyflow_source(*args, **kwargs, _command=ths_probe.command)

    monkeypatch.setattr(moneyflow_ths, "call_moneyflow_source", request)
    monkeypatch.setattr(moneyflow_daily, "call_moneyflow_source", request)
    sql, phase = [], ["precheck"]
    original = candidates.connect_configured_duckdb

    @contextmanager
    def observed(*args, **kwargs):
        with original(*args, **kwargs) as connection:
            class Observed:
                def execute(self, statement, *args, **kwargs):
                    sql.append((phase[0], statement))
                    return connection.execute(statement, *args, **kwargs)

                def __getattr__(self, name):
                    return getattr(connection, name)
            yield Observed()

    monkeypatch.setattr(candidates, "connect_configured_duckdb", observed)
    monkeypatch.setattr(checks, "connect_configured_duckdb", observed)
    D = Decimal
    first_expected = [
        ("000001.SZ", None, D(0), D(10), D(100), D(-2), D(3), D(4), D(5), D(6), D(-7), D(8)),
        ("600000.SH", "旧B", D(0), D(11), D(200), D(-3), D(4), D(5), D(6), D(7), D(-8), D(9)),
    ]
    final_expected = [
        first_expected[0],
        ("000002.SZ", "新增C", D(0), D(13), D(300), D(-10), D(16), D(17), D(18), D(19), D(20), D(21)),
        ("600000.SH", "新B", D(-1), D(12), D(250), D(-9), D(10), D(11), D(12), D(13), D(14), D(15)),
    ]
    silver = silver_moneyflow_path(lake, "moneyflow_ths", DAY)
    cycles = []
    started = perf_counter()
    with localhost_source(reply) as (url, received):
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        with dg.partition_loading_context(dynamic_partitions_store=instance), dg.build_sensor_context(instance=instance, definitions=definitions, resources=definitions.resources) as context:
            result = sensors.evaluate_stock_moneyflow_ths(context, precheck.NOW)
        assert len(result.run_requests) == 1 and len(received) == 1
        assert result.run_requests[0].partition_key == DAY
        cursor = initialized.cursor
        for cycle, expected, missing, http_count in (
            (1, first_expected, ["000002.SZ"], 3),
            (2, final_expected, [], 5),
        ):
            if cycle == 2:
                # Manual supplement uses the original job, not the automatic Raw sensor.
                requests[:] = [
                    dict(zip(FIELDS, ("20261110", "600000.SH", "新B", Decimal(-1), Decimal(12), Decimal(250), Decimal(-9), Decimal(10), Decimal(11), Decimal(12), Decimal(13), Decimal(14), Decimal(15)), strict=True)),
                    dict(zip(FIELDS, ("20261110", "000002.SZ", "新增C", Decimal(0), Decimal(13), Decimal(300), Decimal(-10), Decimal(16), Decimal(17), Decimal(18), Decimal(19), Decimal(20), Decimal(21)), strict=True)),
                ]
            phase[0] = f"raw{cycle}"
            raw_result = definitions.resolve_job_def(sensors.RAW_JOB).execute_in_process(instance=instance, partition_key=DAY)
            assert raw_result.success and len(received) == http_count
            md = raw_result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
            assert md["dagster/row_count"].value == len(expected)
            assert isinstance(md["goldenshare/missing_record_codes"], dg.JsonMetadataValue)
            assert isinstance(md["goldenshare/null_value_codes"], dg.JsonMetadataValue)
            assert md["goldenshare/missing_record_codes"].value == missing
            assert md["goldenshare/null_value_codes"].value == ["000001.SZ"]
            receipt_path = Path(md["goldenshare/source_proof_path"].value)
            receipt = json.loads(receipt_path.read_text())
            assert receipt["row_count"] == 2 and receipt["stability_gap_seconds"] >= 60
            phase[0] = "callback"
            handoff = silver_tick(cursor)
            assert len(handoff.run_requests) == 1
            run_request = handoff.run_requests[0]
            digest = candidates.candidate_file_hash(raw)
            assert run_request.partition_key == DAY and run_request.run_key == f"silver_moneyflow_ths:{DAY}:{digest}"
            assert len(received) == http_count
            phase[0] = f"silver{cycle}"
            silver_result = definitions.resolve_job_def(sensors.SILVER_JOB).execute_in_process(instance=instance, partition_key=run_request.partition_key)
            assert silver_result.success and len(received) == http_count
            silver_md = silver_result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
            assert silver_md["goldenshare/raw_sha256"].value == digest
            assert all(e.passed and e.target_materialization_data.run_id == r.run_id for r in (raw_result, silver_result) for e in r.get_asset_check_evaluations())
            phase[0] = "callback"
            repeated = silver_tick(handoff.cursor)
            assert not repeated.run_requests and len(received) == http_count
            cursor = repeated.cursor
            phase[0] = f"readback{cycle}"
            with candidates.moneyflow_candidate_connection(staging) as connection:
                raw_values = connection.execute("SELECT * FROM read_parquet($p,hive_partitioning=false) ORDER BY ts_code", {"p": str(raw)}).fetchall()
                silver_values = connection.execute("SELECT * FROM read_parquet($p,hive_partitioning=false) ORDER BY ts_code", {"p": str(silver)}).fetchall()
            assert raw_values == [("20261110", *r) for r in expected]
            assert silver_values == [(date(2026, 11, 10), *r) for r in expected]
            cycles.append({"cycle": cycle, "source_rows": 2, "final_rows": len(expected), "missing_record_codes": missing, "null_value_codes": ["000001.SZ"], "receipt": str(receipt_path), "raw_run_id": raw_result.run_id, "silver_run_id": silver_result.run_id, "raw_sha256": digest, "silver_sha256": candidates.candidate_file_hash(silver), "run_key": run_request.run_key, "stability_gap_seconds": receipt["stability_gap_seconds"]})
    names = ("precheck", "raw1", "silver1", "readback1", "raw2", "silver2", "readback2", "callback")
    counts = {name: sum(p == name for p, _ in sql) for name in names}
    # LLD 82.30 adds one retained-row count per source round, two per Raw run.
    assert counts == {"precheck": 2, "raw1": 62, "silver1": 40, "readback1": 2, "raw2": 66, "silver2": 44, "readback2": 2, "callback": 0}
    assert sum(counts.values()) == 218
    assert len(ths_probe.owned) == 5 and candidates.candidate_file_hash(raw) == cycles[1]["raw_sha256"]
    assert cycles[0]["raw_sha256"] != cycles[1]["raw_sha256"]
    assert [r[1]["fields"] for r in received] == ["ts_code,trade_date", *([",".join(FIELDS)] * 4)]
    record_property("ths_stage5_chain", json.dumps({"seconds": perf_counter() - started, "http_requests": len(received), "workers": len(ths_probe.owned), "sql": counts, "raw": str(raw), "silver": str(silver), "instance": str(market.tmp / "instance"), "cycles": cycles}))
