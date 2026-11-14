"""Expansion goldens: source doc32, Prod migration188 and LLD sections7/30.

Fake pages isolate business/file rules here; the HTTP suite tests actual parsing.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import pandas as pd
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    load_daily_basic_input_codes,
)
from orchestrator.defs.bootstrap import daily_basic_events as events
from orchestrator.defs.bootstrap import daily_basic_history as history
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_ASSET,
    DAILY_BASIC_CHECKS,
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_SOURCE_CONTRACT,
    DAILY_BASIC_TYPES,
    DailyBasicValidationError,
    daily_basic_is_b_share,
)
from orchestrator.defs.daily_basic_raw_io import (
    audit_daily_basic_coverage,
    audit_daily_basic_file,
    file_sha256,
)
from orchestrator.defs.paths import raw_daily_basic_path, raw_stock_daily_path
from orchestrator.tushare_download.contract_registry import validate_contract
from orchestrator.tushare_download.source_contract import SourceKind
from tests.test_daily_basic_history import (
    DAYS,
    Source,
    rows,
    source_evidence,
)
from tests.test_daily_basic_history import (
    plan as history_plan,
)
from tests.test_daily_basic_raw_io import DAY, DB, row, write

pytestmark = pytest.mark.usefixtures("isolated_daily_basic_transport")
plan = history_plan


@pytest.mark.parametrize("code", ["200011.SZ", "201872.SZ", "900901.SH"])
def test_source_b_share_is_excluded_before_value_conversion(tmp_path, code):
    evidence = write(
        tmp_path,
        [
            row(limit_status=0),
            row("000737.SZ", limit_status=None),
            row(code, close="deliberately invalid", limit_status=Decimal("1.0")),
        ],
    )
    assert {
        k: evidence[k]
        for k in (
            "source_row_count",
            "fetched_row_count",
            "excluded_b_share_row_count",
            "retained_b_share_row_count",
            "null_limit_status_count",
        )
    } == {
        "source_row_count": 2,
        "fetched_row_count": 3,
        "excluded_b_share_row_count": 1,
        "retained_b_share_row_count": 0,
        "null_limit_status_count": 1,
    }
    path = raw_daily_basic_path(tmp_path / "lake", DAY)
    with DB().connect() as connection:
        assert connection.execute(
            "SELECT ts_code,limit_status FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(path)],
        ).fetchall() == [("000001.SZ", 0), ("000737.SZ", None)]
        audit = audit_daily_basic_file(connection, path, DAY)
    assert not audit_daily_basic_coverage(path, audit, ["000001.SZ"], evidence)
    assert "null_required_limit_status" in audit_daily_basic_coverage(
        path, audit, ["000001.SZ", "000737.SZ"], evidence
    )


@pytest.mark.parametrize(
    "code", ["000001.SZ", "920964.BJ", "200011.SH", "900901.SZ", "20011.SZ"]
)
def test_b_share_predicate_does_not_expand_scope(code):
    assert not daily_basic_is_b_share(code)


@pytest.mark.parametrize("value", [0, 1, 2, 3, 4, 5, 6])
def test_all_integer_status_values_remain_integers(tmp_path, value):
    write(tmp_path, [row(limit_status=value)])
    with DB().connect() as connection:
        result = connection.execute(
            "SELECT limit_status, typeof(limit_status) FROM read_parquet(?,hive_partitioning=false)",
            [str(raw_daily_basic_path(tmp_path / "lake", DAY))],
        ).fetchone()
    assert result == (value, "INTEGER")
    assert type(result[0]) is int


@pytest.mark.parametrize("value", [None, True, False, "1", 1.0, Decimal("1.0"), -1, 7])
def test_required_status_invalid_preserves_existing_date(tmp_path, value):
    write(tmp_path)
    path = raw_daily_basic_path(tmp_path / "lake", DAY)
    original = file_sha256(path)
    with pytest.raises(
        DailyBasicValidationError,
        match="代码=000001.SZ.*名称=缺失.*limit_status.*类型=",
    ):
        write(tmp_path, [row(limit_status=value)], write_mode="replace")
    assert file_sha256(path) == original


def _seed_file(path, values, *, include_status):
    """18-column producer projection: DECIMALs plus VARCHAR keys, never inferred floats."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = DAILY_BASIC_FIELDS if include_status else DAILY_BASIC_FIELDS[:-1]
    frame = pd.DataFrame(values, columns=fields, dtype=object)
    if include_status:
        frame["limit_status"] = pd.array([r[-1] for r in values], dtype="Int64")
    with DB().connect() as connection:
        connection.register("fixture", frame)
        projection = ", ".join(
            f'CAST("{n}" AS {DAILY_BASIC_TYPES[n]}) AS "{n}"' for n in fields
        )
        connection.execute(
            f"COPY (SELECT {projection} FROM fixture) TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def test_daily_replace_keeps_all_existing_b_share_values(tmp_path):
    path = raw_daily_basic_path(tmp_path / "lake", DAY)
    a, b = row(), row("201872.SZ", close="9.0000", limit_status=None)
    _seed_file(
        path, [[r[n] for n in DAILY_BASIC_FIELDS] for r in (a, b)], include_status=True
    )
    with DB().connect() as connection:
        original_b = connection.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE ts_code='201872.SZ'",
            [str(path)],
        ).fetchone()
    with pytest.raises(DailyBasicValidationError, match="conflict"):
        write(
            tmp_path,
            [
                row(close="7"),
                row("000737.SZ", limit_status=None),
                row("201872.SZ", limit_status=4),
            ],
        )
    evidence = write(
        tmp_path,
        [
            row(close="7"),
            row("000737.SZ", limit_status=None),
            row("201872.SZ", limit_status=4),
        ],
        write_mode="replace",
    )
    assert (
        evidence["source_row_count"],
        evidence["fetched_row_count"],
        evidence["excluded_b_share_row_count"],
        evidence["retained_b_share_row_count"],
    ) == (3, 3, 1, 1)
    assert evidence["null_limit_status_count"] == 2
    with DB().connect() as connection:
        assert (
            connection.execute(
                "SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE ts_code='201872.SZ'",
                [str(path)],
            ).fetchone()
            == original_b
        )
        assert connection.execute(
            "SELECT close FROM read_parquet(?,hive_partitioning=false) WHERE ts_code='000001.SZ'",
            [str(path)],
        ).fetchone() == (Decimal("7.0000"),)
    assert (
        write(tmp_path, [row(close="7"), row("000737.SZ", limit_status=None)])[
            "result_status"
        ]
        == "reused"
    )


def test_daily_does_not_migrate_an_eighteen_column_file(tmp_path):
    path = raw_daily_basic_path(tmp_path / "lake", DAY)
    _seed_file(
        path, [[row()[n] for n in DAILY_BASIC_FIELDS[:-1]]], include_status=False
    )
    original = file_sha256(path)
    with pytest.raises(DailyBasicValidationError, match="existing_target_schema"):
        write(tmp_path, write_mode="replace")
    assert file_sha256(path) == original


def test_complete_source_contract_does_not_register_a_new_session_mode():
    from orchestrator.tushare_download.contracts import CONTRACTS
    from orchestrator.tushare_download.dataset_transport_mapping import BINDINGS

    validate_contract(DAILY_BASIC_SOURCE_CONTRACT)
    assert DAILY_BASIC_SOURCE_CONTRACT.field_names == DAILY_BASIC_FIELDS
    assert DAILY_BASIC_SOURCE_CONTRACT.fields[-1].source_kind == SourceKind.INTEGER
    assert DAILY_BASIC_SOURCE_CONTRACT.fields[-1].nullable
    assert (
        len(
            [
                f
                for f in DAILY_BASIC_SOURCE_CONTRACT.fields
                if f.source_kind == SourceKind.NUMBER
            ]
        )
        == 16
    )
    assert not any(c.dataset_id == "daily_basic" for c in CONTRACTS)
    assert [
        (b.kind, b.adapter_key) for b in BINDINGS if b.dataset_id == "daily_basic"
    ] == [(1, "http_pro")]


def test_expected_codes_are_read_from_daily_file_and_exclude_b_shares(tmp_path):
    path = raw_stock_daily_path(tmp_path, DAY)
    path.parent.mkdir(parents=True)
    # Approved producer key projection; this test does not claim the full daily-bar schema.
    with (
        DB().connect() as connection,
        patch(
            "orchestrator.defs.asset_guards.daily_basic_readiness.raw_tushare_stock_daily_ready_for_trade_date",
        ) as ready,
    ):
        ready.return_value.ready = True
        connection.execute(
            "COPY (SELECT unnest(['000001.SZ','201872.SZ','900901.SH']) ts_code, '20260914' trade_date) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
        assert load_daily_basic_input_codes(None, connection, tmp_path, DAY) == (
            "000001.SZ",
        )


@pytest.fixture
def replacement(plan):
    values = sorted([*rows(), *rows("201872.SZ"), *rows("920964.BJ")])
    values = [
        (*r[:-1], None if r[0] in ("201872.SZ", "920964.BJ") else 0) for r in values
    ]
    for day in DAYS:
        _seed_file(
            raw_daily_basic_path(Path(plan["lake_root"]), day),
            [r[:-1] for r in values if r[1] == day.replace("-", "")],
            include_status=False,
        )
    approved = history.make_history_plan(
        start=plan["start"],
        end=plan["end"],
        batch_id=plan["batch_id"],
        lake_root=plan["lake_root"],
        staging_root=plan["staging_root"],
        calendar_path=plan["calendar_path"],
        dates=plan["dates"],
        source_evidence=source_evidence(),
        cost_evidence={},
        limits=plan["limits"],
        replace_existing=True,
    )
    assert not approved["stop_reasons"]
    history.export_daily_basic_history(approved, Source(values), apply=True)
    history.build_daily_basic_history(approved, apply=True)
    with dg.DagsterInstance.ephemeral() as instance:
        yield approved, instance


def test_old_valid_report_is_rejected_before_source_read(plan):
    original = dict(plan)
    original.pop("source_fields")
    source = Source()
    with pytest.raises(DailyBasicValidationError, match="plan_fields_changed"):
        history.export_daily_basic_history(
            history.seal_history_report(original), source, apply=True
        )
    assert source.calls == 0


def test_history_replacement_preserves_old_columns_b_and_nulls(replacement):
    approved, instance = replacement
    audit = history.audit_daily_basic_history(approved, instance=instance)
    assert audit["rows"] == 6 and audit["null_limit_status_count"] == 4
    assert all(
        f["old_sha256"] and f["null_limit_status_count"] == 2 for f in audit["files"]
    )
    assert audit["replacement"]["check_dates"] == DAYS
    export = history.load_history_report(history._workspace(approved) / "export.json")
    assert export["null_limit_status_count"] == 4
    with patch.object(
        history,
        "audit_daily_basic_history",
        side_effect=AssertionError("must not repeat complete audit"),
    ):
        first = history.promote_daily_basic_history(
            approved, audit, sample_date=DAYS[0], apply=True
        )
        second = history.promote_daily_basic_history(
            approved, audit, sample_date=DAYS[1], apply=True
        )
        again = history.promote_daily_basic_history(approved, audit, apply=True)
    assert len(first["files"]) == 1 and len(second["files"]) == len(again["files"]) == 2
    for day in DAYS:
        path = raw_daily_basic_path(Path(approved["lake_root"]), day)
        with DB().connect() as connection:
            checked = audit_daily_basic_file(connection, path, day)
            assert not checked.failed_rules
            assert checked.null_limit_status_codes == ("201872.SZ", "920964.BJ")
            assert connection.execute(
                "SELECT ts_code,limit_status FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                [str(path)],
            ).fetchall() == [("000001.SZ", 0), ("201872.SZ", None), ("920964.BJ", None)]


@pytest.mark.parametrize("failure", ["after_first_file", "checkpoint_save"])
def test_history_resume_uses_committed_file_and_original_progress(replacement, failure):
    approved, instance = replacement
    audit = history.audit_daily_basic_history(approved, instance=instance)
    if failure == "after_first_file":
        actual_copy = history.shutil.copyfile
        calls = []

        def copy(source, target):
            calls.append(source)
            if len(calls) == 2:
                raise OSError("interrupted after first date")
            return actual_copy(source, target)

        seam = patch.object(history.shutil, "copyfile", side_effect=copy)
    else:
        seam = patch.object(
            history,
            "save_history_report",
            side_effect=OSError("state write unavailable"),
        )
    with seam, pytest.raises(OSError):
        history.promote_daily_basic_history(approved, audit, apply=True)
    assert (
        file_sha256(raw_daily_basic_path(Path(approved["lake_root"]), DAYS[0]))
        == audit["files"][0]["sha256"]
    )
    with patch.object(
        history.shutil, "copyfile", wraps=history.shutil.copyfile
    ) as copies:
        done = history.promote_daily_basic_history(approved, audit, apply=True)
    assert len(done["files"]) == 2 and copies.call_count == 1
    assert (
        len(history.promote_daily_basic_history(approved, audit, apply=True)["files"])
        == 2
    )


def test_original_column_change_and_changed_candidate_stop_replacement(replacement):
    approved, instance = replacement
    path = raw_daily_basic_path(Path(approved["lake_root"]), DAYS[0])
    with DB().connect() as connection:
        values = connection.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false)", [str(path)]
        ).fetchall()
    changed = [list(r) for r in values]
    changed[0][2] = Decimal("9.0000")
    _seed_file(path, changed, include_status=False)
    with pytest.raises(DailyBasicValidationError, match="target_conflict"):
        history.audit_daily_basic_history(approved, instance=instance)
    _seed_file(path, values, include_status=False)
    audit = history.audit_daily_basic_history(approved, instance=instance)
    Path(audit["files"][0]["path"]).write_bytes(b"corrupt candidate")
    with pytest.raises(DailyBasicValidationError, match="candidate_changed"):
        history.promote_daily_basic_history(approved, audit, apply=True)


def test_audit_freezes_old_events_without_writing_new_events(replacement):
    approved, instance = replacement
    day = DAYS[0]
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            DAILY_BASIC_ASSET,
            partition=day,
            metadata={
                "goldenshare/file_sha256": file_sha256(
                    raw_daily_basic_path(Path(approved["lake_root"]), day)
                )
            },
        )
    )
    record = events._latest_materializations(instance, [day])[day]
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=dg.AssetKey(DAILY_BASIC_ASSET),
            check_name=DAILY_BASIC_CHECKS[0],
            passed=True,
            blocking=True,
            partition=day,
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id,
                run_id=record.event_log_entry.run_id,
                timestamp=record.event_log_entry.timestamp,
            ),
        )
    )
    with patch.object(events, "RECENT_CHECK_DAYS", 1):
        audit = history.audit_daily_basic_history(approved, instance=instance)
    frozen = audit["replacement"]
    assert frozen["check_dates"] == DAYS  # older checked date plus latest window
    assert frozen["materialization_ids"] == {day: record.storage_id}
    assert list(frozen["check_ids"]) == [f"{day}|{DAILY_BASIC_CHECKS[0]}"]
    assert (
        events._latest_materializations(instance, [day])[day].storage_id
        == record.storage_id
    )


def test_default_import_refuses_existing_targets_and_wrong_integer_schema(replacement):
    approved, _ = replacement
    options = {
        "start": approved["start"],
        "end": approved["end"],
        "batch_id": "other",
        "lake_root": approved["lake_root"],
        "staging_root": approved["staging_root"],
        "calendar_path": approved["calendar_path"],
        "dates": DAYS,
        "cost_evidence": {},
        "limits": approved["limits"],
        "source_evidence": source_evidence(),
    }
    ordinary = history.make_history_plan(**options)
    assert "existing_targets_require_content_audit" in ordinary["stop_reasons"]
    assert ordinary["replace_existing"] is False
    wrong = source_evidence()
    wrong["columns"][-1][1] = "numeric"
    options["source_evidence"] = wrong
    assert (
        "source_limit_status_type"
        in history.make_history_plan(**options, replace_existing=True)["stop_reasons"]
    )


def test_export_resume_keeps_progress_and_counts_null_once(plan, capsys):
    values = [(*rows()[0][:-1], None), rows()[1]]
    with patch.object(history, "HISTORY_BATCH_SIZE", 1):
        with pytest.raises(RuntimeError):
            history.export_daily_basic_history(
                plan, Source(values, fail_at=2), apply=True
            )
        capsys.readouterr()
        complete = history.export_daily_basic_history(plan, Source(values), apply=True)
    lines = capsys.readouterr().out.splitlines()
    assert "confirmed_rows=1" in lines[0]
    assert "prefix_recheck" in lines[1] and "confirmed_rows=1" in lines[1]
    assert "phase=export" in lines[2] and "confirmed_rows=2" in lines[2]
    assert complete["rows"] == 2 and complete["null_limit_status_count"] == 1
    assert len(complete["chunks"]) == 2


def test_replace_check_upper_covers_dates_beyond_original_twenty(plan):
    # 21 SSE weekdays in December 2024; only planner counting is exercised.
    days = [
        (date(2024, 12, 2) + timedelta(days=i)).isoformat()
        for i in range(29)
        if (date(2024, 12, 2) + timedelta(days=i)).weekday() < 5
    ]
    options = {
        "start": days[0],
        "end": days[-1],
        "batch_id": "budget",
        "lake_root": plan["lake_root"],
        "staging_root": plan["staging_root"],
        "calendar_path": plan["calendar_path"],
        "dates": days,
        "source_evidence": source_evidence(),
        "cost_evidence": {},
        "limits": plan["limits"],
    }
    assert history.make_history_plan(**options)["checks_upper"] == 40
    assert (
        history.make_history_plan(**options, replace_existing=True)["checks_upper"]
        == 42
    )


def test_cli_replacement_can_only_be_frozen_in_plan():
    from orchestrator.defs.bootstrap.daily_basic_history_cli import (
        history_parser,
        run_history_cli,
    )

    parser = history_parser()
    assert not parser.parse_args(
        ["plan", "--report", "/private/tmp/fixture.json"]
    ).replace_existing
    args = parser.parse_args(
        ["export", "--replace-existing", "--report", "/private/tmp/fixture.json"]
    )
    with pytest.raises(DailyBasicValidationError, match="replace_only_in_plan"):
        run_history_cli(args)


def test_expected_daily_codes_can_grow_normally(tmp_path):
    write(tmp_path)
    evidence = write(
        tmp_path,
        [row(), row("000002.SZ", limit_status=3)],
        load_expected_codes=lambda: ("000001.SZ", "000002.SZ"),
        write_mode="replace",
    )
    assert evidence["source_row_count"] == evidence["input_code_count"] == 2


def test_missing_limit_status_field_is_not_treated_as_nullable_value(tmp_path):
    missing = row()
    del missing["limit_status"]
    with pytest.raises(DailyBasicValidationError):
        write(tmp_path, [missing])
    assert not raw_daily_basic_path(tmp_path / "lake", DAY).exists()


def test_daily_catalog_schema_and_checks_match_independent_field_contract():
    from orchestrator.defs.assets.daily_basic import raw_tushare_daily_basic
    from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
    from orchestrator.defs.checks.daily_basic_checks import (
        raw_tushare_daily_basic_file_contract_check,
        raw_tushare_daily_basic_source_coverage_check,
    )

    expected = [
        ("ts_code", "VARCHAR"),
        ("trade_date", "VARCHAR"),
        ("close", "DECIMAL(18,4)"),
        ("turnover_rate", "DECIMAL(12,4)"),
        ("turnover_rate_f", "DECIMAL(12,4)"),
        ("volume_ratio", "DECIMAL(12,4)"),
        ("pe", "DECIMAL(18,4)"),
        ("pe_ttm", "DECIMAL(18,4)"),
        ("pb", "DECIMAL(18,4)"),
        ("ps", "DECIMAL(18,4)"),
        ("ps_ttm", "DECIMAL(18,4)"),
        ("dv_ratio", "DECIMAL(12,4)"),
        ("dv_ttm", "DECIMAL(12,4)"),
        ("total_share", "DECIMAL(20,4)"),
        ("float_share", "DECIMAL(20,4)"),
        ("free_share", "DECIMAL(20,4)"),
        ("total_mv", "DECIMAL(20,4)"),
        ("circ_mv", "DECIMAL(20,4)"),
        ("limit_status", "INTEGER"),
    ]
    entry = get_lake_asset_catalog_entry("raw_tushare_daily_basic")
    spec = next(iter(raw_tushare_daily_basic.specs))
    assert [(c.name, c.type) for c in entry.column_schema] == expected
    assert [
        (c.name, c.type) for c in spec.metadata["dagster/column_schema"].value.columns
    ] == expected
    checks = {
        c.name
        for check in (
            raw_tushare_daily_basic_file_contract_check,
            raw_tushare_daily_basic_source_coverage_check,
        )
        for c in check.check_specs
    }
    assert (
        checks
        == set(entry.blocking_check_names)
        == {
            "raw_tushare_daily_basic_file_contract_check",
            "raw_tushare_daily_basic_source_coverage_check",
        }
    )


def test_failed_old_check_stops_before_any_replacement(replacement):
    approved, instance = replacement
    day = DAYS[0]
    path = raw_daily_basic_path(Path(approved["lake_root"]), day)
    before = file_sha256(path)
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            DAILY_BASIC_ASSET,
            partition=day,
            metadata={"goldenshare/file_sha256": before},
        )
    )
    record = events._latest_materializations(instance, [day])[day]
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=dg.AssetKey(DAILY_BASIC_ASSET),
            check_name=DAILY_BASIC_CHECKS[0],
            passed=False,
            blocking=True,
            partition=day,
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id,
                run_id=record.event_log_entry.run_id,
                timestamp=record.event_log_entry.timestamp,
            ),
        )
    )
    with pytest.raises(DailyBasicValidationError, match="history_check_conflict"):
        history.audit_daily_basic_history(approved, instance=instance)
    assert file_sha256(path) == before
