"""Literal fixtures follow Raw SPECS and the actual lifecycle/identity producers.

Contract evidence: run_contracts/stock_weekly.weekly_column_specs and the passed
20261017_135833 audit/probe. Expected business rows below are independent literals,
including the 20200228/29 source example, not produced by the selector under test.
Only files and an isolated Dagster instance are used; no network/formal resources.
"""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import (
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.run_contracts.stock_period_silver import (
    canonical_run_id,
    raw_path,
)

NAMES = (
    "ts_code",
    "trade_date",
    "end_date",
    "freq",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "open_hfq",
    "high_hfq",
    "low_hfq",
    "close_hfq",
    "vol",
    "amount",
    "change",
    "pct_chg",
)
TYPES = (
    ("VARCHAR",) * 4
    + ("DECIMAL(18,4)",) * 13
    + ("DECIMAL(20,4)",) * 2
    + ("DECIMAL(18,4)", "DECIMAL(10,4)")
)
A, B, C, D = "000001.SZ", "920000.BJ", "301569.SZ", "000002.SZ"


def literal_row(code, label, freq, *, asof="20261016", qfq="11.14"):
    return [
        code,
        label,
        asof,
        freq,
        "14.40",
        "14.70",
        "14.30",
        "14.50",
        None,
        "11.10",
        "11.30",
        "11.00",
        qfq,
        "114.40",
        "114.70",
        "114.30",
        "114.50",
        "12345.6700",
        "87654.3200",
        "0.1000",
        None,
    ]


def write_raw(con, path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fixture_raw ("
        + ",".join(f'"{n}" {t}' for n, t in zip(NAMES, TYPES, strict=True))
        + ")"
    )
    # Tiny literal test data only. Production path uses columnar SQL/COPY.
    for row in rows:
        con.execute(
            "INSERT INTO fixture_raw VALUES (" + ",".join("?" for _ in NAMES) + ")", row
        )
    con.execute("COPY fixture_raw TO ? (FORMAT PARQUET)", [str(path)])


@pytest.fixture
def period_fixture(tmp_path):
    lake, staging, report = (tmp_path / n for n in ("lake", "staging", "audit"))
    for path in (lake, staging, report):
        path.mkdir()
    references = {
        "lifecycle": str(silver_stock_lifecycle_path(lake)),
        "identity": str(silver_stock_identity_map_path(lake)),
    }
    data = {
        ("week", "2014-01-03"): [
            literal_row(A, "20140103", "week"),
            literal_row(B, "20140103", "week"),
            literal_row(D, "20140103", "week"),
        ],
        ("week", "2020-04-03"): [
            literal_row(A, "20200403", "week"),
            literal_row(B, "20200403", "week"),
            literal_row(C, "20200403", "week"),
        ],
        ("week", "2026-10-16"): [literal_row(k, "20261016", "week") for k in (A, B, C)],
        ("month", "2020-02"): [
            literal_row(A, "20200228", "month", asof="20250910", qfq="12.01"),
            literal_row(A, "20200229", "month", asof="20261015"),
        ],
        ("month", "2020-04"): [
            literal_row(A, "20200430", "month"),
            literal_row(B, "20200430", "month"),
        ],
        ("month", "2026-10"): [literal_row(k, "20261031", "month") for k in (A, B, C)],
    }
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=tmp_path / "fixture_spill")
    ) as con:
        for path in references.values():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            """COPY (SELECT * FROM (VALUES
            ('000001.SZ','L',DATE '1991-04-03',NULL::DATE,TRUE),
            ('920000.BJ','L',DATE '2020-04-03',NULL::DATE,TRUE),
            ('301569.SZ','L',DATE '2026-10-14',NULL::DATE,TRUE),
            ('000002.SZ','D',DATE '1991-01-01',DATE '2025-01-01',TRUE)
            ) t(ts_code,list_status,list_date,delist_date,is_cny_stock)) TO ? (FORMAT PARQUET)""",
            [references["lifecycle"]],
        )
        con.execute(
            """COPY (SELECT * FROM (VALUES
            ('000001.SZ','000001.SZ','confirmed'),('920000.BJ','920000.BJ','confirmed'),
            ('832000.BJ','920000.BJ','confirmed'),('301569.SZ','301569.SZ','confirmed'),
            ('000002.SZ','000002.SZ','confirmed')) t(source_ts_code,latest_ts_code,confidence)) TO ? (FORMAT PARQUET)""",
            [references["identity"]],
        )
        for (freq, period), rows in data.items():
            write_raw(con, raw_path(lake, freq, period), rows)
    files = {
        freq: [str(raw_path(lake, f, p)) for f, p in data if f == freq]
        for freq in ("week", "month")
    }
    summary = {
        "status": "passed",
        "asof": "2026-10-16",
        "lower": "2014-01-01",
        "references": references,
        "input_file_counts": {"week": 3, "month": 3},
        "frequencies": {
            f: {"status": "passed", "selected": {"stock_periods": 6}}
            for f in ("week", "month")
        },
    }
    (report / "summary.json").write_text(json.dumps(summary))
    (report / "inputs.json").write_text(
        json.dumps({"references": references, "raw_files": files})
    )
    return {
        "lake": lake,
        "staging": staging,
        "report": report,
        "run_id": str(uuid4()),
        "references": references,
        "data": data,
    }


def test_contract_and_names_are_exact():
    from orchestrator.defs.catalog.name_mapping import get_dataset_chinese_name
    from orchestrator.defs.run_contracts.asset_column_schemas import (
        RAW_STK_PERIOD_BAR_ADJ_MONTH_SCHEMA,
        RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
        SILVER_STOCK_MONTHLY_SCHEMA,
        SILVER_STOCK_WEEKLY_SCHEMA,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import SPECS

    assert SPECS == tuple(zip(NAMES, TYPES, strict=True))
    assert SILVER_STOCK_WEEKLY_SCHEMA is RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA
    assert SILVER_STOCK_MONTHLY_SCHEMA is RAW_STK_PERIOD_BAR_ADJ_MONTH_SCHEMA
    assert get_dataset_chinese_name("stock_weekly") == "股票周线"
    assert get_dataset_chinese_name("stock_monthly") == "股票月线"
    with pytest.raises(KeyError):
        get_dataset_chinese_name("not_a_dataset")


@pytest.mark.parametrize("value", ["../escape", uuid4().hex, "LATEST"])
def test_execution_id_rejects_implicit_or_noncanonical_identity(value):
    with pytest.raises(ValueError):
        canonical_run_id(value)


def test_cli_default_does_nothing(monkeypatch, capsys):
    from orchestrator.defs.bootstrap import stock_period_silver_cli as cli

    monkeypatch.setattr(cli, "build", lambda *a, **k: pytest.fail("unexpected build"))
    monkeypatch.setattr(
        cli.dg.DagsterInstance, "get", lambda: pytest.fail("unexpected instance")
    )
    assert cli.main([]) == 0
    assert "build,resume,events" in capsys.readouterr().out




def test_update_config_is_explicit_and_business_identity_has_no_event_ids():
    from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        delivery_ref,
        validate_delivery_ref,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import (
        StockPeriodSilverConfig,
    )

    reference = delivery_ref(str(uuid4()), "week", "daily", "2026-11-10", ["2026-11-13"])
    assert set(reference) == {"producer_run_id", "freq", "upstream_batch_id"}
    assert validate_delivery_ref(reference, "week") == reference
    StockPeriodSilverConfig(execution_id=str(uuid4()), audit_report="audit").validate_intent("week")
    StockPeriodSilverConfig(intent="update", source_completion=reference).validate_intent("week")
    for invalid in (
        {"intent":"update", "execution_id":str(uuid4()), "source_completion":reference},
        {"intent":"update", "source_completion":reference, "resume_from_execution_id":str(uuid4())},
        {"intent":"update", "source_completion":reference, "audit_report":"audit"},
        {"intent":"update"}, {},
    ):
        with pytest.raises(ValueError):
            StockPeriodSilverConfig(**invalid).validate_intent("week")
    for extra in ("storage_id", "path", "raw_execution_id", "file_receipt_hash"):
        with pytest.raises(ValueError, match="reference_invalid"):
            validate_delivery_ref({**reference, extra:"untrusted"}, "week")
    for invalid in ({}, {"automatic_intent_date":None}, {"automatic_intent_date":"2026-11-10", "intent":"history"}):
        with pytest.raises(ValueError):
            StockPeriodRawConfig(**invalid)
