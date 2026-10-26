"""A historical date reuses B-K+U while the day entry remains type restricted."""

from datetime import date
from types import SimpleNamespace

import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from tests.stk_factor_pro_history_test_support import NAMES, connection

P = date(2026, 10, 15)
A, B, C = "000001.SZ", "600000.SH", "000002.SZ"


def literal_row(code, value, raw_day="20261015"):
    # Full fields independently enumerated from doc328 by the shared fixture.
    return "SELECT " + ",".join(
        f"'{code}'::VARCHAR AS ts_code"
        if field == "ts_code"
        else f"'{raw_day}'::VARCHAR AS trade_date"
        if field == "trade_date"
        else 'NULL::DOUBLE AS "pe"'
        if field == "pe"
        else f'{value}::DOUBLE AS "{field}"'
        for field in NAMES
    )


def input_table(conn, *, raw_day="20261015"):
    conn.execute(
        f"CREATE TEMP TABLE {candidates.HISTORY_DAY_SOURCE} AS "
        f"{literal_row(A, 12.5, raw_day)} UNION ALL {literal_row(C, -1.25, raw_day)}"
    )


def build(conn, root, target, *, source_relation=None, prior=None, day=P):
    return candidates.build_stk_factor_pro_raw_candidate_from_relation(
        conn,
        source_relation=candidates.HISTORY_DAY_SOURCE
        if source_relation is None
        else source_relation,
        target_trade_date=day,
        prior_path=prior,
        candidate_path=target,
        run_root=root,
    )


def test_history_date_uses_whole_raw_merge_and_preserves_unrelated_all_fields(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    old, output = (
        tmp_path / "prior.parquet",
        root / f"candidates/history/{P}/raw/data.parquet",
    )
    with connection(tmp_path) as conn:
        conn.execute(
            "CREATE TEMP TABLE original AS "
            + literal_row(A, 7)
            + " UNION ALL "
            + literal_row(B, -4)
        )
        conn.execute(
            copy_query_to_parquet("SELECT * FROM original ORDER BY ts_code", old)
        )
        input_table(conn)
        audit = build(conn, root, output, prior=old)
        assert audit.passed and audit.row_count == 3 and audit.trade_date == P
        assert conn.execute(
            "SELECT ts_code,trade_date,close,pe FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(output)],
        ).fetchall() == [
            (A, "20261015", 12.5, None),
            (C, "20261015", -1.25, None),
            (B, "20261015", -4.0, None),
        ]
        # Both directions include all 261 business columns of the unrelated B.
        assert (
            conn.execute(
                "SELECT count(*) FROM ((SELECT * FROM original WHERE ts_code=?) EXCEPT ALL "
                "(SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?))",
                [B, str(output), B],
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM ((SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?) EXCEPT ALL "
                "(SELECT * FROM original WHERE ts_code=?))",
                [str(output), B, B],
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "relation", ["external", "stk_factor_pro_history_day_source;DROP TABLE x", "x.y"]
)
def test_arbitrary_relation_or_sql_is_rejected_before_copy(tmp_path, relation):
    root = tmp_path / "run"
    root.mkdir()
    output = root / "candidates/history/raw/data.parquet"
    with connection(tmp_path) as conn, pytest.raises(ValueError, match="内部已核单日"):
        build(conn, root, output, source_relation=relation)
    assert not output.exists()


@pytest.mark.parametrize("day", ["2026-10-15", None])
def test_explicit_processing_date_must_be_date(tmp_path, day):
    root = tmp_path / "run"
    root.mkdir()
    output = root / "candidates/history/raw/data.parquet"
    with connection(tmp_path) as conn, pytest.raises(ValueError):
        build(conn, root, output, day=day)
    assert not output.exists()


def test_history_rows_of_another_date_cannot_be_silently_written(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    output = root / "candidates/history/raw/data.parquet"
    with connection(tmp_path) as conn:
        input_table(conn, raw_day="20261014")
        with pytest.raises(ValueError, match="日期"):
            build(conn, root, output)
    assert not output.exists()


def test_day_wrapper_cannot_accept_an_unverified_source_object(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    with (
        connection(tmp_path) as conn,
        pytest.raises(TypeError, match="VerifiedDaySource"),
    ):
        candidates.build_stk_factor_pro_raw_candidate(
            conn,
            source=SimpleNamespace(
                identity=SimpleNamespace(target_trade_date=P),
                raw_relation=candidates.DAY_SOURCE,
            ),
            prior_path=None,
            candidate_path=root / "candidates/day/raw/data.parquet",
            run_root=root,
        )


@pytest.mark.parametrize("kind", ["outside", "live_link", "dangling_link"])
def test_history_candidate_path_is_checked_before_creating_external_file(
    tmp_path, kind
):
    root, outside = tmp_path / "run", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    if kind == "outside":
        output = outside / "data.parquet"
    else:
        (root / "candidates").mkdir()
        destination = outside if kind == "live_link" else tmp_path / "absent"
        (root / "candidates/history").symlink_to(destination, target_is_directory=True)
        output = root / "candidates/history/data.parquet"
    with connection(tmp_path) as conn:
        input_table(conn)
        with pytest.raises(ValueError):
            build(conn, root, output)
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "absent").exists()
