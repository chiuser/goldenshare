from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import dagster as dg
import duckdb
import pytest
from dagster._core.definitions.data_version import get_input_event_pointer_tag

from orchestrator.defs.bootstrap import adj_factor_history_refresh as refresh
from orchestrator.defs.bootstrap import adj_factor_history_refresh_cli as cli
from orchestrator.defs.bootstrap import adj_factor_history_refresh_events as events
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)

EARLY = "2014-01-02"
LATE = "2026-11-23"
SAME = "2026-11-24"
ACTIVE = "000001.SZ"
ABSENT_AT_SOURCE = "000751.SZ"
RETIRED = "600832.SH"
NO_RAW = "600831.SH"
DELIST_DAY = "600830.SH"


def _copy_table(path: Path, schema: str, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as c:
        c.execute(f"CREATE TABLE fixture({schema})")
        placeholders = ",".join("?" for _ in rows[0])
        c.executemany(f"INSERT INTO fixture VALUES ({placeholders})", rows)
        c.execute(f"COPY fixture TO {duckdb_string(path)} (FORMAT PARQUET)")


def _file_rows(path: Path):
    with duckdb.connect() as c:
        return c.execute("SELECT ts_code, adj_factor FROM read_parquet(?, hive_partitioning=false) ORDER BY 1",
                         [str(path)]).fetchall()


def _source(day: str, values: dict[str, float]) -> list[dict]:
    return [{"ts_code": code, "trade_date": day.replace("-", ""), "adj_factor": value}
            for code, value in values.items()]


@pytest.fixture
def revision(tmp_path):
    lake, staging = tmp_path.resolve() / "lake", tmp_path.resolve() / "staging"
    lake.mkdir()
    staging.mkdir()
    operation = str(uuid4())
    _copy_table(silver_trade_calendar_path(lake), "exchange VARCHAR, trade_date DATE, is_open BOOL",
                [("SSE", day, True) for day in (EARLY, LATE, SAME)])
    _copy_table(silver_stock_lifecycle_path(lake),
                "ts_code VARCHAR, list_status VARCHAR, list_date DATE, delist_date DATE, is_cny_stock BOOL",
                [(ACTIVE, "L", "1991-01-01", None, True), (ABSENT_AT_SOURCE, "L", "1997-06-26", None, True),
                 (RETIRED, "D", "1993-01-01", "2015-05-20", True),
                 (NO_RAW, "D", "1993-01-01", "2015-05-20", True),
                 (DELIST_DAY, "D", "1993-01-01", EARLY, True)])

    def files(day: str, raw: dict, silver: dict) -> None:
        for path, kind, values in ((raw_adj_factor_path(lake, day), "VARCHAR", raw),
                                   (silver_adj_factor_path(lake, day), "DATE", silver)):
            stamp = day.replace("-", "") if kind == "VARCHAR" else day
            _copy_table(path, f"ts_code VARCHAR, trade_date {kind}, adj_factor DOUBLE",
                        [(code, stamp, value) for code, value in values.items()])

    arguments = {"lake": lake, "staging": staging, "operation_id": operation,
                 "registered": {EARLY, LATE, SAME}}
    run = staging / "adj_factor" / "history_refresh" / operation
    return arguments, run, files


def test_prepare_publish_and_review_unapproved_keys(revision):
    arguments, run, files = revision
    lake = arguments["lake"]
    files(EARLY, {ACTIVE: 2, ABSENT_AT_SOURCE: 3.371, RETIRED: 17.155, DELIST_DAY: 4},
          {ACTIVE: 2, ABSENT_AT_SOURCE: 3.371})
    raw = raw_adj_factor_path(lake, EARLY)
    silver = silver_adj_factor_path(lake, EARLY)
    source = _source(EARLY, {ACTIVE: 2.1, RETIRED: 17.1552, DELIST_DAY: 4, NO_RAW: 9})
    refresh.prepare_history_refresh(start=EARLY, end=EARLY, pages=lambda _: [(0, source)], **arguments)
    record = refresh._json(run / f"{EARLY}.json")
    assert record["layers"]["raw"]["actions"] == {"retain": 1, "review": 1, "update": 2}
    assert record["layers"]["silver"]["actions"] == {"restore": 1, "retain": 1, "review": 2, "update": 1}
    assert _file_rows(silver) == [(ACTIVE, 2), (ABSENT_AT_SOURCE, 3.371)]
    assert refresh.publish_history_refresh(**arguments) == {
        "days": 1, "blocked": 0, "raw_changed": 1, "silver_changed": 1,
    }
    assert _file_rows(raw) == [(ACTIVE, 2.1), (ABSENT_AT_SOURCE, 3.371), (DELIST_DAY, 4), (RETIRED, 17.1552)]
    assert _file_rows(silver) == [(ACTIVE, 2.1), (ABSENT_AT_SOURCE, 3.371), (RETIRED, 17.1552)]


def test_silver_only_restoration_leaves_raw_identity(revision):
    arguments, _, files = revision
    raw = {ACTIVE: 2, ABSENT_AT_SOURCE: 3.371, RETIRED: 17.1552}
    files(EARLY, raw, {ACTIVE: 2, ABSENT_AT_SOURCE: 3.371})
    path = raw_adj_factor_path(arguments["lake"], EARLY)
    before = refresh.file_identity(path)
    refresh.prepare_history_refresh(start=EARLY, end=EARLY,
                                    pages=lambda _: [(0, _source(EARLY, raw))], **arguments)
    totals = refresh.publish_history_refresh(**arguments)
    assert (totals["raw_changed"], totals["silver_changed"]) == (0, 1)
    assert refresh.file_identity(path) == before


def test_post_cutover_unresolved_raw_source_difference_is_blocked(revision):
    arguments, run, files = revision
    values = {ACTIVE: 2, ABSENT_AT_SOURCE: 3.371}
    files(LATE, {**values, RETIRED: 1}, values)
    source = _source(LATE, {**values, RETIRED: 2})
    refresh.prepare_history_refresh(start=LATE, end=LATE, pages=lambda _: [(0, source)], **arguments)
    record = refresh._json(run / f"{LATE}.json")
    assert record["layers"]["silver"]["actions"] == {"review": 1}
    assert record["layers"]["silver"]["checks"]["source_missing"] == 1
    assert refresh.publish_history_refresh(**arguments)["blocked"] == 1
    assert _file_rows(raw_adj_factor_path(arguments["lake"], LATE))[-1] == (RETIRED, 1)


def test_prepare_resumes_after_mid_page_stop(revision, monkeypatch):
    arguments, run, files = revision
    monkeypatch.setattr(refresh, "PAGE_SIZE", 1)
    calls = []

    def source(day: str):
        calls.append(day)
        rows = _source(day, {ACTIVE: 1, ABSENT_AT_SOURCE: 2})
        yield 0, rows[:1]
        if day == SAME and calls.count(SAME) == 1:
            raise KeyboardInterrupt
        yield 1, rows[1:]
        yield 2, []

    for day in (LATE, SAME):
        files(day, {ACTIVE: 1, ABSENT_AT_SOURCE: 2}, {ACTIVE: 1, ABSENT_AT_SOURCE: 2})
    with pytest.raises(KeyboardInterrupt):
        refresh.prepare_history_refresh(start=LATE, end=SAME, pages=source, **arguments)
    old_receipt = (run / f"{LATE}.json").read_bytes()
    assert not (run / "sealed.json").exists()
    refresh.prepare_history_refresh(start=LATE, end=SAME, pages=source, **arguments)
    assert calls == [LATE, SAME, SAME]
    assert (run / f"{LATE}.json").read_bytes() == old_receipt


def test_publish_recovers_replace_before_readback_receipt(revision, monkeypatch):
    arguments, run, files = revision
    values = {ACTIVE: 1, ABSENT_AT_SOURCE: 2}
    files(LATE, values, values)
    files(SAME, {ACTIVE: 3, ABSENT_AT_SOURCE: 2}, {ACTIVE: 3, ABSENT_AT_SOURCE: 2})
    lake = arguments["lake"]
    current = {ACTIVE: 3, ABSENT_AT_SOURCE: 2}
    refresh.prepare_history_refresh(start=LATE, end=SAME,
                                    pages=lambda day: [(0, _source(day, current))], **arguments)
    checkpoint = refresh._checkpoint

    def interrupt(path, value):
        if path.name == "raw-publication.json" and value["phase"] == "verified":
            raise KeyboardInterrupt
        checkpoint(path, value)

    with monkeypatch.context() as m:
        m.setattr(refresh, "_checkpoint", interrupt)
        with pytest.raises(KeyboardInterrupt):
            refresh.publish_history_refresh(**arguments)
    raw = raw_adj_factor_path(lake, LATE)
    silver = silver_adj_factor_path(lake, LATE)
    identity = refresh.file_identity(raw)
    unchanged = refresh.file_identity(silver_adj_factor_path(lake, SAME))
    assert refresh._json(run / LATE / "raw-publication.json")["phase"] == "prepared"
    assert _file_rows(raw) == sorted(current.items())
    assert _file_rows(silver) == sorted(values.items())
    assert refresh.publish_history_refresh(**arguments) == {
        "days": 2, "blocked": 0, "raw_changed": 1, "silver_changed": 1,
    }
    assert _file_rows(silver) == sorted(current.items())
    assert refresh.file_identity(raw) == identity
    assert refresh.file_identity(silver_adj_factor_path(lake, SAME)) == unchanged
    assert refresh._json(run / LATE / "silver-publication.json")["checks"]["rows"] == 2


def test_silver_candidate_tampering_blocks_raw_publish(revision):
    arguments, run, files = revision
    values = {ACTIVE: 1, ABSENT_AT_SOURCE: 2}
    files(LATE, values, values)
    refresh.prepare_history_refresh(start=LATE, end=LATE, pages=lambda _: [
        (0, _source(LATE, {ACTIVE: 3, ABSENT_AT_SOURCE: 2})),
    ], **arguments)
    record = refresh._json(run / f"{LATE}.json")
    candidate = run / LATE / record["attempt"] / "silver.parquet"
    candidate.write_bytes(b"changed")
    with pytest.raises(refresh.AdjFactorHistoryRefreshError, match="Sealed artifact changed"):
        refresh.publish_history_refresh(**arguments)
    assert _file_rows(raw_adj_factor_path(arguments["lake"], LATE)) == sorted(values.items())


def test_cli_prepares_and_publishes_only_the_explicit_fixture_date(revision, tmp_path):
    arguments, _, files = revision
    values = {ACTIVE: 1, ABSENT_AT_SOURCE: 2}
    files(LATE, values, values)
    registered = tmp_path / "registered.json"
    registered.write_text(json.dumps([LATE]))
    rows = _source(LATE, {ACTIVE: 3, ABSENT_AT_SOURCE: 2})
    (tmp_path / f"{LATE}.adj_factor.json").write_text(json.dumps({"pages": [[0, len(rows)]], "rows": rows}))
    common = ["--operation-id", arguments["operation_id"], "--lake-root", str(arguments["lake"]),
              "--staging-root", str(arguments["staging"]), "--registered-days-file", str(registered)]
    seal = cli.main(["prepare", *common, "--start-date", LATE, "--end-date", LATE,
                     "--source-snapshot-dir", str(tmp_path)])
    assert list(seal["days"]) == [LATE]
    assert _file_rows(raw_adj_factor_path(arguments["lake"], LATE)) == sorted(values.items())
    assert cli.main(["publish", *common])["raw_changed"] == 1
    assert _file_rows(silver_adj_factor_path(arguments["lake"], LATE)) == [(ACTIVE, 3), (ABSENT_AT_SOURCE, 2)]


def test_optional_events_are_explicit_bound_and_retryable(revision, tmp_path, monkeypatch):
    arguments, _, files = revision
    values = {ACTIVE: 1, ABSENT_AT_SOURCE: 2}
    files(LATE, values, values)
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path)) as instance:
        instance.add_dynamic_partitions(events.ADJ_FACTOR_PARTITION_SET, [LATE])
        instance.report_runless_asset_event(dg.AssetMaterialization(events.LIFECYCLE))
        life_event = instance.get_latest_materialization_event(events.LIFECYCLE)
        life_record = instance.fetch_materializations(dg.AssetRecordsFilter(events.LIFECYCLE), limit=1).records[0]
        assert life_event is not None
        refresh.prepare_history_refresh(start=LATE, end=LATE, pages=lambda _: [
            (0, _source(LATE, {ACTIVE: 3, ABSENT_AT_SOURCE: 2})),
        ], **arguments)
        refresh.publish_history_refresh(**arguments)
        assert all(instance.get_latest_materialization_event(asset) is None for asset in events.ASSETS.values())
        scope = tmp_path / "scope.json"
        scope.write_text(json.dumps({"items": [{"layer": "raw", "day": LATE}, {
            "layer": "silver", "day": LATE, "lifecycle_materialization_id": life_record.storage_id,
        }]}))
        operation = {k: v for k, v in arguments.items() if k != "registered"}
        report = type(instance).report_runless_asset_event

        def lost_ack(self, event):
            report(self, event)
            raise RuntimeError("simulated loss of event acknowledgment")

        with monkeypatch.context() as m:
            m.setattr(type(instance), "report_runless_asset_event", lost_ack)
            with pytest.raises(RuntimeError, match="loss of event acknowledgment"):
                events.register_history_events(instance=instance, scope_path=scope, **operation)
        assert events.register_history_events(instance=instance, scope_path=scope, **operation) == {
            "publications": 1, "checks": 7,
        }
        assert events.register_history_events(instance=instance, scope_path=scope, **operation) == {
            "publications": 0, "checks": 0,
        }
        raw, silver = [instance.fetch_materializations(dg.AssetRecordsFilter(asset), limit=10).records
                       for asset in events.ASSETS.values()]
        assert len(raw) == len(silver) == 1
        assert silver[0].asset_materialization.tags == {
            get_input_event_pointer_tag(events.ASSETS["raw"]): str(raw[0].storage_id),
            get_input_event_pointer_tag(events.LIFECYCLE): str(life_record.storage_id),
        }


@pytest.mark.parametrize("bad_page", ["empty", "wrong_day", "duplicate", "invalid_value", "not_finished"])
def test_invalid_source_does_not_seal(revision, monkeypatch, bad_page):
    arguments, run, files = revision
    values = {ACTIVE: 1, ABSENT_AT_SOURCE: 2}
    files(LATE, values, values)
    rows = _source(LATE, values)
    if bad_page == "empty":
        rows = []
    elif bad_page == "wrong_day":
        rows[0]["trade_date"] = "20261124"
    elif bad_page == "duplicate":
        rows.append(rows[0])
    elif bad_page == "invalid_value":
        rows[0]["adj_factor"] = 0
    elif bad_page == "not_finished":
        monkeypatch.setattr(refresh, "PAGE_SIZE", 2)
    with pytest.raises(refresh.AdjFactorHistoryRefreshError):
        refresh.prepare_history_refresh(start=LATE, end=LATE, pages=lambda _: [(0, rows)], **arguments)
    assert not (run / "sealed.json").exists()
    assert _file_rows(raw_adj_factor_path(arguments["lake"], LATE)) == sorted(values.items())
