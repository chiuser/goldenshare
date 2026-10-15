import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
)

from .stock_weekly_capture_test_support import (prod_frame, prod_plan)


def test_exact_decimal_null_and_receipt_replay(tmp_path):
    plan = prod_plan()
    unit = plan.units[0]
    store = WeeklyCaptureStore(tmp_path, plan)
    with store.locked(), duckdb.connect() as connection:
        attempt = store.begin_attempt(unit)
        chunk = store.write_chunk(connection, prod_frame(), unit, attempt, 0)
        receipt = store.seal(connection, unit, [chunk], 1, {"snapshot": "100:200:"})
        values = connection.execute(
            "SELECT open,close,trade_date FROM read_parquet(?)",
            [str(attempt / "chunk-0000.parquet")],
        ).fetchone()
        assert (
            str(values[0]) == "10.1234"
            and values[1] is None
            and values[2] == "20200228"
        )
        assert store.resume(connection, unit) == receipt
        (attempt.parent / "checkpoint.json").unlink()
        assert store.resume(connection, unit) == receipt
        assert (
            json.loads((attempt.parent / "checkpoint.json").read_text())["status"]
            == "captured"
        )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("open", "1.12345", "decimal_precision_loss"),
        ("trade_date", "20200199", "source_key_invalid"),
        ("trade_date", "20210101", "source_range_mismatch"),
        ("ts_code", "000001.SZ", "source_range_mismatch"),
        ("freq", "month", "source_range_mismatch"),
        ("ts_code", None, "required_field_null"),
    ],
)
def test_bad_source_rejected_before_promotion(tmp_path, field, value, reason):
    plan = prod_plan()
    store = WeeklyCaptureStore(tmp_path, plan)
    frame = prod_frame()
    frame[field] = value
    with store.locked(), duckdb.connect() as connection:
        attempt = store.begin_attempt(plan.units[0])
        with pytest.raises(WeeklyCaptureError, match=reason):
            store.write_chunk(connection, frame, plan.units[0], attempt, 0)
        assert not list(attempt.glob("*.parquet"))


def test_trailing_zero_precision_and_overflow(tmp_path):
    plan = prod_plan()
    store = WeeklyCaptureStore(tmp_path, plan)
    with store.locked(), duckdb.connect() as connection:
        attempt = store.begin_attempt(plan.units[0])
        frame = prod_frame()
        frame["open"] = "10.12340000"
        store.write_chunk(connection, frame, plan.units[0], attempt, 0)
        frame["open"] = "9999999999999999999999.0000"
        with pytest.raises(duckdb.ConversionException):
            store.write_chunk(connection, frame, plan.units[0], attempt, 1)


def test_duplicate_keys_across_chunks_rejected(tmp_path):
    plan = prod_plan()
    unit = plan.units[0]
    store = WeeklyCaptureStore(tmp_path, plan)
    with store.locked(), duckdb.connect() as connection:
        attempt = store.begin_attempt(unit)
        chunks = [
            store.write_chunk(connection, prod_frame(), unit, attempt, i)
            for i in range(2)
        ]
        with pytest.raises(WeeklyCaptureError, match="source_duplicate_key"):
            store.seal(connection, unit, chunks, 2, {})
        assert not (attempt.parent / "receipt.json").exists()


def test_tampered_chunk_does_not_resume(tmp_path):
    plan = prod_plan()
    store = WeeklyCaptureStore(tmp_path, plan)
    unit = plan.units[0]
    with store.locked(), duckdb.connect() as connection:
        attempt = store.begin_attempt(unit)
        chunk = store.write_chunk(connection, prod_frame(), unit, attempt, 0)
        store.seal(connection, unit, [chunk], 1, {})
        with (attempt / "chunk-0000.parquet").open("ab") as stream:
            stream.write(b"bad")
        with pytest.raises(WeeklyCaptureError, match="capture_hash_mismatch"):
            store.resume(connection, unit)


def test_lock_path_and_foreign_unit_rejected(tmp_path):
    plan = prod_plan()
    with pytest.raises(WeeklyCaptureError, match="capture_root_forbidden"):
        WeeklyCaptureStore(Path("/Volumes/datasource/data_lake/raw"), plan)
    with pytest.raises(WeeklyCaptureError, match="capture_path_invalid"):
        WeeklyCaptureStore(tmp_path / ".." / "escape", plan)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(WeeklyCaptureError, match="symlink"):
        WeeklyCaptureStore(alias, plan)
    first = WeeklyCaptureStore(tmp_path, plan)
    second = WeeklyCaptureStore(tmp_path, plan)
    with first.locked():
        with (
            pytest.raises(WeeklyCaptureError, match="capture_writer_active"),
            second.locked(),
        ):
            pass
        with pytest.raises(WeeklyCaptureError, match="unit_not_in_frozen_plan"):
            first.begin_attempt(replace(plan.units[0], max_rows=1))


def test_mixed_source_manifest_rejected(tmp_path):
    plan = prod_plan()
    with pytest.raises(ValueError):
        replace(plan, source="primary_unadjusted")
