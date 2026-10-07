"""Independent DC board facts, three-scope collection and isolated file acceptance."""

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
DATASET = "moneyflow_ind_dc"
SCOPES = ("行业", "概念", "地域")
FIELDS = (
    "trade_date",
    "content_type",
    "ts_code",
    "name",
    "pct_change",
    "close",
    "net_amount",
    "net_amount_rate",
    "buy_elg_amount",
    "buy_elg_amount_rate",
    "buy_lg_amount",
    "buy_lg_amount_rate",
    "buy_md_amount",
    "buy_md_amount_rate",
    "buy_sm_amount",
    "buy_sm_amount_rate",
    "buy_sm_amount_stock",
    "rank",
)


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


def row(content_type="行业", name="测试板块", code=None):
    return {
        "trade_date": "20260930",
        "content_type": content_type,
        "ts_code": code,
        "name": name,
        "pct_change": "-1.23",
        "close": "2050.67",
        "net_amount": "-5.1234",
        "net_amount_rate": None,
        "buy_elg_amount": "3",
        "buy_elg_amount_rate": "2.5",
        "buy_lg_amount": "2",
        "buy_lg_amount_rate": "1.94",
        "buy_md_amount": None,
        "buy_md_amount_rate": None,
        "buy_sm_amount": "-4",
        "buy_sm_amount_rate": "-2.38",
        "buy_sm_amount_stock": None,
        "rank": 1,
    }


def sample():
    return [row(s) for s in SCOPES]


def pages_for_round(rows):
    pages = []
    for scope in SCOPES:
        scoped = [r for r in rows if r["content_type"] == scope]
        pages.extend(scoped[i : i + 2000] for i in range(0, len(scoped), 2000))
        if len(scoped) % 2000 == 0:
            pages.append([])
    return pages


def build_pages(tmp_path, pages, **kwargs):
    source, clock = Source(pages), Clock()
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


def build(tmp_path, rows=None, second=None, **kwargs):
    rows = sample() if rows is None else rows
    second = rows[::-1] if second is None else second
    return build_pages(
        tmp_path, [*pages_for_round(rows), *pages_for_round(second)], **kwargs
    )


def silver(raw):
    return build_daily_moneyflow_silver_candidate(raw, DAY, dataset=DATASET)


def test_three_scopes_preserve_source_units_nulls_and_triple_key(tmp_path):
    rows = sample() + [
        row("行业", "同代码另一名称", "BK0000.DC"),
        row("行业", "第三名称", "BK0000.DC"),
    ]
    raw, source, clock = build(tmp_path, rows)
    result = silver(raw)
    assert clock.now >= 60
    assert (
        source.calls
        == [
            (
                DATASET,
                {
                    "trade_date": "20260930",
                    "limit": 2000,
                    "offset": 0,
                    "content_type": s,
                },
                FIELDS,
            )
            for s in SCOPES
        ]
        * 2
    )
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert receipt["scope_row_counts"] == {"行业": 3, "概念": 1, "地域": 1}
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, result, DAY, dataset=DATASET)
            == 5
        )
        assert (
            c.execute(
                "SELECT count(*) FROM read_parquet(?) WHERE ts_code IS NULL",
                [str(result)],
            ).fetchone()[0]
            == 3
        )
        assert (
            c.execute(
                "SELECT net_amount,buy_md_amount,net_amount_rate FROM read_parquet(?)",
                [str(result)],
            ).fetchall()
            == [(Decimal("-5.1234"), None, None)] * 5
        )


def test_real_public_1031_row_readback(tmp_path):
    rows = json.loads(
        (Path(__file__).parent / "fixtures/moneyflow_ind_dc_20260930.json").read_text()
    )
    assert len(rows) == 1031
    raw, source, _ = build(tmp_path, rows)
    result = silver(raw)
    assert len(source.calls) == 6
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert receipt["scope_row_counts"] == {"行业": 496, "概念": 504, "地域": 31}
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, result, DAY, dataset=DATASET)
            == 1031
        )
        assert c.execute(
            "SELECT net_amount,buy_elg_amount,buy_lg_amount,buy_md_amount,buy_sm_amount,rank FROM read_parquet(?) WHERE content_type='概念' AND name='创新药'",
            [str(result)],
        ).fetchone() == (
            Decimal(4150709248),
            Decimal(2218624512),
            Decimal(1932084736),
            Decimal(-1931396608),
            Decimal(-2047282688),
            1,
        )
        # Check the exact source amount in yuan, without unit rescaling.
        assert c.execute(
            "SELECT net_amount,buy_elg_amount,buy_lg_amount FROM read_parquet(?) WHERE content_type='地域' AND name='浙江板块'",
            [str(result)],
        ).fetchone() == (Decimal(1319086848), Decimal(1111375872), Decimal(207710976))


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("round_number", [1, 2])
def test_any_empty_scope_is_unready(tmp_path, scope, round_number):
    missing = [r for r in sample() if r["content_type"] != scope]
    with pytest.raises(MoneyflowContractError, match=f"source_pending:{scope}"):
        build(tmp_path, missing if round_number == 1 else sample(), missing)
    receipt = json.loads(next(tmp_path.rglob("receipt.json")).read_text())
    assert receipt["stage"] == "collecting"
    assert bool(list(tmp_path.rglob("raw.parquet"))) == (round_number == 2)
    assert not list(tmp_path.rglob("silver.parquet"))


@pytest.mark.parametrize("value", ["概念", "未知", None, "", 123])
def test_scope_response_cannot_cross_or_invent_category(tmp_path, value):
    with pytest.raises(MoneyflowContractError, match="source_partition_or_key"):
        build_pages(tmp_path, [[{**row(), "content_type": value}]])
    assert not list(tmp_path.rglob("raw.parquet"))


@pytest.mark.parametrize(
    "key,value",
    [
        ("trade_date", "20260929"),
        ("trade_date", 20260930),
        ("name", None),
        ("name", " "),
        ("name", 123),
        ("ts_code", 123),
        ("buy_sm_amount_stock", True),
        ("close", True),
        ("close", "0.00001"),
        ("net_amount", "NaN"),
        ("net_amount", "Infinity"),
        ("net_amount", "1e-20"),
        ("net_amount", "1e-999999999999"),
        ("net_amount", float(2**53)),
        ("net_amount", "100000000000000000000"),
        ("net_amount_rate", "1000000"),
        ("rank", "1.1"),
        ("rank", True),
        ("rank", 2147483648),
    ],
)
def test_identity_and_numeric_contract_rejects_invalid_scalars(tmp_path, key, value):
    with pytest.raises(MoneyflowContractError):
        build_pages(tmp_path, [[{**row(), key: value}]])
    assert not list(tmp_path.rglob("raw.parquet"))


@pytest.mark.parametrize(
    "value", ["1.23000", "123e-2", "1000e-3", "0e-20", Decimal("1.2300")]
)
def test_exact_scale_and_nullable_rank(tmp_path, value):
    rows = [{**r, "net_amount": value, "rank": None} for r in sample()]
    raw, _, _ = build(tmp_path, rows)
    result = silver(raw)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            c.execute(
                "SELECT net_amount,rank FROM read_parquet(?)", [str(result)]
            ).fetchall()
            == [(Decimal(str(value)), None)] * 3
        )


@pytest.mark.parametrize(
    "rows", [[{k: v for k, v in row().items() if k != "rank"}], [{**row(), "extra": 1}]]
)
def test_exact_source_fields_required(tmp_path, rows):
    with pytest.raises(MoneyflowContractError, match="source_row_schema"):
        build_pages(tmp_path, [rows])


def test_duplicate_triple_key_rejected_even_when_code_differs(tmp_path):
    with pytest.raises(MoneyflowContractError, match="source_duplicate_key"):
        build_pages(tmp_path, [[row(code="BK0001.DC"), row(code="BK0002.DC")]])


def test_full_page_termination_scope_offsets_and_cross_page_duplicates(tmp_path):
    rows = [row("行业", f"行业{i}") for i in range(2000)]
    raw, source, _ = build(tmp_path / "ok", rows + sample()[1:])
    assert [(call[1]["content_type"], call[1]["offset"]) for call in source.calls] == [
        ("行业", 0),
        ("行业", 2000),
        ("概念", 0),
        ("地域", 0),
    ] * 2
    assert (raw.parent / "round-1/scope-1/page-0.json").is_file()
    with pytest.raises(MoneyflowContractError, match="source_duplicate_key"):
        build_pages(tmp_path / "duplicate", [rows, [rows[0]]])


@pytest.mark.parametrize(
    "second",
    [
        [{**r, "net_amount": "99"} for r in sample()],
        [{**r, "name": "新名称"} for r in sample()],
        sample() + [row("概念", "新名称")],
    ],
)
def test_unstable_second_round_preserves_first_raw(tmp_path, second):
    with pytest.raises(MoneyflowContractError, match="source_unstable"):
        build(tmp_path, second=second)
    raw = next(tmp_path.rglob("raw.parquet"))
    assert (
        json.loads((raw.parent / "receipt.json").read_text())["stage"] == "collecting"
    )
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        silver(raw)


def test_shared_request_budget_across_scopes_and_rounds(monkeypatch, tmp_path):
    from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

    monkeypatch.setattr(
        "orchestrator.defs.source_readiness.moneyflow_daily.market_moneyflow_policy",
        lambda: TushareRequestPolicy(max_requests=4),
    )
    with pytest.raises(MoneyflowContractError, match="max_requests_exceeded"):
        build(tmp_path)
    assert list(tmp_path.rglob("raw.parquet"))
    assert not list(tmp_path.rglob("silver.parquet"))


def test_transient_retry_counts_in_same_session(tmp_path):
    pages = [[row(s)] for s in SCOPES] * 2
    raw, source, _ = build_pages(tmp_path, [TimeoutError("timeout"), *pages])
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert receipt["request_count"] == 7
    assert receipt["retry_count"] == 1
    assert source.calls[0] == source.calls[1]


def test_cancellation_between_scopes_does_not_fetch_next_category(tmp_path):
    source, clock = Source([[row()]]), Clock()

    def cancel():
        if list(tmp_path.rglob("page-*.json")):
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
    assert len(source.calls) == 1
    assert not list(tmp_path.rglob("raw.parquet"))


def test_cancellation_during_stability_wait_preserves_first_round(tmp_path):
    source, clock = Source([[row(s)] for s in SCOPES]), Clock()
    wait_started = [None]

    def cancel():
        if list(tmp_path.rglob("raw.parquet")) and wait_started[0] is None:
            wait_started[0] = clock.now
        if wait_started[0] is not None and clock.now - wait_started[0] >= 2:
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
    assert len(source.calls) == 3
    assert list(tmp_path.rglob("raw.parquet"))


def test_elapsed_budget_does_not_reset_at_scope_or_round():
    clock, source = Clock(), Source([[row(s)] for s in SCOPES])

    def consume(*_):
        clock.now = 275

    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        collect_daily_moneyflow(
            tushare=source,
            dataset=DATASET,
            trade_date=DAY,
            consume_page=consume,
            complete_round=lambda *_: None,
            clock=clock,
            sleep_fn=clock.sleep,
        )
    assert len(source.calls) == 1


def fresh_large_fixture(test_name):
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
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return True


def test_exact_20000_rows_with_26_requests_across_all_scopes(tmp_path):
    if fresh_large_fixture("test_exact_20000_rows_with_26_requests_across_all_scopes"):
        return
    rows = [
        row(s, f"{s}{i}")
        for s, count in zip(SCOPES, (16000, 2000, 2000), strict=True)
        for i in range(count)
    ]
    raw, source, _ = build(tmp_path, rows)
    result = silver(raw)
    assert len(source.calls) == 26
    assert len(list(raw.parent.rglob("page-*.json"))) == 20
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, result, DAY, dataset=DATASET)
            == 20000
        )


def test_total_rows_budget_includes_all_three_categories(tmp_path):
    if fresh_large_fixture("test_total_rows_budget_includes_all_three_categories"):
        return
    rows = [row("行业", f"行业{i}") for i in range(20000)] + sample()[1:]
    with pytest.raises(MoneyflowContractError, match="source_row_budget"):
        build(tmp_path, rows)
    assert len(list(tmp_path.rglob("page-*.json"))) == 10
    assert not list(tmp_path.rglob("raw.parquet"))


@pytest.mark.parametrize(
    "projection",
    [
        "* REPLACE('20260929' AS trade_date)",
        "* EXCLUDE(content_type)",
        "* REPLACE(NULL::VARCHAR AS name)",
    ],
)
def test_physical_key_schema_and_date_rejected(tmp_path, projection):
    raw, _, _ = build(tmp_path)
    bad = raw.parent / "bad.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            f"COPY (SELECT {projection} FROM read_parquet($source)) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(bad)},
        )
        with pytest.raises(MoneyflowContractError):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)


def test_physical_missing_category_and_duplicate_block(tmp_path):
    raw, _, _ = build(tmp_path)
    with moneyflow_candidate_connection(raw.parent) as c:
        for filename, sql, reason in [
            (
                "missing",
                "SELECT * FROM read_parquet($source) WHERE content_type != '地域'",
                "file_scope_coverage",
            ),
            (
                "duplicate",
                "SELECT * FROM read_parquet($source) UNION ALL SELECT * FROM read_parquet($source)",
                "file_count_date_or_key",
            ),
        ]:
            bad = raw.parent / f"{filename}.parquet"
            c.execute(
                f"COPY ({sql}) TO $target (FORMAT PARQUET)",
                {"source": str(raw), "target": str(bad)},
            )
            with pytest.raises(MoneyflowContractError, match=reason):
                audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)


def test_physical_schema_is_independent_18_field_contract(tmp_path):
    raw, _, _ = build(tmp_path)
    result = silver(raw)
    expected = [
        ("trade_date", "VARCHAR"),
        ("content_type", "VARCHAR"),
        ("ts_code", "VARCHAR"),
        ("name", "VARCHAR"),
        ("pct_change", "DECIMAL(10,4)"),
        ("close", "DECIMAL(18,4)"),
        ("net_amount", "DECIMAL(24,4)"),
        ("net_amount_rate", "DECIMAL(10,4)"),
        ("buy_elg_amount", "DECIMAL(24,4)"),
        ("buy_elg_amount_rate", "DECIMAL(10,4)"),
        ("buy_lg_amount", "DECIMAL(24,4)"),
        ("buy_lg_amount_rate", "DECIMAL(10,4)"),
        ("buy_md_amount", "DECIMAL(24,4)"),
        ("buy_md_amount_rate", "DECIMAL(10,4)"),
        ("buy_sm_amount", "DECIMAL(24,4)"),
        ("buy_sm_amount_rate", "DECIMAL(10,4)"),
        ("buy_sm_amount_stock", "VARCHAR"),
        ("rank", "INTEGER"),
    ]
    with moneyflow_candidate_connection(raw.parent) as c:
        for path, date_type in ((raw, "VARCHAR"), (result, "DATE")):
            actual = c.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
            assert [(r[0], r[1]) for r in actual] == [
                ("trade_date", date_type),
                *expected[1:],
            ]


@pytest.mark.parametrize("target", ["raw.parquet", "verification.parquet"])
def test_tampered_source_proof_rejected(tmp_path, target):
    raw, _, _ = build(tmp_path)
    (raw.parent / target).write_bytes(b"tampered")
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        silver(raw)


def test_receipt_scope_counts_and_elapsed_must_match(tmp_path):
    raw, _, _ = build(tmp_path)
    path = raw.parent / "receipt.json"
    receipt = json.loads(path.read_text())
    path.write_text(json.dumps({**receipt, "scope_row_counts": {"行业": 3}}))
    with pytest.raises(MoneyflowContractError, match="raw_source_scope_count"):
        silver(raw)
    path.write_text(json.dumps({**receipt, "elapsed_ms": 300000}))
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        silver(raw)
    assert not (raw.parent / "silver.parquet").exists()


def test_numeric_rejection_reports_nullable_code_business_key(tmp_path):
    with pytest.raises(
        MoneyflowContractError, match="source_numeric_contract"
    ) as error:
        build_pages(tmp_path, [[{**row(name="问题板块"), "net_amount": "1.23456"}]])
    assert all(
        text in str(error.value)
        for text in ["行业", "问题板块", "net_amount", "1.23456"]
    )


def test_formal_and_cross_dataset_paths_and_no_overwrite(tmp_path):
    formal = (
        Path("/Volumes/datasource/data_lake/moneyflow/test/moneyflow_ind_dc")
        / DAY
        / "raw.parquet"
    )
    with pytest.raises(MoneyflowContractError, match="formal_lake_is_not_staging"):
        silver(formal)
    raw, _, _ = build(tmp_path)
    with pytest.raises(MoneyflowContractError, match="raw_candidate_path"):
        build_daily_moneyflow_silver_candidate(raw, DAY, dataset="moneyflow_ind_ths")
    with pytest.raises(MoneyflowContractError, match="operation_conflict"):
        build(tmp_path)
    silver(raw)
    with pytest.raises(
        MoneyflowContractError, match="raw_source_proof|operation_conflict"
    ):
        silver(raw)


def test_memory_refusal_happens_before_source(monkeypatch, tmp_path):
    import orchestrator.defs.run_contracts.moneyflow as contract

    monkeypatch.setattr(
        contract.resource, "getrusage", lambda _: SimpleNamespace(ru_maxrss=10**12)
    )
    source, clock = Source([[row()]]), Clock()
    with pytest.raises(MoneyflowContractError, match="memory_budget_exceeded"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            dataset=DATASET,
            staging_root=tmp_path,
            operation_id="test",
            trade_date=DAY,
            clock=clock,
            sleep_fn=clock.sleep,
        )
    assert source.calls == []


def test_wrong_columns_and_oversize_page_are_not_empty_success(tmp_path):
    for directory, page in [
        ("columns", SimpleNamespace(columns=(), rows=[])),
        ("oversize", [row(name=f"板块{i}") for i in range(2001)]),
    ]:
        with pytest.raises(MoneyflowContractError, match="page_request_failed"):
            build_pages(tmp_path / directory, [page])


def test_all_business_numeric_nulls_are_preserved(tmp_path):
    numeric = [
        f
        for f in FIELDS
        if f
        not in ("trade_date", "content_type", "ts_code", "name", "buy_sm_amount_stock")
    ]
    rows = [{**r, **{f: None for f in numeric}} for r in sample()]
    raw, _, _ = build(tmp_path, rows)
    result = silver(raw)
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            c.execute(
                "SELECT close,net_amount,buy_elg_amount,rank FROM read_parquet(?)",
                [str(result)],
            ).fetchall()
            == [(None, None, None, None)] * 3
        )


def test_exact_20000_rows_with_28_candidate_files(tmp_path):
    if fresh_large_fixture("test_exact_20000_rows_with_28_candidate_files"):
        return
    rows = [row("行业", f"行业{i}") for i in range(19998)] + sample()[1:]
    raw, source, _ = build(tmp_path, rows)
    result = silver(raw)
    assert len(source.calls) == 24
    assert len([p for p in raw.parent.rglob("*") if p.is_file()]) == 28
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, result, DAY, dataset=DATASET)
            == 20000
        )


def test_physical_unknown_category_rejected_even_with_three_distinct_types(tmp_path):
    raw, _, _ = build(tmp_path)
    bad = raw.parent / "unknown.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            "COPY (SELECT * REPLACE(CASE WHEN content_type='地域' THEN '未知' ELSE content_type END AS content_type) FROM read_parquet($source)) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(bad)},
        )
        with pytest.raises(MoneyflowContractError, match="file_scope_coverage"):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)
