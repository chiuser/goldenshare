"""Minute nine-turn publication against small, real producer contracts.

The eleven-column inputs follow ``stk_mins_qfq.py`` / GOLD_STK_MINS_QFQ_SCHEMA;
the eight-column seed follows GOLD_STK_MINS_QFQ_NINETURN_SCHEMA. Prices 1..10
give four warmup bars, four prior upward bars, then literal target counts 5, 6.
No expected business value is calculated by the implementation under test.
All Lake, staging and DuckDB files live inside one disposable parent directory.
"""

import hashlib
import json
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs import qfq_nineturn as module
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io import stk_mins_qfq_publication as publication_module
from orchestrator.defs.paths import gold_stk_mins_qfq_nineturn_path
from orchestrator.defs.qfq_nineturn_integrity import audit_qfq_nineturn_integrity
from orchestrator.defs.resources import DuckDBResource

DAY = "2026-10-22"
PREVIOUS_DAY = "2026-10-21"
CODE = "000001.SZ"
EXPECTED_COLUMNS = (
    "ts_code", "freq", "trade_date", "trade_time", "up_count", "down_count",
    "nine_up_turn", "nine_down_turn",
)


class InterruptedPublication(RuntimeError):
    """Explicit injected process boundary, not an expected business rejection."""


def _write_query(path, sql):
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(copy_query_to_parquet(sql, path))


def _output_sql(freq=60, *, code=CODE, day=DAY, time_day=DAY):
    return f"""
    SELECT * FROM (VALUES
      ('{code}'::VARCHAR, {freq}::INTEGER, DATE '{day}',
        TIMESTAMP '{time_day} 10:30:00', 5::INTEGER, 0::INTEGER,
        NULL::VARCHAR, NULL::VARCHAR),
      ('{code}'::VARCHAR, {freq}::INTEGER, DATE '{day}',
        TIMESTAMP '{time_day} 11:30:00', 6::INTEGER, 0::INTEGER,
        NULL::VARCHAR, NULL::VARCHAR)
    ) AS rows(ts_code, freq, trade_date, trade_time, up_count, down_count,
      nine_up_turn, nine_down_turn)
    ORDER BY ts_code, trade_time
    """


def _write_qfq(path, freq, bars):
    """Use literal source types, independently checked against the producer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE source(ts_code VARCHAR, freq INTEGER, trade_date DATE, "
            "trade_time TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, "
            "close DOUBLE, vol DOUBLE, amount DOUBLE, exchange VARCHAR)"
        )
        rows = [
            (CODE, freq, date.fromisoformat(day), datetime.fromisoformat(f"{day} {time}"),
             close, close, close, close, 1.0, close, "SZSE")
            for day, time, close in bars
        ]
        connection.executemany("INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute(copy_query_to_parquet("SELECT * FROM source ORDER BY trade_time", path))
        observed = tuple((row[0], row[1]) for row in connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall())
        assert observed == (
            ("ts_code", "VARCHAR"), ("freq", "INTEGER"), ("trade_date", "DATE"),
            ("trade_time", "TIMESTAMP"), ("open", "DOUBLE"), ("high", "DOUBLE"),
            ("low", "DOUBLE"), ("close", "DOUBLE"), ("vol", "DOUBLE"),
            ("amount", "DOUBLE"), ("exchange", "VARCHAR"),
        )


def _identity(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@dataclass
class MinuteCase:
    root: Path
    freq: int
    plan: object
    sql: str
    target: Path
    seed: Path

    def write(self, *, sql=None, plan=None, run_id="one-root"):
        return module.write_gold_stk_mins_qfq_nineturn_partition(
            duckdb_resource=DuckDBResource(), lake_root=self.root, freq=self.freq,
            partition_key=DAY, run_id=run_id, select_sql=self.sql if sql is None else sql,
            source_plan=self.plan if plan is None else plan,
        )

    def replan(self):
        with duckdb.connect(":memory:") as connection:
            return module.plan_gold_stk_mins_qfq_nineturn_source(
                connection, lake_root=self.root, freq=self.freq,
                partition_key=DAY, previous_trade_date=PREVIOUS_DAY,
            )

    def publication(self):
        return publication_module.StkMinsQfqPublication(
            lake_root=self.root, family="nineturn", freq=self.freq,
            trade_dates=(DAY,), publication_id="one-root",
        )

    def receipt(self):
        publication = self.publication()
        return json.loads(publication._receipt_path(self.target).read_text())


@pytest.fixture
def minute_case():
    # The sibling staging directory is also inside parent, so leaving the
    # context removes every fixture/partial candidate/frozen-input file.
    with TemporaryDirectory(prefix="nineturn_minute_test_", dir="/private/tmp") as directory:
        parent = Path(directory)
        root = parent / "lake"
        root.mkdir()

        @contextmanager
        def isolated_connection():
            with duckdb.connect(":memory:", config={
                "temp_directory": str(parent / "duckdb"),
            }) as connection:
                yield connection

        with patch("orchestrator.defs.resources.connect_configured_duckdb", isolated_connection):
            def build(freq=60):
                source = root / "gold/quote/stk_mins_qfq" / f"freq={freq}" / f"ts_code={CODE}"
                _write_qfq(source / "year=2025/part-000.parquet", freq, [
                    ("2025-12-29", "10:30:00", 1.0), ("2025-12-29", "11:30:00", 2.0),
                    ("2025-12-30", "10:30:00", 3.0), ("2025-12-30", "11:30:00", 4.0),
                ])
                _write_qfq(source / "year=2026/part-000.parquet", freq, [
                    ("2026-10-20", "10:30:00", 5.0), ("2026-10-20", "11:30:00", 6.0),
                    (PREVIOUS_DAY, "10:30:00", 7.0), (PREVIOUS_DAY, "11:30:00", 8.0),
                    (DAY, "10:30:00", 9.0), (DAY, "11:30:00", 10.0),
                    ("2026-10-23", "10:30:00", 99.0),
                ])
                seed = gold_stk_mins_qfq_nineturn_path(root, freq, PREVIOUS_DAY)
                _write_query(seed, _output_sql(
                    freq, day=PREVIOUS_DAY, time_day=PREVIOUS_DAY,
                ).replace("5::INTEGER", "3::INTEGER").replace("6::INTEGER", "4::INTEGER"))
                with duckdb.connect(":memory:") as connection:
                    plan = module.plan_gold_stk_mins_qfq_nineturn_source(
                        connection, lake_root=root, freq=freq,
                        partition_key=DAY, previous_trade_date=PREVIOUS_DAY,
                    )
                sql = module.build_gold_stk_mins_qfq_nineturn_partition_select_sql(
                    source_paths=plan.source_paths, freq=freq, target_trade_date=DAY,
                    previous_partition_path=plan.previous_partition_path,
                    fallback_source_paths=plan.fallback_source_paths,
                    fallback_codes=plan.fallback_codes,
                )
                return MinuteCase(root, freq, plan, sql,
                                  gold_stk_mins_qfq_nineturn_path(root, freq, DAY), seed)

            yield build


@pytest.mark.parametrize("freq", [30, 60, 90, 120])
def test_real_contract_plan_formula_publication_and_original_integrity(minute_case, freq):
    case = minute_case(freq)
    seed_before = _identity(case.seed)
    result = case.write()
    with duckdb.connect(":memory:") as connection:
        rows = connection.execute(
            f"SELECT * FROM {read_parquet(case.target, hive_partitioning=False)} ORDER BY trade_time"
        ).fetchall()
        diagnostics = audit_qfq_nineturn_integrity(
            connection, target_path=case.target, source_paths=case.plan.source_paths,
            partition_key=DAY, freq=freq,
        )
    assert rows == [
        (CODE, freq, date(2026, 10, 22), datetime.fromisoformat("2026-10-22T10:30:00"), 5, 0, None, None),
        (CODE, freq, date(2026, 10, 22), datetime.fromisoformat("2026-10-22T11:30:00"), 6, 0, None, None),
    ]
    assert diagnostics.passed
    assert result.source_row_count == result.output_row_count == 2
    assert result.stock_code_count == 1
    assert result.fallback_recomputed_code_count == 0
    assert result.source_file_count == 2  # Seed is not added to old metadata.
    assert result.observed_columns == EXPECTED_COLUMNS
    # The legacy metadata hashes only QFQ relative path / size / mtime. Build
    # this expected value from the literal two input paths, not the helper.
    source_identities = []
    for year in (2025, 2026):
        relative = f"gold/quote/stk_mins_qfq/freq={freq}/ts_code={CODE}/year={year}/part-000.parquet"
        observed = (case.root / relative).stat()
        source_identities.append(f"{relative}\t{observed.st_size}\t{observed.st_mtime_ns}")
    expected_fingerprint = hashlib.sha256("\n".join(source_identities).encode()).hexdigest()
    assert result.source_fingerprint == expected_fingerprint
    assert _identity(case.seed) == seed_before
    assert not (case.root / "gold/indicator/stk_mins_qfq_nineturn/_staging").exists()
    assert case.receipt()["status"] == "promoted"


@pytest.mark.parametrize("failure", [
    "wrong_schema", "wrong_type", "wrong_code", "wrong_time", "cross_day", "wrong_freq",
    "wrong_date", "duplicate", "null_key", "negative_count", "invalid_signal",
])
def test_full_candidate_contract_rejects_before_replacing_existing_target(minute_case, failure):
    case = minute_case()
    _write_query(case.target, _output_sql())
    previous = case.target.read_bytes()
    sql = {
        "wrong_schema": "SELECT 1 AS marker",
        "wrong_type": _output_sql().replace("5::INTEGER", "5::DOUBLE"),
        "wrong_code": _output_sql(code="600000.SH"),
        "wrong_time": _output_sql().replace("10:30:00", "10:31:00"),
        "cross_day": _output_sql(time_day=PREVIOUS_DAY),
        "wrong_freq": _output_sql(freq=30),
        "wrong_date": _output_sql(day=PREVIOUS_DAY),
        "duplicate": _output_sql().replace("11:30:00", "10:30:00"),
        "null_key": _output_sql().replace(f"'{CODE}'::VARCHAR", "NULL::VARCHAR"),
        "negative_count": _output_sql().replace("5::INTEGER", "-1::INTEGER"),
        "invalid_signal": _output_sql().replace("NULL::VARCHAR", "'+9'::VARCHAR", 1),
    }[failure]
    with pytest.raises((ValueError, RuntimeError)):
        case.write(sql=sql)
    assert case.target.read_bytes() == previous
    receipt = case.receipt()
    assert receipt["status"] == "building"
    assert Path(receipt["candidate"]).is_file()  # Failed candidate is retained.


def test_normal_copy_and_candidate_digest_are_each_once(minute_case):
    case = minute_case()
    with (
        patch.object(module, "copy_query_to_parquet", wraps=copy_query_to_parquet) as copies,
        patch.object(publication_module, "_digest", wraps=publication_module._digest) as digests,
    ):
        case.write()
    assert copies.call_count == 1  # bind freezes a description, never executes source SQL.
    paths = [call.args[0] for call in digests.call_args_list]
    assert sum("candidates" in path.parts for path in paths) == 1
    assert case.target not in paths


@pytest.mark.parametrize("stage", ["validated", "before_replace", "after_replace", "promoted"])
def test_resume_reuses_validated_or_promoted_result_without_copy(minute_case, stage):
    case = minute_case()
    original_validated = publication_module.StkMinsQfqPublication.validated
    original_promote = publication_module.StkMinsQfqPublication.promote
    original_replace = os.replace

    def validated_then_exit(publication, *args, **kwargs):
        original_validated(publication, *args, **kwargs)
        raise InterruptedPublication("after validation")

    def promote_then_exit(publication):
        original_promote(publication)
        raise InterruptedPublication("after promotion before event")

    def replace_then_exit(source, target):
        if Path(target) != case.target:
            return original_replace(source, target)
        if stage == "before_replace":
            raise InterruptedPublication("before atomic replacement")
        original_replace(source, target)
        raise InterruptedPublication("after atomic replacement")

    seam = (
        patch.object(publication_module.StkMinsQfqPublication, "validated", validated_then_exit)
        if stage == "validated" else
        patch.object(publication_module.StkMinsQfqPublication, "promote", promote_then_exit)
        if stage == "promoted" else
        patch.object(publication_module.os, "replace", replace_then_exit)
    )
    with seam, pytest.raises(InterruptedPublication):
        case.write()
    if case.target.exists():
        completed_identity = _identity(case.target)
    else:
        completed_identity = None
    with (
        patch.object(module, "copy_query_to_parquet", side_effect=AssertionError("repeated COPY")),
        patch.object(publication_module.StkMinsQfqPublication, "validated",
                     side_effect=AssertionError("repeated validation")),
        patch.object(publication_module, "_digest", wraps=publication_module._digest) as digests,
    ):
        result = case.write(plan=case.replan())
    assert result.output_row_count == 2
    assert result.stock_code_count == 1
    assert case.receipt()["status"] == "promoted"
    if completed_identity is not None:
        assert _identity(case.target) == completed_identity
    data_reads = [call.args[0] for call in digests.call_args_list
                  if "candidates" in call.args[0].parts or call.args[0] == case.target]
    assert len(data_reads) == 1  # One recovery hash; subsequent promote uses stat.


def test_building_failure_preserves_partial_candidate_and_rebuilds_once(minute_case):
    case = minute_case()

    def partial_copy(sql, path, **kwargs):
        path.write_bytes(b"deliberately interrupted parquet write")
        raise InterruptedPublication("during COPY")

    with patch.object(module, "copy_query_to_parquet", partial_copy), pytest.raises(InterruptedPublication):
        case.write()
    previous = Path(case.receipt()["candidate"])
    assert previous.read_bytes() == b"deliberately interrupted parquet write"
    assert not case.target.exists()
    with patch.object(module, "copy_query_to_parquet", wraps=copy_query_to_parquet) as copies:
        case.write(plan=case.replan())
    assert copies.call_count == 1
    assert previous.is_file()
    assert previous != Path(case.receipt()["candidate"])


def test_candidate_changed_after_business_audit_cannot_be_recorded_as_validated(minute_case):
    case = minute_case()
    original_validated = publication_module.StkMinsQfqPublication.validated

    def replace_before_validation(publication, target, candidate, row_count, **kwargs):
        # This file was never audited: change a valid business value after the
        # writer's integrity check, immediately before its one digest.
        replacement = candidate.with_name("different-unaudited.parquet")
        _write_query(replacement, _output_sql().replace("5::INTEGER", "50::INTEGER"))
        os.replace(replacement, candidate)
        return original_validated(publication, target, candidate, row_count, **kwargs)

    with (
        patch.object(publication_module.StkMinsQfqPublication, "validated", replace_before_validation),
        pytest.raises((ValueError, RuntimeError)),
    ):
        case.write()
    assert not case.target.exists()
    # A later attempt must rebuild and revalidate, never reuse a false approval.
    assert case.receipt()["status"] == "building"
    rejected_candidate = Path(case.receipt()["candidate"])
    with patch.object(module, "copy_query_to_parquet", wraps=copy_query_to_parquet) as copies:
        result = case.write(plan=case.replan())
    assert copies.call_count == 1
    assert result.output_row_count == 2
    assert case.receipt()["status"] == "promoted"
    assert rejected_candidate.is_file()


@pytest.mark.parametrize("changed", ["source", "seed", "sql"])
def test_changed_input_cannot_resume_even_when_rows_are_unchanged(minute_case, changed):
    case = minute_case()
    case.write()
    completed = _identity(case.target)
    sql = case.sql
    if changed == "sql":
        sql += "\n-- same rows, different request"
    else:
        path = case.seed if changed == "seed" else case.plan.source_paths[0]
        identity = path.stat()
        path.write_bytes(path.read_bytes())  # Identical rows, different physical input.
        os.utime(path, ns=(identity.st_atime_ns, identity.st_mtime_ns))
    with (
        patch.object(module, "copy_query_to_parquet", side_effect=AssertionError("must reject before COPY")),
        pytest.raises((ValueError, RuntimeError)),
    ):
        case.write(plan=case.replan(), sql=sql)
    assert _identity(case.target) == completed


def test_missing_input_snapshot_is_rejected_before_any_candidate(minute_case):
    case = minute_case()
    with pytest.raises((ValueError, RuntimeError)):
        case.write(plan=replace(case.plan, input_file_identities=None))
    assert not case.target.exists()


def test_source_and_seed_changes_after_planning_are_rejected(minute_case):
    case = minute_case()
    for path in (case.plan.source_paths[0], case.seed):
        old_plan = case.replan()
        path.write_bytes(path.read_bytes())
        with pytest.raises((ValueError, RuntimeError)):
            case.write(plan=old_plan)
    assert not case.target.exists()


@pytest.mark.parametrize("changed", ["source", "seed"])
def test_input_changed_while_copy_is_prepared_cannot_be_promoted(minute_case, changed):
    case = minute_case()
    path = case.seed if changed == "seed" else case.plan.source_paths[0]

    def change_input(sql, candidate, **kwargs):
        statement = copy_query_to_parquet(sql, candidate, **kwargs)
        path.write_bytes(path.read_bytes())
        return statement

    with (
        patch.object(module, "copy_query_to_parquet", change_input),
        pytest.raises((ValueError, RuntimeError)),
    ):
        case.write()
    assert not case.target.exists()
    assert case.receipt()["status"] == "building"


@pytest.mark.parametrize("conflict", [
    "receipt", "same_bytes_in_place", "same_bytes_new_inode", "ctime_only", "different_content",
])
def test_conflicting_completion_record_or_target_blocks_resume(minute_case, conflict):
    case = minute_case()
    case.write()
    if conflict == "receipt":
        publication = case.publication()
        publication._receipt_path(case.target).unlink()
    elif conflict == "same_bytes_in_place":
        case.target.write_bytes(case.target.read_bytes())
    elif conflict == "same_bytes_new_inode":
        previous = case.target.stat()
        replacement = case.target.with_name("external-replacement.parquet")
        replacement.write_bytes(case.target.read_bytes())
        os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        os.replace(replacement, case.target)
    elif conflict == "ctime_only":
        previous = _identity(case.target)
        mode = stat.S_IMODE(case.target.stat().st_mode)
        os.chmod(case.target, mode ^ stat.S_IWUSR)
        os.chmod(case.target, mode)
        assert _identity(case.target)[:4] == previous[:4]
        assert _identity(case.target)[4] != previous[4]
    else:
        _write_query(case.target, _output_sql().replace("5::INTEGER", "50::INTEGER"))
    before = case.target.read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        case.write(plan=case.replan())
    assert case.target.read_bytes() == before


def test_family_writer_lock_prevents_second_nineturn_writer(minute_case):
    case = minute_case()
    with case.publication(), pytest.raises(BlockingIOError):
        case.write()
    assert not case.target.exists()


def test_cross_device_candidate_is_rejected_before_copy(minute_case):
    case = minute_case()
    original_stat = Path.stat

    def other_device(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if "candidates" in path.parts and stat.S_ISDIR(value.st_mode):
            values = list(value)
            values[2] += 1
            return os.stat_result(values)
        return value

    with (
        patch.object(Path, "stat", other_device),
        patch.object(module, "copy_query_to_parquet", side_effect=AssertionError("must not COPY")),
        pytest.raises(ValueError, match="same filesystem"),
    ):
        case.write()
    assert not case.target.exists()


def test_symbolic_source_replacement_cannot_bypass_plan_identity(minute_case):
    case = minute_case()
    source = case.plan.source_paths[0]
    moved = source.with_name("original.parquet")
    source.rename(moved)
    source.symlink_to(moved)
    with pytest.raises((ValueError, RuntimeError)):
        case.write()
    assert not case.target.exists()
