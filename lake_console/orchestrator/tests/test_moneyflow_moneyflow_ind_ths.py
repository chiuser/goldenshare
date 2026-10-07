"""Industry fixtures exercise isolated candidate generation without live resources."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
)
from orchestrator.defs.io.moneyflow_candidates import (
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
)
from orchestrator.defs.io.moneyflow_daily_raw_writer import (
    build_daily_moneyflow_raw_candidate,
)
from orchestrator.defs.io.moneyflow_daily_silver_writer import (
    build_daily_moneyflow_silver_candidate,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.run_contracts.moneyflow_daily import daily_fields
from orchestrator.defs.source_readiness.moneyflow_daily import (
    collect_daily_moneyflow,
)

DAY = "2026-09-30"
DATASET = "moneyflow_ind_ths"
MONEYFLOW_IND_THS_FIELDS = daily_fields(DATASET)


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Source:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def call(self, api, params, fields):
        self.calls.append((api, params, fields))
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        return (
            page
            if isinstance(page, SimpleNamespace)
            else SimpleNamespace(columns=MONEYFLOW_IND_THS_FIELDS, rows=page)
        )


def row(code="881142.TI"):
    return {
        "trade_date": "20260930",
        "ts_code": code,
        "industry": "生物制品",
        "lead_stock": None,
        "close": "6727.88",
        "pct_change": "4.63",
        "company_num": 56,
        "pct_change_stock": None,
        "close_price": "102.64",
        "net_buy_amount": "80.0",
        "net_sell_amount": None,
        "net_amount": "-14.1234",
    }


def build(tmp_path, pages, **kwargs):
    clock, source = Clock(), Source(pages)
    raw = build_daily_moneyflow_raw_candidate(
        tushare=source,
        staging_root=tmp_path,
        operation_id="test",
        trade_date=DAY,
        clock=clock,
        sleep_fn=clock.sleep,
        **kwargs,
        dataset=DATASET,
    )
    return raw, source, clock


def test_stable_order_independent_preserves_units_nulls_and_negative(tmp_path):
    raw, source, clock = build(
        tmp_path, [[row(), row("881175.TI")], [row("881175.TI"), row()]]
    )
    silver = build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, silver, DAY, dataset=DATASET)
            == 2
        )
        assert (
            c.execute(
                "SELECT net_buy_amount,net_sell_amount,net_amount FROM read_parquet(?) ORDER BY ts_code",
                [str(raw)],
            ).fetchall()
            == [(Decimal(80), None, Decimal("-14.1234"))] * 2
        )
    assert clock.now >= 60
    assert (
        source.calls
        == [
            (
                "moneyflow_ind_ths",
                {"trade_date": "20260930", "limit": 2000, "offset": 0},
                MONEYFLOW_IND_THS_FIELDS,
            )
        ]
        * 2
    )


def test_real_public_ninety_row_readback(tmp_path):
    rows = json.loads(
        (Path(__file__).parent / "fixtures/moneyflow_ind_ths_20260930.json").read_text()
    )
    assert len(rows) == 90
    raw, _, _ = build(tmp_path, [rows, rows[::-1]])
    silver = build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, silver, DAY, dataset=DATASET)
            == 90
        )
        assert c.execute(
            "SELECT net_buy_amount,net_sell_amount,net_amount FROM read_parquet(?) WHERE ts_code='881273.TI'",
            [str(silver)],
        ).fetchone() == (Decimal(50), Decimal(34), Decimal(15))


def test_full_page_requires_termination(tmp_path):
    rows = [row(f"{i:06d}.TI") for i in range(2000)]
    raw, source, _ = build(tmp_path, [rows, [], rows[::-1], []])
    assert [c[1]["offset"] for c in source.calls] == [0, 2000, 0, 2000]
    assert (raw.parent / "round-1/scope-1/page-0.json").is_file()
    with moneyflow_candidate_connection(raw.parent) as c:
        assert audit_daily_moneyflow_file(c, raw, DAY, dataset=DATASET) == 2000


@pytest.mark.parametrize(
    "key,value",
    [
        ("trade_date", "20260929"),
        ("ts_code", None),
        ("ts_code", ""),
        ("ts_code", 123),
        ("industry", True),
        ("lead_stock", 12),
        ("close", True),
        ("close", "NaN"),
        ("close", "Infinity"),
        ("close", "0.00001"),
        ("close", "1e-20"),
        ("close", "1e-999999999999"),
        ("pct_change", "1000000"),
        ("company_num", "1.1"),
        ("company_num", 2147483648),
        ("company_num", True),
        ("net_amount", "100000000000000000000"),
        ("net_amount", float(2**53)),
    ],
)
def test_invalid_source_scalars(tmp_path, key, value):
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, [[{**row(), key: value}]])
    assert not list(tmp_path.rglob("raw.parquet"))


@pytest.mark.parametrize(
    "value", ["1.23000", "123e-2", "0e-20", "1000e-3", "1000.000e-3", Decimal("1.2300")]
)
def test_exact_decimal_not_rounded(tmp_path, value):
    r = {**row(), "net_amount": value}
    raw, _, _ = build(tmp_path, [[r], [r]])
    with moneyflow_candidate_connection(raw.parent) as c:
        assert c.execute(
            "SELECT net_amount FROM read_parquet(?)", [str(raw)]
        ).fetchone()[0] == Decimal(str(value))


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{k: v for k, v in row().items() if k != "industry"}],
        [{**row(), "extra": 1}],
        [row(), row()],
    ],
)
def test_empty_schema_duplicate_unready(tmp_path, rows):
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, [rows])
    assert (
        json.loads(next(tmp_path.rglob("receipt.json")).read_text())["stage"]
        == "collecting"
    )


def test_cross_page_duplicate(tmp_path):
    rows = [row(f"{i:06d}.TI") for i in range(2000)]
    with pytest.raises(MoneyflowContractError, match="source_duplicate_key"):
        build(tmp_path, [rows, [rows[0]]])
    assert len(list(tmp_path.rglob("page-*.json"))) == 2


@pytest.mark.parametrize(
    "second",
    [[{**row(), "net_amount": "99"}], [row("881175.TI")], [row(), row("881175.TI")]],
)
def test_changed_second_round_preserves_unready_raw(tmp_path, second):
    with pytest.raises(MoneyflowContractError, match="source_unstable"):
        build(tmp_path, [[row()], second])
    raw = next(tmp_path.rglob("raw.parquet"))
    assert (
        json.loads((raw.parent / "receipt.json").read_text())["stage"] == "collecting"
    )
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)


def run_large_fixture_in_fresh_process(test_name):
    # A Dagster execution worker is a fresh process. Do not combine native
    # allocation high-water marks from separate 20k-row fixtures in one worker.
    if os.environ.get("MONEYFLOW_FIXTURE_CHILD") == "1":
        return False
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            f"tests/{Path(__file__).name}::{test_name}",
        ],
        cwd=Path(__file__).parents[1],
        env={
            "MONEYFLOW_FIXTURE_CHILD": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": os.defpath,
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return True


def test_page_and_total_row_budgets(tmp_path):
    if run_large_fixture_in_fresh_process("test_page_and_total_row_budgets"):
        return
    with pytest.raises(MoneyflowContractError, match="page_request_failed"):
        build(tmp_path / "oversized", [[row(f"{i:06d}.TI") for i in range(2001)]])
    pages = [
        [row(f"{page * 2000 + i:06d}.TI") for i in range(2000)] for page in range(10)
    ]
    with pytest.raises(MoneyflowContractError, match="source_row_budget"):
        build(tmp_path / "total", [*pages, [row("999999.TI")]])
    assert len(list((tmp_path / "total").rglob("page-*.json"))) == 10


def test_shared_budget(monkeypatch, tmp_path):
    from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

    monkeypatch.setattr(
        "orchestrator.defs.source_readiness.moneyflow_daily.market_moneyflow_policy",
        lambda: TushareRequestPolicy(max_requests=1),
    )
    with pytest.raises(MoneyflowContractError, match="max_requests_exceeded"):
        build(tmp_path, [[row()]])
    assert len(list(tmp_path.rglob("raw.parquet"))) == 1


def test_cancel_after_page(tmp_path):
    def cancel():
        if list(tmp_path.rglob("page-*.json")):
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        build(
            tmp_path, [[row(f"{i:06d}.TI") for i in range(2000)]], check_cancel=cancel
        )
    assert len(list(tmp_path.rglob("page-*.json"))) == 1
    assert not list(tmp_path.rglob("raw.parquet"))


def test_no_overwrite_or_tampered_proof(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    with pytest.raises(MoneyflowContractError, match="operation_conflict"):
        build(tmp_path, [[row()], [row()]])
    (raw.parent / "verification.parquet").write_bytes(b"tampered")
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)


def test_formal_cross_dataset_and_unknown_dataset_rejected_before_io(tmp_path):
    raw = (
        Path("/Volumes/datasource/data_lake/moneyflow/test/moneyflow_ind_ths")
        / DAY
        / "raw.parquet"
    )
    with pytest.raises(MoneyflowContractError, match="formal_lake_is_not_staging"):
        build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    raw = (
        moneyflow_candidate_directory(tmp_path, "test", DAY, dataset="moneyflow_mkt_dc")
        / "raw.parquet"
    )
    with pytest.raises(MoneyflowContractError, match="raw_candidate_path"):
        build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with pytest.raises(MoneyflowContractError, match="candidate_dataset"):
        moneyflow_candidate_directory(tmp_path, "test", DAY, dataset="moneyflow_dc")


def test_no_schema_is_not_empty_success(tmp_path):
    with pytest.raises(MoneyflowContractError, match="page_request_failed"):
        build(tmp_path, [SimpleNamespace(columns=(), rows=[])])


def test_numeric_nulls_preserved(tmp_path):
    r = {
        **row(),
        **{
            f: None
            for f in MONEYFLOW_IND_THS_FIELDS
            if f not in ("trade_date", "ts_code", "industry", "lead_stock")
        },
    }
    raw, _, _ = build(tmp_path, [[r], [r]])
    silver = build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert c.execute(
            "SELECT company_num,net_amount FROM read_parquet(?)", [str(silver)]
        ).fetchone() == (None, None)


def test_elapsed_budget():
    clock, source = Clock(), Source([[row()]])

    def complete(*_):
        clock.now = 280

    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        collect_daily_moneyflow(
            tushare=source,
            trade_date=DAY,
            consume_page=lambda *_: None,
            complete_round=complete,
            clock=clock,
            sleep_fn=clock.sleep,
            dataset=DATASET,
        )
    assert len(source.calls) == 1


def test_exact_row_limit_succeeds_with_both_terminators(tmp_path):
    if run_large_fixture_in_fresh_process(
        "test_exact_row_limit_succeeds_with_both_terminators"
    ):
        return
    pages = [
        [row(f"{page * 2000 + i:06d}.TI") for i in range(2000)] for page in range(10)
    ]
    raw, source, _ = build(tmp_path, [*pages, [], *pages, []])
    silver = build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    assert len(source.calls) == 22
    assert len(list(raw.parent.rglob("page-*.json"))) == 20
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, silver, DAY, dataset=DATASET)
            == 20000
        )


def test_cancel_during_stability_wait_preserves_first_round(tmp_path):
    clock, source = Clock(), Source([[row()]])

    def cancel():
        if clock.now >= 2:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            staging_root=tmp_path,
            operation_id="test",
            trade_date=DAY,
            clock=clock,
            sleep_fn=clock.sleep,
            check_cancel=cancel,
            dataset=DATASET,
        )
    assert len(source.calls) == 1
    raw = next(tmp_path.rglob("raw.parquet"))
    assert (
        json.loads((raw.parent / "receipt.json").read_text())["stage"] == "collecting"
    )


def test_transient_retry_shares_attempt_accounting(tmp_path):
    raw, source, _ = build(tmp_path, [TimeoutError("timeout"), [row()], [row()]])
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert receipt["request_count"] == 3
    assert receipt["retry_count"] == 1
    assert [c[1]["offset"] for c in source.calls] == [0, 0, 0]


@pytest.mark.parametrize(
    "projection", ["* REPLACE('20260929' AS trade_date)", "* EXCLUDE(industry)"]
)
def test_physical_file_date_and_schema_block(tmp_path, projection):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    bad = raw.parent / "bad.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            f"COPY (SELECT {projection} FROM read_parquet($source)) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(bad)},
        )
        with pytest.raises(MoneyflowContractError):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)


def test_physical_duplicate_and_business_change_block(tmp_path):
    from orchestrator.defs.checks.moneyflow_daily import (
        audit_daily_moneyflow_equality,
    )

    raw, _, _ = build(tmp_path, [[row()], [row()]])
    bad = raw.parent / "bad.parquet"
    changed = raw.parent / "changed.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            "COPY (SELECT * FROM read_parquet($source) UNION ALL SELECT * FROM read_parquet($source)) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(bad)},
        )
        with pytest.raises(MoneyflowContractError, match="file_count_date_or_key"):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)
        c.execute(
            "COPY (SELECT * REPLACE(99::DECIMAL(24,4) AS net_amount) FROM read_parquet($source)) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(changed)},
        )
        with pytest.raises(MoneyflowContractError, match="source_unstable"):
            audit_daily_moneyflow_equality(c, raw, changed, dataset=DATASET)


def test_memory_limit_rejects_before_source_call(monkeypatch, tmp_path):
    import orchestrator.defs.run_contracts.moneyflow as contract

    monkeypatch.setattr(
        contract.resource, "getrusage", lambda _: SimpleNamespace(ru_maxrss=10**12)
    )
    source, clock = Source([[row()]]), Clock()
    with pytest.raises(MoneyflowContractError, match="memory_budget_exceeded"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            staging_root=tmp_path,
            operation_id="test",
            trade_date=DAY,
            clock=clock,
            sleep_fn=clock.sleep,
            dataset=DATASET,
        )
    assert source.calls == []


def test_silver_conflict_and_corrupt_raw_block(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with pytest.raises(
        MoneyflowContractError, match="raw_source_proof|operation_conflict"
    ):
        build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        corrupt = raw.parent / "corrupt.parquet"
        corrupt.write_bytes(b"bad")
        with pytest.raises(MoneyflowContractError, match="file_unreadable"):
            audit_daily_moneyflow_file(c, corrupt, DAY, dataset=DATASET)


def test_numeric_reject_identifies_field_key_and_sample(tmp_path):
    with pytest.raises(
        MoneyflowContractError, match="source_numeric_contract"
    ) as error:
        build(tmp_path, [[{**row(), "net_amount": "1.23456"}]])
    assert "net_amount" in str(error.value)
    assert "881142.TI" in str(error.value)
    assert "1.23456" in str(error.value)


def test_silver_respects_cumulative_elapsed_budget(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    path = raw.parent / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["elapsed_ms"] = 300000
    path.write_text(json.dumps(receipt))
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    assert not (raw.parent / "silver.parquet").exists()
