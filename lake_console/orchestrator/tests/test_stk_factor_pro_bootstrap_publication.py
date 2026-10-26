"""Real temporary Parquet/atomic replacement, with independent business values."""

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import operation_path
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection


def setup(conn, tmp_path):
    lake, staging, approval, _ = approval_fixture(conn, tmp_path)
    source = source_fixture(
        conn, staging_root=staging, approval=approval, rows=(native_row(),)
    )
    return {
        "lake_root": lake,
        "staging_root": staging,
        "approval": approval,
        "source_complete": source,
        "before_publish": lambda: None,
    }


def test_full_two_layer_publication_and_repeat_zero_source_reads(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        raw, silver = P.publish_bootstrap_date(conn, **args)
        assert raw.passed and silver.passed and raw.row_count == silver.row_count == 1
        assert conn.execute(
            "SELECT ts_code,trade_date,open,close FROM read_parquet(?)",
            [str(silver.path)],
        ).fetchone() == ("000001.SZ", args["source_complete"].trade_date, 1.25, 10.0)
        monkeypatch.setattr(
            P,
            "load_complete_source",
            lambda *_a, **_k: pytest.fail("complete date source must not be rescanned"),
        )
        assert P.publish_bootstrap_date(conn, **args) == (raw, silver)
        assert (
            conn.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name LIKE 'stk_factor_pro_%'"
            ).fetchone()[0]
            == 0
        )


def test_raw_completed_silver_failure_then_same_operation_continues(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        original = P.build_stk_factor_pro_silver_candidate

        def fail(*_a, **_k):
            raise OSError("silver failure")

        monkeypatch.setattr(P, "build_stk_factor_pro_silver_candidate", fail)
        with pytest.raises(OSError, match="silver failure"):
            P.publish_bootstrap_date(conn, **args)
        monkeypatch.setattr(P, "build_stk_factor_pro_silver_candidate", original)
        monkeypatch.setattr(
            P,
            "load_complete_source",
            lambda *_a, **_k: pytest.fail("Raw complete must be reused"),
        )
        raw, silver = P.publish_bootstrap_date(conn, **args)
        assert raw.passed and silver.passed


def test_replace_completed_but_record_write_failed_can_recover(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        original = P.write_stk_factor_pro_bootstrap_publication_complete

        def fail(**kwargs):
            if kwargs["record"].layer == "raw":
                raise OSError("checkpoint failure")
            return original(**kwargs)

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", fail
        )
        with pytest.raises(OSError, match="checkpoint"):
            P.publish_bootstrap_date(conn, **args)
        assert not operation_path(
            args["staging_root"],
            args["approval"],
            "candidates/2019-10-16/raw/part-000.parquet",
        ).exists()
        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", original
        )
        assert all(a.passed for a in P.publish_bootstrap_date(conn, **args))


def test_changed_complete_target_never_overwritten(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        raw, _ = P.publish_bootstrap_date(conn, **args)
        raw.path.write_bytes(b"external modification")
        before = factor_file_sha(raw.path)
        with pytest.raises(ValueError, match="改变"):
            P.publish_bootstrap_date(conn, **args)
        assert factor_file_sha(raw.path) == before


def test_existing_different_target_stops_before_replace(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        target = P._target(args["lake_root"], args["source_complete"].trade_date, "raw")
        target.parent.mkdir(parents=True)
        source_path = operation_path(
            args["staging_root"],
            args["approval"],
            args["source_complete"].fragments[0].fragment.relative_path,
        )
        from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet

        conn.execute(
            copy_query_to_parquet(
                f"SELECT * REPLACE (99.0::DOUBLE AS close) FROM {read_parquet(source_path, hive_partitioning=False)}",
                target,
            )
        )
        before = factor_file_sha(target)
        with pytest.raises(ValueError, match="内容不同"):
            P.publish_bootstrap_date(conn, **args)
        assert factor_file_sha(target) == before
