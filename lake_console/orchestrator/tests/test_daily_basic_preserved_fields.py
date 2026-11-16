"""LLD41: DG old values and frozen Prod status have separate authorities.

The typed fixture producer follows migration188 / DAILY_BASIC_COLUMN_SPECS.
dv_ratio and volume_ratio differences use the bounded examples in LLD38;
other values and NULL differences are synthetic, with literal expectations.
All Parquet and Dagster SQLite storage is temporary; no production resources.
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap import daily_basic_events as events
from orchestrator.defs.bootstrap import daily_basic_history as history
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_TYPES,
    DailyBasicValidationError,
)
from orchestrator.defs.daily_basic_raw_io import file_sha256
from orchestrator.defs.paths import raw_daily_basic_path
from tests.test_daily_basic_history import DAYS, Source, rows, source_evidence
from tests.test_daily_basic_history import plan as history_plan
from tests.test_daily_basic_limit_status import _seed_file

plan = history_plan


@pytest.fixture
def preserved(plan, request):
    values = []
    originals = {}
    for day in DAYS:
        old = []
        codes = [
            ("000001.SZ", 0),
            ("201872.SZ", None),
            ("920964.BJ", None),
        ]
        if getattr(request, "param", False) and day == DAYS[1]:
            codes.append(("000002.SZ", 6))
        for code, status in codes:
            source = dict(zip(DAILY_BASIC_FIELDS, rows(code)[0], strict=True))
            source.update(
                trade_date=day.replace("-", ""),
                dv_ratio=Decimal("4.8355"),
                volume_ratio=Decimal("1.2700"),
                pb=None,
                limit_status=status,
            )
            values.append(tuple(source[n] for n in DAILY_BASIC_FIELDS))
            original = {
                **source,
                "dv_ratio": Decimal("4.8356"),
                "volume_ratio": Decimal("1.2800"),
                "close": None,
                "turnover_rate": Decimal("8.0000"),
                "pb": Decimal("9.0000"),
            }
            old.append(tuple(original[n] for n in DAILY_BASIC_FIELDS[:-1]))
        path = raw_daily_basic_path(Path(plan["lake_root"]), day)
        _seed_file(path, old, include_status=False)
        originals[day] = file_sha256(path)
    approved = history.make_history_plan(
        start=plan["start"],
        end=plan["end"],
        batch_id=plan["batch_id"],
        lake_root=plan["lake_root"],
        staging_root=plan["staging_root"],
        calendar_path=plan["calendar_path"],
        dates=DAYS,
        source_evidence=source_evidence(),
        cost_evidence={},
        limits=plan["limits"],
        replace_existing=True,
    )
    source = Source(sorted(values))
    export = history.export_daily_basic_history(approved, source, apply=True)
    return approved, export, source, originals


@pytest.mark.parametrize(
    "preserved",
    [False, True],
    indirect=True,
    ids=["stable_codes", "new_code_on_second_day"],
)
def test_build_preserves_dg_values_nulls_types_and_all_codes(preserved, request):
    plan, export, source, originals = preserved
    build = history.build_daily_basic_history(plan, apply=True)
    with duckdb.connect() as connection:
        for item in build["files"]:
            codes = [("000001.SZ", 0), ("201872.SZ", None), ("920964.BJ", None)]
            if request.node.callspec.params["preserved"] and item["date"] == DAYS[1]:
                codes = [
                    ("000001.SZ", 0),
                    ("000002.SZ", 6),
                    ("201872.SZ", None),
                    ("920964.BJ", None),
                ]
            result = connection.execute(
                "SELECT ts_code,close,turnover_rate,volume_ratio,dv_ratio,pb,limit_status "
                "FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                [item["path"]],
            ).fetchall()
            assert result == [
                (
                    code,
                    None,
                    Decimal("8.0000"),
                    Decimal("1.2800"),
                    Decimal("4.8356"),
                    Decimal("9.0000"),
                    status,
                )
                for code, status in codes
            ]
            assert [
                (r[0], r[1])
                for r in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                    [item["path"]],
                ).fetchall()
            ] == list(DAILY_BASIC_TYPES.items())
            old_path = raw_daily_basic_path(Path(plan["lake_root"]), item["date"])
            columns = ", ".join(f'"{n}"' for n in DAILY_BASIC_FIELDS[:-1])
            assert (
                connection.execute(
                    f"SELECT {columns} FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                    [item["path"]],
                ).fetchall()
                == connection.execute(
                    "SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                    [str(old_path)],
                ).fetchall()
            )
    with dg.DagsterInstance.ephemeral() as instance:
        audit = history.audit_daily_basic_history(plan, instance=instance)
    assert audit["rows"] == (7 if request.node.callspec.params["preserved"] else 6)
    assert audit["null_limit_status_count"] == 4
    assert audit["field_sources"] == {
        **{n: "data_lake" for n in DAILY_BASIC_FIELDS[:-1]},
        "limit_status": "prod_raw_db",
    }
    assert (
        events._history_evidence(plan, audit, audit["files"][0])["field_sources"]
        == audit["field_sources"]
    )
    assert build["export_fingerprint"] == export["fingerprint"]
    assert source.calls == 2
    assert {
        d: file_sha256(raw_daily_basic_path(Path(plan["lake_root"]), d)) for d in DAYS
    } == originals


def test_old_completed_build_and_full_source_cache_are_reused_correctly(preserved):
    plan, export, _, _ = preserved
    workspace = history._workspace(plan)
    # Producer layout is the old build: full19 annual cache and full-Prod candidates.
    cache = workspace / "annual_old"
    legacy_files = []
    cache_files = []
    with duckdb.connect() as connection:
        for chunk in export["chunks"]:
            source_rows = connection.execute(
                "SELECT * FROM read_parquet(?,hive_partitioning=false)", [chunk["path"]]
            ).fetchall()
        for day in DAYS:
            values = [r for r in source_rows if r[1] == day.replace("-", "")]
            annual_path = cache / f"history_year={day[:4]}" / "data_0.parquet"
            _seed_file(annual_path, values, include_status=True)
            cache_files.append(
                {"path": str(annual_path), "sha256": file_sha256(annual_path)}
            )
            path = (
                workspace
                / "by_date"
                / day[:4]
                / "old"
                / f"partition_date={day}"
                / "part-000.parquet"
            )
            _seed_file(path, values, include_status=True)
            legacy_files.append(
                {"date": day, "path": str(path), "sha256": file_sha256(path), "rows": 3}
            )
    history.save_history_report(
        workspace / "annual.json",
        {
            "export_fingerprint": export["fingerprint"],
            "root": str(cache),
            "files": cache_files,
        },
    )
    history.save_history_report(
        workspace / "build.json",
        {
            "stage": "build",
            "plan_fingerprint": plan["fingerprint"],
            "export_fingerprint": export["fingerprint"],
            "files": legacy_files,
            "completed_years": ["2024", "2025"],
        },
    )
    protected = [
        workspace / "build.json",
        workspace / "annual.json",
        workspace / "export.json",
        *(Path(i["path"]) for i in legacy_files + cache_files),
    ]
    hashes = {p: file_sha256(p) for p in protected}
    build = history.build_daily_basic_history(plan, apply=True)
    assert len(build["files"]) == 2 and build["completed_years"] == ["2024", "2025"]
    assert all(
        Path(i["path"]).is_relative_to(workspace / "field_expansion" / "by_date")
        for i in build["files"]
    )
    assert {p: file_sha256(p) for p in protected} == hashes
    with dg.DagsterInstance.ephemeral() as instance:
        audit = history.audit_daily_basic_history(plan, instance=instance)
        assert audit["passed"]
        stale = history.seal_history_report(
            {
                **audit,
                "build_fingerprint": history.load_history_report(
                    workspace / "build.json"
                )["fingerprint"],
            }
        )
        with pytest.raises(DailyBasicValidationError, match="history_stale_audit"):
            history.promote_daily_basic_history(plan, stale, apply=True)
        assert (
            len(history.promote_daily_basic_history(plan, audit, apply=True)["files"])
            == 2
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "wrong_date"])
def test_dg_key_mismatch_cannot_silently_drop_or_add_rows(preserved, mutation):
    plan, _, _, _ = preserved
    path = raw_daily_basic_path(Path(plan["lake_root"]), DAYS[0])
    with duckdb.connect() as connection:
        values = connection.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false)", [str(path)]
        ).fetchall()
    values = [list(r) for r in values]
    if mutation == "missing":
        values.pop()
    elif mutation == "extra":
        values.append(["000002.SZ", *values[0][1:]])
    elif mutation == "duplicate":
        values.append(values[0])
    else:
        values[0][1] = "20241230"
    _seed_file(path, values, include_status=False)
    with pytest.raises(
        DailyBasicValidationError, match="history_source_keys_difference"
    ):
        history.build_daily_basic_history(plan, apply=True)
    assert not (history._build_workspace(plan) / "build.json").exists()


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("dv_ratio", "4.8357", "history_target_conflict"),
        ("limit_status", "6", "history_value_difference"),
    ],
)
def test_audit_checks_both_sources_even_when_candidate_hash_is_updated(
    preserved, field, value, reason
):
    plan, _, _, _ = preserved
    build = history.build_daily_basic_history(plan, apply=True)
    item = build["files"][0]
    path = Path(item["path"])
    temporary = path.with_suffix(".changed")
    with duckdb.connect() as connection:
        connection.execute(
            f"COPY (SELECT * REPLACE (CASE WHEN ts_code='000001.SZ' THEN {value} "
            f'ELSE "{field}" END::{DAILY_BASIC_TYPES[field]} AS "{field}") '
            "FROM read_parquet($input,hive_partitioning=false)) TO $output (FORMAT PARQUET)",
            {"input": str(path), "output": str(temporary)},
        )
    temporary.replace(path)
    item["sha256"] = file_sha256(path)
    history.save_history_report(history._build_workspace(plan) / "build.json", build)
    with (
        dg.DagsterInstance.ephemeral() as instance,
        pytest.raises(DailyBasicValidationError, match=reason),
    ):
        history.audit_daily_basic_history(plan, instance=instance)


@pytest.mark.parametrize("failure", ["after_year", "save_then_error"])
def test_build_resume_keeps_committed_year_and_frozen_export(preserved, failure):
    plan, export, source, _ = preserved
    save = history.save_history_report
    committed = []

    def stop(path, value):
        if Path(path).name == "build.json":
            if failure == "after_year" and value["completed_years"] == ["2024", "2025"]:
                raise KeyboardInterrupt()
            save(path, value)
            committed.append(history.load_history_report(path))
            if failure == "save_then_error":
                raise OSError("saved checkpoint then connection lost")
        else:
            save(path, value)

    with (
        patch.object(history, "save_history_report", side_effect=stop),
        pytest.raises((KeyboardInterrupt, OSError)),
    ):
        history.build_daily_basic_history(plan, apply=True)
    assert committed[0]["completed_years"] == ["2024"]
    first = committed[0]["files"][0]
    resumed = history.build_daily_basic_history(plan, apply=True)
    assert resumed["files"][0] == first and len(resumed["files"]) == 2
    assert file_sha256(Path(first["path"])) == first["sha256"]
    assert history.build_daily_basic_history(plan, apply=True) == resumed
    assert (
        history.load_history_report(history._workspace(plan) / "export.json") == export
    )
    assert source.calls == 2
    annual = history.load_history_report(history._workspace(plan) / "annual.json")
    with duckdb.connect() as connection:
        for item in annual["files"]:
            assert connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [item["path"]],
            ).fetchall() == [
                ("ts_code", "VARCHAR", "YES", None, None, None),
                ("trade_date", "VARCHAR", "YES", None, None, None),
                ("limit_status", "INTEGER", "YES", None, None, None),
            ]


@pytest.mark.parametrize(
    "projection,reason",
    [
        ("* EXCLUDE(limit_status)", "limit_status"),
        ("* REPLACE (limit_status::VARCHAR AS limit_status)", "history_schema"),
        ("* REPLACE (7::INTEGER AS limit_status)", "history_keys"),
        ("* REPLACE ('20250101' AS trade_date)", "history_keys"),
        ("* REPLACE ('000001.SZ' AS ts_code)", "history_keys"),
    ],
)
def test_status_projection_keeps_source_key_type_and_value_checks(
    preserved, projection, reason
):
    plan, export, _, _ = preserved
    # Negative frozen input: reseal identity to reach semantic validation, rather
    # than merely testing SHA rejection. Source contract itself stays full19.
    chunk = export["chunks"][0]
    path = Path(chunk["path"])
    changed = path.with_suffix(".changed")
    with duckdb.connect() as connection:
        connection.execute(
            f"COPY (SELECT {projection} FROM read_parquet($input,hive_partitioning=false)) "
            "TO $output (FORMAT PARQUET)",
            {"input": str(path), "output": str(changed)},
        )
    changed.replace(path)
    chunk["sha256"] = file_sha256(path)
    history.save_history_report(history._workspace(plan) / "export.json", export)
    with pytest.raises(
        (DailyBasicValidationError, duckdb.BinderException), match=reason
    ):
        history.build_daily_basic_history(plan, apply=True)
