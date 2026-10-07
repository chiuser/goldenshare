"""Independent DC stock units, identity, pagination and bounded candidate acceptance."""

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
DATASET = "moneyflow_dc"
# Independent approved Prod projection; do not derive expected fields from the implementation.
FIELDS = (
    "trade_date",
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
)
NUMERICS = FIELDS[3:]
AMOUNTS = (
    "net_amount",
    "buy_elg_amount",
    "buy_lg_amount",
    "buy_md_amount",
    "buy_sm_amount",
)
RATES = (
    "pct_change",
    "net_amount_rate",
    "buy_elg_amount_rate",
    "buy_lg_amount_rate",
    "buy_md_amount_rate",
    "buy_sm_amount_rate",
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


def row(code="000001.SZ", name="样本"):
    return {
        "trade_date": "20260930",
        "ts_code": code,
        "name": name,
        **{f: "5.1234" for f in NUMERICS},
        "net_amount": "-91.4321",
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


def fixture_rows():
    return json.loads(
        (Path(__file__).parent / "fixtures/moneyflow_dc_20260930.json").read_text()
    )


def numeric_type(field):
    return (
        "DECIMAL(24,4)"
        if field in AMOUNTS
        else "DECIMAL(18,4)"
        if field == "close"
        else "DECIMAL(10,4)"
    )


def test_independent_schema_stock_keys_nullable_name_and_wan_units(tmp_path):
    rows = [row("920202.BJ", None), row("退市样本.SZ"), row("600000.SH")]
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
                    date_type
                    if f == "trade_date"
                    else "VARCHAR"
                    if f in ("ts_code", "name")
                    else numeric_type(f),
                )
                for f in FIELDS
            ]
        assert (
            audit_daily_moneyflow_standardization(c, raw, target, DAY, dataset=DATASET)
            == 3
        )
        assert (
            c.execute(
                "SELECT net_amount,buy_elg_amount,buy_lg_amount FROM read_parquet(?)",
                [str(target)],
            ).fetchall()
            == [(Decimal("-91.4321"), Decimal("5.1234"), Decimal("5.1234"))] * 3
        )
        assert c.execute(
            "SELECT name FROM read_parquet(?) WHERE ts_code='920202.BJ'", [str(target)]
        ).fetchone() == (None,)
    assert clock.now >= 60
    assert (
        source.calls
        == [(DATASET, {"trade_date": "20260930", "limit": 2000, "offset": 0}, FIELDS)]
        * 2
    )


def test_real_public_6024_rows_full_field_readback(tmp_path):
    if fresh_process("test_real_public_6024_rows_full_field_readback"):
        return
    rows = fixture_rows()
    assert len(rows) == 6024
    raw, source, _ = build(tmp_path, rows)
    target = silver(raw)
    assert [r[1]["offset"] for r in source.calls] == [0, 2000, 4000, 6000] * 2
    assert all(
        r[0] == DATASET
        and r[2] == FIELDS
        and set(r[1]) == {"trade_date", "limit", "offset"}
        for r in source.calls
    )
    with moneyflow_candidate_connection(raw.parent) as c:
        assert (
            audit_daily_moneyflow_standardization(c, raw, target, DAY, dataset=DATASET)
            == 6024
        )
        assert dict(
            c.execute(
                "SELECT split_part(ts_code,'.',2),count(*) FROM read_parquet(?) GROUP BY 1",
                [str(target)],
            ).fetchall()
        ) == {"SZ": 3154, "SH": 2522, "BJ": 348}
        assert c.execute(
            "SELECT name,net_amount,buy_elg_amount,buy_lg_amount FROM read_parquet(?) WHERE ts_code='000001.SZ'",
            [str(target)],
        ).fetchone() == (
            "平安银行",
            Decimal("12506.12"),
            Decimal("-2657.3"),
            Decimal("15163.42"),
        )
        source_json = Path(__file__).parent / "fixtures/moneyflow_dc_20260930.json"
        projection = ",".join(
            f"{f}::{'VARCHAR' if f in FIELDS[:3] else numeric_type(f)} AS {f}"
            for f in FIELDS
        )
        assert (
            c.execute(
                f"SELECT count(*) FROM ((SELECT {projection} FROM read_json_auto($source) EXCEPT SELECT * FROM read_parquet($raw)) UNION ALL "
                f"(SELECT * FROM read_parquet($raw) EXCEPT SELECT {projection} FROM read_json_auto($source)))",
                {"source": str(source_json), "raw": str(raw)},
            ).fetchone()[0]
            == 0
        )
    receipt = json.loads((raw.parent / "receipt.json").read_text())
    assert receipt["row_count"] == receipt["scope_row_counts"]["all"] == 6024
    assert receipt["request_count"] == 8 and receipt["retry_count"] == 0


def test_zero_flows_and_all_nulls_are_source_facts(tmp_path):
    raw, _, _ = build(
        tmp_path,
        [
            {**row("000001.SZ", None), **{f: None for f in NUMERICS}},
            {**row("000002.SZ"), **{f: 0 for f in NUMERICS}},
        ],
    )
    with moneyflow_candidate_connection(raw.parent) as c:
        assert c.execute(
            "SELECT * EXCLUDE(trade_date,ts_code,name) FROM read_parquet(?) ORDER BY ts_code",
            [str(silver(raw))],
        ).fetchall() == [(None,) * 12, (Decimal(0),) * 12]


@pytest.mark.parametrize("field", NUMERICS)
@pytest.mark.parametrize("sign", ["", "-"])
def test_exact_numeric_bounds_all_fields(tmp_path, field, sign):
    digits = 20 if field in AMOUNTS else 14 if field == "close" else 6
    value = sign + "9" * digits + ".9999"
    raw, _, _ = build(tmp_path, [{**row(), field: value}])
    with moneyflow_candidate_connection(raw.parent) as c:
        assert c.execute(
            f"SELECT {field} FROM read_parquet(?)", [str(silver(raw))]
        ).fetchone()[0] == Decimal(value)


@pytest.mark.parametrize("field", NUMERICS)
@pytest.mark.parametrize("invalid", ["scale", "overflow", "bool", "nonfinite"])
def test_precision_range_and_types_reject_all_fields(tmp_path, field, invalid):
    digits = 20 if field in AMOUNTS else 14 if field == "close" else 6
    value = {
        "scale": "0.00001",
        "overflow": "1" + "0" * digits,
        "bool": True,
        "nonfinite": "Infinity",
    }[invalid]
    with pytest.raises(
        MoneyflowContractError, match="source_numeric_contract"
    ) as error:
        build(tmp_path, [{**row(), field: value}])
    assert field in str(error.value) and "000001.SZ" in str(error.value)
    assert not list(tmp_path.rglob("raw.parquet"))


@pytest.mark.parametrize(
    "key,value",
    [
        ("trade_date", "20260929"),
        ("trade_date", 20260930),
        ("ts_code", None),
        ("ts_code", " "),
        ("ts_code", 1),
        ("name", True),
        ("name", 1),
        ("net_amount", "NaN"),
        ("net_amount", float(2**53)),
        ("net_amount", "1e-999999999999"),
    ],
)
def test_invalid_identity_name_and_unsafe_numeric(tmp_path, key, value):
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, [{**row(), key: value}])


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row(), row(name="换名称")],
        [{**row(), "content_type": "行业"}],
        [{k: v for k, v in row().items() if k != "name"}],
    ],
)
def test_empty_duplicate_key_and_foreign_schema_unready(tmp_path, rows):
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, rows)
    assert (
        json.loads(next(tmp_path.rglob("receipt.json")).read_text())["stage"]
        == "collecting"
    )


@pytest.mark.parametrize(
    "second",
    [
        [{**row(), "net_amount": "99"}],
        [row(name="源名称修订")],
        [row("600000.SH")],
        [row(), row("600000.SH")],
    ],
)
def test_any_numeric_name_key_or_count_revision_blocks(tmp_path, second):
    with pytest.raises(MoneyflowContractError, match="source_unstable"):
        build(tmp_path, second=second)
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        silver(next(tmp_path.rglob("raw.parquet")))


def test_cross_page_duplicate_and_exact_page_termination(tmp_path):
    rows = [row(f"{i:06d}.SZ") for i in range(2000)]
    with pytest.raises(MoneyflowContractError, match="source_duplicate_key"):
        build(tmp_path / "bad", pages=[rows, [rows[0]]])
    raw, source, _ = build(tmp_path / "good", rows)
    assert [r[1]["offset"] for r in source.calls] == [0, 2000] * 2
    assert len(list(raw.parent.rglob("page-*.json"))) == 2


def test_exact_20000_rows_and_total_budget_rejection(tmp_path):
    if fresh_process("test_exact_20000_rows_and_total_budget_rejection"):
        return
    observed = fixture_rows()
    rows = [
        {**observed[i % len(observed)], "ts_code": f"{i:06d}.SZ"} for i in range(20000)
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


def test_oversized_page_and_missing_columns_rejected(tmp_path):
    for i, page in enumerate(([row()] * 2001, SimpleNamespace(columns=(), rows=[]))):
        with pytest.raises(MoneyflowContractError, match="page_request_failed"):
            build(tmp_path / str(i), pages=[page])


def test_retry_and_shared_request_budget(monkeypatch, tmp_path):
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
def test_cancel_after_page_or_during_wait(tmp_path, during_wait):
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
        {"dataset": "moneyflow_ind_dc"},
        {"source": "prod"},
        {"row_count": 2},
        {"scope_row_counts": {"all": 2}},
        {"elapsed_ms": 300000},
    ],
)
def test_silver_proof_and_cumulative_budget_revalidated(tmp_path, change):
    raw, _, _ = build(tmp_path)
    p = raw.parent / "receipt.json"
    p.write_text(json.dumps({**json.loads(p.read_text()), **change}))
    with pytest.raises(MoneyflowContractError):
        silver(raw)


def test_conflicts_and_hash_tamper(tmp_path):
    raw, _, _ = build(tmp_path)
    with pytest.raises(MoneyflowContractError, match="operation_conflict"):
        build(tmp_path)
    silver(raw)
    with pytest.raises(
        MoneyflowContractError, match="operation_conflict|raw_source_proof"
    ):
        silver(raw)
    (raw.parent / "verification.parquet").write_bytes(b"tampered")
    with pytest.raises(MoneyflowContractError, match="raw_source_proof"):
        silver(raw)


@pytest.mark.parametrize(
    "projection",
    [
        "* REPLACE('20260929' AS trade_date)",
        "* EXCLUDE(name)",
        "* REPLACE(1::INTEGER AS net_amount)",
        "* REPLACE('' AS ts_code)",
    ],
)
def test_physical_schema_date_and_key_fail(tmp_path, projection):
    raw, _, _ = build(tmp_path)
    bad = raw.parent / "bad.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            f"COPY (SELECT {projection} FROM read_parquet($raw)) TO $bad (FORMAT PARQUET)",
            {"raw": str(raw), "bad": str(bad)},
        )
        with pytest.raises(MoneyflowContractError):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)


def test_physical_duplicate_and_business_difference(tmp_path):
    raw, _, _ = build(tmp_path)
    bad, changed = raw.parent / "bad.parquet", raw.parent / "changed.parquet"
    with moneyflow_candidate_connection(raw.parent) as c:
        c.execute(
            "COPY (SELECT * FROM read_parquet($raw) UNION ALL SELECT * FROM read_parquet($raw)) TO $bad (FORMAT PARQUET)",
            {"raw": str(raw), "bad": str(bad)},
        )
        with pytest.raises(MoneyflowContractError, match="file_count_date_or_key"):
            audit_daily_moneyflow_file(c, bad, DAY, dataset=DATASET)
        c.execute(
            "COPY (SELECT * REPLACE('改名称' AS name) FROM read_parquet($raw)) TO $bad (FORMAT PARQUET)",
            {"raw": str(raw), "bad": str(changed)},
        )
        with pytest.raises(MoneyflowContractError, match="source_unstable"):
            audit_daily_moneyflow_equality(c, raw, changed, dataset=DATASET)


def test_memory_limit_before_source_call(monkeypatch, tmp_path):
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


def test_paths_unknown_dataset_and_cross_dataset_files_fail(tmp_path):
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
    raw, _, _ = build(tmp_path)
    with moneyflow_candidate_connection(raw.parent) as c, pytest.raises(
        MoneyflowContractError, match="file_schema"
    ):
        audit_daily_moneyflow_file(c, raw, DAY, dataset="moneyflow_ind_dc")
    source = Source([])
    with pytest.raises(MoneyflowContractError, match="daily_dataset"):
        build_daily_moneyflow_raw_candidate(
            tushare=source,
            dataset="moneyflow_ths",
            staging_root=tmp_path,
            operation_id="unknown",
            trade_date=DAY,
        )
    assert source.calls == [] and not (tmp_path / "moneyflow/unknown").exists()
