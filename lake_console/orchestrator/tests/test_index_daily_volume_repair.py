"""Isolated Parquet checks using literal CNI samples from the approved design."""

import json
from datetime import datetime

import duckdb
import pytest

from orchestrator.defs.bootstrap import index_daily_volume_repair as repair
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet


def _official_response():
    def timestamp(day):
        return int(
            datetime.fromisoformat(day).replace(tzinfo=repair.SHANGHAI).timestamp()
            * 1000
        )

    return json.dumps(
        {
            "code": 200,
            "data": {
                "indexCode": "399001",
                "item": ["timestamp", "volume", "amount", "close"],
                "data": [
                    [timestamp(repair.START), 9704619752, 158586146576, 9785.5667],
                    [
                        timestamp(repair.CONTROL),
                        27853874678,
                        827937999366.13,
                        15225.1136,
                    ],
                ],
            },
        }
    ).encode()


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(repair.writer, "gettempdir", lambda: str(tmp_path))
    root = tmp_path / "lake"
    stage = tmp_path / "run"
    with duckdb.connect() as connection:
        for day in (repair.START, repair.CONTROL):
            if day == repair.START:
                volume, amount, close = "416126766", "478095879.6", "9785.5667"
            else:
                volume, amount, close = "278538746.78", "827937999.3661", "15225.1136"
            for name, path_for in repair.LAYERS.items():
                path = path_for(root, day)
                path.parent.mkdir(parents=True)
                trade_date = (
                    f"'{day.replace('-', '')}'"
                    if name == "raw_index_daily"
                    else f"DATE '{day}'"
                )
                values = {
                    "ts_code": "code",
                    "trade_date": trade_date,
                    "rank": "CASE WHEN code = '399001.SZ' THEN 4 ELSE 1 END",
                    "display_name": "code",
                    "close": f"CASE WHEN code = '399001.SZ' THEN {close} ELSE 3476.47 END",
                    "vol": f"CASE WHEN code = '399001.SZ' THEN {volume} ELSE 789654 END",
                    "amount": f"CASE WHEN code = '399001.SZ' THEN {amount} ELSE 654321 END",
                }
                columns = ", ".join(
                    f'CAST({values.get(col.name, "120.5")} AS {col.type}) AS "{col.name}"'
                    for col in repair.writer.SCHEMAS[name]
                )
                connection.execute(
                    copy_query_to_parquet(
                        f"SELECT {columns} FROM (VALUES ('399001.SZ'), ('000001.SH')) AS codes(code)",
                        path,
                    )
                )
        plan = repair.build_plan(
            connection, root, _official_response(), (repair.START, repair.CONTROL)
        )
        yield connection, root, stage, plan


def test_scope_and_official_units(files):
    connection, root, _, plan = files
    assert tuple(plan["days"]) == (repair.START,)
    assert plan["days"][repair.START]["official"] == {
        "vol": "97046197.52",
        "amount": "158586146.576",
        "close": "9785.5667",
    }
    repair.audit_control(connection, root, plan)
    with pytest.raises(ValueError, match="coverage mismatch"):
        repair.build_plan(connection, root, _official_response(), (repair.START,))


def test_three_layer_patch_and_readback(files):
    db, root, stage, plan = files
    day = repair.START
    old_rows = {}
    for layer, path_for in repair.LAYERS.items():
        src = read_parquet(path_for(root, day), hive_partitioning=False)
        old_rows[layer] = db.execute(f"SELECT * FROM {src} ORDER BY ts_code").fetchall()
    repair.apply_day(db, root, stage, "approved", day, plan["days"][day])
    first_ids = {}
    for layer, path_for in repair.LAYERS.items():
        path = path_for(root, day)
        src = read_parquet(path, hive_partitioning=False)
        rows = db.execute(f"SELECT * FROM {src} ORDER BY ts_code").fetchall()
        original = old_rows[layer]
        assert rows[0] == original[0]
        assert rows[1] == (*original[1][:-2], 97046197.52, 158586146.576)
        first_ids[layer] = path.stat().st_ino
    repair.apply_day(db, root, stage, "approved", day, plan["days"][day])
    for layer, path_for in repair.LAYERS.items():
        assert path_for(root, day).stat().st_ino == first_ids[layer]
    repair.audit_day(db, root, stage, day, plan["days"][day])
    repair.audit_control(db, root, plan)


def test_resume_after_raw_published(files, monkeypatch):
    db, root, stage, plan = files
    day = repair.START
    apply = repair.writer.write_index_daily_partition

    def interrupt_before_silver(*args, **kwargs):
        if kwargs["dataset"] == "silver_index_daily":
            raise RuntimeError("interrupt after Raw")
        return apply(*args, **kwargs)

    monkeypatch.setattr(
        repair.writer, "write_index_daily_partition", interrupt_before_silver
    )
    with pytest.raises(RuntimeError, match="interrupt after Raw"):
        repair.apply_day(db, root, stage, "approved", day, plan["days"][day])
    raw = repair.LAYERS["raw_index_daily"](root, day)
    raw_after_first_write = raw.stat().st_ino
    assert not (stage / day / "complete.json").exists()

    monkeypatch.setattr(repair.writer, "write_index_daily_partition", apply)
    repair.apply_day(db, root, stage, "approved", day, plan["days"][day])
    assert raw.stat().st_ino == raw_after_first_write
    repair.audit_day(db, root, stage, day, plan["days"][day])


def test_changed_gold_blocks_entire_day_before_publication(files):
    db, root, stage, plan = files
    day = repair.START
    gold = repair.LAYERS["gold_market_major_indices_daily"](root, day)
    with gold.open("ab") as stream:
        stream.write(b"x")
    with pytest.raises(ValueError, match="original file differs"):
        repair.apply_day(db, root, stage, "approved", day, plan["days"][day])
    raw = repair.LAYERS["raw_index_daily"](root, day)
    assert repair.inspect_partition(db, raw, "raw_index_daily", day)["vol"] == 416126766
