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


@pytest.fixture
def update_fixture(period_fixture):
    """Actual Raw receipts/events, actual Silver baseline; only HTTP is replaced.

    Source fields/values come from the independently documented literals above.
    Raw remains at files_ready: subsequent scoped captures are genuine permitted
    bootstrap children. This does not claim Raw daily handoff is being tested.
    """
    import dagster as dg

    from orchestrator.defs import stock_period_silver as silver
    from orchestrator.defs.bootstrap import stock_period_history as raw
    from orchestrator.defs.bootstrap import stock_period_history_cli as raw_cli
    from orchestrator.defs.bootstrap import stock_period_silver_cli as silver_cli
    from orchestrator.defs.io.stock_period_silver import read_json
    from orchestrator.defs.run_contracts.stock_period import (
        VERSION,
        completion_reference,
    )
    from orchestrator.defs.stock_period_update import (
        report_completion_events,
        report_file_events,
    )
    from tests.test_stock_period_history import POLICY

    f = period_fixture
    state = {"rows": [list(row) for rows in f["data"].values() for row in rows]}
    count = [0]
    source_calls = []

    def source(params):
        source_calls.append(dict(params))
        rows = [r for r in state["rows"] if r[3] == params["freq"]]
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

    with dg.DagsterInstance.ephemeral() as instance:

        def capture(
            *,
            mode="history",
            freq="week",
            codes=(A,),
            periods=None,
            asof="2026-10-16",
            frequencies=None,
        ):
            count[0] += 1
            intent = {
                "version": VERSION,
                "mode": mode,
                "frequencies": frequencies
                or (["week", "month"] if mode == "bootstrap" else [freq]),
                "codes": [A, B, C] if mode == "bootstrap" else list(codes),
                "request_id": f"silver-receipt-{count[0]}",
                "asof": asof,
            }
            if mode != "bootstrap":
                intent["bootstrap_parent"] = f["raw_base_id"]
            if periods is not None:
                intent["periods"] = {freq: periods}

            def operation(context):
                return raw.run_period(
                    root=f["lake"],
                    staging=f["staging"],
                    listed={A, B, C},
                    aliases={"832000.BJ": B},
                    intent=intent,
                    transport=source,
                    policy=POLICY,
                    events=lambda item, completion=None: report_file_events(
                        instance, item, completion=completion, context=context
                    ),
                    completion_events=lambda notice: report_completion_events(
                        instance, notice
                    ),
                )

            result = raw_cli._run_reporting(instance, operation)
            saved = read_json(Path(result["path"]) / "manifest.json")
            return completion_reference(
                result["run_id"], saved["file_receipt_hash"], freq
            )

        reference = capture(mode="bootstrap")
        f["raw_base_id"] = reference["raw_execution_id"]
        silver.build(
            f["lake"],
            f["staging"],
            f["run_id"],
            audit_report=f["report"],
            emit=lambda _: None,
        )
        silver_cli.run_reporting(
            instance,
            lambda context: silver_cli.replay_events(
                f["lake"], f["staging"], f["run_id"], instance, context
            ),
        )
        yield {
            **f,
            "instance": instance,
            "capture": capture,
            "state": state,
            "source_calls": source_calls,
            "base_reference": reference,
        }


def test_update_config_is_explicit_and_business_identity_has_no_event_ids():
    from orchestrator.defs.run_contracts.stock_period import (
        completion_reference,
        validate_completion_reference,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import (
        StockPeriodSilverConfig,
        update_run_id,
    )

    reference = completion_reference("a" * 64, "b" * 64, "week")
    assert set(reference) == {
        "raw_execution_id",
        "file_receipt_hash",
        "upstream_batch_id",
    }
    assert update_run_id("week", reference) == update_run_id("week", dict(reference))
    assert validate_completion_reference(reference, "week") == reference
    StockPeriodSilverConfig(
        execution_id=str(uuid4()), audit_report="audit"
    ).validate_intent("week")
    StockPeriodSilverConfig(
        execution_id=str(uuid4()), intent="update", source_completion=reference
    ).validate_intent("week")
    self_id = str(uuid4())
    for recovery in (
        {
            "execution_id": self_id,
            "audit_report": "audit",
            "resume_from_execution_id": str(uuid4()),
        },
        {
            "execution_id": self_id,
            "intent": "update",
            "source_completion": reference,
            "resume_from_execution_id": self_id,
        },
        {
            "execution_id": self_id,
            "intent": "update",
            "source_completion": reference,
            "resume_from_execution_id": "../latest",
        },
    ):
        with pytest.raises(ValueError):
            StockPeriodSilverConfig(**recovery).validate_intent("week")
    for extra in ("storage_id", "path"):
        with pytest.raises(ValueError, match="reference_invalid"):
            validate_completion_reference({**reference, extra: "untrusted"}, "week")
    for kwargs in (
        {},
        {"intent": "update"},
        {"intent": "update", "source_completion": reference, "audit_report": "audit"},
    ):
        with pytest.raises(ValueError):
            StockPeriodSilverConfig(
                execution_id=str(uuid4()), **kwargs
            ).validate_intent("week")


def publish_completion_contract(f, reference, freq):
    """Assert the actual Raw producer's shared contract; do not manufacture events."""
    import dagster as dg

    from orchestrator.defs.io.stock_period_raw import read_json
    from orchestrator.defs.run_contracts.stock_period import (
        COMPLETION_METADATA_KEY,
        completion_notice,
    )

    complete = read_json(
        f["staging"]
        / "stock_period/runs"
        / reference["raw_execution_id"]
        / "complete.json"
    )
    items = [i for i in complete["files"] if i["freq"] == freq]
    for item in items:
        record = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"),
                    asset_partitions=[item["period"]],
                ),
                limit=1,
            )
            .records[0]
        )
        assert record.asset_materialization.metadata[
            COMPLETION_METADATA_KEY
        ].value == completion_notice(reference, freq, len(items))
