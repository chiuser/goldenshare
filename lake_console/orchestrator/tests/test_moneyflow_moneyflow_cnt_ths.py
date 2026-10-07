"""Concept fixtures exercise isolated candidate generation without live resources."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.checks.moneyflow_board import (
    audit_board_moneyflow_file,
    audit_board_moneyflow_standardization,
)
from orchestrator.defs.io.moneyflow_board_raw_writer import (
    build_board_moneyflow_raw_candidate,
)
from orchestrator.defs.io.moneyflow_board_silver_writer import (
    build_board_moneyflow_silver_candidate,
)
from orchestrator.defs.io.moneyflow_candidates import (
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.run_contracts.moneyflow_board import board_fields
from orchestrator.defs.source_readiness.moneyflow_board import (
    collect_board_moneyflow,
)

DAY = "2026-09-30"
DATASET = "moneyflow_cnt_ths"
MONEYFLOW_CNT_THS_FIELDS = board_fields(DATASET)


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
            else SimpleNamespace(columns=MONEYFLOW_CNT_THS_FIELDS, rows=page)
        )


def row(code="885955.TI"):
    return {
        "trade_date": "20260930",
        "ts_code": code,
        "name": "重组蛋白",
        "lead_stock": None,
        "close_price": "30.67",
        "pct_change": "3.78",
        "industry_index": "851.77",
        "company_num": 128,
        "pct_change_stock": None,
        "net_buy_amount": "80.0",
        "net_sell_amount": None,
        "net_amount": "-14.1234",
    }


def build(tmp_path, pages, **kwargs):
    clock, source = Clock(), Source(pages)
    raw = build_board_moneyflow_raw_candidate(
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
        tmp_path, [[row(), row("885769.TI")], [row("885769.TI"), row()]]
    )
    silver = build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_board_moneyflow_standardization(c, raw, silver, DAY, dataset=DATASET)
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
                "moneyflow_cnt_ths",
                {"trade_date": "20260930", "limit": 2000, "offset": 0},
                MONEYFLOW_CNT_THS_FIELDS,
            )
        ]
        * 2
    )


def test_real_public_387_row_readback(tmp_path):
    rows = json.loads(
        (Path(__file__).parent / "fixtures/moneyflow_cnt_ths_20260930.json").read_text()
    )
    assert len(rows) == 387
    raw, _, _ = build(tmp_path, [rows, rows[::-1]])
    silver = build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_board_moneyflow_standardization(c, raw, silver, DAY, dataset=DATASET)
            == 387
        )
        assert c.execute(
            "SELECT net_buy_amount,net_sell_amount,net_amount FROM read_parquet(?) WHERE ts_code='885955.TI'",
            [str(silver)],
        ).fetchone() == (Decimal(95), Decimal(75), Decimal(19))


def test_full_page_requires_termination(tmp_path):
    rows = [row(f"{i:06d}.TI") for i in range(2000)]
    raw, source, _ = build(tmp_path, [rows, [], rows[::-1], []])
    assert [c[1]["offset"] for c in source.calls] == [0, 2000, 0, 2000]
    assert (raw.parent / "round-1/scope-1/page-0.json").is_file()
    with moneyflow_candidate_connection(raw.parent) as c:
        assert audit_board_moneyflow_file(c, raw, DAY, dataset=DATASET) == 2000


@pytest.mark.parametrize(
    "key,value",
    [
        ("trade_date", "20260929"),
        ("ts_code", None),
        ("ts_code", ""),
        ("ts_code", 123),
        ("name", True),
        ("lead_stock", 12),
        ("industry_index", True),
        ("industry_index", "NaN"),
        ("industry_index", "Infinity"),
        ("industry_index", "0.00001"),
        ("industry_index", "1e-20"),
        ("industry_index", "1e-999999999999"),
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
        [{k: v for k, v in row().items() if k != "name"}],
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
    [[{**row(), "net_amount": "99"}], [row("885769.TI")], [row(), row("885769.TI")]],
)
def test_changed_second_round_preserves_unready_raw(tmp_path, second):
    with pytest.raises(MoneyflowContractError, match="source_unstable"):
        build(tmp_path, [[row()], second])
    raw = next(tmp_path.rglob("raw.parquet"))
    assert (
        json.loads((raw.parent / "receipt.json").read_text())["stage"] == "collecting"
    )
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)


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
        "orchestrator.defs.source_readiness.moneyflow_board.market_moneyflow_policy",
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
        build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)


def test_formal_cross_dataset_and_unknown_dataset_rejected_before_io(tmp_path):
    raw = (
        Path("/Volumes/datasource/data_lake/moneyflow/test/moneyflow_cnt_ths")
        / DAY
        / "raw.parquet"
    )
    with pytest.raises(MoneyflowContractError, match="formal_lake_is_not_staging"):
        build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    raw = (
        moneyflow_candidate_directory(tmp_path, "test", DAY, dataset="moneyflow_mkt_dc")
        / "raw.parquet"
    )
    with pytest.raises(MoneyflowContractError, match="raw_candidate_path"):
        build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
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
            for f in MONEYFLOW_CNT_THS_FIELDS
            if f not in ("trade_date", "ts_code", "name", "lead_stock")
        },
    }
    raw, _, _ = build(tmp_path, [[r], [r]])
    silver = build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert c.execute(
            "SELECT company_num,net_amount FROM read_parquet(?)", [str(silver)]
        ).fetchone() == (None, None)


def test_elapsed_budget():
    clock, source = Clock(), Source([[row()]])

    def complete(*_):
        clock.now = 280

    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        collect_board_moneyflow(
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
    silver = build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    assert len(source.calls) == 22
    assert len(list(raw.parent.rglob("page-*.json"))) == 20
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_board_moneyflow_standardization(c, raw, silver, DAY, dataset=DATASET)
            == 20000
        )


def test_cancel_during_stability_wait_preserves_first_round(tmp_path):
    clock, source = Clock(), Source([[row()]])

    def cancel():
        if clock.now >= 2:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        build_board_moneyflow_raw_candidate(
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
    "projection", ["* REPLACE('20260929' AS trade_date)", "* EXCLUDE(name)"]
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
            audit_board_moneyflow_file(c, bad, DAY, dataset=DATASET)


def test_physical_duplicate_and_business_change_block(tmp_path):
    from orchestrator.defs.checks.moneyflow_board import (
        audit_board_moneyflow_equality,
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
            audit_board_moneyflow_file(c, bad, DAY, dataset=DATASET)
        c.execute(
            "COPY (SELECT * REPLACE(99::DECIMAL(24,4) AS net_amount) FROM read_parquet($source)) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(changed)},
        )
        with pytest.raises(MoneyflowContractError, match="source_unstable"):
            audit_board_moneyflow_equality(c, raw, changed, dataset=DATASET)


def test_memory_limit_rejects_before_source_call(monkeypatch, tmp_path):
    import orchestrator.defs.run_contracts.moneyflow as contract

    monkeypatch.setattr(
        contract.resource, "getrusage", lambda _: SimpleNamespace(ru_maxrss=10**12)
    )
    source, clock = Source([[row()]]), Clock()
    with pytest.raises(MoneyflowContractError, match="memory_budget_exceeded"):
        build_board_moneyflow_raw_candidate(
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
    build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with pytest.raises(
        MoneyflowContractError, match="raw_source_proof|operation_conflict"
    ):
        build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        corrupt = raw.parent / "corrupt.parquet"
        corrupt.write_bytes(b"bad")
        with pytest.raises(MoneyflowContractError, match="file_unreadable"):
            audit_board_moneyflow_file(c, corrupt, DAY, dataset=DATASET)


def test_numeric_reject_identifies_field_key_and_sample(tmp_path):
    with pytest.raises(
        MoneyflowContractError, match="source_numeric_contract"
    ) as error:
        build(tmp_path, [[{**row(), "net_amount": "1.23456"}]])
    assert "net_amount" in str(error.value)
    assert "885955.TI" in str(error.value)
    assert "1.23456" in str(error.value)


def test_silver_respects_cumulative_elapsed_budget(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    path = raw.parent / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["elapsed_ms"] = 300000
    path.write_text(json.dumps(receipt))
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    assert not (raw.parent / "silver.parquet").exists()


@pytest.mark.parametrize(
    "wrong_dataset", ["moneyflow_mkt_dc", "moneyflow_dc", "", "../moneyflow_cnt_ths"]
)
def test_engine_rejects_other_sources_before_creating_candidate(
    tmp_path, wrong_dataset
):
    source, clock = Source([[row()]]), Clock()
    with pytest.raises(MoneyflowContractError, match="board_dataset"):
        build_board_moneyflow_raw_candidate(
            tushare=source,
            dataset=wrong_dataset,
            staging_root=tmp_path,
            operation_id="test",
            trade_date=DAY,
            clock=clock,
            sleep_fn=clock.sleep,
        )
    assert source.calls == []
    assert list(tmp_path.iterdir()) == []


def test_concept_index_has_24_digit_contract_and_nullable_name(tmp_path):
    r = {**row(), "industry_index": "123456789012345.1234", "name": None}
    raw, _, _ = build(tmp_path, [[r], [r]])
    silver = build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert c.execute(
            "SELECT name,industry_index FROM read_parquet(?)", [str(silver)]
        ).fetchone() == (None, Decimal("123456789012345.1234"))


@pytest.mark.parametrize(
    "industry_fields", [{"industry": "生物制品"}, {"close": "851.77"}]
)
def test_concept_rejects_industry_source_columns(tmp_path, industry_fields):
    with pytest.raises(MoneyflowContractError, match="source_row_schema"):
        build(tmp_path, [[{**row(), **industry_fields}]])
    assert not list(tmp_path.rglob("raw.parquet"))


def test_industry_and_concept_are_independent_with_same_operation(tmp_path):

    from orchestrator.defs.checks.moneyflow_board import (
        audit_board_moneyflow_equality,
    )

    raw, _, _ = build(tmp_path, [[row()], [row()]])
    industry_rows = json.loads(
        (Path(__file__).parent / "fixtures/moneyflow_ind_ths_20260930.json").read_text()
    )[:1]
    page = SimpleNamespace(
        columns=board_fields("moneyflow_ind_ths"), rows=industry_rows
    )
    industry_source, clock = Source([page, page]), Clock()
    industry = build_board_moneyflow_raw_candidate(
        tushare=industry_source,
        dataset="moneyflow_ind_ths",
        staging_root=tmp_path,
        operation_id="test",
        trade_date=DAY,
        clock=clock,
        sleep_fn=clock.sleep,
    )
    assert raw.parent != industry.parent
    assert industry_source.calls[0][0] == "moneyflow_ind_ths"
    assert json.loads((raw.parent / "receipt.json").read_text())["dataset"] == DATASET
    assert (
        json.loads((industry.parent / "receipt.json").read_text())["dataset"]
        == "moneyflow_ind_ths"
    )
    with pytest.raises(MoneyflowContractError, match="raw_candidate_path"):
        build_board_moneyflow_silver_candidate(industry, DAY, dataset=DATASET)
    with pytest.raises(MoneyflowContractError, match="raw_candidate_path"):
        build_board_moneyflow_silver_candidate(raw, DAY, dataset="moneyflow_ind_ths")
    with moneyflow_candidate_connection(raw.parent) as c:
        with pytest.raises(MoneyflowContractError, match="file_schema"):
            audit_board_moneyflow_file(c, raw, DAY, dataset="moneyflow_ind_ths")
        with pytest.raises(MoneyflowContractError, match="file_schema"):
            audit_board_moneyflow_equality(c, industry, industry, dataset=DATASET)
    build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    build_board_moneyflow_silver_candidate(industry, DAY, dataset="moneyflow_ind_ths")


def test_cross_dataset_receipt_cannot_be_reused(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    path = raw.parent / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["dataset"] = "moneyflow_ind_ths"
    path.write_text(json.dumps(receipt))
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    assert not (raw.parent / "silver.parquet").exists()


def test_industry_response_columns_rejected_before_page_persistence(tmp_path):
    page = SimpleNamespace(columns=board_fields("moneyflow_ind_ths"), rows=[row()])
    with pytest.raises(MoneyflowContractError, match="source_schema"):
        build(tmp_path, [page])
    assert not list(tmp_path.rglob("page-*.json"))


def test_physical_concept_schema_matches_independent_contract(tmp_path):
    raw, _, _ = build(tmp_path, [[row()], [row()]])
    silver = build_board_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)
    expected = [
        ("trade_date", "VARCHAR"),
        ("ts_code", "VARCHAR"),
        ("name", "VARCHAR"),
        ("lead_stock", "VARCHAR"),
        ("close_price", "DECIMAL(18,4)"),
        ("pct_change", "DECIMAL(10,4)"),
        ("industry_index", "DECIMAL(24,4)"),
        ("company_num", "INTEGER"),
        ("pct_change_stock", "DECIMAL(10,4)"),
        ("net_buy_amount", "DECIMAL(24,4)"),
        ("net_sell_amount", "DECIMAL(24,4)"),
        ("net_amount", "DECIMAL(24,4)"),
    ]
    with moneyflow_candidate_connection(raw.parent) as c:
        for path, date_type in ((raw, "VARCHAR"), (silver, "DATE")):
            actual = c.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
            assert [(r[0], r[1]) for r in actual] == [
                ("trade_date", date_type),
                *expected[1:],
            ]
