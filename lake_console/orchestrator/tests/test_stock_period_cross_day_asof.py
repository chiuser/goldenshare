"""LLD12.22: real tiny Raw receipts -> both Silver jobs/checks, no formal resources.

The independent 21-column literals are from the actual weekly/monthly source
contract in test_stock_period_silver_contracts. The 29/30 dates model the saved
920306.BJ MCP evidence, without downloading that source again. HTTP is replaced;
candidate SQL, files, receipts, isolated Dagster storage and checks are real.
"""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs import stock_period_source as source
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.bootstrap import stock_period_history_cli as raw_cli
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.io.stock_period_silver import run_directory
from orchestrator.defs.run_contracts.stock_period import (
    StockPeriodPolicy,
    completion_reference,
    digest,
)
from orchestrator.defs.stock_period_update import (
    report_completion_events,
    report_file_events,
)
from tests.test_stock_period_silver_contracts import (
    NAMES,
    A,
    B,
    C,
    literal_row,
    write_raw,
)
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit isolated fixture.
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414 -- Explicit isolated fixture.
)
from tests.test_stock_period_silver_daily_integration import run_request, tick
from tests.test_stock_period_silver_sensors import context


@pytest.fixture(autouse=True)
def isolated_boundaries(monkeypatch):
    original_open = Path.open
    violations = []

    def guarded_open(path, *args, **kwargs):
        value = str(path.absolute())
        if value.startswith(("/Volumes/datasource/", "/Users/congming/.goldenshare/")):
            violations.append(value)
            pytest.fail("cross-day test tried to access a formal path")
        return original_open(path, *args, **kwargs)

    def prohibited(*args, **kwargs):
        violations.append("formal instance or HTTP")
        pytest.fail("cross-day test tried to open a formal instance or HTTP source")

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(dg.DagsterInstance, "get", prohibited)
    monkeypatch.setattr(source.HttpPage, "__call__", prohibited)
    yield
    assert not violations


class Clock(datetime):
    instant = datetime.fromisoformat("2026-10-29T19:30:00+08:00")

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


def freeze(monkeypatch, value):
    Clock.instant = datetime.fromisoformat(value)
    monkeypatch.setattr(source, "datetime", Clock)
    monkeypatch.setattr(history, "execution_time", lambda: Clock.instant.isoformat())
    monkeypatch.setattr(
        source,
        "time",
        SimpleNamespace(time_ns=lambda: int(Clock.instant.timestamp() * 1e9)),
    )


def retime(rows, day):
    result = []
    for original in rows:
        row = list(original)
        # The real 20200228/29 example has two different source versions. Keep
        # the older one old; making both current would invent a price conflict.
        if row[0] in (A, B) and row[1] != "20200228":
            row[2] = day
        result.append(row)
    return result


def resumed_source(f, calls):
    def transport(params):
        calls.append(dict(params))
        rows = [r for r in f["state"]["rows"] if r[3] == params["freq"]]
        if params.get("ts_code"):
            rows = [r for r in rows if r[0] == params["ts_code"]]
        elif params.get("trade_date"):
            rows = [r for r in rows if r[1] == params["trade_date"]]
        else:
            rows = [
                r for r in rows if params["start_date"] <= r[1] <= params["end_date"]
            ]
        return json.dumps(
            {"code": 0, "data": {"fields": list(NAMES), "items": rows}}
        ).encode()

    return transport


def pending_capture(f, monkeypatch):
    """A completes on 29; B is empty, then the original intent resumes on 30."""
    freeze(monkeypatch, "2026-10-29T19:30:00+08:00")
    complete_rows = retime(f["state"]["rows"], "20261029")
    f["state"]["rows"] = [
        r for r in complete_rows if not (r[0] == B and r[3] == "week")
    ]
    existing = set((f["staging"] / "stock_period/runs").iterdir())
    with pytest.raises(ValueError, match="period_source_empty"):
        f["capture"](
            mode="upsert",
            freq="month",
            codes=(A, B),
            periods=["2026-10"],
            asof="2026-10-29",
            frequencies=["week", "month"],
        )
    created = set((f["staging"] / "stock_period/runs").iterdir()) - existing
    assert len(created) == 1
    work = created.pop()
    saved = raw.read_json(work / "manifest.json")
    assert saved["phase"] == "download"
    identity = saved["identity"]
    assert identity["intent"]["asof"] == "2026-10-29"
    successful = next(
        p
        for p in (work / "source").glob("*/complete.json")
        if raw.read_json(p)["identity"]["code"] == A
    )
    successful_bytes = successful.read_bytes()
    successful_version = raw.file_version(successful)
    f["state"]["rows"] = retime(complete_rows, "20261030")
    freeze(monkeypatch, "2026-10-30T20:00:00+08:00")
    calls = []

    def operation(ctx):
        return history.run_period(
            root=f["lake"],
            staging=f["staging"],
            intent=identity["intent"],
            listed=set(identity["listed"]),
            aliases=identity["aliases"],
            policy=StockPeriodPolicy(**identity["policy"]),
            transport=resumed_source(f, calls),
            events=lambda item, completion=None: report_file_events(
                f["instance"],
                item,
                completion=completion,
                context=ctx,
            ),
            completion_events=lambda notice: report_completion_events(
                f["instance"], notice
            ),
        )

    result = raw_cli._run_reporting(f["instance"], operation)
    assert result["run_id"] == work.name
    assert raw.read_json(work / "manifest.json")["identity"] == identity
    assert successful.read_bytes() == successful_bytes
    assert raw.file_version(successful) == successful_version
    assert not any(p.get("ts_code") == A and p["freq"] == "week" for p in calls)
    assert any(p.get("ts_code") == B and p["freq"] == "week" for p in calls)
    saved = raw.read_json(work / "manifest.json")
    return completion_reference(work.name, saved["file_receipt_hash"], "week"), work


def test_candidate_source_date_uses_one_existing_aggregate_and_survives_rename(
    tmp_path,
    monkeypatch,
):
    candidate = tmp_path / "candidate.parquet"
    target = tmp_path / "lake" / "part-000.parquet"
    checkpoint = tmp_path / "committed.json"
    statements = []
    original_execute = raw.execute

    def tracked(*args, **kwargs):
        statements.append(kwargs.get("stage"))
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(raw, "execute", tracked)
    with raw.connection(tmp_path / "duckdb") as con:
        write_raw(
            con,
            candidate,
            [
                literal_row(A, "20261030", "week", asof="20261029"),
                literal_row(B, "20261030", "week", asof="20261030"),
            ],
        )
        facts = raw._validate_candidates(
            con,
            [("2026-10-30", candidate)],
            "week",
            lambda: False,
            lambda _: None,
            raw.DEFAULT_POLICY,
        )
    assert statements == ["candidate_schemas", "candidate_facts"]
    assert facts[str(candidate)]["source_asof"] == "2026-10-30"
    item = {
        "freq": "week",
        "period": "2026-10-30",
        "candidate": str(candidate),
        "target": str(target),
        "target_preimage": None,
        **facts[str(candidate)],
    }
    write = raw.atomic_json
    failed = False

    def interrupted(path, value):
        nonlocal failed
        if path == checkpoint and not failed:
            failed = True
            raise OSError("checkpoint interrupted after rename")
        return write(path, value)

    monkeypatch.setattr(raw, "atomic_json", interrupted)
    with pytest.raises(OSError, match="checkpoint interrupted"):
        raw.publish(item, checkpoint=checkpoint)
    version = raw.file_version(target)
    assert not candidate.exists()
    result = raw.publish(item, checkpoint=checkpoint)
    assert result["source_asof"] == "2026-10-30"
    assert raw.file_version(target) == version
    with pytest.raises(ValueError, match="period_checkpoint_identity_changed"):
        raw.publish({**item, "source_asof": "2026-10-29"}, checkpoint=checkpoint)


def test_cross_day_original_capture_then_two_silver_jobs(update_fixture, monkeypatch):
    f = update_fixture
    contexts = {freq: context(f) for freq in ("week", "month")}
    untouched = f["lake"] / "gold" / "unrelated" / "keep.txt"
    untouched.parent.mkdir(parents=True)
    untouched.write_text("completed unrelated output")
    untouched_version = raw.file_version(untouched)
    baseline_complete = (
        f["staging"] / "stock_period/runs" / f["raw_base_id"] / "complete.json"
    )
    baseline_bytes = baseline_complete.read_bytes()
    reference, raw_work = pending_capture(f, monkeypatch)
    assert reference["raw_execution_id"] == raw_work.name
    complete_before = (raw_work / "complete.json").read_bytes()
    assert (
        raw.read_json(raw_work / "manifest.json")["identity"]["intent"]["asof"]
        == "2026-10-29"
    )
    for freq in ("week", "month"):
        request = tick(f, contexts[freq], freq).run_requests[0]
        assert run_request(f, request, monkeypatch).success
        asset = request.job_name.removesuffix("_update_job")
        execution = request.run_config["ops"][asset]["config"]["execution_id"]
        work = run_directory(f["staging"], execution)
        units = raw.read_json(work / "execution.json")["identity"]["units"]
        assert units and all(u["asof"] == "2026-10-30" for u in units)
        native = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(asset),
                    asset_partitions=[request.partition_key],
                ),
                limit=1,
            )
            .records[0]
        )
        assert (
            native.asset_materialization.metadata["goldenshare/silver_asof"].value
            == "2026-10-30"
        )
        before = {u["period"]: raw.file_version(u["target"]) for u in units}
        assert (
            tick(f, contexts[freq], freq).skip_reason.skip_message
            == "silver_batch_complete"
        )
        assert {u["period"]: raw.file_version(u["target"]) for u in units} == before
        assert "pending" not in json.loads(contexts[freq].cursor)
        assert (work / "events_complete.json").exists()
    assert (raw_work / "complete.json").read_bytes() == complete_before
    assert untouched.read_text() == "completed unrelated output"
    assert raw.file_version(untouched) == untouched_version
    assert baseline_complete.read_bytes() == baseline_bytes


def rewrite_completion(f, reference, change):
    work = f["staging"] / "stock_period/runs" / reference["raw_execution_id"]
    complete = raw.read_json(work / "complete.json")
    change(complete)
    raw.atomic_json(work / "complete.json", complete)
    saved = raw.read_json(work / "manifest.json")
    saved["file_receipt_hash"] = digest(complete)
    # Independent physical completion date; source date is tested against this.
    saved["files_completed_at"] = "2026-10-30T20:00:00+08:00"
    raw.atomic_json(work / "manifest.json", saved)
    return completion_reference(work.name, saved["file_receipt_hash"], "week")


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_each_period_keeps_its_source_date_through_job_checks_and_resume(
    update_fixture,
    monkeypatch,
    freq,
    interrupt,
):
    f = update_fixture
    ctx = context(f)
    freeze(monkeypatch, "2026-10-31T10:00:00+08:00")
    changed = []
    for original in f["state"]["rows"]:
        row = list(original)
        if row[0] == A and row[1] != "20200228":
            row[2] = "20261030" if row[1].startswith("2026") else "20261029"
        changed.append(row)
    f["state"]["rows"] = changed
    reference = f["capture"](freq=freq, asof="2026-10-29")
    raw_work = f["staging"] / "stock_period/runs" / reference["raw_execution_id"]
    raw_before = (raw_work / "complete.json").read_bytes()
    requested = tick(f, ctx, freq).run_requests[0]
    asset = requested.job_name.removesuffix("_update_job")
    execution_id = requested.run_config["ops"][asset]["config"]["execution_id"]
    work = run_directory(f["staging"], execution_id)
    if interrupt:
        publish = silver.publish
        calls = []

        def stop_after_first(record, *args, **kwargs):
            calls.append(record["period"])
            if len(calls) == 2:
                raise OSError("isolated interruption between Silver files")
            return publish(record, *args, **kwargs)

        monkeypatch.setattr(silver, "publish", stop_after_first)
        with pytest.raises(OSError, match="isolated interruption"):
            run_request(f, requested, monkeypatch)
        unit = raw.read_json(work / "execution.json")["identity"]["units"][0]
        first_version = raw.file_version(unit["target"])
        first_asof = unit["asof"]
        monkeypatch.setattr(silver, "publish", publish)
    result = run_request(f, requested, monkeypatch)
    assert result.success
    assert len(result.get_asset_check_evaluations()) == 3
    assert all(e.passed and e.blocking for e in result.get_asset_check_evaluations())
    units = raw.read_json(work / "execution.json")["identity"]["units"]
    assert [u["asof"] for u in units] == ["2026-10-29", "2026-10-29", "2026-10-30"]
    if interrupt:
        assert units[0]["asof"] == first_asof == "2026-10-29"
        assert raw.file_version(units[0]["target"]) == first_version
    before = {u["period"]: raw.file_version(u["target"]) for u in units}
    assert tick(f, ctx, freq).skip_reason.skip_message == "silver_batch_complete"
    assert {u["period"]: raw.file_version(u["target"]) for u in units} == before
    for unit in units:
        mat = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(asset), asset_partitions=[unit["period"]]
                ),
                limit=1,
            )
            .records[0]
            .asset_materialization
        )
        assert mat.metadata["goldenshare/silver_asof"].value == unit["asof"]
    with raw.connection(f["staging"] / "readback") as con:
        assert con.execute(
            "SELECT ts_code,end_date,close_qfq::VARCHAR FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [units[-1]["target"]],
        ).fetchall() == [
            (A, "20261030", "11.1400"),
            (C, "20261016", "11.1400"),
            (B, "20261016", "11.1400"),
        ]
    assert (raw_work / "complete.json").read_bytes() == raw_before


@pytest.mark.parametrize("freq", ["week", "month"])
def test_missing_source_date_evidence_keeps_original_date_predicate(
    update_fixture,
    monkeypatch,
    freq,
):
    f = update_fixture
    freeze(monkeypatch, "2026-10-30T20:00:00+08:00")
    f["state"]["rows"] = retime(f["state"]["rows"], "20261030")
    ref = f["capture"](freq=freq, asof="2026-10-29")
    ref = rewrite_completion(
        f, ref, lambda c: [item.pop("source_asof") for item in c["files"]]
    )
    ref = completion_reference(ref["raw_execution_id"], ref["file_receipt_hash"], freq)
    delivery = silver.read_completion(f["lake"], f["staging"], ref, freq)
    unit = list(delivery["items"].values())[-1]
    assert unit["asof"] == "2026-10-29"
    with raw.connection(f["staging"] / "original-date-predicate") as con:
        silver.load_references(con, f["references"])
        with pytest.raises(
            ValueError, match="silver_source_identity_date_or_partition_invalid"
        ):
            silver.select_period(
                con, unit["target"], freq, unit["period"], asof=unit["asof"]
            )


@pytest.mark.parametrize(
    "freq,label,period",
    [("week", "20261030", "2026-10-30"), ("month", "20261031", "2026-10")],
)
@pytest.mark.parametrize(
    "asof,empty", [(None, False), (None, True), ("20260230", False)]
)
def test_raw_source_date_does_not_hide_null_empty_or_invalid_dates(
    tmp_path,
    freq,
    label,
    period,
    asof,
    empty,
):
    candidate = tmp_path / "candidate.parquet"
    with raw.connection(tmp_path / "duckdb") as con:
        write_raw(
            con, candidate, [] if empty else [literal_row(A, label, freq, asof=asof)]
        )
        if asof == "20260230":
            with pytest.raises(
                ValueError, match="period_file_key_or_partition_invalid"
            ):
                raw._validate_candidates(
                    con,
                    [(period, candidate)],
                    freq,
                    lambda: False,
                    lambda _: None,
                    raw.DEFAULT_POLICY,
                )
        else:
            facts = raw._validate_candidates(
                con,
                [(period, candidate)],
                freq,
                lambda: False,
                lambda _: None,
                raw.DEFAULT_POLICY,
            )
            assert facts[str(candidate)]["source_asof"] is None
            assert facts[str(candidate)]["rows"] == (0 if empty else 1)


@pytest.mark.parametrize(
    "value", ["bad", "20261030", 20261030, {}, "2026-02-30", "2026-10-31"]
)
def test_invalid_or_future_source_date_stops_before_silver_read(
    update_fixture,
    monkeypatch,
    value,
):
    f = update_fixture
    reference = f["capture"](asof="2026-10-29")
    reference = rewrite_completion(
        f, reference, lambda c: c["files"][0].update(source_asof=value)
    )
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("unexpected data read"),
    )
    with pytest.raises(ValueError, match="silver_raw_completion_source_date_invalid"):
        silver.read_completion(f["lake"], f["staging"], reference, "week")


@pytest.mark.parametrize(
    "value", ["absent", None, "2026-10-28", "2026-10-29", "2026-10-30"]
)
def test_receipt_scope_is_per_file_and_never_uses_current_clock(
    update_fixture,
    monkeypatch,
    value,
):
    f = update_fixture
    reference = f["capture"](asof="2026-10-29")

    def change(complete):
        for item in complete["files"]:
            item["source_asof"] = "2026-10-29"
        first = complete["files"][0]
        if value == "absent":
            first.pop("source_asof")
        else:
            first["source_asof"] = value

    reference = rewrite_completion(f, reference, change)
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("unexpected data read"),
    )
    delivery = silver.read_completion(f["lake"], f["staging"], reference, "week")
    assert delivery["asof"] == "2026-10-29"
    items = list(delivery["items"].values())
    assert items[0]["asof"] == ("2026-10-30" if value == "2026-10-30" else "2026-10-29")
    assert all(item["asof"] == "2026-10-29" for item in items[1:])


@pytest.mark.parametrize("freq", ["week", "month"])
def test_old_notice_uses_the_selected_successor_file_source_date(
    update_fixture, monkeypatch, freq
):
    f = update_fixture
    freeze(monkeypatch, "2026-10-31T10:00:00+08:00")
    f["state"]["rows"] = retime(f["state"]["rows"], "20261030")
    old = f["capture"](freq=freq, asof="2026-10-29")
    f["state"]["rows"] = retime(f["state"]["rows"], "20261031")
    current = f["capture"](freq=freq, asof="2026-10-30")
    units, _ = silver.resolve_update_sources(
        f["lake"], f["staging"], freq, old, f["instance"]
    )
    assert units and all(u["source_completion"] == current for u in units)
    assert all(u["asof"] == "2026-10-31" for u in units)
    assert all(u["supersedes"] == old for u in units)


def test_later_source_does_not_advance_daily_factor_or_refresh_to_later_day(tmp_path):
    from orchestrator.defs.stock_period_update import _consume_daily_files

    staging = tmp_path / "staging"
    raw.atomic_json(
        staging / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-23", "month": "2026-09"},
            "last_refresh": {"month": "2026-10-28"},
            "factor_through": "2026-10-28",
        },
    )
    raw.atomic_json(staging / "stock_period/baseline.json", {"listed": [A]})
    work = {
        "intent": {"asof": "2026-10-29", "request_id": "original-29"},
        "frequency": "month",
        "pending": [],
        "holidays": [],
        "listed": [A],
    }
    _consume_daily_files(
        staging, work, {"unit_asofs": {"month": {"2026-10": "20261030"}}}, []
    )
    result = raw.read_json(staging / "stock_period/daily.json")
    assert result["factor_through"] == "2026-10-29"
    assert result["last_refresh"]["month"] == "2026-10-29"
    assert result["last_source_asof"]["month"] == "20261030"
    assert result["completed_through"]["month"] == "2026-09"
