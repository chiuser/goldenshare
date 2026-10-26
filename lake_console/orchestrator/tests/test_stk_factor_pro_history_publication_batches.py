"""LLD 8/16 materialized history batches and per-date two-layer publication.

The explicit calendar is a bounded fixture, including an omitted holiday week;
it is not a claim that real SSE calendar readiness has been tested.
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

import pandas as pd
import pytest

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_download as downloads
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.io import stk_factor_pro_publication as publication
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as models
from tests.stk_factor_pro_history_test_support import (
    NAMES,
    HistoryDownloader,
    connection,
    contract,
    eligibility,
    identity,
    roots,
    row,
    write_factor_file,
)

T, P = date(2026, 10, 16), date(2026, 10, 15)
A, B = "000001.SZ", "600000.SH"
BATCH = "stk_factor_pro_history_batch_source"


def trading_dates(count):
    dates = []
    current = date(2026, 8, 1)
    holidays = {date(2026, 10, day) for day in range(1, 8)}
    while current <= P:
        if current.weekday() < 5 and current not in holidays:
            dates.append(current)
        current += timedelta(days=1)
    result = tuple(dates[-count:])
    assert len(result) == count and result[-1] == P
    return result


def write_rows(conn, path, rows, *, layer):
    """Independent explicit doc328 fields and types for existing business files."""
    frame = pd.DataFrame(
        {
            name: pd.array(
                [values[index] for values in rows],
                dtype="string" if index < 2 else "Float64",
            )
            for index, name in enumerate(NAMES)
        }
    )
    conn.register("test_history_publication_input", frame)
    projection = ", ".join(
        "CAST(strptime(trade_date,'%Y%m%d') AS DATE) AS trade_date"
        if index == 1 and layer == "silver"
        else f'CAST("{name}" AS {"VARCHAR" if index < 2 else "DOUBLE"}) AS "{name}"'
        for index, name in enumerate(NAMES)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn.execute(
            copy_query_to_parquet(
                f"SELECT {projection} FROM test_history_publication_input ORDER BY ts_code,trade_date",
                path,
            )
        )
    finally:
        conn.unregister("test_history_publication_input")


def setup(conn, tmp_path, count, *, missing_dates=(), unrelated=False):
    lake, staging = roots(tmp_path)
    dates = trading_dates(count)
    raw_t = raw_stk_factor_pro_path(lake, T.isoformat())
    silver_t = silver_stock_factor_pro_path(lake, T.isoformat())
    sentinel = row(A, T.strftime("%Y%m%d"), close=Decimal(99))
    write_rows(conn, raw_t, (sentinel,), layer="raw")
    write_rows(conn, silver_t, (sentinel,), layer="silver")
    t_hashes = factor_file_sha(raw_t), factor_file_sha(silver_t)
    refs = (
        write_factor_file(conn, lake, T, ((A, 2.0), (B, 1.0))),
        write_factor_file(conn, lake, P, ((A, 1.0), (B, 1.0))),
    )
    old = models.StkFactorProRecordedResults(
        T, None, None, None, None, None, None, (), (), None, None
    )
    run = identity()
    plan = history.build_stk_factor_pro_history_plan(
        conn,
        identity=run,
        contract=contract(),
        lake_root=lake,
        staging_root=staging,
        factor_t=refs[0],
        factor_p=refs[1],
        prior_results=old,
        history_starts=(models.StkFactorProHistoryStart(A, dates[0], 1, dates[0]),),
        check_cancel=lambda: None,
    )
    root = stk_factor_pro_run_staging_root(staging, run.creator_run_id, T.isoformat())
    ranges = history.read_stk_factor_pro_history_ranges(conn, root=root, plan=plan)
    valid = eligibility(run, plan, *t_hashes)
    source_rows = tuple(
        row(A, day.strftime("%Y%m%d"))
        for day in (*dates, T)
        if day not in missing_dates
    )
    downloader = HistoryDownloader({A: source_rows})

    def recheck():
        return refs[0], refs[1], valid.raw_coverage, valid.target_silver

    source = downloads.download_stk_factor_pro_history(
        conn,
        identity=run,
        contract=contract(),
        plan=plan,
        ranges=ranges,
        prior_results=old,
        eligibility=valid,
        lake_root=lake,
        staging_root=staging,
        recheck_inputs=recheck,
        downloader=downloader,
        check_cancel=lambda: None,
    )
    untouched = None
    if unrelated:
        untouched = tuple(
            B
            if index == 0
            else dates[0].strftime("%Y%m%d")
            if index == 1
            else None
            if index == 2
            else Decimal(index)
            for index in range(261)
        )
        write_rows(
            conn,
            raw_stk_factor_pro_path(lake, dates[0].isoformat()),
            (untouched,),
            layer="raw",
        )
    args = {
        "source": source,
        "plan": plan,
        "ranges": ranges,
        "lake_root": lake,
        "staging_root": staging,
        "calendar": (*dates, T),
        "registered_dates": dates,
        "recheck_inputs": recheck,
        "check_cancel": lambda: None,
    }
    return lake, root, dates, t_hashes, downloader, untouched, args


class BatchQueries:
    """Count batch materialization, separately from required verification I/O."""

    def __init__(self, conn, *, fail_batch=None):
        self.conn, self.fail_batch = conn, fail_batch
        self.batch_queries = []
        self.other_queries = []
        self.in_batch = False

    def __getattr__(self, key):
        return getattr(self.conn, key)

    def execute(self, query, parameters=None):
        text = str(query)
        lower = text.lower()
        source = "source/history/units/" in text + repr(parameters)
        is_batch = (
            re.match(
                rf'\s*create(?:\s+or\s+replace)?\s+temp(?:orary)?\s+table\s+"?{BATCH}"?(?:\s|$)',
                lower,
            )
            is not None
        )
        if is_batch:
            assert source and "read_parquet" in lower
            self.batch_queries.append((text, parameters))
            self.in_batch = True
            if len(self.batch_queries) == self.fail_batch:
                raise OSError("test: batch source read failed")
        else:
            self.other_queries.append((text, parameters))
            if self.in_batch:
                assert not (source and "read_parquet" in lower), (
                    "A date query reopened historical source files instead of the materialized batch"
                )
        return (
            self.conn.execute(query)
            if parameters is None
            else self.conn.execute(query, parameters)
        )


def assert_clean(conn):
    names = conn.execute(
        "SELECT table_name FROM duckdb_tables() WHERE temporary UNION ALL "
        "SELECT view_name FROM duckdb_views() WHERE temporary AND NOT internal"
    ).fetchall()
    assert not [name for (name,) in names if name.startswith("stk_factor_pro_")]


def assert_current_day_unchanged(conn, lake, expected_hashes):
    paths = (
        raw_stk_factor_pro_path(lake, T.isoformat()),
        silver_stock_factor_pro_path(lake, T.isoformat()),
    )
    assert tuple(factor_file_sha(path) for path in paths) == expected_hashes
    for path in paths:
        assert conn.execute(
            "SELECT close FROM read_parquet(?,hive_partitioning=false)", [str(path)]
        ).fetchall() == [(99.0,)]


@pytest.mark.parametrize(
    ("count", "batches"), [(1, 1), (20, 1), (21, 2), (41, 3), (45, 3)]
)
def test_one_batch_source_query_per_twenty_dates_and_raw_silver_order(
    tmp_path, count, batches
):
    with connection(tmp_path) as conn:
        lake, root, dates, hashes, downloader, untouched, args = setup(
            conn, tmp_path, count, unrelated=count == 1
        )
        observed = BatchQueries(conn)
        outputs = tuple(publication.publish_stk_factor_pro_history(observed, **args))
        assert len(observed.batch_queries) == batches
        assert tuple(
            (target.trade_date, target.layer) for target, _ in outputs
        ) == tuple((day, layer) for day in dates for layer in ("raw", "silver"))
        assert len(outputs) == count * 2 and all(
            not target.skip_no_file and audit is not None and audit.passed
            for target, audit in outputs
        )
        assert all(target.trade_date < T for target, _ in outputs)
        assert len(downloader.calls) == 1 and downloader.sessions[0].closed
        assert_current_day_unchanged(conn, lake, hashes)
        if untouched is not None:
            for layer, path in (
                ("raw", raw_stk_factor_pro_path(lake, dates[0].isoformat())),
                ("silver", silver_stock_factor_pro_path(lake, dates[0].isoformat())),
            ):
                actual = conn.execute(
                    "SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?",
                    [str(path), B],
                ).fetchone()
                expected = tuple(
                    value
                    if index == 0 or value is None
                    else dates[0]
                    if index == 1 and layer == "silver"
                    else value
                    if index == 1
                    else float(value)
                    for index, value in enumerate(untouched)
                )
                assert actual == expected
        assert not (root / "publication/history" / T.isoformat()).exists()
        assert_clean(conn)


def test_holiday_gap_and_no_row_dates_keep_explicit_skip_without_file_audit(tmp_path):
    with connection(tmp_path) as conn:
        dates = trading_dates(20)
        omitted = dates[4]
        lake, root, dates, hashes, _, _, args = setup(
            conn, tmp_path, 20, missing_dates=(omitted,)
        )
        assert any((later - earlier).days > 3 for earlier, later in pairwise(dates))
        observed = BatchQueries(conn)
        outputs = tuple(publication.publish_stk_factor_pro_history(observed, **args))
        missing = [
            (target, audit) for target, audit in outputs if target.trade_date == omitted
        ]
        assert len(missing) == 2
        for target, audit in missing:
            assert target.skip_no_file and audit is None
            assert target.file_rows == 0 and target.file_sha256 is None
            assert target.checkpoint_ref is None
            assert not (
                root / f"candidates/history/{omitted}/{target.layer}/data.parquet"
            ).exists()
        assert len(observed.batch_queries) == 1
        assert_current_day_unchanged(conn, lake, hashes)
        assert_clean(conn)


def test_business_closes_iterator_after_raw_retains_raw_and_releases_all_relations(
    tmp_path,
):
    with connection(tmp_path) as conn:
        lake, _, dates, hashes, _, _, args = setup(conn, tmp_path, 1)
        iterator = publication.publish_stk_factor_pro_history(
            BatchQueries(conn), **args
        )
        target, audit = next(iterator)
        assert target.trade_date == dates[0] and target.layer == "raw" and audit.passed
        iterator.close()
        assert raw_stk_factor_pro_path(lake, dates[0].isoformat()).exists()
        assert not silver_stock_factor_pro_path(lake, dates[0].isoformat()).exists()
        assert_current_day_unchanged(conn, lake, hashes)
        assert_clean(conn)


def test_silver_failure_keeps_completed_raw_and_cleans_current_batch(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        lake, _, dates, hashes, _, _, args = setup(conn, tmp_path, 1)

        def failed(*args, **kwargs):
            raise OSError("test: silver candidate failed")

        monkeypatch.setattr(
            publication, "build_stk_factor_pro_silver_candidate", failed
        )
        iterator = publication.publish_stk_factor_pro_history(
            BatchQueries(conn), **args
        )
        target, audit = next(iterator)
        assert target.layer == "raw" and audit.passed
        with pytest.raises(OSError, match="silver candidate"):
            next(iterator)
        assert raw_stk_factor_pro_path(lake, dates[0].isoformat()).exists()
        assert not silver_stock_factor_pro_path(lake, dates[0].isoformat()).exists()
        assert_current_day_unchanged(conn, lake, hashes)
        assert_clean(conn)


@pytest.mark.parametrize("failed_batch", [1, 2])
def test_batch_read_failure_stops_new_dates_and_releases_prior_relations(
    tmp_path, failed_batch
):
    with connection(tmp_path) as conn:
        lake, _, dates, hashes, _, _, args = setup(conn, tmp_path, 21)
        observed = BatchQueries(conn, fail_batch=failed_batch)
        completed = []
        with pytest.raises(OSError, match="batch source read"):
            for target, audit in publication.publish_stk_factor_pro_history(
                observed, **args
            ):
                completed.append((target, audit))
        assert len(completed) == (failed_batch - 1) * 40
        assert len(observed.batch_queries) == failed_batch
        assert not raw_stk_factor_pro_path(lake, dates[-1].isoformat()).exists()
        if failed_batch == 2:
            assert silver_stock_factor_pro_path(lake, dates[19].isoformat()).exists()
        assert_current_day_unchanged(conn, lake, hashes)
        assert_clean(conn)
