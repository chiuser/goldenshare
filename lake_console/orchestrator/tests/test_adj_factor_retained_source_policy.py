"""Independent literal fixtures for LLD25, based on Raw/lifecycle column contracts."""

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import (
    adj_factor_repair_scope_select,
    adj_factor_required_stock_select,
    silver_adj_factor_select,
)
from orchestrator.defs.stock_factor_price_checks import audit_adj_factor_candidate_rules
from tests.adj_factor_test_support import (
    isolated_factor_duckdb,
)

pytestmark = pytest.mark.usefixtures(isolated_factor_duckdb.__name__)


def write_rows(db, path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    placeholders = ",".join("?" for _ in columns)
    db.execute("DROP TABLE IF EXISTS fixture")
    db.execute("CREATE TEMP TABLE fixture (" + ",".join(columns) + ")")
    if rows:
        db.executemany(f"INSERT INTO fixture VALUES ({placeholders})", rows)
    db.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(path)])
    return path


@pytest.fixture
def sample(tmp_path):
    with duckdb.connect() as db:
        life = write_rows(db, tmp_path / "lifecycle.parquet", [
            ("000001.SZ", "L", "2010-01-01", None, True),
            ("301139.SZ", "D", "2022-07-08", "2026-10-28", True),
            ("600001.SH", "D", "2010-01-01", "2020-01-01", True),
            ("600002.SH", "D", "2010-01-01", None, True),
            ("000002.SZ", "P", "2010-01-01", None, True),
            ("200001.SZ", "L", "2010-01-01", None, False),
            ("000003.SZ", "L", "2027-01-01", None, True),
        ], ["ts_code VARCHAR", "list_status VARCHAR", "list_date DATE", "delist_date DATE", "is_cny_stock BOOLEAN"])
        yield db, tmp_path, life


def raw(db, root, day, rows):
    return write_rows(db, root / f"raw-{day}.parquet", rows,
                      ["ts_code VARCHAR", "trade_date VARCHAR", "adj_factor DOUBLE"])


def silver(db, root, day, rows):
    return write_rows(db, root / f"silver-{day}.parquet", rows,
                      ["ts_code VARCHAR", "trade_date DATE", "adj_factor DOUBLE"])


def rules(sample, day, raw_rows, silver_rows):
    db, root, life = sample
    rp = raw(db, root, day, raw_rows)
    sp = silver(db, root, day, silver_rows)
    return audit_adj_factor_candidate_rules(db, sp, day, raw=False, lifecycle_path=life, raw_path=rp)


def test_new_partition_retains_real_delisted_and_unknown_delist_date_source(sample):
    db, root, life = sample
    rp = raw(db, root, "2026-10-28", [
        ("000001.SZ", "20261028", 1.5), ("301139.SZ", "20261028", 1.1319),
        ("600001.SH", "20261028", 2.5), ("600002.SH", "20261028", 3.5),
        ("000002.SZ", "20261028", 4.5), ("200001.SZ", "20261028", 5.5),
        ("000003.SZ", "20261028", 6.5), ("999999.SZ", "20261028", 7.5),
    ])
    assert db.execute(f"SELECT ts_code,adj_factor FROM ({silver_adj_factor_select(rp, life)}) ORDER BY ts_code").fetchall() == [
        ("000001.SZ", 1.5), ("301139.SZ", 1.1319), ("600001.SH", 2.5), ("600002.SH", 3.5),
    ]


def test_source_retention_and_required_coverage_are_independent(sample):
    result = rules(sample, "2026-10-28",
                   [("000001.SZ", "20261028", 1.5), ("301139.SZ", "20261028", 1.1319)],
                   [("000001.SZ", "2026-10-28", 1.5)])
    assert result["coverage_missing"] == 0  # Already retired on the target day.
    assert result["source_missing"] == 1  # Actual source row must still be retained.
    assert result["coverage_unexpected"] == 0


def test_no_daily_factor_requirement_for_every_delisted_stock(sample):
    result = rules(sample, "2026-10-28", [("000001.SZ", "20261028", 1.5)],
                   [("000001.SZ", "2026-10-28", 1.5)])
    assert all(v == 0 for k, v in result.items() if k != "rows")


def test_old_history_requires_newly_retired_but_not_pre_cutover_retired_stock(sample):
    db, _root, life = sample
    assert db.execute(f"SELECT ts_code FROM ({adj_factor_required_stock_select(life, '2026-10-22')}) ORDER BY ts_code").fetchall() == [
        ("000001.SZ",), ("301139.SZ",),
    ]
    result = rules(sample, "2026-10-22", [("000001.SZ", "20261022", 1.5)],
                   [("000001.SZ", "2026-10-22", 1.5), ("301139.SZ", "2026-10-22", 1.0079)])
    assert all(v == 0 for k, v in result.items() if k != "rows")


def test_in_market_missing_factor_still_fails(sample):
    result = rules(sample, "2026-10-28", [("301139.SZ", "20261028", 1.1319)],
                   [("301139.SZ", "2026-10-28", 1.1319)])
    assert result["coverage_missing"] == 1


def test_wrong_delisted_source_value_cannot_pass(sample):
    result = rules(sample, "2026-10-28", [("000001.SZ", "20261028", 1.5), ("301139.SZ", "20261028", 1.1319)],
                   [("000001.SZ", "2026-10-28", 1.5), ("301139.SZ", "2026-10-28", 1.0079)])
    assert (result["source_missing"], result["source_unexpected"]) == (1, 1)


def test_retained_without_delist_date_is_not_permanently_in_market(sample):
    db, _root, life = sample
    values = {r[0]: (r[-2], r[-1]) for r in db.execute(adj_factor_repair_scope_select(life, "2026-10-28")).fetchall()}
    assert values["600002.SH"] == (False, True)
    assert values["301139.SZ"] == (False, False)
    assert values["000001.SZ"] == (True, False)
    before = {r[0]: r[-2] for r in db.execute(adj_factor_repair_scope_select(life, "2026-10-22")).fetchall()}
    assert before["301139.SZ"] is True


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), 0.0, -1.0, None])
def test_invalid_factors_cannot_be_hidden_by_retention(sample, bad):
    result = rules(sample, "2026-10-28", [("000001.SZ", "20261028", bad)],
                   [("000001.SZ", "2026-10-28", bad)])
    assert result["nonpositive_factor"] == 1


def test_new_date_candidate_requires_raw_evidence(sample):
    db, root, life = sample
    sp = silver(db, root, "2026-10-28", [("000001.SZ", "2026-10-28", 1.5)])
    with pytest.raises(FileNotFoundError, match="Raw factor partition"):
        audit_adj_factor_candidate_rules(db, sp, "2026-10-28", raw=False, lifecycle_path=life)


def test_mixed_date_batch_matches_candidate_rules(sample):
    from orchestrator.defs.asset_guards import adj_factor_lake_readiness as readiness
    from orchestrator.defs.paths import (
        raw_adj_factor_path,
        silver_adj_factor_path,
        silver_stock_lifecycle_path,
    )

    db, root, life = sample
    target_life = silver_stock_lifecycle_path(root)
    target_life.parent.mkdir(parents=True, exist_ok=True)
    target_life.write_bytes(life.read_bytes())
    days = ("2026-10-27", "2026-10-28")
    for day in days:
        factor = 1.0079 if day.endswith("27") else 1.1319
        values = [("000001.SZ", day.replace("-", ""), 1.5), ("301139.SZ", day.replace("-", ""), factor)]
        rp = raw(db, root, day, values)
        target_raw = raw_adj_factor_path(root, day)
        target_raw.parent.mkdir(parents=True, exist_ok=True)
        target_raw.write_bytes(rp.read_bytes())
        sp = silver(db, root, day, [("000001.SZ", day, 1.5), ("301139.SZ", day, factor)])
        target_silver = silver_adj_factor_path(root, day)
        target_silver.parent.mkdir(parents=True, exist_ok=True)
        target_silver.write_bytes(sp.read_bytes())
    batch = readiness.batch_silver_adj_factor_lake_readiness(
        connection=db, lake_root=root, expected_trade_dates=days, registered_trade_days=days,
    )
    assert all(s.ready for s in batch.statuses_by_trade_date.values())
    combined = readiness.batch_adj_factor_lake_readiness(
        connection=db, lake_root=root, expected_trade_dates=days, registered_trade_days=days,
    )
    assert all(s.ready for s in combined.statuses_by_trade_date.values())
    assert db.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name='_adj_factor_readiness_raw'").fetchone()[0] == 0
    # Wrong retained D value must fail both paths, even when D is no longer required.
    target = silver_adj_factor_path(root, days[1])
    target.unlink()
    write_rows(db, target, [("000001.SZ", days[1], 1.5), ("301139.SZ", days[1], 1.0079)],
               ["ts_code VARCHAR", "trade_date DATE", "adj_factor DOUBLE"])
    checked = audit_adj_factor_candidate_rules(db, target, days[1], raw=False,
                    lifecycle_path=target_life, raw_path=raw_adj_factor_path(root, days[1]))
    failed = readiness.batch_silver_adj_factor_lake_readiness(
        connection=db, lake_root=root, expected_trade_dates=days, registered_trade_days=days,
    ).statuses_by_trade_date[days[1]]
    assert (checked["source_missing"], checked["source_unexpected"]) == (1, 1)
    assert not failed.ready
    assert failed.summary["silver_retained_source_failed_count"] == 2
    assert readiness.SILVER_ADJ_FACTOR_COVERAGE_COMPLETE_CHECK in failed.failed_check_names
