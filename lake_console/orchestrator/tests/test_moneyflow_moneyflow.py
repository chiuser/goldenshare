"""Ordinary stock moneyflow: fixed Prod projection and isolated daily candidates."""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_equality,
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.io.moneyflow_daily_raw_writer import (
    build_daily_moneyflow_raw_candidate,
)
from orchestrator.defs.io.moneyflow_daily_silver_writer import (
    build_daily_moneyflow_silver_candidate,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.source_readiness.moneyflow_daily import collect_daily_moneyflow

DAY = "2026-09-30"
DATASET = "moneyflow"
FIELDS = (
    "ts_code",
    "trade_date",
    "buy_sm_vol",
    "buy_sm_amount",
    "sell_sm_vol",
    "sell_sm_amount",
    "buy_md_vol",
    "buy_md_amount",
    "sell_md_vol",
    "sell_md_amount",
    "buy_lg_vol",
    "buy_lg_amount",
    "sell_lg_vol",
    "sell_lg_amount",
    "buy_elg_vol",
    "buy_elg_amount",
    "sell_elg_vol",
    "sell_elg_amount",
    "net_mf_vol",
    "net_mf_amount",
)
VOLUMES = tuple(f for f in FIELDS if f.endswith("_vol"))
AMOUNTS = tuple(f for f in FIELDS if f.endswith("_amount"))


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
            else SimpleNamespace(columns=FIELDS, rows=page)
        )


def row(code="000001.SZ"):
    return {
        "ts_code": code,
        "trade_date": "20260930",
        **{f: 23 for f in VOLUMES},
        **{f: "5.1234" for f in AMOUNTS},
        "net_mf_vol": -77,
        "net_mf_amount": "-91.4321",
    }


def round_pages(rows):
    pages = [rows[i : i + 2000] for i in range(0, len(rows), 2000)]
    return pages + ([[]] if len(rows) % 2000 == 0 else [])


def build(tmp_path, rows=None, second=None, pages=None, **kwargs):
    rows = [row()] if rows is None else rows
    second = rows[::-1] if second is None else second
    source = Source(
        [*round_pages(rows), *round_pages(second)] if pages is None else pages
    )
    clock = Clock()
    raw = build_daily_moneyflow_raw_candidate(
        tushare=source,
        dataset=DATASET,
        staging_root=tmp_path,
        operation_id="test",
        trade_date=DAY,
        clock=clock,
        sleep_fn=clock.sleep,
        **kwargs,
    )
    return raw, source, clock


def silver(raw):
    return build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)


def fresh_process(test_name):
    # Each Dagster worker has its own native allocation high-water mark.
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
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return True


def test_independent_schema_market_and_source_units(tmp_path):
    rows = [row("920344.BJ"), row("退市代码.SZ"), row("600000.SH")]
    raw, source, clock = build(tmp_path, rows)
    target = silver(raw)
    with moneyflow_candidate_connection(raw.parent) as c:
        for path, date_type in ((raw, "VARCHAR"), (target, "DATE")):
            actual = c.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
            assert [(r[0], r[1]) for r in actual] == [
                (
                    f,
                    "VARCHAR"
                    if f == "ts_code"
                    else date_type
                    if f == "trade_date"
                    else "BIGINT"
                    if f in VOLUMES
                    else "DECIMAL(20,4)",
                )
                for f in FIELDS
            ]
        assert (
            audit_daily_moneyflow_standardization(c, raw, target, DAY, dataset=DATASET)
            == 3
        )
        assert (
            c.execute(
                "SELECT buy_sm_vol,buy_sm_amount,net_mf_vol,net_mf_amount FROM read_parquet(?)",
                [str(target)],
            ).fetchall()
            == [(23, Decimal("5.1234"), -77, Decimal("-91.4321"))] * 3
        )
    assert clock.now >= 60
    assert (
        source.calls
        == [(DATASET, {"trade_date": "20260930", "limit": 2000, "offset": 0}, FIELDS)]
        * 2
    )


def test_real_public_5572_rows_readback(tmp_path):
    if fresh_process("test_real_public_5572_rows_readback"):
        return
    rows = json.loads(
        (Path(__file__).parent / "fixtures/moneyflow_20260930.json").read_text()
    )
    assert len(rows) == 5572
    raw, source, _ = build(tmp_path, rows)
    target = silver(raw)
    assert [r[1]["offset"] for r in source.calls] == [0, 2000, 4000] * 2
    assert all(
        r[0] == DATASET
        and r[2] == FIELDS
        and set(r[1]) == {"trade_date", "limit", "offset"}
        for r in source.calls
    )
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, target, DAY, dataset=DATASET)
            == 5572
        )
        assert (
            c.execute(
                "SELECT count(*) FROM read_parquet(?) WHERE ends_with(ts_code,'.BJ')",
                [str(target)],
            ).fetchone()[0]
            == 348
        )
        assert c.execute(
            "SELECT buy_sm_vol,buy_sm_amount,net_mf_vol,net_mf_amount FROM read_parquet(?) WHERE ts_code='000001.SZ'",
            [str(target)],
        ).fetchone() == (205754, Decimal("23685.55"), 301546, Decimal("34829.27"))
        # Source JSON -> typed Raw equality covers every value, not only row counts.
        fixture = Path(__file__).parent / "fixtures/moneyflow_20260930.json"
        projection = ",".join(
            f"{f}::{'VARCHAR' if f in ('ts_code', 'trade_date') else 'BIGINT' if f in VOLUMES else 'DECIMAL(20,4)'} AS {f}"
            for f in FIELDS
        )
        assert (
            c.execute(
                f"SELECT count(*) FROM (SELECT {projection} FROM read_json_auto($fixture) EXCEPT SELECT * FROM read_parquet($raw))",
                {"fixture": str(fixture), "raw": str(raw)},
            ).fetchone()[0]
            == 0
        )
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert receipt["row_count"] == receipt["scope_row_counts"]["all"] == 5572
    assert receipt["request_count"] == 6 and receipt["retry_count"] == 0
    assert receipt["peak_rss_bytes"] <= 768 * 1024**2


@pytest.mark.parametrize("field", VOLUMES)
@pytest.mark.parametrize("value", [-(2**63), 2**63 - 1, "1000e-3", None])
def test_bigint_exact_limits_all_nine_columns(tmp_path, field, value):
    r = {**row(), field: value}
    raw, _, _ = build(tmp_path, [r])
    target = silver(raw)
    with moneyflow_candidate_connection(raw.parent) as c:
        expected = None if value is None else int(Decimal(str(value)))
        assert (
            c.execute(f"SELECT {field} FROM read_parquet(?)", [str(target)]).fetchone()[
                0
            ]
            == expected
        )


@pytest.mark.parametrize("field", VOLUMES)
@pytest.mark.parametrize("value", [2**63, -(2**63) - 1, "1.1"])
def test_bigint_overflow_and_rounding_rejected_all_nine_columns(tmp_path, field, value):
    with pytest.raises(MoneyflowContractError, match="source_numeric_contract"):
        build(tmp_path, [{**row(), field: value}])
    assert not list(tmp_path.rglob("raw.parquet"))


@pytest.mark.parametrize("field", AMOUNTS)
@pytest.mark.parametrize("value", ["0.00001", "10000000000000000"])
def test_amount_precision_and_range_all_nine_columns(tmp_path, field, value):
    with pytest.raises(MoneyflowContractError, match="source_numeric_contract"):
        build(tmp_path, [{**row(), field: value}])


@pytest.mark.parametrize(
    "value",
    ["9999999999999999.9999", "-9999999999999999.9999", "1.23000", Decimal("0.1234")],
)
def test_decimal_exact_limits(tmp_path, value):
    raw, _, _ = build(tmp_path, [{**row(), "net_mf_amount": value}])
    with moneyflow_candidate_connection(raw.parent) as c:
        assert c.execute(
            "SELECT net_mf_amount FROM read_parquet(?)", [str(silver(raw))]
        ).fetchone()[0] == Decimal(str(value))


def test_all_numeric_nulls_preserved(tmp_path):
    raw, _, _ = build(tmp_path, [{**row(), **{f: None for f in (*VOLUMES, *AMOUNTS)}}])
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            c.execute(
                "SELECT * EXCLUDE(ts_code,trade_date) FROM read_parquet(?)",
                [str(silver(raw))],
            ).fetchone()
            == (None,) * 18
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("ts_code", None),
        ("ts_code", " "),
        ("ts_code", 123),
        ("trade_date", "20260929"),
        ("trade_date", 20260930),
        ("buy_sm_vol", True),
        ("buy_sm_vol", float(2**53)),
        ("net_mf_amount", True),
        ("net_mf_amount", "NaN"),
        ("net_mf_amount", "Infinity"),
        ("net_mf_amount", "1e-999999999999"),
        ("net_mf_amount", float(2**53)),
    ],
)
def test_invalid_source_scalar(tmp_path, key, value):
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, [{**row(), key: value}])


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row(), row()],
        [{**row(), "trade_count": 1}],
        [{k: v for k, v in row().items() if k != "net_mf_vol"}],
    ],
)
def test_empty_duplicates_and_schema_unready(tmp_path, rows):
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, rows)
    assert (
        json.loads(next(tmp_path.rglob("receipt.json")).read_text())["stage"]
        == "collecting"
    )


@pytest.mark.parametrize(
    "second",
    [[{**row(), "buy_md_vol": 99}], [row("600000.SH")], [row(), row("600000.SH")]],
)
def test_second_round_any_field_key_or_count_changed(tmp_path, second):
    with pytest.raises(MoneyflowContractError, match="source_unstable"):
        build(tmp_path, second=second)
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        silver(next(tmp_path.rglob("raw.parquet")))


def test_cross_page_duplicate_and_full_page_termination(tmp_path):
    rows = [row(f"{i:06d}.SZ") for i in range(2000)]
    with pytest.raises(MoneyflowContractError, match="source_duplicate_key"):
        build(tmp_path / "bad", pages=[rows, [rows[0]]])
    raw, source, _ = build(tmp_path / "good", rows)
    assert [r[1]["offset"] for r in source.calls] == [0, 2000] * 2
    assert len(list(raw.parent.rglob("page-*.json"))) == 2


def test_exact_20000_row_pressure_and_total_rejection(tmp_path):
    if fresh_process("test_exact_20000_row_pressure_and_total_rejection"):
        return
    observed = json.loads(
        (Path(__file__).parent / "fixtures/moneyflow_20260930.json").read_text()
    )
    rows = [
        {**observed[i % len(observed)], "ts_code": f"{i:06d}.SZ"}
        for i in range(20000)
    ]
    raw, source, _ = build(tmp_path / "good", rows)
    assert len(source.calls) == 22 and len(list(raw.parent.rglob("page-*.json"))) == 20
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(
                c, raw, silver(raw), DAY, dataset=DATASET
            )
            == 20000
        )
    assert (
        json.loads((raw.parent / "receipt.json").read_text())["peak_rss_bytes"]
        <= 768 * 1024**2
    )
    with pytest.raises(MoneyflowContractError, match="source_row_budget"):
        build(tmp_path / "bad", pages=[*round_pages(rows)[:-1], [row("999999.SZ")]])
    assert len(list((tmp_path / "bad").rglob("page-*.json"))) == 10


def test_page_oversized_and_empty_columns_fail(tmp_path):
    for i, page in enumerate(([row()] * 2001, SimpleNamespace(columns=(), rows=[]))):
        with pytest.raises(MoneyflowContractError, match="page_request_failed"):
            build(tmp_path / str(i), pages=[page])


def test_retry_shared_request_budget(monkeypatch, tmp_path):
    from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

    raw, source, _ = build(
        tmp_path / "retry", pages=[TimeoutError("timeout"), [row()], [row()]]
    )
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert (
        receipt["request_count"] == len(source.calls) == 3
        and receipt["retry_count"] == 1
    )
    monkeypatch.setattr(
        "orchestrator.defs.source_readiness.moneyflow_daily.market_moneyflow_policy",
        lambda: TushareRequestPolicy(max_requests=1),
    )
    with pytest.raises(MoneyflowContractError, match="max_requests_exceeded"):
        build(tmp_path / "budget")


@pytest.mark.parametrize("during_wait", [False, True])
def test_cancel_preserves_page_or_unready_round(tmp_path, during_wait):
    clock, source = (
        Clock(),
        Source([[row()] if during_wait else [row(f"{i:06d}.SZ") for i in range(2000)]]),
    )

    def cancel():
        if clock.now >= 2 if during_wait else bool(list(tmp_path.rglob("page-*.json"))):
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            dataset=DATASET,
            staging_root=tmp_path,
            operation_id="test",
            trade_date=DAY,
            clock=clock,
            sleep_fn=clock.sleep,
            check_cancel=cancel,
        )
    assert len(source.calls) == len(list(tmp_path.rglob("page-*.json"))) == 1
    assert (
        json.loads(next(tmp_path.rglob("receipt.json")).read_text())["stage"]
        == "collecting"
    )


def test_elapsed_budget_includes_conversion_and_wait():
    clock, source = Clock(), Source([[row()]])

    def complete(*_):
        clock.now = 280

    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        collect_daily_moneyflow(
            tushare=source,
            dataset=DATASET,
            trade_date=DAY,
            consume_page=lambda *_: None,
            complete_round=complete,
            clock=clock,
            sleep_fn=clock.sleep,
        )
    assert len(source.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"dataset": "moneyflow_dc"},
        {"source": "prod"},
        {"row_count": 2},
        {"scope_row_counts": {"all": 2}},
        {"elapsed_ms": 300000},
    ],
)
def test_silver_proof_tampered_or_budget_rejected(tmp_path, change):
    raw, _, _ = build(tmp_path)
    p = raw.parent / "receipt.json"
    p.write_text(json.dumps({**json.loads(p.read_text()), **change}))
    with pytest.raises(MoneyflowContractError):
        silver(raw)


def test_no_overwrite_and_file_hash_tamper(tmp_path):
    raw, _, _ = build(tmp_path)
    with pytest.raises(MoneyflowContractError, match="operation_conflict"):
        build(tmp_path)
    silver(raw)
    with pytest.raises(MoneyflowContractError, match="operation_conflict|raw_source_proof"):
        silver(raw)
    (raw.parent / "verification.parquet").write_bytes(b"tampered")
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        silver(raw)


@pytest.mark.parametrize(
    "projection",
    [
        "* REPLACE('20260929' AS trade_date)",
        "* EXCLUDE(buy_sm_vol)",
        "* REPLACE(1::INTEGER AS buy_sm_vol)",
        "* REPLACE('' AS ts_code)",
    ],
)
def test_physical_date_key_and_schema_fail(tmp_path, projection):
    raw, _, _ = build(tmp_path)
    bad = raw.parent / "bad.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            f"COPY (SELECT {projection} FROM read_parquet($raw)) TO $bad (FORMAT PARQUET)",
            {"raw": str(raw), "bad": str(bad)},
        )
        with pytest.raises(MoneyflowContractError):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)


def test_physical_duplicate_and_value_difference_fail(tmp_path):
    raw, _, _ = build(tmp_path)
    bad = raw.parent / "bad.parquet"
    changed = raw.parent / "changed.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            "COPY (SELECT * FROM read_parquet($raw) UNION ALL SELECT * FROM read_parquet($raw)) TO $bad (FORMAT PARQUET)",
            {"raw": str(raw), "bad": str(bad)},
        )
        with pytest.raises(MoneyflowContractError, match="file_count_date_or_key"):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)
        c.execute(
            "COPY (SELECT * REPLACE(99::BIGINT AS net_mf_vol) FROM read_parquet($raw)) TO $bad (FORMAT PARQUET)",
            {"raw": str(raw), "bad": str(changed)},
        )
        with pytest.raises(MoneyflowContractError, match="source_unstable"):
            audit_daily_moneyflow_equality(c, raw, changed, dataset=DATASET)


def test_memory_budget_before_source_call(monkeypatch, tmp_path):
    import orchestrator.defs.run_contracts.moneyflow as contract

    monkeypatch.setattr(
        contract.resource, "getrusage", lambda _: SimpleNamespace(ru_maxrss=10**12)
    )
    source = Source([[row()]])
    with pytest.raises(MoneyflowContractError, match="memory_budget_exceeded"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            dataset=DATASET,
            staging_root=tmp_path,
            operation_id="test",
            trade_date=DAY,
        )
    assert source.calls == []


def test_foreign_formal_retired_and_unknown_dataset_paths_fail_before_io(tmp_path):
    for dataset, base, reason in (
        (DATASET, Path("/Volumes/datasource/data_lake"), "formal_lake_is_not_staging"),
        (
            DATASET,
            Path("/Volumes/datasource/goldenshare-tushare-lake"),
            "staging_volume_root",
        ),
        ("moneyflow_ind_dc", tmp_path, "raw_candidate_path"),
    ):
        raw = base / "moneyflow/test" / dataset / DAY / "raw.parquet"
        with pytest.raises(MoneyflowContractError, match=reason):
            silver(raw)
    source = Source([])
    with pytest.raises(MoneyflowContractError, match="daily_dataset"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            dataset="moneyflow_dc",
            staging_root=tmp_path,
            operation_id="unknown",
            trade_date=DAY,
        )
    assert source.calls == [] and not (tmp_path / "moneyflow/unknown").exists()
