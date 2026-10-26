"""Small independent coverage cases using real producer schemas and file audits.

Upstream schema and domains: run_contracts.asset_column_schemas; lifecycle,
identity and final-suspend producer/check modules. A/B/C are synthetic fixtures.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_coverage as B
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    operation_path,
)
from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_file_sha,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    build_stk_factor_pro_raw_batch,
)
from orchestrator.defs.paths import (
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection

DAY = date(2019, 10, 16)
A, B_CODE, C_CODE = "000001.SZ", "600000.SH", "000002.SZ"
EMPTY_MIDDLE_COUNTS = (
    (DAY - timedelta(days=1), 1),
    (DAY, 0),
    (DAY + timedelta(days=1), 1),
)


def parquet(conn, path, schema, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("DROP TABLE IF EXISTS coverage_fixture")
    conn.execute(
        "CREATE TEMP TABLE coverage_fixture ("
        + ",".join(f"{c.name} {c.type}" for c in schema)
        + ")"
    )
    if rows:
        conn.executemany(
            "INSERT INTO coverage_fixture VALUES ("
            + ",".join("?" for _ in schema)
            + ")",
            rows,
        )
    conn.execute("COPY coverage_fixture TO ? (FORMAT PARQUET)", [str(path)])
    conn.execute("DROP TABLE coverage_fixture")


def upstream(
    conn,
    lake,
    days=(DAY,),
    *,
    codes=(A, B_CODE, C_CODE),
    suspensions=None,
    calendar=None,
    identities=None,
    life=None,
):
    parquet(
        conn,
        silver_trade_calendar_path(lake),
        SILVER_TRADE_CALENDAR_SCHEMA,
        calendar
        if calendar is not None
        else [("SSE", d, True, d - timedelta(days=1)) for d in days],
    )
    parquet(
        conn,
        silver_stock_lifecycle_path(lake),
        SILVER_STOCK_LIFECYCLE_SCHEMA,
        life
        if life is not None
        else [
            (
                c,
                c[:6],
                c,
                "SZSE" if c.endswith("SZ") else "SSE",
                None,
                "CNY",
                True,
                "L",
                date(2010, 1, 1),
                None,
            )
            for c in codes
        ],
    )
    parquet(
        conn,
        silver_stock_identity_map_path(lake),
        SILVER_STOCK_IDENTITY_MAP_SCHEMA,
        identities
        if identities is not None
        else [
            (
                c,
                c,
                date(2010, 1, 1),
                None,
                date(2010, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in codes
        ],
    )
    for day in days:
        rows = (suspensions or {}).get(day, ())
        parquet(
            conn,
            silver_stock_suspend_daily_path(lake, day.isoformat()),
            SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
            rows,
        )


def setup(
    conn, tmp_path, *, codes=(A, C_CODE), counts=None, days=(DAY,), **upstream_args
):
    lake, staging, approval, _ = approval_fixture(
        conn, tmp_path, counts=counts or tuple((d, len(codes)) for d in days)
    )
    upstream(conn, lake, days, **upstream_args)
    source = source_fixture(
        conn,
        staging_root=staging,
        approval=approval,
        rows=tuple(native_row(c, day=days[0]) for c in codes),
        day=days[0],
    )
    raw, silver = P.publish_bootstrap_date(
        conn,
        lake_root=lake,
        staging_root=staging,
        approval=approval,
        source_complete=source,
        before_publish=lambda: None,
        check_space=check_test_space,
    )
    inputs = B.prepare_stk_factor_pro_bootstrap_coverage_month(
        conn,
        lake_root=lake,
        staging_root=staging,
        approval=approval,
        month=approval.month_limits[0],
    )
    return {
        "lake_root": lake,
        "staging_root": staging,
        "approval": approval,
        "inputs": inputs,
        "trade_date": days[0],
        "source_complete": source,
        "raw_audit": raw,
        "silver_audit": silver,
        "current_publication": None,
    }


def save(conn, args):
    result = B.evaluate_stk_factor_pro_bootstrap_coverage_date(
        conn,
        **args,
        check_space=check_test_space,
    )
    return B.write_stk_factor_pro_bootstrap_coverage_date(
        conn,
        **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
        result=result,
        check_space=check_test_space,
    )


def summary(args, imported=(DAY,), current=(DAY,)):
    return B.summarize_stk_factor_pro_bootstrap_coverage(
        **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
        inputs=(args["inputs"],),
        verified_import_dates=imported,
        verified_current_dates=current,
        check_space=check_test_space,
    )


def test_literal_missing_extra_details_and_summary(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path, suspensions={DAY: ((C_CODE, DAY, None, "S"),)})
        result = save(conn, args)
        assert (
            result.expected_count,
            result.actual_count,
            result.matched_count,
            result.missing_count,
            result.extra_count,
        ) == (2, 2, 1, 1, 1)
        assert result.missing_sample_codes == (B_CODE,)
        assert result.extra_sample_codes == (C_CODE,)
        for ref, code in (
            (result.missing_codes_ref, B_CODE),
            (result.extra_codes_ref, C_CODE),
        ):
            path = operation_path(
                args["staging_root"], args["approval"], ref.relative_path
            )
            assert conn.execute(
                "SELECT trade_date,ts_code FROM read_parquet(?)", [str(path)]
            ).fetchall() == [(DAY, code)]
        report = summary(args)
        assert report.total_missing_count == 1 and report.all_expected_present is False
        assert report.verified_source_rows == report.current_raw_rows == 2
        assert report.import_pending_dates == ()
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'stk_factor_pro_coverage_%'"
            ).fetchall()
            == []
        )


@pytest.mark.parametrize("timing", ["09:30-10:00", "source-defined-nonempty"])
def test_intraday_not_deducted_or_invented_timing_regex(tmp_path, timing):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path, suspensions={DAY: ((C_CODE, DAY, timing, "S"),)})
        result = save(conn, args)
        assert (
            result.expected_count,
            result.actual_count,
            result.missing_count,
            result.extra_count,
        ) == (3, 2, 1, 0)


@pytest.mark.parametrize(
    "bad", ["missing", "wrong_date", "blank_timing", "duplicate", "wrong_schema"]
)
def test_bad_suspend_unknown_keeps_published_business_files(tmp_path, bad):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        path = silver_stock_suspend_daily_path(args["lake_root"], DAY.isoformat())
        if bad == "missing":
            path.unlink()
        elif bad == "wrong_schema":
            parquet(conn, path, SILVER_TRADE_CALENDAR_SCHEMA, ())
        else:
            row = (
                C_CODE,
                DAY + timedelta(days=1) if bad == "wrong_date" else DAY,
                " " if bad == "blank_timing" else None,
                "S",
            )
            parquet(
                conn,
                path,
                SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
                (row, row) if bad == "duplicate" else (row,),
            )
        args["inputs"] = B.prepare_stk_factor_pro_bootstrap_coverage_month(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
            month=args["approval"].month_limits[0],
        )
        result = save(conn, args)
        assert result.coverage_complete is None and result.expected_count is None
        assert result.unknown_input_kinds == ("suspend",)
        assert (
            result.raw_rows == 2
            and factor_file_sha(args["raw_audit"].path) == result.raw_file_sha256
        )
        assert summary(args).total_missing_count is None


def test_valid_empty_suspend_and_source_empty_are_explicit(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path, codes=(), counts=EMPTY_MIDDLE_COUNTS)
        result = save(conn, args)
        assert (
            result.source_rows,
            result.raw_rows,
            result.raw_physical_code_count,
        ) == (0, 0, 0)
        assert (
            result.source_empty and result.expected_count == result.missing_count == 3
        )
        assert result.actual_count == 0 and result.raw_file_sha256 is None
        report = summary(args)
        assert (
            report.source_empty_dates == (DAY,)
            and report.missing_count_known_dates == 3
        )
        assert report.total_missing_count is None  # Other approved dates not imported.


@pytest.mark.parametrize(
    "rows",
    [
        (),
        (("SSE", DAY, None, DAY - timedelta(days=1)),),
        (("SSE", DAY, True, DAY - timedelta(days=1)),) * 2,
    ],
)
def test_calendar_unknown_not_fake_closed_or_zero(tmp_path, rows):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path, calendar=rows)
        result = save(conn, args)
        assert (
            result.is_open is None
            and result.raw_rows == 2
            and result.coverage_complete is None
        )
        assert "calendar" in result.unknown_input_kinds
        assert summary(args).calendar_unknown_dates == (DAY,)


def test_one_calendar_gap_does_not_invalidate_other_day(tmp_path):
    days = (DAY, DAY + timedelta(days=1))
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            days=days,
            calendar=(("SSE", DAY, True, DAY - timedelta(days=1)),),
        )
        assert args["inputs"].open_dates == (DAY,)
        assert args["inputs"].calendar_unknown_dates == (days[1],)
        result = save(conn, args)
        assert result.expected_count == 3
        report = summary(args)
        assert report.known_coverage_dates == (
            DAY,
        ) and report.import_pending_dates == (days[1],)
        assert report.total_missing_count is None and report.current_raw_rows is None


def test_known_closed_rejects_coverage_but_empty_not_pending(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            codes=(),
            counts=EMPTY_MIDDLE_COUNTS,
            calendar=(("SSE", DAY, False, DAY - timedelta(days=1)),),
        )
        with pytest.raises(ValueError, match="休市"):
            save(conn, args)
        report = summary(args, imported=(), current=())
        assert DAY not in report.import_pending_dates and report.known_closed_dates == (
            DAY,
        )
        assert report.all_expected_present is None


def test_known_closed_positive_source_conflict(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, calendar=(("SSE", DAY, False, DAY - timedelta(days=1)),)
        )
        with pytest.raises(ValueError, match="休市"):
            save(conn, args)
        with pytest.raises(ValueError, match="休市"):
            summary(args)


def test_unknown_identity_and_physical_rule_rejects(tmp_path):
    with connection(tmp_path) as conn:
        identities = [
            (
                c,
                c,
                date(2010, 1, 1),
                None,
                date(2010, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in (A, B_CODE)
        ]
        args = setup(conn, tmp_path, identities=identities)
        result = save(conn, args)
        assert (
            result.identity_unmapped_count == 1
            and result.identity_unmapped_sample_codes == (C_CODE,)
        )
        assert (
            result.unknown_input_kinds == ("identity",) and result.missing_count is None
        )


def test_aliases_map_once_and_raw_physical_rows_not_changed(tmp_path):
    latest, alias = "920001.BJ", "830001.BJ"
    day = date(2026, 10, 16)
    with connection(tmp_path) as conn:
        identities = [
            (
                latest,
                c,
                date(2020, 1, 1),
                None,
                date(2020, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in (latest, alias)
        ]
        args = setup(
            conn,
            tmp_path,
            codes=(latest, alias),
            days=(day,),
            identities=identities,
            life=[
                (
                    latest,
                    latest[:6],
                    latest,
                    "BSE",
                    None,
                    "CNY",
                    True,
                    "L",
                    date(2020, 1, 1),
                    None,
                )
            ],
        )
        result = save(conn, args)
        assert (
            result.source_rows,
            result.raw_rows,
            result.raw_physical_code_count,
        ) == (2, 2, 2)
        assert (result.expected_count, result.actual_count, result.missing_count) == (
            1,
            1,
            0,
        )


def test_invalid_audit_and_partial_two_layer_never_coverage(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        args["silver_audit"] = None
        with pytest.raises(ValueError, match="audit"):
            save(conn, args)
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/2019-10-16/result.json"
        ).exists()


def test_result_write_failure_preserves_files_and_no_summary_success(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        before = factor_file_sha(args["raw_audit"].path)
        monkeypatch.setattr(
            B,
            "write_json",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("save result")),
        )
        with pytest.raises(OSError, match="save result"):
            save(conn, args)
        assert factor_file_sha(args["raw_audit"].path) == before
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/2019-10-16/result.json"
        ).exists()
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'stk_factor_pro_coverage_%'"
            ).fetchall()
            == []
        )


def test_stale_basis_requires_local_reprepare_only(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        save(conn, args)
        path = silver_stock_suspend_daily_path(args["lake_root"], DAY.isoformat())
        parquet(
            conn, path, SILVER_STOCK_SUSPEND_DAILY_SCHEMA, ((C_CODE, DAY, None, "S"),)
        )
        with pytest.raises(ValueError, match="改变"):
            save(conn, args)
        args["inputs"] = B.prepare_stk_factor_pro_bootstrap_coverage_month(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
            month=args["approval"].month_limits[0],
        )
        result = save(conn, args)
        assert (result.missing_count, result.extra_count) == (1, 1)
        assert summary(args).total_missing_count == 1


def test_changed_current_file_not_counted_as_valid(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        save(conn, args)
        args["silver_audit"].path.write_bytes(b"changed")
        report = summary(args)
        assert report.imported_dates == (
            DAY,
        ) and report.current_files_unverified_dates == (DAY,)
        assert report.current_raw_rows is None and report.total_missing_count is None


def test_update_same_publication_reuses_counts_no_key_scan(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        result = save(conn, args)
        publication = C.StkFactorProBootstrapCurrentPublication(
            "run-b",
            DAY,
            1,
            2,
            3,
            4,
            result.raw_file_sha256,
            result.silver_file_sha256,
            result.raw_file_sha256,
            args["approval"].contract_content_digest,
            "1",
        )
        monkeypatch.setattr(
            B,
            "evaluate_stk_factor_pro_bootstrap_coverage_date",
            lambda *_a, **_k: pytest.fail(
                "unchanged bytes and basis must not recalculate keys"
            ),
        )
        kwargs = {
            k: args[k]
            for k in (
                "lake_root",
                "staging_root",
                "approval",
                "inputs",
                "raw_audit",
                "silver_audit",
            )
        }
        updated = B.update_stk_factor_pro_bootstrap_after_publication(
            conn,
            **kwargs,
            publication=publication,
            check_space=check_test_space,
        )
        assert updated.current_publication == publication and updated.missing_count == 1
        assert (
            B.update_stk_factor_pro_bootstrap_after_publication(
                conn,
                **kwargs,
                publication=publication,
                check_space=check_test_space,
            )
            == updated
        )
        assert summary(args).verified_source_rows == 2


def supplement_audits(conn, args, codes):
    """Real temporary files and full audits; event discovery is outside this unit test."""
    day = args["trade_date"]
    frame = build_stk_factor_pro_raw_batch(
        rows=tuple(native_row(c, day=day) for c in codes),
        source_fields=C.STK_FACTOR_PRO_SOURCE_COLUMNS,
        source="prod_postgres",
        expected_dates=(day,),
    )
    conn.register("coverage_supplement_input", frame)
    try:
        projection = ",".join(
            f'CAST("{name}" AS {kind}) AS "{name}"'
            for name, kind in C.STK_FACTOR_PRO_RAW_COLUMN_TYPES.items()
        )
        conn.execute(
            f"CREATE TEMP TABLE coverage_supplement_raw AS SELECT {projection} FROM coverage_supplement_input"
        )
        conn.execute(
            "CREATE TEMP TABLE coverage_supplement_silver AS SELECT * REPLACE (strptime(trade_date,'%Y%m%d')::DATE AS trade_date) FROM coverage_supplement_raw"
        )
        audits = []
        for layer, path in zip(
            ("raw", "silver"), B._targets(args["lake_root"], day), strict=True
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            conn.execute(
                f"COPY (SELECT * FROM coverage_supplement_{layer} ORDER BY ts_code) TO ? (FORMAT PARQUET)",
                [str(path)],
            )
            audits.append(
                audit_stk_factor_pro_file(
                    conn,
                    path=path,
                    expected_relation=f"coverage_supplement_{layer}",
                    target_trade_date=day,
                    layer=layer,
                )
            )
        # Independent literal values ensure business data did not change shape.
        assert conn.execute(
            f"SELECT ts_code,trade_date,macd_bfq,pe FROM {read_parquet(audits[1].path, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall() == [(c, day, -1.25, None) for c in sorted(codes)]
        return tuple(audits)
    finally:
        conn.unregister("coverage_supplement_input")
        conn.execute("DROP TABLE IF EXISTS coverage_supplement_raw")
        conn.execute("DROP TABLE IF EXISTS coverage_supplement_silver")


@pytest.mark.parametrize("original_codes", [(A, C_CODE), ()])
def test_supplement_current_counts_update_original_facts_unchanged(
    tmp_path, original_codes
):
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            codes=original_codes,
            counts=EMPTY_MIDDLE_COUNTS if not original_codes else None,
        )
        if not original_codes:
            days = tuple(d for d, _ in EMPTY_MIDDLE_COUNTS)
            upstream(conn, args["lake_root"], days)
            args["inputs"] = B.prepare_stk_factor_pro_bootstrap_coverage_month(
                conn,
                **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
                month=args["approval"].month_limits[0],
            )
            for d in (days[0], days[2]):
                source = source_fixture(
                    conn,
                    staging_root=args["staging_root"],
                    approval=args["approval"],
                    rows=(native_row(A, day=d),),
                    day=d,
                    attempt=d.strftime("%Y%m%d") + "b" * 24,
                )
                raw, silver = P.publish_bootstrap_date(
                    conn,
                    **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
                    source_complete=source,
                    before_publish=lambda: None,
                    check_space=check_test_space,
                )
                other = {
                    **args,
                    "trade_date": d,
                    "source_complete": source,
                    "raw_audit": raw,
                    "silver_audit": silver,
                }
                save(conn, other)
        save(conn, args)
        root = B.operation_path(
            args["staging_root"], args["approval"], "approval.json"
        ).parent
        originals = {
            p: p.read_bytes()
            for prefix in ("source/dates", "publication")
            for p in (root / prefix).rglob("*.json")
        }
        raw, silver = supplement_audits(conn, args, (A, B_CODE, C_CODE))
        publication = C.StkFactorProBootstrapCurrentPublication(
            "supplement-run",
            DAY,
            11,
            12,
            13,
            14,
            raw.file_sha256,
            silver.file_sha256,
            raw.file_sha256,
            args["approval"].contract_content_digest,
            "1",
        )
        updated = B.update_stk_factor_pro_bootstrap_after_publication(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval", "inputs")},
            publication=publication,
            raw_audit=raw,
            silver_audit=silver,
            check_space=check_test_space,
        )
        assert (
            updated.source_rows == len(original_codes)
            and updated.raw_rows == updated.silver_rows == 3
        )
        assert (
            updated.source_empty is (not bool(original_codes))
            and updated.missing_count == 0
        )
        assert all(p.read_bytes() == before for p, before in originals.items())
        days = (
            tuple(d for d, _ in EMPTY_MIDDLE_COUNTS) if not original_codes else (DAY,)
        )
        report = summary(args, imported=days, current=days)
        assert (
            report.verified_source_rows
            == report.verified_raw_rows
            == report.verified_silver_rows
            == 2
        )
        assert (
            report.current_raw_rows
            == report.current_silver_rows
            == (5 if not original_codes else 3)
        )
        assert report.source_empty_dates == ((DAY,) if not original_codes else ())
        assert report.total_missing_count == (4 if not original_codes else 0)


def test_wrong_current_publication_contract_or_raw_binding_rejected(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        result = save(conn, args)
        publication = C.StkFactorProBootstrapCurrentPublication(
            "run-b",
            DAY,
            1,
            2,
            3,
            4,
            result.raw_file_sha256,
            result.silver_file_sha256,
            result.raw_file_sha256,
            args["approval"].contract_content_digest,
            "1",
        )
        with pytest.raises(ValueError, match="来源Raw"):
            replace(publication, silver_source_raw_sha256="f" * 64)
        for wrong in (replace(publication, contract_content_digest="f" * 64),):
            with pytest.raises(ValueError, match="不符"):
                B.update_stk_factor_pro_bootstrap_after_publication(
                    conn,
                    **{
                        k: args[k]
                        for k in (
                            "lake_root",
                            "staging_root",
                            "approval",
                            "inputs",
                            "raw_audit",
                            "silver_audit",
                        )
                    },
                    publication=wrong,
                    check_space=check_test_space,
                )


def test_replay_zero_keys_zero_result_rewrites_and_global_hash_reuse(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        hashes = []
        original_sha = B.factor_file_sha
        monkeypatch.setattr(
            B,
            "factor_file_sha",
            lambda path: (hashes.append(path), original_sha(path))[1],
        )
        args = setup(conn, tmp_path)
        calls = []
        original_keys = B.build_stk_factor_pro_coverage_keys
        monkeypatch.setattr(
            B,
            "build_stk_factor_pro_coverage_keys",
            lambda *a, **k: (calls.append(1), original_keys(*a, **k))[1],
        )
        result = save(conn, args)
        assert len(calls) == 1
        before = len(hashes)
        global_paths = (
            silver_trade_calendar_path(args["lake_root"]),
            silver_stock_lifecycle_path(args["lake_root"]),
            silver_stock_identity_map_path(args["lake_root"]),
        )
        assert [hashes.count(p) for p in global_paths] == [1, 1, 1]
        monkeypatch.setattr(
            B,
            "write_json",
            lambda *_a, **_k: pytest.fail("unchanged result must not be replaced"),
        )
        assert save(conn, args) == result
        assert len(calls) == 1
        assert all(p not in hashes[before:] for p in global_paths)
        # Summary has no connection and hashes each global once plus final recheck.
        monkeypatch.undo()
        hashes = []
        monkeypatch.setattr(
            B,
            "factor_file_sha",
            lambda path: (hashes.append(path), original_sha(path))[1],
        )
        summary(args)
        assert [hashes.count(p) for p in global_paths] == [2, 2, 2]


@pytest.mark.parametrize("kind", ["lifecycle", "identity"])
def test_original_upstream_physical_rules_not_hidden_by_filters(tmp_path, kind):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        path = (
            silver_stock_lifecycle_path(args["lake_root"])
            if kind == "lifecycle"
            else silver_stock_identity_map_path(args["lake_root"])
        )
        conn.execute(
            f"CREATE TEMP TABLE bad_basis AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        if kind == "lifecycle":
            conn.execute("UPDATE bad_basis SET list_date=NULL WHERE ts_code=?", [A])
        else:
            conn.execute("INSERT INTO bad_basis SELECT * FROM bad_basis LIMIT 1")
        conn.execute("COPY bad_basis TO ? (FORMAT PARQUET)", [str(path)])
        args["inputs"] = B.prepare_stk_factor_pro_bootstrap_coverage_month(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
            month=args["approval"].month_limits[0],
        )
        result = save(conn, args)
        assert result.expected_count is None and kind in result.unknown_input_kinds
        assert result.raw_rows == 2


@pytest.mark.parametrize("edge", ["self_expired", "not_started"])
def test_identity_validity_end_exclusive_and_no_self_fallback(tmp_path, edge):
    with connection(tmp_path) as conn:
        identities = [
            (
                c,
                c,
                DAY + timedelta(days=1)
                if edge == "not_started" and c == A
                else date(2010, 1, 1),
                DAY if edge == "self_expired" and c == A else None,
                date(2010, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in (A, B_CODE, C_CODE)
        ]
        args = setup(conn, tmp_path, identities=identities)
        result = save(conn, args)
        assert (
            result.identity_unmapped_count == 1
            and result.identity_unmapped_sample_codes == (A,)
        )
        assert result.coverage_complete is None


def test_bse_not_expected_before_market_open_and_listing_end_exclusive(tmp_path):
    bj = "830001.BJ"
    with connection(tmp_path) as conn:
        life = [
            (A, A[:6], A, "SZSE", None, "CNY", True, "L", DAY, None),
            (
                B_CODE,
                B_CODE[:6],
                B_CODE,
                "SSE",
                None,
                "CNY",
                True,
                "D",
                date(2010, 1, 1),
                DAY,
            ),
            (bj, bj[:6], bj, "BSE", None, "CNY", True, "L", date(2010, 1, 1), None),
        ]
        args = setup(
            conn,
            tmp_path,
            codes=(A, bj),
            life=life,
            identities=[
                (
                    c,
                    c,
                    date(2010, 1, 1),
                    None,
                    date(2010, 1, 1),
                    None,
                    "stock_lifecycle",
                    "confirmed",
                    None,
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
                for c in (A, B_CODE, bj)
            ],
        )
        result = save(conn, args)
        assert (
            result.expected_count,
            result.actual_count,
            result.matched_count,
            result.missing_count,
            result.extra_count,
        ) == (1, 2, 1, 0, 1)
        assert result.extra_sample_codes == (bj,)


def test_transfer_mismatch_not_misreported_as_market_gap(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        raw, silver = supplement_audits(conn, args, (A,))
        with pytest.raises(ValueError, match="原两层完成事实"):
            save(conn, {**args, "raw_audit": raw, "silver_audit": silver})
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/2019-10-16/result.json"
        ).exists()


def test_summary_write_failure_keeps_result_and_business_files(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        result = save(conn, args)
        monkeypatch.setattr(
            B,
            "write_json",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("summary save")),
        )
        with pytest.raises(OSError, match="summary save"):
            summary(args)
        assert factor_file_sha(args["raw_audit"].path) == result.raw_file_sha256
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/summary.json"
        ).exists()


def test_cleanup_all_tables_preserves_primary_failure(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        monkeypatch.setattr(
            B,
            "build_stk_factor_pro_coverage_keys",
            lambda *_a, **_k: (_ for _ in ()).throw(
                KeyboardInterrupt("primary cancel")
            ),
        )
        executed = []

        class WrappedConnection:
            def execute(self, query, *a, **k):
                executed.append(query)
                if query.startswith("DROP TABLE IF EXISTS ") and query.endswith(
                    B._DAILY[0]
                ):
                    raise OSError("cleanup one")
                if query.startswith("DROP TABLE IF EXISTS ") and query.endswith(
                    B._DAILY[1]
                ):
                    raise RuntimeError("cleanup two")
                return conn.execute(query, *a, **k)

        with pytest.raises(KeyboardInterrupt, match="primary cancel") as caught:
            save(WrappedConnection(), args)
        assert "bootstrap清理同时失败：OSError" in caught.value.__notes__
        assert any(q.endswith(B._PURE_TABLES[-1]) for q in executed)


def test_summary_stale_basis_marks_only_input_unknown_no_false_zero(tmp_path):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        result = save(conn, args)
        path = silver_stock_suspend_daily_path(args["lake_root"], DAY.isoformat())
        parquet(
            conn, path, SILVER_STOCK_SUSPEND_DAILY_SCHEMA, ((C_CODE, DAY, None, "S"),)
        )
        report = summary(args)
        assert report.coverage_unknown_dates[0][1] == ("suspend",)
        assert (
            report.total_missing_count is None
            and report.current_files_unverified_dates == ()
        )
        assert report.current_raw_rows == result.raw_rows


def test_release_month_preserves_global_tables_and_bounded_identity_cache(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        args = setup(conn, tmp_path)
        result = save(conn, args)
        B.release_stk_factor_pro_bootstrap_coverage_month(conn)
        names = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary"
            ).fetchall()
        }
        assert B._MONTH not in names and B._SUSPEND not in names
        assert all(
            B._PREFIX + kind in names for kind in ("calendar", "lifecycle", "identity")
        )
        assert conn.execute(f"SELECT count(*) FROM {B._IDENTITIES}").fetchone()[0] == 3
        original = B.factor_file_sha
        hashes = []
        monkeypatch.setattr(
            B, "factor_file_sha", lambda p: (hashes.append(p), original(p))[1]
        )
        args["inputs"] = B.prepare_stk_factor_pro_bootstrap_coverage_month(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
            month=args["approval"].month_limits[0],
        )
        assert save(conn, args) == result
        assert all(
            p not in hashes
            for p in (
                silver_trade_calendar_path(args["lake_root"]),
                silver_stock_lifecycle_path(args["lake_root"]),
                silver_stock_identity_map_path(args["lake_root"]),
            )
        )


def test_release_attempts_all_tables_after_multiple_cleanup_failures(tmp_path):
    with connection(tmp_path) as conn:
        setup(conn, tmp_path)
        dropped = []

        class WrappedConnection:
            def execute(self, query, *a, **k):
                if query.startswith("DROP TABLE IF EXISTS "):
                    dropped.append(query.split()[-1])
                    if query.endswith(B._MONTH):
                        raise OSError("first cleanup")
                    if query.endswith(B._SUSPEND):
                        raise RuntimeError("second cleanup")
                return conn.execute(query, *a, **k)

        with pytest.raises(OSError, match="first cleanup"):
            B.release_stk_factor_pro_bootstrap_coverage_month(WrappedConnection())
        assert B._PURE_TABLES[-1] in dropped
