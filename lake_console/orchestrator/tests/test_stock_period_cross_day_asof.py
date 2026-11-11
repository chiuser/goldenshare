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

from orchestrator.defs import stock_period_source as source
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_silver_contracts import (
    NAMES,
    A,
    B,
    literal_row,
    write_raw,
)
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit isolated fixture.
)


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
