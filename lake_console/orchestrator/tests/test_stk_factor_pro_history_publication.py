"""Small per-file history tests; batch-size boundaries live in the other file.

The shared isolated fixture performs the native planner/download chain, using
doc328's full fields and literal upstream three-column factor files.
"""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import dagster as dg
import pytest
from duckdb import Error as DuckDBError

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.io import stk_factor_pro_publication as publication
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from tests.stk_factor_pro_history_test_support import connection, row
from tests.test_stk_factor_pro_history_publication_batches import setup, write_rows

A, B = "000001.SZ", "600000.SH"


def run(conn, args):
    return tuple(publication.publish_stk_factor_pro_history(conn, **args))


def run_incomplete(conn, args):
    results = []
    with pytest.raises(dg.Failure):
        results.extend(publication.publish_stk_factor_pro_history(conn, **args))
    return tuple(results)


def test_single_history_file_records_bind_actual_day_and_complete_schema(tmp_path):
    with connection(tmp_path) as conn:
        lake, root, days, _, _, _, args = setup(conn, tmp_path, 1)
        results = run(conn, args)
        assert [(target.trade_date, target.layer) for target, _ in results] == [
            (days[0], "raw"),
            (days[0], "silver"),
        ]
        for target, audit in results:
            assert not target.skip_no_file and audit is not None and audit.passed
            assert target.scope_rows == 1 and target.scope_content_version == 1
            record = publication.read_stk_factor_pro_publication_record(
                root / target.checkpoint_ref.relative_path
            )
            assert record.phase == "history" and record.trade_date == days[0]
            assert record.day_source_digest is None
            assert (
                record.history_input_digest
                == args["source"].source_complete.history_input_digest
            )
            assert (
                record.source_manifest_digest
                == args["source"].source_complete.files_manifest_digest
            )
            assert (
                record.unrefreshed_count == 0
                and record.unrefreshed_keys_ref is not None
            )
            diagnostic = root / record.unrefreshed_keys_ref.relative_path
            assert (
                factor_file_sha(diagnostic) == record.unrefreshed_keys_ref.file_sha256
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                    [str(diagnostic)],
                ).fetchone()[0]
                == 0
            )
            schema = conn.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(diagnostic)],
            ).fetchall()
            assert tuple((item[0], item[1]) for item in schema) == (
                ("layer", "VARCHAR"),
                ("ts_code", "VARCHAR"),
                ("trade_date", "DATE"),
            )
        assert (root / "publication/history/publication-complete.json").is_file()
        assert raw_stk_factor_pro_path(lake, days[0].isoformat()).is_file()


def test_missing_source_key_preserves_old_raw_and_reports_each_old_layer(tmp_path):
    with connection(tmp_path) as conn:
        lake, root, days, _, _, _, args = setup(
            conn, tmp_path, 1, missing_dates=(date(2026, 10, 15),)
        )
        day = days[0]
        raw, silver = (
            raw_stk_factor_pro_path(lake, day.isoformat()),
            silver_stock_factor_pro_path(lake, day.isoformat()),
        )
        old_rows = (
            row(A, day.strftime("%Y%m%d"), close=Decimal(20)),
            row(B, day.strftime("%Y%m%d"), close=Decimal(30)),
        )
        write_rows(conn, raw, old_rows, layer="raw")
        write_rows(conn, silver, old_rows, layer="silver")
        results = run_incomplete(conn, args)
        assert [target.unrefreshed_count for target, _ in results] == [1, 1]
        assert conn.execute(
            "SELECT ts_code,close FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(raw)],
        ).fetchall() == [(A, 20.0), (B, 30.0)]
        assert conn.execute(
            "SELECT ts_code,close FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(silver)],
        ).fetchall() == [(A, 20.0), (B, 30.0)]
        for target, _ in results:
            record = publication.read_stk_factor_pro_publication_record(
                root / target.checkpoint_ref.relative_path
            )
            assert conn.execute(
                "SELECT layer,ts_code,trade_date FROM read_parquet(?,hive_partitioning=false)",
                [str(root / record.unrefreshed_keys_ref.relative_path)],
            ).fetchall() == [(target.layer, A, day)]
        # Whole-range failure does not erase the real per-file results.
        assert not (root / "publication/history/publication-complete.json").exists()


def test_silver_diagnostic_uses_its_own_old_keys(tmp_path):
    with connection(tmp_path) as conn:
        lake, _, days, _, _, _, args = setup(
            conn, tmp_path, 1, missing_dates=(date(2026, 10, 15),)
        )
        day = days[0]
        write_rows(
            conn,
            raw_stk_factor_pro_path(lake, day.isoformat()),
            (row(B, day.strftime("%Y%m%d")),),
            layer="raw",
        )
        write_rows(
            conn,
            silver_stock_factor_pro_path(lake, day.isoformat()),
            (row(A, day.strftime("%Y%m%d")),),
            layer="silver",
        )
        results = run_incomplete(conn, args)
        assert [target.unrefreshed_count for target, _ in results] == [0, 1]


@pytest.mark.parametrize("fault", ["closed-date", "unregistered", "plan-not-saved"])
def test_all_history_source_checks_precede_first_formal_write(tmp_path, fault):
    with connection(tmp_path) as conn:
        lake, _, days, _, _, _, args = setup(conn, tmp_path, 3)
        if fault == "closed-date":
            args["calendar"] = tuple(day for day in args["calendar"] if day != days[1])
        elif fault == "unregistered":
            args["registered_dates"] = (days[0], days[2])
        else:
            args["plan"] = replace(args["plan"], revision=2)
        with pytest.raises(ValueError):
            run(conn, args)
        assert all(
            not raw_stk_factor_pro_path(lake, day.isoformat()).exists() for day in days
        )


def test_first_promotion_rechecks_inputs_once_and_stops_before_write(tmp_path):
    with connection(tmp_path) as conn:
        lake, _, days, _, _, _, args = setup(conn, tmp_path, 1)
        calls = 0

        def missing():
            nonlocal calls
            calls += 1
            raise RuntimeError("Raw覆盖已不再齐备")

        args["recheck_inputs"] = missing
        with pytest.raises(RuntimeError, match="不再齐备"):
            run(conn, args)
        assert calls == 1
        assert not raw_stk_factor_pro_path(lake, days[0].isoformat()).exists()


def test_formal_target_changed_after_candidate_stops_without_overwrite(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        lake, _, days, _, _, _, args = setup(conn, tmp_path, 1)
        target = raw_stk_factor_pro_path(lake, days[0].isoformat())
        write_rows(
            conn,
            target,
            (row(A, days[0].strftime("%Y%m%d"), close=Decimal(30)),),
            layer="raw",
        )
        original = publication.build_stk_factor_pro_raw_candidate_from_relation

        def changed(connection, **kwargs):
            result = original(connection, **kwargs)
            write_rows(
                connection,
                target,
                (row(A, days[0].strftime("%Y%m%d"), close=Decimal(50)),),
                layer="raw",
            )
            return result

        monkeypatch.setattr(
            publication, "build_stk_factor_pro_raw_candidate_from_relation", changed
        )
        with pytest.raises(ValueError, match="正式目标.*改变"):
            run(conn, args)
        assert (
            conn.execute(
                "SELECT close FROM read_parquet(?,hive_partitioning=false)",
                [str(target)],
            ).fetchone()[0]
            == 50.0
        )


def test_history_candidate_symlink_rejected_before_outside_write(tmp_path):
    with connection(tmp_path) as conn:
        _, root, _, _, _, _, args = setup(conn, tmp_path, 1)
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "candidates").mkdir()
        (root / "candidates/history").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError):
            run(conn, args)
        assert tuple(outside.iterdir()) == ()


class FailedFirstCleanup:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            raise DuckDBError("controlled first cleanup failure")


@pytest.mark.parametrize("mode", ["business-error", "normal", "close"])
def test_cleanup_tries_every_resource_preserves_primary_and_surfaces_close_failure(
    mode,
):
    conn = FailedFirstCleanup()
    primary = ValueError("original source error")
    if mode == "business-error":
        with (
            pytest.raises(ValueError) as actual,
            publication._history_cleanup(
                conn, publication._release_stk_factor_pro_history_batch
            ),
        ):
            raise primary
        assert actual.value is primary
        assert any("清理同时失败" in note for note in primary.__notes__)
    elif mode == "normal":
        with (
            pytest.raises(DuckDBError, match="first cleanup"),
            publication._history_cleanup(
                conn, publication._release_stk_factor_pro_history_batch
            ),
        ):
            pass
    else:

        def values():
            with publication._history_cleanup(
                conn, publication._release_stk_factor_pro_history_batch
            ):
                yield None

        iterator = values()
        next(iterator)
        with pytest.raises(DuckDBError, match="first cleanup"):
            iterator.close()
    assert len(conn.statements) == 8
    assert (
        conn.statements[-1]
        == "DROP TABLE IF EXISTS stk_factor_pro_history_batch_source"
    )


@pytest.mark.parametrize("fault", ["unknown-field", "wrong-identity", "wrong-phase"])
def test_history_record_reader_keeps_closed_contract_and_path(tmp_path, fault):
    with connection(tmp_path) as conn:
        _, root, _, _, _, _, args = setup(conn, tmp_path, 1)
        iterator = publication.publish_stk_factor_pro_history(conn, **args)
        target, _ = next(iterator)
        iterator.close()
        path = root / target.checkpoint_ref.relative_path
        value = json.loads(path.read_text())
        if fault == "unknown-field":
            value["new_field"] = True
        elif fault == "wrong-identity":
            value["unrefreshed_keys_ref"]["creator_run_id"] = "other-run"
        else:
            value["phase"] = "day"
        path.write_text(json.dumps(value))
        with pytest.raises((ValueError, TypeError)):
            publication.read_stk_factor_pro_publication_record(path)
