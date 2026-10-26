"""LLD 8 whole-range completion on one-date real isolated download fixtures."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from orchestrator.defs.io import stk_factor_pro_publication as publication
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from tests.stk_factor_pro_history_test_support import connection, row, write_factor_file
from tests.test_stk_factor_pro_history_publication_batches import setup, write_rows

T, P = date(2026, 10, 16), date(2026, 10, 15)
A, B = "000001.SZ", "600000.SH"


def complete_path(root):
    return root / "publication/history/publication-complete.json"


def assert_released(conn):
    assert (
        conn.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name IN "
            "('stk_factor_pro_history_batch_source','stk_factor_pro_history_day_source',"
            "'stk_factor_pro_day_prior','stk_factor_pro_raw_expected','stk_factor_pro_silver_expected',"
            "'stk_factor_pro_history_prior_silver','stk_factor_pro_history_unrefreshed_keys')"
        ).fetchone()[0]
        == 0
    )


def test_complete_record_covers_exact_delivered_targets_and_current_source(tmp_path):
    with connection(tmp_path) as conn:
        _, root, days, _, _, _, args = setup(conn, tmp_path, 1)
        facts = args["recheck_inputs"]()
        calls = []

        def observed():
            calls.append(True)
            return facts

        args["recheck_inputs"] = observed
        delivered = tuple(publication.publish_stk_factor_pro_history(conn, **args))
        record = publication.read_stk_factor_pro_history_publication_complete(
            root, expected_target=T, expected_run_id="run-a"
        )
        assert record.targets == tuple(target for target, _ in delivered)
        assert [(target.trade_date, target.layer) for target in record.targets] == [
            (days[0], "raw"),
            (days[0], "silver"),
        ]
        assert (
            record.identity == args["source"].identity
            and record.contract == args["source"].contract
        )
        assert record.source_complete_ref == args["source"].source_complete_ref
        assert record.scope_digest == args["source"].source_complete.scope_digest
        assert (
            record.history_input_digest
            == args["source"].source_complete.history_input_digest
        )
        assert record.day_source_digest is None
        # Download already checked once in setup. Publication checks only at the
        # first promotion and final completion, not per file or historical date.
        assert len(calls) == 2
        assert_released(conn)


@pytest.mark.parametrize("fault", ["factor", "raw-incomplete", "silver-not-ready"])
def test_final_input_change_keeps_valid_files_but_no_range_complete(tmp_path, fault):
    with connection(tmp_path) as conn:
        lake, root, days, _, _, _, args = setup(conn, tmp_path, 1)
        facts = args["recheck_inputs"]()
        calls = 0

        def changed():
            nonlocal calls
            calls += 1
            if calls == 1:
                return facts
            if fault == "factor":
                ft = write_factor_file(conn, lake, T, ((A, 3.0), (B, 1.0)))
                return ft, facts[1], facts[2], facts[3]
            if fault == "raw-incomplete":
                return facts[0], facts[1], replace(facts[2], complete=False), facts[3]
            return facts[0], facts[1], facts[2], replace(facts[3], ready=False)

        args["recheck_inputs"] = changed
        iterator = publication.publish_stk_factor_pro_history(conn, **args)
        assert next(iterator)[0].layer == "raw"
        assert next(iterator)[0].layer == "silver"
        with pytest.raises(ValueError):
            next(iterator)
        assert calls == 2 and not complete_path(root).exists()
        assert raw_stk_factor_pro_path(lake, days[0].isoformat()).is_file()
        assert silver_stock_factor_pro_path(lake, days[0].isoformat()).is_file()
        assert_released(conn)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-checkpoint",
        "changed-target",
        "changed-ranges",
        "changed-source-metadata",
    ],
)
def test_final_physical_or_metadata_identity_must_still_match(tmp_path, fault):
    with connection(tmp_path) as conn:
        lake, root, days, _, _, _, args = setup(conn, tmp_path, 1)
        iterator = publication.publish_stk_factor_pro_history(conn, **args)
        raw, _ = next(iterator)
        next(iterator)
        if fault == "missing-checkpoint":
            (root / raw.checkpoint_ref.relative_path).unlink()
        elif fault == "changed-target":
            write_rows(
                conn,
                raw_stk_factor_pro_path(lake, days[0].isoformat()),
                (row(A, days[0].strftime("%Y%m%d"), close=Decimal(77)),),
                layer="raw",
            )
        else:
            path = root / (
                "history-ranges.parquet"
                if fault == "changed-ranges"
                else "source/history/source-complete.json"
            )
            with path.open("ab") as stream:
                stream.write(b"\nchanged")
        with pytest.raises((ValueError, FileNotFoundError)):
            next(iterator)
        assert not complete_path(root).exists()
        assert_released(conn)


def test_write_complete_failure_does_not_undo_published_files(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        lake, root, days, _, _, _, args = setup(conn, tmp_path, 1)

        def failed(root, identity, relative, record):
            assert relative == "publication/history/publication-complete.json"
            raise OSError("controlled complete write failure")

        monkeypatch.setattr(publication, "_json_write", failed)
        iterator = publication.publish_stk_factor_pro_history(conn, **args)
        next(iterator)
        next(iterator)
        with pytest.raises(OSError, match="controlled"):
            next(iterator)
        assert not complete_path(root).exists()
        assert raw_stk_factor_pro_path(lake, days[0].isoformat()).is_file()
        assert silver_stock_factor_pro_path(lake, days[0].isoformat()).is_file()
        assert_released(conn)


def test_explicit_skips_complete_without_file_audits_or_fake_checkpoints(tmp_path):
    with connection(tmp_path) as conn:
        _, root, _, _, _, _, args = setup(conn, tmp_path, 1, missing_dates=(P,))
        delivered = tuple(publication.publish_stk_factor_pro_history(conn, **args))
        assert len(delivered) == 2
        assert all(
            target.skip_no_file
            and audit is None
            and target.checkpoint_ref is None
            and target.file_sha256 is None
            for target, audit in delivered
        )
        record = publication.read_stk_factor_pro_history_publication_complete(
            root, expected_target=T, expected_run_id="run-a"
        )
        assert record.targets == tuple(target for target, _ in delivered)
        assert all(target.scope_rows == 0 for target in record.targets)
        assert_released(conn)


class NoSecondFieldAudit:
    def __init__(self, conn):
        self.conn, self.final = conn, False

    def __getattr__(self, key):
        return getattr(self.conn, key)

    def execute(self, query, parameters=None):
        if self.final:
            # Final metadata and SHA checks must not rescan source units or join
            # all 261 fields again. T/P key/value queries remain permitted.
            text = str(query) + repr(parameters)
            assert "source/history/units/" not in text
            assert "FULL OUTER JOIN" not in str(query).upper()
        return (
            self.conn.execute(query)
            if parameters is None
            else self.conn.execute(query, parameters)
        )


def test_completion_reuses_file_audits_without_another_full_field_scan(tmp_path):
    with connection(tmp_path) as conn:
        _, root, _, _, _, _, args = setup(conn, tmp_path, 1)
        observed = NoSecondFieldAudit(conn)
        iterator = publication.publish_stk_factor_pro_history(observed, **args)
        next(iterator)
        next(iterator)
        observed.final = True
        with pytest.raises(StopIteration):
            next(iterator)
        assert complete_path(root).is_file()
