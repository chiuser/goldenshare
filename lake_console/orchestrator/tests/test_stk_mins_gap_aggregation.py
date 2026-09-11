"""Exact-key aggregation acceptance; all files isolated, no source/network writes."""

import functools
import operator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from orchestrator.defs.bootstrap.stk_mins_gap_aggregation import build_date, main
from orchestrator.defs.bootstrap.stk_mins_gap_aggregation_plan import (
    freeze_missing_plan,
    stage_path,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery import (
    atomic_json,
    connection,
    file_digest,
    literal,
    parquet,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_source import expected_clocks

DAY = "2018-07-27"
CODE = "000979.SZ"


@pytest.fixture
def root():
    with TemporaryDirectory(dir="/private/tmp", prefix="minute-aggregate-test-") as d:
        yield Path(d)


def row(time, freq=1, **changes):
    value = {
        "ts_code": CODE,
        "freq": freq,
        "trade_time": f"{DAY} {time}",
        "open": 10.0,
        "close": 10.2,
        "high": 11.0,
        "low": 9.0,
        "vol": 10,
        "amount": 102.0,
        "exchange": None,
        "vwap": 10.2,
    }
    value.update(changes)
    return value


def write_rows(root, name, rows):
    source = root / f"{name}.json"
    atomic_json(source, rows)
    target = root / f"{name}.parquet"
    with connection(root) as c:
        parquet(
            c,
            f"SELECT ts_code::VARCHAR AS ts_code,freq::INTEGER AS freq,trade_time::TIMESTAMP AS trade_time,open::DOUBLE AS open,close::DOUBLE AS close,high::DOUBLE AS high,low::DOUBLE AS low,vol::BIGINT AS vol,amount::DOUBLE AS amount,exchange::VARCHAR AS exchange,vwap::DOUBLE AS vwap FROM read_json_auto({literal(source)})",
            target,
        )
    return target


def setup(root, freqs=(5,), native=None, one=None, mutate_task=None):
    one = one if one is not None else [row(t) for t in sorted(expected_clocks(1))]
    path = write_rows(root, "one", one)
    native_paths = [] if native is None else [str(write_rows(root, "native", native))]
    scopes = []
    tasks = []
    for freq in freqs:
        scopes.append(
            {
                "scope_id": f"s{freq}",
                "latest_ts_code": CODE,
                "source_candidates": [CODE, "000001.SZ"],
                "freq": freq,
                "trade_date": DAY,
                "expected_grid_count": 240 // freq + 1,
                "missing_grid_count": 240 // freq + 1,
            }
        )
        tasks.append(
            {
                "scope_id": f"s{freq}",
                "latest_ts_code": CODE,
                "freq": freq,
                "trade_date": DAY,
                "one_code": CODE,
                "one_paths": [str(path)],
                "native_paths": native_paths,
            }
        )
    if mutate_task:
        mutate_task(tasks)
    atomic_json(root / "scope.json", scopes)
    atomic_json(root / "manifest.json", tasks)
    with connection(root) as c:
        parquet(
            c,
            f"SELECT * REPLACE(trade_date::DATE AS trade_date) FROM read_json_auto({literal(root / 'scope.json')})",
            root / "scope.parquet",
        )
    plan = freeze_missing_plan(
        root / "manifest.json", root / "scope.parquet", root / "plan", "recovery-test"
    )
    return root / "plan/plan.json", plan, path


def query(root, path, sql="SELECT * FROM read_parquet(?)"):
    with connection(root) as c:
        return c.execute(sql, [str(path)]).fetchall()


@pytest.mark.parametrize("freq", [5, 15, 30, 60])
def test_each_period_auction_lunch_small_volume(root, freq):
    plan, _p, _ = setup(root, (freq,))
    state = build_date(plan, DAY)
    assert state["rows"] == 240 // freq + 1
    rows = query(
        root,
        plan.parent / f"additions/{DAY}/rows.parquet",
        "SELECT freq,strftime(trade_time,'%H:%M:%S'),open,high,low,close,vol,amount FROM read_parquet(?) ORDER BY trade_time",
    )
    assert {r[0] for r in rows} == {freq}
    assert rows[0][1:] == ("09:30:00", 10.0, 11.0, 9.0, 10.2, 10, 102.0)
    assert rows[1][2:] == (10.0, 11.0, 9.0, 10.2, 10 * freq, 102.0 * freq)
    assert {r[1] for r in rows} == expected_clocks(freq)
    afternoon_end = f"13:{freq:02d}:00" if freq < 60 else "14:00:00"
    assert next(r for r in rows if r[1] == afternoon_end)[6] == 10 * freq


def test_only_one_missing_record_preserves_all_native_values(root):
    native = [
        row(t, 5, open=20.0, close=20.0, high=20.0, low=20.0, vol=999, amount=19980.0)
        for t in sorted(expected_clocks(5))
        if t != "09:35:00"
    ]
    plan, p, _ = setup(root, native=native)
    assert p["counts"]["missing"] == 1
    old = file_digest(plan.parent / "existing.parquet")
    state = build_date(plan, DAY)
    assert state["rows"] == 1 and file_digest(plan.parent / "existing.parquet") == old
    assert query(
        root,
        plan.parent / f"additions/{DAY}/rows.parquet",
        "SELECT freq,strftime(trade_time,'%H:%M:%S'),vol FROM read_parquet(?)",
    ) == [(5, "09:35:00", 50)]


def test_multiple_missing_periods_share_input_without_other_periods(root):
    plan, _p, _ = setup(root, (5, 30))
    build_date(plan, DAY)
    assert query(
        root,
        plan.parent / f"additions/{DAY}/rows.parquet",
        "SELECT DISTINCT freq FROM read_parquet(?) ORDER BY 1",
    ) == [(5,), (30,)]


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "bad_price", "bad_vol", "amount"]
)
def test_bad_one_minute_cannot_be_filled(root, defect):
    one = [row(t) for t in sorted(expected_clocks(1))]
    if defect == "missing":
        one.pop(1)
    elif defect == "duplicate":
        one.append(one[1])
    elif defect == "bad_price":
        one[1]["open"] = 999
    elif defect == "bad_vol":
        one[1]["vol"] = -1
    else:
        one[1].update(vol=0, amount=1)
    plan, _, _ = setup(root, one=one)
    with pytest.raises(ValueError, match="241-point"):
        build_date(plan, DAY)
    assert not (plan.parent / f"additions/{DAY}/complete.json").exists()


def test_zero_volume_and_vwap(root):
    plan, _, _ = setup(
        root, one=[row(t, vol=0, amount=0) for t in sorted(expected_clocks(1))]
    )
    build_date(plan, DAY)
    assert query(
        root,
        plan.parent / f"additions/{DAY}/rows.parquet",
        "SELECT DISTINCT vol,amount,vwap FROM read_parquet(?)",
    ) == [(0, 0.0, 10.2)]


def test_native_invalid_and_extra_rows_are_not_overwritten(root):
    native = [row(t, 5) for t in sorted(expected_clocks(5))]
    native[1]["open"] = None
    native.append(row("09:31:00", 5))
    plan, p, _ = setup(root, native=native)
    assert (
        p["counts"]["missing"] == 0
        and p["counts"]["blocked"] == 1
        and p["counts"]["extras"] == 1
    )
    with pytest.raises(ValueError, match="No missing"):
        build_date(plan, DAY)


def test_cancel_exit_resume_and_idempotency(root):
    plan, _, _ = setup(root)
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) == 3

    with pytest.raises(InterruptedError):
        build_date(plan, DAY, cancelled=cancel)
    assert (plan.parent / f"additions/{DAY}/rows.parquet").exists()
    assert not (plan.parent / f"additions/{DAY}/complete.json").exists()
    state = build_date(plan, DAY)
    candidate = plan.parent / f"additions/{DAY}/rows.parquet"
    before = candidate.stat().st_mtime_ns
    assert build_date(plan, DAY) == state and candidate.stat().st_mtime_ns == before
    with pytest.raises(InterruptedError):
        build_date(plan, DAY, cancelled=lambda: True)


def test_scope_identity_and_frequency_boundaries(root):
    with pytest.raises(ValueError, match="scope or identity"):
        setup(root, mutate_task=lambda t: t[0].update(one_code="600000.SH"))


def test_plan_and_candidate_tamper(root):
    plan, _, _ = setup(root)
    build_date(plan, DAY)
    f = plan.parent / f"additions/{DAY}/rows.parquet"
    f.write_bytes(b"changed")
    with pytest.raises(ValueError, match="candidate was changed"):
        build_date(plan, DAY)


def test_no_formal_output_or_unbounded_cli():
    with pytest.raises(ValueError):
        stage_path("/Volumes/datasource/data_lake/raw/test")
    with pytest.raises(ValueError, match="ten distinct"):
        main(
            [
                "build",
                "--plan",
                "/private/tmp/not-read.json",
                *functools.reduce(
                    operator.iadd, (["--date", DAY] for _ in range(11)), []
                ),
            ]
        )


def test_hive_named_staging_does_not_add_business_columns(root):
    nested = root / "run_id=sample"
    nested.mkdir()
    plan, _, _ = setup(nested)
    assert build_date(plan, DAY)["rows"] == 49


def test_equivalent_old_code_does_not_duplicate_missing_keys(root):
    native = [row(t, 5) for t in sorted(expected_clocks(5)) if t != "09:35:00"]
    native += [dict(r, ts_code="000001.SZ") for r in native]
    plan, p, _ = setup(root, native=native)
    assert p["counts"]["missing"] == 1 and p["counts"]["existing"] == 48
    assert build_date(plan, DAY)["rows"] == 1


def test_conflicting_alias_values_cannot_be_selected_silently(root):
    native = [row("09:30:00", 5), row("09:30:00", 5, ts_code="000001.SZ", vol=999)]
    with pytest.raises(ValueError, match="Conflicting native"):
        setup(root, native=native)


def test_changed_input_is_rejected_before_calculation(root):
    plan, _, one = setup(root)
    one.touch()
    with pytest.raises(ValueError, match="input changed"):
        build_date(plan, DAY)


def test_time_order_drives_ohlc_not_input_order(root):
    one = [row(t) for t in sorted(expected_clocks(1))]
    one[1].update(open=8.0, low=7.0, close=9.0)
    one[3].update(high=13.0)
    one[5].update(open=11.0, high=12.0, close=12.0)
    plan, _, _ = setup(root, one=list(reversed(one)))
    build_date(plan, DAY)
    assert query(
        root,
        plan.parent / f"additions/{DAY}/rows.parquet",
        "SELECT open,high,low,close FROM read_parquet(?) WHERE strftime(trade_time,'%H:%M:%S')='09:35:00'",
    ) == [(8.0, 13.0, 7.0, 12.0)]


def test_cli_failure_is_recorded_without_completion(root):
    plan, _, _ = setup(root, one=[row(t) for t in sorted(expected_clocks(1))][1:])
    with pytest.raises(ValueError, match="241-point"):
        main(["build", "--plan", str(plan), "--date", DAY])
    assert (plan.parent / f"additions/{DAY}/last-stop.json").exists()
    assert not (plan.parent / f"additions/{DAY}/complete.json").exists()
