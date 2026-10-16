import csv
from decimal import Decimal
from pathlib import Path

import pytest

from orchestrator.defs.io.stock_period_raw import (
    FIELDS,
    assemble,
    connection,
    file_version,
    publish,
    target_path,
)
from orchestrator.defs.run_contracts.stock_period import StockPeriodPolicy

POLICY = StockPeriodPolicy(
    duckdb_memory="256MiB", workspace_bytes=1024**3, spill_bytes=128 * 1024**2
)


def sample(work, rows):
    work.mkdir(parents=True, exist_ok=True)
    p = work / "source.csv"
    with p.open("w") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerows(rows)
    return p


def row(code, day, freq="week", price="1.2500"):
    return [code, day, "20261015", freq] + [price] * 17


def commit(items, work):
    with connection(work, POLICY) as con:
        return [
            publish(i, checkpoint=work / (i["period"] + ".json"), con=con)
            for i in items
        ]


def read(root, freq, period):
    with connection(root / "read", POLICY) as con:
        return con.execute(
            "SELECT ts_code,trade_date,close FROM read_parquet(?,hive_partitioning=false) ORDER BY 1,2",
            [str(target_path(root, freq, period))],
        ).fetchall()


def test_history_replaces_old_keys_keeps_other_stocks_and_old_only_partition(tmp_path):
    root = tmp_path / "lake"
    old = [
        row("000001.SZ", "20261002"),
        row("000002.SZ", "20261002", "week", "9"),
        row("000001.SZ", "20261009"),
        row("000002.SZ", "20261009", "week", "8"),
    ]
    items = assemble(
        [sample(tmp_path / "old", old)],
        work=tmp_path / "b1",
        root=root,
        mode="bootstrap",
        freq="week",
        policy=POLICY,
    )
    commit(items, tmp_path / "c1")
    untouched = target_path(root, "week", "2026-10-09").read_bytes()
    new = [
        row("000001.SZ", "20261009", "week", "2"),
        row("000001.SZ", "20261016", "week", "3"),
    ]
    items = assemble(
        [sample(tmp_path / "new", new)],
        work=tmp_path / "b2",
        root=root,
        mode="history",
        freq="week",
        codes=["000001.SZ"],
        policy=POLICY,
    )
    assert {i["period"] for i in items} == {"2026-10-02", "2026-10-09", "2026-10-16"}
    commit(items, tmp_path / "c2")
    assert read(root, "week", "2026-10-02") == [("000002.SZ", "20261002", Decimal(9))]
    assert read(root, "week", "2026-10-09") == [
        ("000001.SZ", "20261009", Decimal(2)),
        ("000002.SZ", "20261009", Decimal(8)),
    ]
    assert read(root, "week", "2026-10-16") == [("000001.SZ", "20261016", Decimal(3))]
    assert untouched != target_path(root, "week", "2026-10-09").read_bytes()


def test_upsert_full_row_and_unselected_partition_unchanged(tmp_path):
    root = tmp_path / "lake"
    old = [
        row("000001.SZ", "20200228", "month"),
        row("000001.SZ", "20200229", "month"),
        row("000002.SZ", "20200229", "month", "7"),
        row("000001.SZ", "20200131", "month"),
    ]
    commit(
        assemble(
            [sample(tmp_path / "old", old)],
            work=tmp_path / "b1",
            root=root,
            mode="bootstrap",
            freq="month",
            policy=POLICY,
        ),
        tmp_path / "c1",
    )
    other = target_path(root, "month", "2020-01")
    before = file_version(other)
    new = row("000001.SZ", "20200229", "month", "3")
    new[9] = None
    items = assemble(
        [sample(tmp_path / "new", [new])],
        work=tmp_path / "b2",
        root=root,
        mode="upsert",
        freq="month",
        periods=["2020-02"],
        policy=POLICY,
    )
    commit(items, tmp_path / "c2")
    assert file_version(other) == before
    assert read(root, "month", "2020-02") == [
        ("000001.SZ", "20200228", Decimal("1.25")),
        ("000001.SZ", "20200229", Decimal(3)),
        ("000002.SZ", "20200229", Decimal(7)),
    ]


def test_publish_checkpoint_failure_readback_and_no_rewrite(tmp_path, monkeypatch):
    import orchestrator.defs.io.stock_period_raw as module

    root = tmp_path / "lake"
    item = assemble(
        [sample(tmp_path / "source", [row("000001.SZ", "20261016")])],
        work=tmp_path / "build",
        root=root,
        mode="bootstrap",
        freq="week",
        policy=POLICY,
    )[0]
    real = module.atomic_json
    monkeypatch.setattr(
        module,
        "atomic_json",
        lambda *_: (_ for _ in ()).throw(OSError("record_failure")),
    )
    with connection(tmp_path / "con", POLICY) as con:
        with pytest.raises(OSError):
            publish(item, checkpoint=tmp_path / "checkpoint.json", con=con)
        version = file_version(item["target"])
        monkeypatch.setattr(module, "atomic_json", real)
        publish(item, checkpoint=tmp_path / "checkpoint.json", con=con)
        assert file_version(item["target"]) == version
        Path(item["target"]).write_bytes(b"corrupt")
        with pytest.raises(ValueError):
            publish(item, checkpoint=tmp_path / "checkpoint.json", con=con)


def test_sql_cancel_interrupts_and_no_progress_is_invented(tmp_path):
    import time

    from orchestrator.defs.io.stock_period_raw import PeriodCancelled, execute

    started = time.monotonic()
    events = []
    with connection(tmp_path / "sql", POLICY) as con, pytest.raises(PeriodCancelled):
        execute(
            con,
            "SELECT sum(i) FROM range(1000000000000) t(i)",
            cancel=lambda: time.monotonic() - started > 0.3,
            progress=events.append,
        )
    assert time.monotonic() - started < 3
    assert all(e.get("completed", 0) == 0 for e in events)


def test_confirmed_retirement_prunes_without_any_download(tmp_path):
    root = tmp_path / "lake"
    commit(
        assemble(
            [
                sample(
                    tmp_path / "initial",
                    [
                        row("000001.SZ", "20261009"),
                        row("000002.SZ", "20261009", "week", "7"),
                    ],
                )
            ],
            work=tmp_path / "b1",
            root=root,
            mode="bootstrap",
            freq="week",
            policy=POLICY,
        ),
        tmp_path / "c1",
    )
    items = assemble(
        [],
        work=tmp_path / "b2",
        root=root,
        mode="history",
        freq="week",
        retired_codes=["000001.SZ"],
        policy=POLICY,
    )
    commit(items, tmp_path / "c2")
    assert read(root, "week", "2026-10-09") == [("000002.SZ", "20261009", Decimal(7))]


def test_independent_literal_all_21_fields_and_null_survive(tmp_path):
    root = tmp_path / "lake"
    values = [
        "000001.SZ",
        "20200229",
        None,
        "month",
        "10.1234",
        "11.2345",
        "9.3456",
        "10.4567",
        "10.5678",
        "5.1111",
        None,
        "4.2222",
        "5.3333",
        "100.1111",
        "110.2222",
        "90.3333",
        "100.4444",
        "123456.7890",
        None,
        "-0.1111",
        "-0.9876",
    ]
    commit(
        assemble(
            [sample(tmp_path / "literal", [values])],
            work=tmp_path / "build",
            root=root,
            mode="bootstrap",
            freq="month",
            policy=POLICY,
        ),
        tmp_path / "commit",
    )
    with connection(tmp_path / "read_all", POLICY) as con:
        observed = con.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(target_path(root, "month", "2020-02"))],
        ).fetchone()
    assert observed == (
        "000001.SZ",
        "20200229",
        None,
        "month",
        Decimal("10.1234"),
        Decimal("11.2345"),
        Decimal("9.3456"),
        Decimal("10.4567"),
        Decimal("10.5678"),
        Decimal("5.1111"),
        None,
        Decimal("4.2222"),
        Decimal("5.3333"),
        Decimal("100.1111"),
        Decimal("110.2222"),
        Decimal("90.3333"),
        Decimal("100.4444"),
        Decimal("123456.7890"),
        None,
        Decimal("-0.1111"),
        Decimal("-0.9876"),
    )
