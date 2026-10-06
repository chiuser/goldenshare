"""Market fixtures use fake source, clock and isolated candidate files."""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.checks.moneyflow import (
    audit_market_moneyflow_file,
    audit_market_moneyflow_standardization,
)
from orchestrator.defs.io.moneyflow_candidates import (
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
)
from orchestrator.defs.io.moneyflow_raw_writer import (
    build_market_moneyflow_raw_candidate,
)
from orchestrator.defs.io.moneyflow_silver_writer import (
    build_market_moneyflow_silver_candidate,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MKT_DC_FIELDS,
    MoneyflowContractError,
    normalize_market_moneyflow_row,
)
from orchestrator.defs.source_readiness.moneyflow import collect_market_moneyflow

DAY = "2026-09-30"


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def row():
    return {
        f: "20260930" if f == "trade_date" else None if f == "close_sh" else -123.4567
        for f in MONEYFLOW_MKT_DC_FIELDS
    }


class Source:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def call(self, api, params, fields):
        self.calls.append((api, params, fields))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(columns=MONEYFLOW_MKT_DC_FIELDS, rows=value)


def build(tmp_path, responses):
    clock = Clock()
    source = Source(responses)
    raw = build_market_moneyflow_raw_candidate(
        tushare=source,
        staging_root=tmp_path,
        operation_id="p1",
        trade_date=DAY,
        clock=clock,
        sleep_fn=clock.sleep,
    )
    return raw, source, clock


def test_stable_raw_silver_preserve_null_and_negative(tmp_path):
    raw, source, clock = build(tmp_path, [[row()], [row()]])
    silver = build_market_moneyflow_silver_candidate(raw, DAY)
    assert clock.now >= 60
    assert (
        source.calls
        == [
            (
                "moneyflow_mkt_dc",
                {"trade_date": "20260930", "limit": 2000, "offset": 0},
                MONEYFLOW_MKT_DC_FIELDS,
            )
        ]
        * 2
    )
    with moneyflow_candidate_connection(raw.parent) as c:
        audit_market_moneyflow_standardization(c, raw, silver, DAY)
        assert c.execute(
            "SELECT close_sh,net_amount FROM read_parquet(?,hive_partitioning=false)",
            [str(silver)],
        ).fetchone() == (None, Decimal("-123.4567"))
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert receipt["stage"] == "silver_candidate_ready"
    assert receipt["request_count"] == 2
    assert not (tmp_path / "raw").exists()


@pytest.mark.parametrize(
    "value", [True, "garbage", "NaN", "Infinity", "0.00001", "1e24"]
)
def test_invalid_numeric_not_rounded(value):
    with pytest.raises(MoneyflowContractError):
        normalize_market_moneyflow_row({**row(), "net_amount": value}, DAY)


@pytest.mark.parametrize(
    "responses",
    [
        [[]],
        [[row(), row()]],
        [[{**row(), "trade_date": "20260929"}]],
        [[{k: v for k, v in row().items() if k != "net_amount"}]],
    ],
)
def test_bad_source_not_ready(tmp_path, responses):
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, responses)
    assert (
        json.loads(next(tmp_path.rglob("receipt.json")).read_text())["stage"]
        == "collecting"
    )
    assert not list(tmp_path.rglob("silver.parquet"))


def test_unstable_keeps_first_candidate_unready(tmp_path):
    with pytest.raises(MoneyflowContractError, match="source_unstable"):
        build(tmp_path, [[row()], [{**row(), "net_amount": 1}]])
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        build_market_moneyflow_silver_candidate(
            next(tmp_path.rglob("raw.parquet")), DAY
        )


def test_tamper_rejected(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    raw.write_bytes(b"bad")
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        build_market_moneyflow_silver_candidate(raw, DAY)


def test_wrong_day_and_corrupt_file(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    with moneyflow_candidate_connection(raw.parent) as c:
        with pytest.raises(MoneyflowContractError, match="file_count_or_date"):
            audit_market_moneyflow_file(c, raw, "2026-09-29")
        raw.write_bytes(b"bad")
        with pytest.raises(MoneyflowContractError, match="file_unreadable"):
            audit_market_moneyflow_file(c, raw, DAY)


def test_operation_collision_no_overwrite(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    before = raw.read_bytes()
    with pytest.raises(MoneyflowContractError, match="operation_conflict"):
        build(tmp_path, [])
    assert before == raw.read_bytes()


def test_cancel_before_second_round(tmp_path):
    clock = Clock()
    source = Source([[row()], [row()]])

    def cancel():
        if clock.now >= 5:
            raise MoneyflowContractError("cancelled")

    with pytest.raises(MoneyflowContractError, match="cancelled"):
        build_market_moneyflow_raw_candidate(
            tushare=source,
            staging_root=tmp_path,
            operation_id="cancel",
            trade_date=DAY,
            clock=clock,
            sleep_fn=clock.sleep,
            check_cancel=cancel,
        )
    assert len(source.calls) == 1


def test_late_response_budget_rejected():
    clock = Clock()
    source = Source([[row()]])
    call = source.call

    def late(*args):
        clock.now += 301
        return call(*args)

    source.call = late
    with pytest.raises(MoneyflowContractError):
        collect_market_moneyflow(
            tushare=source,
            trade_date=DAY,
            on_first_round=lambda r: None,
            clock=clock,
            sleep_fn=clock.sleep,
        )
    assert len(source.calls) == 1


def test_no_formal_or_path_traversal():
    for root, op in [
        (Path("/Volumes/datasource/data_lake"), "x"),
        (Path("/Volumes"), "x"),
        (Path("/private/tmp"), "../x"),
        (Path("relative"), "x"),
    ]:
        with pytest.raises(MoneyflowContractError):
            moneyflow_candidate_directory(root, op, DAY, dataset="moneyflow_mkt_dc")


def test_recorded_source_sample(tmp_path):
    evidence = json.loads(
        (
            Path(__file__).parents[2] / "reports/moneyflow_p0_evidence_20261006.json"
        ).read_text()
    )
    sample = next(
        r
        for r in evidence["matrix_sdk"]
        if r["api"] == "moneyflow_mkt_dc" and r["mode"] == "explicit_sample"
    )["sample"][0]
    raw, _, _ = build(tmp_path, [[sample], [sample]])
    silver = build_market_moneyflow_silver_candidate(raw, DAY)
    with moneyflow_candidate_connection(raw.parent) as c:
        audit_market_moneyflow_standardization(c, raw, silver, DAY)


def test_shared_budget_is_not_reset_between_rounds(monkeypatch, tmp_path):
    from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

    monkeypatch.setattr(
        "orchestrator.defs.source_readiness.moneyflow.market_moneyflow_policy",
        lambda: TushareRequestPolicy(max_requests=1),
    )
    clock = Clock()
    source = Source([[row()], [row()]])
    with pytest.raises(MoneyflowContractError):
        build_market_moneyflow_raw_candidate(
            tushare=source,
            staging_root=tmp_path,
            operation_id="budget",
            trade_date=DAY,
            clock=clock,
            sleep_fn=clock.sleep,
        )
    assert len(source.calls) == 1
    assert (
        json.loads(next(tmp_path.rglob("receipt.json")).read_text())["stage"]
        == "collecting"
    )


def test_silver_value_change_fails_standardization(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    silver = build_market_moneyflow_silver_candidate(raw, DAY)
    changed = raw.parent / "changed.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            "COPY (SELECT * REPLACE(CAST(net_amount+1 AS DECIMAL(24,4)) AS net_amount) FROM read_parquet($source,hive_partitioning=false)) TO $target (FORMAT PARQUET)",
            {"source": str(silver), "target": str(changed)},
        )
        with pytest.raises(MoneyflowContractError, match="standardization_difference"):
            audit_market_moneyflow_standardization(c, raw, changed, DAY)


def test_no_spill_and_extensions_off(tmp_path):
    with moneyflow_candidate_connection(tmp_path) as c:
        settings = dict(
            c.execute(
                "SELECT name,value FROM duckdb_settings() WHERE name IN ('max_temp_directory_size','autoload_known_extensions','autoinstall_known_extensions')"
            ).fetchall()
        )
    assert settings == {
        "max_temp_directory_size": "0 bytes",
        "autoload_known_extensions": "false",
        "autoinstall_known_extensions": "false",
    }


def test_staging_symlink_is_rejected(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "moneyflow").symlink_to(other, target_is_directory=True)
    with pytest.raises(MoneyflowContractError, match="staging_symlink"):
        moneyflow_candidate_directory(
            tmp_path, "symlink", DAY, dataset="moneyflow_mkt_dc"
        )


def test_float_outside_exact_integer_range_is_rejected():
    with pytest.raises(MoneyflowContractError, match="numeric_type"):
        normalize_market_moneyflow_row({**row(), "net_amount": float(2**53)}, DAY)


def test_staging_root_symlink_is_rejected(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    root = tmp_path / "linked"
    root.symlink_to(other, target_is_directory=True)
    with pytest.raises(MoneyflowContractError, match="staging_symlink"):
        moneyflow_candidate_directory(root, "x", DAY, dataset="moneyflow_mkt_dc")


def test_invalid_calendar_day_is_rejected():
    with pytest.raises(MoneyflowContractError, match="partition_date"):
        normalize_market_moneyflow_row(row(), "2026-02-30")


def test_silver_rejects_formal_path_before_read():
    raw = (
        Path("/Volumes/datasource/data_lake/moneyflow/x/moneyflow_mkt_dc")
        / DAY
        / "raw.parquet"
    )
    with pytest.raises(MoneyflowContractError, match="formal_lake_is_not_staging"):
        build_market_moneyflow_silver_candidate(raw, DAY)
