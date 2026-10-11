"""Closed-batch capture, real temporary Parquet merge and recovery; zero network."""

import csv
import io
import json
import subprocess
import sys
import time
from dataclasses import replace
from decimal import Decimal

import dagster as dg
import duckdb
import pytest
from pydantic import ValidationError

from orchestrator.defs.bootstrap.stock_weekly_candidates import partition_path
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.bootstrap.stock_weekly_promote import promote_weekly_candidates
from orchestrator.defs.prod_db.stock_weekly_adj_delivery import (
    PsqlWeeklyAdjDeliveryReader,
    build_delivery_record_sql,
    build_next_closed_batch_sql,
)
from orchestrator.defs.run_contracts.configs import StockWeeklyAdjProdConfig
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
)
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    WeeklyAdjProdDeliveryBudget,
)
from orchestrator.defs.stock_weekly_adj_delivery import (
    capture_closed_adjusted_batch,
    prepare_adjusted_delivery_year,
    validate_closed_unit,
)

from .stock_weekly_adj_delivery_test_support import (
    BATCH,
    HISTORY,
    OfflineDeliveryReader,
    delivery_fixture,
    source_row,
    wire_digest,
)

SOURCE = StockWeeklySource.PRIMARY_ADJUSTED


def test_adjusted_actual_job_cross_year_events_bind_exact_materializations(
    tmp_path, monkeypatch
):
    from orchestrator.defs.assets import stock_weekly as assets
    from orchestrator.defs.partitions import cn_a_stock_week_ends
    from orchestrator.defs.run_contracts.configs import (
        build_stock_weekly_adj_prod_run_config,
    )
    from orchestrator.defs.run_contracts.stock_weekly import (
        weekly_check_names,
        weekly_job_name,
    )
    from orchestrator.defs.stock_weekly_adj_run import (
        DELIVERY_METADATA_KEY,
        deliver_closed_adjusted_batch,
    )

    from .test_stock_weekly_definitions import definition_for

    header, records = delivery_fixture()
    reader = OfflineDeliveryReader(records)
    (tmp_path / "lake").mkdir()
    original = deliver_closed_adjusted_batch

    def deliver(*args, **kwargs):
        kwargs.update(staging_root=tmp_path / "stage", reader=reader)
        yield from original(*args, **kwargs)

    monkeypatch.setattr(assets, "deliver_closed_adjusted_batch", deliver)
    monkeypatch.setattr(
        assets.LakeRootResource, "ensure_available_for_run", lambda _: None
    )
    definitions, asset, _ = definition_for(tmp_path, SOURCE)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(
            cn_a_stock_week_ends.name, ["2020-02-28", "2026-10-09"]
        )
        job = definitions.resolve_job_def(weekly_job_name(SOURCE))
        result = job.execute_in_process(
            instance=instance,
            partition_key=header.anchor_partition,
            run_config=build_stock_weekly_adj_prod_run_config(BATCH, header.revision),
        )
        assert result.success
        mats = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset.key), limit=10
        ).records
        assert {r.partition_key for r in mats} == {"2020-02-28", "2026-10-09"}
        assert len(mats) == 2
        by_id = {r.storage_id: r for r in mats}
        evaluations = [
            e.event_specific_data
            for e in result.all_events
            if e.event_type_value == "ASSET_CHECK_EVALUATION"
        ]
        assert len(evaluations) == 6
        for evaluation in evaluations:
            assert evaluation.passed and evaluation.blocking
            target = evaluation.target_materialization_data
            record = by_id[target.storage_id]
            assert evaluation.partition == record.partition_key
            assert target.run_id == record.event_log_entry.run_id
            assert target.timestamp == record.event_log_entry.timestamp
        summary = (
            next(r for r in mats if r.partition_key == header.anchor_partition)
            .asset_materialization.metadata[DELIVERY_METADATA_KEY]
            .value
        )
        assert (
            summary["complete"]
            and summary["files_verified"] == summary["files_expected"] == 2
        )
        assert (
            summary["historical_checks"] == 3 and summary["anchor_checks_expected"] == 3
        )
        from orchestrator.defs.stock_weekly_adj_feed import _completed_run

        pending = {
            "batch_id": BATCH,
            "revision": header.revision,
            "anchor": header.anchor_partition,
            "rows_written": header.rows_written,
        }
        assert _completed_run(instance, instance.get_run_by_id(result.run_id), pending)
        assert not _completed_run(
            instance,
            instance.get_run_by_id(result.run_id),
            {**pending, "rows_written": 999},
        )
        calls = list(reader.calls)
        replay = job.execute_in_process(
            instance=instance,
            partition_key=header.anchor_partition,
            run_config=build_stock_weekly_adj_prod_run_config(BATCH, header.revision),
        )
        assert replay.success and reader.calls == calls
        historical_mats = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset.key, asset_partitions=["2020-02-28"]),
            limit=10,
        ).records
        assert len(historical_mats) == 1
        for name in weekly_check_names(SOURCE):
            checks = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(asset.key, name), limit=10
            )
            assert sum(r.partition == "2020-02-28" for r in checks) == 1


def write_rows(root, week, rows):
    path = partition_path(root, SOURCE, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        specs = weekly_column_specs(SOURCE)
        con.execute(
            "CREATE TABLE fixture (" + ",".join(f'"{n}" {t}' for n, t, _ in specs) + ")"
        )
        con.executemany(
            "INSERT INTO fixture VALUES (" + ",".join("?" for _ in specs) + ")",
            [[r[n] for n, _, _ in specs] for r in rows],
        )
        con.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        con.close()
    return path


def read_rows(path):
    con = duckdb.connect()
    try:
        fields = [n for n, _, _ in weekly_column_specs(SOURCE)]
        return [
            dict(zip(fields, r, strict=True))
            for r in con.execute(
                "SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code,trade_date",
                [str(path)],
            ).fetchall()
        ]
    finally:
        con.close()


def test_closed_batch_cross_year_corrects_all_columns_preserves_unselected(tmp_path):
    header, records = delivery_fixture()
    reader = OfflineDeliveryReader(records)
    root, manifest = capture_closed_adjusted_batch(
        reader, header, staging_root=tmp_path / "stage"
    )
    lake = tmp_path / "lake"
    lake.mkdir()
    for week, day in [("2020-02-28", "20200228"), ("2026-10-09", "20261009")]:
        retained = source_row(day=day, code="000002.SZ", qfq="4.0000")
        write_rows(lake, week, [source_row(day=day, qfq="1.0000"), retained])
        audit_path = prepare_adjusted_delivery_year(
            root, manifest, target_root=lake, year=int(week[:4])
        )
        audit = json.loads(audit_path.read_text())
        assert audit["stats"]["preserved_keys"] == audit["stats"]["replaced_keys"] == 1
        assert audit["stats"]["value_difference_rows"] == 0
        promote_weekly_candidates(audit_path, apply=True)
        actual = read_rows(partition_path(lake, SOURCE, week))
        assert actual[0]["close_qfq"] == Decimal(9)
        assert actual[0]["amount"] == Decimal("9999999999999999.9999")
        assert actual[0]["vol"] == Decimal("1234567890123456.1234")
        assert actual[0]["open_hfq"] is None
        for name, value in retained.items():
            expected = (
                Decimal(value)
                if isinstance(value, str)
                and name not in ("ts_code", "trade_date", "end_date", "freq")
                else value
            )
            assert actual[1][name] == expected
    # Same intent reuses frozen capture; no source download and no replacement.
    calls = list(reader.calls)
    root2, manifest2 = capture_closed_adjusted_batch(
        reader, header, staging_root=tmp_path / "stage"
    )
    assert reader.calls == calls and manifest2 == manifest and root2 == root
    audit = prepare_adjusted_delivery_year(root, manifest, target_root=lake, year=2026)
    promote_weekly_candidates(
        audit, apply=True, fault_probe=lambda *_: pytest.fail("must not replace twice")
    )


def test_replace_crash_recovers_without_rolling_back_and_third_party_change_blocks(
    tmp_path,
):
    header, records = delivery_fixture(historical_only=True)
    root, manifest = capture_closed_adjusted_batch(
        OfflineDeliveryReader(records), header, staging_root=tmp_path / "stage"
    )
    lake = tmp_path / "lake"
    lake.mkdir()
    target = write_rows(lake, "2020-02-28", [source_row(day="20200228", qfq="1.0000")])
    audit = prepare_adjusted_delivery_year(root, manifest, target_root=lake, year=2020)

    def crash(stage, week):
        if stage == "after_replace":
            raise RuntimeError("simulated process exit")

    with pytest.raises(RuntimeError, match="process exit"):
        promote_weekly_candidates(audit, apply=True, fault_probe=crash)
    assert read_rows(target)[0]["close_qfq"] == Decimal(9)
    promote_weekly_candidates(audit, apply=True)
    write_rows(lake, "2020-02-28", [source_row(day="20200228", qfq="7.0000")])
    with pytest.raises(WeeklyCaptureError, match="baseline_changed"):
        promote_weekly_candidates(audit, apply=True)
    assert read_rows(target)[0]["close_qfq"] == Decimal(7)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda r: r["payload"]["rows"][0].update(freq="month"), "source_key_invalid"),
        (lambda r: r["payload"]["rows"][0].update(close_qfq=9.0), "decimal_invalid"),
        (
            lambda r: r["payload"]["rows"][0].update(close_qfq="9.00001"),
            "decimal_invalid",
        ),
        (
            lambda r: r["payload"]["rows"][0].update(ts_code="000002.SZ"),
            "scope_mismatch",
        ),
        (
            lambda r: r["payload"]["rows"][0].update(trade_date="20090102"),
            "scope_mismatch",
        ),
        (lambda r: r["payload"]["rows"][0].update(source="prod"), "schema_invalid"),
        (lambda r: r.update(rows_written=123), "counts_invalid"),
    ],
)
def test_transport_rejects_invalid_rows_and_technical_columns(mutation, reason):
    header, records = delivery_fixture(historical_only=True)
    unit = records["unit", HISTORY]
    mutation(unit)
    planned = records["plan", "plan"]["payload"]["units"][0]
    with pytest.raises(WeeklyCaptureError, match=reason):
        validate_closed_unit(unit, planned, header, WeeklyAdjProdDeliveryBudget())


def test_original_prefixed_raw_code_is_retained_and_not_stripped():
    header, records = delivery_fixture(historical_only=True)
    unit = records["unit", HISTORY]
    unit["ts_code"] = unit["payload"]["rows"][0]["ts_code"] = "T600018.SH"
    planned = records["plan", "plan"]["payload"]["units"][0]
    planned["params"]["ts_code"] = "T600018.SH"
    assert (
        validate_closed_unit(unit, planned, header, WeeklyAdjProdDeliveryBudget())[
            "rows"
        ]
        == 1
    )
    assert unit["payload"]["rows"][0]["ts_code"] == "T600018.SH"


def test_historical_anchor_is_actual_source_week_and_empty_does_not_write_parquet(
    tmp_path,
):
    header, records = delivery_fixture(historical_only=True)
    assert (
        header.cutoff_week == "2026-10-09" and header.anchor_partition == "2020-02-28"
    )
    empty, records = delivery_fixture(empty=True)
    root, manifest = capture_closed_adjusted_batch(
        OfflineDeliveryReader(records), empty, staging_root=tmp_path / "stage"
    )
    assert empty.anchor_partition is None and not list(root.rglob("*.parquet"))
    assert all(not u["chunks"] for u in manifest["units"])


def test_digest_or_closed_unit_scope_mismatch_never_reaches_candidates(tmp_path):
    header, records = delivery_fixture()
    records["unit", HISTORY]["payload"]["rows"][0]["close_qfq"] = "8.0000"
    with pytest.raises(WeeklyCaptureError, match="digest_mismatch"):
        capture_closed_adjusted_batch(
            OfflineDeliveryReader(records), header, staging_root=tmp_path / "stage"
        )
    assert not list((tmp_path / "stage").rglob("audit.json"))


def test_closed_header_sql_is_ordered_small_explicit_and_rollback_only():
    budget = WeeklyAdjProdDeliveryBudget()
    sql = build_next_closed_batch_sql(4, budget)
    assert "revision>4" in sql and "ORDER BY revision ASC" in sql and "LIMIT 1" in sql
    assert "payload->'header'" in sql and '"payload"' not in sql
    assert "READ ONLY" in sql and "REPEATABLE READ" in sql and "ROLLBACK" in sql
    for forbidden in (
        "SELECT *",
        "MAX(",
        "raw_tushare",
        "ops.",
        "UPDATE ",
        "DELETE ",
        "INSERT ",
    ):
        assert forbidden not in sql
    for bad in (True, -1, "0; DROP TABLE x"):
        with pytest.raises(ValueError):
            build_next_closed_batch_sql(bad, budget)
    with pytest.raises(ValueError):
        build_delivery_record_sql(BATCH, "unit", "x'; DROP TABLE x", budget)


@pytest.mark.parametrize(
    "extra",
    [
        {"code_list_path": "x"},
        {"write_mode": "replace"},
        {"automatic_intent_date": "2026-10-11"},
        {"contract_version": 2},
        {"closure_revision": True},
    ],
)
def test_adjusted_config_rejects_old_inputs_and_unknown_contract(extra):
    with pytest.raises(ValidationError):
        StockWeeklyAdjProdConfig(
            delivery_batch_id=BATCH, **{"closure_revision": 4, **extra}
        )


def test_reader_uses_only_wrapper_and_rejects_large_response(tmp_path):
    header, _ = delivery_fixture()
    observed = []

    def process(argv, **kwargs):
        observed.append(argv)
        return subprocess.Popen(
            [sys.executable, "-c", f"print({json.dumps(header.__dict__)!r})"], **kwargs
        )

    reader = PsqlWeeklyAdjDeliveryReader(process_factory=process)
    assert reader.next_closed_batch(0) == header
    assert len(observed) == 1 and observed[0][1].endswith("scripts/psql-remote.sh")
    reader.budget = replace(reader.budget, max_control_bytes=5)
    with pytest.raises(WeeklyCaptureError, match="read_budget_exceeded"):
        reader.next_closed_batch(0)
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        reader.next_closed_batch(0, cancel=lambda: True)
    assert len(observed) == 2


def test_copy_reader_counts_and_parses_one_immutable_record():
    header, records = delivery_fixture(historical_only=True)
    record = records["unit", HISTORY]
    output = io.StringIO()
    output.write('{"record_count":1}\n')
    csv.writer(output).writerow([json.dumps(record)])
    wire = output.getvalue()
    calls = []

    def process(argv, **kwargs):
        calls.append(argv)
        return subprocess.Popen(
            [sys.executable, "-c", f"import sys;sys.stdout.write({wire!r})"], **kwargs
        )

    reader = PsqlWeeklyAdjDeliveryReader(process_factory=process)
    assert reader.read_record(header, "unit", HISTORY) == record
    sql = calls[0][3]
    assert "COPY (SELECT row_to_json" in sql and "count(*) AS record_count" in sql
    assert "REPEATABLE READ READ ONLY" in sql and "ROLLBACK" in sql


def test_reader_deadline_terminates_the_child_without_hanging():
    children = []

    def process(argv, **kwargs):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(10)"], **kwargs
        )
        children.append(child)
        return child

    reader = PsqlWeeklyAdjDeliveryReader(
        process_factory=process,
        budget=WeeklyAdjProdDeliveryBudget(
            prod_unit_seconds=1, prod_statement_timeout_ms=500
        ),
    )
    started = time.monotonic()
    with pytest.raises(WeeklyCaptureError, match="read_timeout"):
        reader.next_closed_batch(0)
    assert time.monotonic() - started < 3 and children[0].poll() is not None


def test_old_adjusted_source_and_automatic_date_contract_are_rejected_before_io(
    tmp_path,
):
    from orchestrator.defs.run_contracts.configs import (
        build_stock_weekly_update_job_run_config,
    )
    from orchestrator.defs.stock_weekly_point import (
        StockWeeklyPointWorker,
        deliver_stock_weekly_point,
    )
    from orchestrator.defs.stock_weekly_update import weekly_update_intent

    with pytest.raises(WeeklyCaptureError, match="requires_prod_closed_batch"):
        deliver_stock_weekly_point(
            SOURCE,
            "2026-10-09",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
        )
    with pytest.raises(WeeklyCaptureError, match="requires_prod_closed_batch"):
        StockWeeklyPointWorker("offline", SOURCE)({}, (), 1)
    with pytest.raises(ValueError, match="requires_prod_closed_batch"):
        build_stock_weekly_update_job_run_config(SOURCE, "2026-10-11")
    with pytest.raises(ValueError, match="requires_prod_closed_batch"):
        weekly_update_intent(SOURCE, "2026-10-09", "2026-10-11")
    assert not (tmp_path / "stage").exists()


def test_capture_chunk_or_manifest_tampering_blocks_before_candidate(tmp_path):
    header, records = delivery_fixture(historical_only=True)
    root, manifest = capture_closed_adjusted_batch(
        OfflineDeliveryReader(records), header, staging_root=tmp_path / "stage"
    )
    lake = tmp_path / "lake"
    lake.mkdir()
    chunk = (
        root
        / "units"
        / manifest["units"][0]["unit_id"]
        / manifest["units"][0]["chunks"][0]["path"]
    )
    chunk.write_bytes(b"tampered")
    with pytest.raises(WeeklyCaptureError, match="capture_changed"):
        prepare_adjusted_delivery_year(root, manifest, target_root=lake, year=2020)
    assert not list(root.rglob("audit.json")) and not list(lake.rglob("*.parquet"))


def test_cancel_between_files_preserves_committed_file_and_resumes(tmp_path):
    header, records = delivery_fixture()
    root, manifest = capture_closed_adjusted_batch(
        OfflineDeliveryReader(records), header, staging_root=tmp_path / "stage"
    )
    lake = tmp_path / "lake"
    lake.mkdir()
    first = prepare_adjusted_delivery_year(root, manifest, target_root=lake, year=2020)
    second = prepare_adjusted_delivery_year(root, manifest, target_root=lake, year=2026)
    promote_weekly_candidates(first, apply=True)
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        promote_weekly_candidates(second, apply=True, cancel=lambda: True)
    assert partition_path(lake, SOURCE, "2020-02-28").exists()
    assert not partition_path(lake, SOURCE, "2026-10-09").exists()
    promote_weekly_candidates(second, apply=True)
    assert read_rows(partition_path(lake, SOURCE, "2026-10-09"))[0][
        "close_qfq"
    ] == Decimal(9)


def test_stored_historical_event_before_checkpoint_exit_is_reused_on_retry(
    tmp_path, monkeypatch
):
    from orchestrator.defs import stock_weekly_adj_run as driver
    from orchestrator.defs.assets import stock_weekly as assets
    from orchestrator.defs.partitions import cn_a_stock_week_ends
    from orchestrator.defs.run_contracts.configs import (
        build_stock_weekly_adj_prod_run_config,
    )
    from orchestrator.defs.run_contracts.stock_weekly import weekly_job_name

    from .test_stock_weekly_definitions import definition_for

    header, records = delivery_fixture()
    reader = OfflineDeliveryReader(records)
    (tmp_path / "lake").mkdir()

    def deliver(*args, **kwargs):
        kwargs.update(staging_root=tmp_path / "stage", reader=reader)
        yield from driver.deliver_closed_adjusted_batch(*args, **kwargs)

    monkeypatch.setattr(assets, "deliver_closed_adjusted_batch", deliver)
    monkeypatch.setattr(
        assets.LakeRootResource, "ensure_available_for_run", lambda _: None
    )
    definitions, asset, _ = definition_for(tmp_path, SOURCE)
    original = driver._atomic_json
    writes = []

    def fail_checkpoint(path, value):
        writes.append(path)
        if len(writes) == 2:
            raise RuntimeError("exit after stored event before checkpoint")
        original(path, value)

    monkeypatch.setattr(driver, "_atomic_json", fail_checkpoint)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(
            cn_a_stock_week_ends.name, ["2020-02-28", "2026-10-09"]
        )
        job = definitions.resolve_job_def(weekly_job_name(SOURCE))
        config = build_stock_weekly_adj_prod_run_config(BATCH, header.revision)
        failed = job.execute_in_process(
            instance=instance,
            partition_key=header.anchor_partition,
            run_config=config,
            raise_on_error=False,
        )
        assert not failed.success
        assert partition_path(tmp_path / "lake", SOURCE, "2020-02-28").exists()
        mats = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset.key), limit=10
        ).records
        assert len(mats) == 1 and mats[0].partition_key == "2020-02-28"
        stored = mats[0]
        monkeypatch.setattr(driver, "_atomic_json", original)
        calls = list(reader.calls)
        resumed = job.execute_in_process(
            instance=instance, partition_key=header.anchor_partition, run_config=config
        )
        assert resumed.success and reader.calls == calls
        mats = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset.key), limit=10
        ).records
        assert len(mats) == 2 and any(r.storage_id == stored.storage_id for r in mats)
        evaluations = [
            e.event_specific_data
            for e in resumed.all_events
            if e.event_type_value == "ASSET_CHECK_EVALUATION"
            and e.event_specific_data.partition == "2020-02-28"
        ]
        assert len(evaluations) == 3
        assert all(
            e.target_materialization_data.storage_id == stored.storage_id
            and e.target_materialization_data.run_id == failed.run_id
            for e in evaluations
        )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("max_unit_rows", 1, "row_budget_exceeded"),
        ("max_unit_payload_bytes", 1, "payload_budget_exceeded"),
    ],
)
def test_unit_budget_rejects_before_chunk_capture(field, value, reason):
    header, records = delivery_fixture()
    unit = records["unit", HISTORY]
    planned = records["plan", "plan"]["payload"]["units"][1]
    with pytest.raises(WeeklyCaptureError, match=reason):
        validate_closed_unit(
            unit,
            planned,
            header,
            replace(WeeklyAdjProdDeliveryBudget(), **{field: value}),
        )


def test_two_history_units_cannot_silently_last_win(tmp_path):
    from copy import deepcopy

    header, records = delivery_fixture()
    plan = records["plan", "plan"]
    replacement = deepcopy(plan["payload"]["units"][1])
    replacement["unit_id"] = plan["payload"]["units"][0]["unit_id"]
    plan["payload"]["units"][0] = replacement
    plan["payload_digest"] = wire_digest(plan["payload"])
    point = records["unit", replacement["unit_id"]]
    point.update(
        unit_kind="stock_history",
        ts_code="000001.SZ",
        start_date="2010-01-01",
        end_date="2026-10-09",
    )
    root, manifest = capture_closed_adjusted_batch(
        OfflineDeliveryReader(records), header, staging_root=tmp_path / "stage"
    )
    lake = tmp_path / "lake"
    lake.mkdir()
    with pytest.raises(WeeklyCaptureError, match="overlap"):
        prepare_adjusted_delivery_year(root, manifest, target_root=lake, year=2026)
    assert not list(lake.rglob("*.parquet"))


def test_maximum_unit_is_captured_with_existing_duckdb_budget(tmp_path):
    header, records = delivery_fixture()
    ids = records["batch_closed", header.revision]["payload"]["unit_ids"]
    unit = records["unit", ids[0]]
    unit["payload"]["rows"] = [
        source_row(code=f"{index:06d}.SZ") for index in range(1, 12_001)
    ]
    unit.update(rows_received=12_000, rows_unique=12_000, rows_written=12_000)
    unit["payload_digest"] = wire_digest(unit["payload"])
    closure = records["batch_closed", header.revision]
    control = {
        **header.header,
        "total_payload_bytes": sum(
            len(
                json.dumps(
                    records["unit", identity]["payload"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            for identity in ids
        ),
        "units_digest": wire_digest(
            [
                {
                    "unit_id": identity,
                    "digest": records["unit", identity]["payload_digest"],
                }
                for identity in ids
            ]
        ),
    }
    closure["payload"]["header"] = control
    closure.update(rows_received=12_002, rows_unique=12_002, rows_written=12_002)
    closure["payload_digest"] = wire_digest(closure["payload"])
    header = replace(
        header,
        header=control,
        rows_received=12_002,
        rows_unique=12_002,
        rows_written=12_002,
        payload_digest=closure["payload_digest"],
    )
    root, manifest = capture_closed_adjusted_batch(
        OfflineDeliveryReader(records), header, staging_root=tmp_path / "stage"
    )
    assert manifest["units"][0]["rows"] == 12_000
    assert sum(c["rows"] for c in manifest["units"][0]["chunks"]) == 12_000
    assert root.exists()
