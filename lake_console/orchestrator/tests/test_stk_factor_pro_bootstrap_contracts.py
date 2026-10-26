"""LLD 9/10/17 closed bootstrap records; literal doc328 schema, no external I/O."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from orchestrator.defs.run_contracts import stk_factor_pro as m
from orchestrator.tushare_download.contract_registry import content_digest

D = date(2026, 10, 15)
NEXT = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 19, tzinfo=timezone(timedelta(hours=8)))
SHA, OTHER = "a" * 64, "b" * 64
ATTEMPT = "c" * 32


def documented_fields():
    document = (
        Path(__file__).resolve().parents[3]
        / "docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md"
    )
    section = document.read_text().split("## 输出参数", 1)[1].split("## ", 1)[0]
    result = []
    for line in section.splitlines():
        if line.startswith("|"):
            cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
            if cells[1] in ("str", "float"):
                result.append((cells[0], cells[1], cells[3]))
    assert len(result) == 261
    return tuple(result)


def expected_schema(layer):
    return tuple(
        (
            name,
            "DATE"
            if layer == "silver" and name == "trade_date"
            else "VARCHAR"
            if kind == "str"
            else "DOUBLE",
        )
        for name, kind, _ in documented_fields()
    )


NAMES = tuple(item[0] for item in documented_fields())
SOURCE_SCHEMA = tuple(
    (
        name,
        "date"
        if name == "trade_date"
        else "text"
        if kind == "str"
        else "double precision",
        name not in ("ts_code", "trade_date"),
    )
    for name, kind, _ in documented_fields()
)


def source_identity():
    return m.StkFactorProSourceIdentity(
        "approved-host",
        5432,
        "prod_raw",
        "raw_tushare",
        "stk_factor_pro",
        SOURCE_SCHEMA,
        SHA,
    )


def month():
    return m.StkFactorProBootstrapMonthLimit(D, NEXT + timedelta(days=1), 3)


def approval():
    return m.StkFactorProBootstrapApproval(
        1,
        "operation-a",
        D,
        NEXT,
        NEXT,
        NOW,
        NOW + timedelta(hours=1),
        m.stk_factor_pro_bootstrap_source_identity_digest(source_identity()),
        SHA,
        "approved-daily-counts.parquet",
        SHA,
        "approved-source-evidence.json",
        SHA,
        (month(),),
        1000,
    )


def fragment(
    *,
    layer="raw",
    relative_path=None,
    minimum=D,
    maximum=D,
    first="000001.SZ",
    last="000001.SZ",
    rows=1,
):
    return m.StkFactorProFragment(
        relative_path
        or f"source/month=2026-10/attempt_id={ATTEMPT}/fragment-000001.parquet",
        SHA,
        SHA if rows else sha256(b"").hexdigest(),
        m.stk_factor_pro_schema_digest(layer),
        rows,
        expected_schema(layer),
        minimum,
        maximum,
        first,
        last,
    )


def source_complete():
    refs = (m.StkFactorProBootstrapFragmentRef(1, ATTEMPT, fragment()),)
    return m.StkFactorProBootstrapSourceComplete(
        1,
        "operation-a",
        SHA,
        approval().source_identity_digest,
        SHA,
        NEXT,
        D,
        NEXT + timedelta(days=1),
        ATTEMPT,
        m.stk_factor_pro_bootstrap_query_digest(approval(), SHA, month(), (D, NEXT)),
        (D, NEXT),
        3,
        D,
        1,
        1,
        refs,
        m.fragments_manifest_digest(refs),
        m.stk_factor_pro_schema_digest("raw"),
        SHA,
        1,
        "next_date",
        NEXT,
        False,
        SHA,
        NOW,
    )


def audit(layer="raw", *, rows=1):
    return m.StkFactorProFileAudit(
        D,
        layer,
        Path(f"/private/tmp/lake/{layer}/data.parquet"),
        SHA,
        expected_schema(layer),
        rows,
        0,
        0,
        0,
        0,
        m.StkFactorProComparison(rows, rows, 0, 0, 0, ()),
        True,
        Path("diagnostics/result.json"),
    )


def intent(layer="raw"):
    candidate = fragment(
        layer=layer, relative_path=f"candidates/{D}/{layer}/part-000.parquet"
    )
    return m.StkFactorProBootstrapPublicationIntent(
        1,
        "operation-a",
        SHA,
        D,
        layer,
        SHA,
        None if layer == "raw" else SHA,
        "replace",
        None,
        candidate,
        SHA,
        SHA,
        NOW,
    )


def publication_complete(layer="raw"):
    return m.StkFactorProBootstrapPublicationComplete(
        1,
        "operation-a",
        SHA,
        D,
        layer,
        SHA,
        f"publication/{D}/{layer}/intent.json",
        SHA,
        SHA,
        SHA,
        1,
        m.stk_factor_pro_schema_digest(layer),
        SHA,
        1,
        audit(layer),
        NOW,
    )


def basis_files():
    return tuple(
        m.StkFactorProBootstrapBasisFile(
            kind, D if kind == "suspend" else None, SHA, SHA, 1, True
        )
        for kind in ("calendar", "identity", "lifecycle", "suspend")
    )


def current_publication():
    return m.StkFactorProBootstrapCurrentPublication(
        "run-a", D, 1, 2, 3, 4, SHA, SHA, SHA, SHA, "1"
    )


def date_coverage():
    return m.StkFactorProBootstrapDateCoverage(
        1,
        "operation-a",
        SHA,
        D,
        1,
        1,
        1,
        1,
        SHA,
        SHA,
        SHA,
        True,
        False,
        None,
        True,
        basis_files(),
        (),
        SHA,
        0,
        0,
        (),
        (),
        1,
        1,
        1,
        0,
        0,
        True,
        "按本次DG正式生命周期事实统计",
        None,
        None,
        (),
        (),
        NOW,
    )


def coverage_inputs():
    return m.StkFactorProBootstrapCoverageInputs(
        "operation-a", month(), (D, NEXT), (D, NEXT), (), (), basis_files(), (), SHA
    )


def summary():
    return m.StkFactorProBootstrapCoverageSummary(
        1,
        "operation-a",
        SHA,
        D,
        D,
        NOW,
        (D,),
        (),
        (),
        (D,),
        (),
        (),
        (D,),
        (),
        (),
        1,
        1,
        1,
        1,
        1,
        (),
        ((D, SHA),),
        1,
        1,
        1,
        0,
        0,
        True,
        0,
        True,
    )


def source_evidence():
    return m.StkFactorProBootstrapSourceEvidence(
        1,
        "operation-a",
        source_identity(),
        approval().source_identity_digest,
        SHA,
        D,
        NEXT,
        1,
        "approved-daily-counts.parquet",
        SHA,
        NOW,
        NOW + timedelta(hours=1),
        "获准维护窗口内来源保持静止",
        NOW,
        "source-sample.json",
        SHA,
    )


def source_sample():
    return m.StkFactorProBootstrapSourceSample(
        1,
        "operation-a",
        approval().source_identity_digest,
        SHA,
        D,
        ("000001.SZ",),
        2,
        NAMES,
        1,
        SOURCE_SCHEMA,
        True,
        NOW,
    )


@pytest.mark.parametrize(
    "factory",
    [
        source_identity,
        month,
        approval,
        fragment,
        source_evidence,
        source_sample,
        source_complete,
        intent,
        publication_complete,
        coverage_inputs,
        current_publication,
        date_coverage,
        summary,
        lambda: m.StkFactorProBootstrapFragmentRef(1, ATTEMPT, fragment()),
        lambda: m.StkFactorProBootstrapMonthResult(
            month(),
            ATTEMPT,
            1,
            (fragment(),),
            (D,),
            (NEXT,),
            (audit(), audit("silver")),
        ),
        lambda: m.StkFactorProBootstrapDateResult(
            D, SHA, audit(), audit("silver"), date_coverage()
        ),
        lambda: m.StkFactorProBootstrapPublicationBatch(
            (current_publication(),), (), (NEXT,)
        ),
        lambda: m.StkFactorProBootstrapBasisFile(
            "calendar", None, None, None, None, False
        ),
    ],
)
def test_every_bootstrap_record_is_frozen_closed_and_roundtrips(factory):
    record = factory()
    encoded = m.stk_factor_pro_record_to_dict(record)
    assert m.parse_stk_factor_pro_record(type(record), encoded) == record
    with pytest.raises(FrozenInstanceError):
        setattr(record, fields(record)[0].name, None)
    with pytest.raises(ValueError, match="未知"):
        m.parse_stk_factor_pro_record(type(record), {**encoded, "unapproved": True})
    missing = dict(encoded)
    del missing[next(iter(missing))]
    with pytest.raises(ValueError, match="缺字段"):
        m.parse_stk_factor_pro_record(type(record), missing)


def test_path_codec_roundtrips_audit_without_repr_or_loss():
    encoded = m.stk_factor_pro_record_to_dict(publication_complete())
    assert encoded["audit"]["path"] == "/private/tmp/lake/raw/data.parquet"
    assert encoded["audit"]["diagnostics_path"] == "diagnostics/result.json"
    assert encoded["verified_at"] == "2026-10-16T19:00:00.000000+08:00"
    for value in (
        "../escape",
        "/private/tmp/../escape",
        "a//b",
        "a\\b",
        "a/./b",
        "bad\x00path",
    ):
        bad = m.stk_factor_pro_record_to_dict(publication_complete())
        bad["audit"]["path"] = value
        with pytest.raises(ValueError):
            m.parse_stk_factor_pro_record(
                m.StkFactorProBootstrapPublicationComplete, bad
            )


@pytest.mark.parametrize(
    ("factory", "changes"),
    [
        (source_identity, {"port": True}),
        (source_identity, {"schema": "arbitrary"}),
        (source_identity, {"columns": SOURCE_SCHEMA[:-1]}),
        (source_identity, {"columns": (("ts_code", "text", 1), *SOURCE_SCHEMA[1:])}),
        (month, {"row_upper_bound": False}),
        (month, {"month_end_exclusive": date(2026, 11, 2)}),
        (approval, {"source_statement_timeout_ms": True}),
        (approval, {"source_statement_timeout_ms": 0}),
        (approval, {"source_cutoff_trade_date": D}),
        (approval, {"month_limits": ()}),
        (approval, {"source_maintenance_end": NOW}),
        (approval, {"source_maintenance_start": NOW.replace(tzinfo=None)}),
        (approval, {"source_maintenance_start": NOW.astimezone(timezone.utc)}),
        (approval, {"approved_daily_counts_ref": "../outside"}),
        (approval, {"approved_source_evidence_ref": "/tmp/source"}),
        (source_evidence, {"source_identity_digest": OTHER}),
        (source_evidence, {"maintenance_statement": " "}),
        (source_sample, {"row_limit": True}),
        (source_sample, {"returned_rows": 3}),
        (source_sample, {"request_columns": NAMES[:-1]}),
        (source_sample, {"passed": 1}),
        (source_complete, {"actual_rows": 0}),
        (source_complete, {"selected_dates": (NEXT, D)}),
        (source_complete, {"attempt_id": "old-run"}),
        (source_complete, {"fragments": ()}),
        (source_complete, {"close_reason": "full_page"}),
        (source_complete, {"next_trade_date": D}),
        (source_complete, {"schema_content_digest": OTHER}),
        (intent, {"prior_file_sha256": OTHER}),
        (intent, {"raw_file_sha256": SHA}),
        (intent, {"expected_file_sha256": OTHER}),
        (publication_complete, {"actual_rows": 2}),
        (publication_complete, {"actual_file_sha256": OTHER}),
        (publication_complete, {"intent_relative_path": "old-run/intent.json"}),
        (current_publication, {"raw_check_event_storage_id": True}),
        (current_publication, {"silver_source_raw_sha256": OTHER}),
        (date_coverage, {"import_complete": False}),
        (date_coverage, {"raw_rows": 2}),
        (date_coverage, {"raw_physical_code_count": 2}),
        (date_coverage, {"is_open": False}),
        (date_coverage, {"missing_count": 1}),
        (date_coverage, {"coverage_complete": False}),
        (date_coverage, {"unknown_input_kinds": ("new_kind",)}),
        (summary, {"verified_raw_rows": 2}),
        (summary, {"total_missing_count": 1}),
        (summary, {"all_expected_present": False}),
        (summary, {"known_closed_dates": (D,)}),
    ],
)
def test_closed_records_reject_wrong_types_ranges_or_cross_field_facts(
    factory, changes
):
    with pytest.raises((ValueError, TypeError)):
        replace(factory(), **changes)


def test_fragment_cross_day_code_order_does_not_invent_a_global_code_order():
    cross_day = fragment(maximum=NEXT, first="600000.SH", last="000001.SZ")
    assert cross_day.first_code > cross_day.last_code
    with pytest.raises(ValueError, match="逆序"):
        replace(cross_day, max_trade_date=D)
    with pytest.raises(ValueError, match="首尾"):
        replace(cross_day, min_trade_date=NEXT, max_trade_date=D)
    with pytest.raises(ValueError, match="空片段"):
        replace(cross_day, row_count=0)


def test_source_complete_empty_requires_real_empty_shape_but_not_file_audits():
    empty = replace(
        source_complete(),
        approved_rows=0,
        actual_rows=0,
        fragments=(),
        source_empty=True,
        close_reason="eof",
        next_trade_date=None,
        date_content_sha256=sha256(b"").hexdigest(),
    )
    assert (
        m.parse_stk_factor_pro_record(
            type(empty), m.stk_factor_pro_record_to_dict(empty)
        )
        == empty
    )
    for change in (
        {"next_trade_date": NEXT},
        {"date_content_sha256": SHA},
        {"source_empty": False},
    ):
        with pytest.raises(ValueError):
            replace(empty, **change)
    assert m.StkFactorProBootstrapDateResult(D, SHA, None, None, None).raw_audit is None


def test_fragment_month_and_attempt_ownership_are_not_inferred_from_file_existence():
    record = source_complete()
    outside = fragment(minimum=date(2026, 9, 30))
    with pytest.raises(ValueError, match="本日的片段"):
        replace(
            record, fragments=(m.StkFactorProBootstrapFragmentRef(1, ATTEMPT, outside),)
        )
    valid = m.StkFactorProBootstrapMonthResult(
        month(), ATTEMPT, 1, (fragment(),), (D,), (NEXT,), (audit(), audit("silver"))
    )
    with pytest.raises(ValueError, match="attempt/编号"):
        replace(valid, attempt_id="d" * 32)
    with pytest.raises(ValueError, match="升序唯一"):
        replace(valid, file_audits=(audit(), audit()))
    with pytest.raises(ValueError, match="日期/月"):
        replace(valid, fragments=(outside,))


def test_fixed_source_sample_does_not_inherit_the_diagnostic_twenty_code_limit():
    codes = tuple(f"{number:06d}.SZ" for number in range(1, 22))
    sample = replace(
        source_sample(), sample_codes=codes, row_limit=21, returned_rows=21
    )
    assert sample.sample_codes == codes
    with pytest.raises(ValueError):
        replace(sample, sample_codes=tuple(reversed(codes)))


def test_original_empty_source_can_later_have_real_supplement_without_rewriting_import():
    current = current_publication()
    updated = replace(
        date_coverage(), source_rows=0, source_empty=True, current_publication=current
    )
    assert updated.source_rows == 0 and updated.raw_rows == updated.silver_rows == 1
    assert updated.source_empty
    with pytest.raises(ValueError, match="原导入"):
        replace(updated, current_publication=None)
    with pytest.raises(ValueError, match="日期/文件"):
        replace(updated, current_publication=replace(current, trade_date=NEXT))


def test_coverage_unknown_does_not_smuggle_counts_and_gap_requires_exact_ref():
    unknown = replace(
        date_coverage(),
        is_open=None,
        unknown_input_kinds=("calendar",),
        expected_count=None,
        actual_count=None,
        matched_count=None,
        missing_count=None,
        extra_count=None,
        coverage_complete=None,
    )
    assert unknown.coverage_complete is None
    with pytest.raises(ValueError, match="混入"):
        replace(unknown, missing_count=0)
    gap = replace(
        date_coverage(),
        expected_count=2,
        missing_count=1,
        coverage_complete=False,
        missing_codes_ref=m.StkFactorProBootstrapCodesRef(
            f"coverage/{D}/input={SHA}/missing-codes.parquet", SHA, 1
        ),
        missing_sample_codes=("600000.SH",),
    )
    assert gap.actual_count == 1 and gap.expected_count == 2
    with pytest.raises(ValueError, match="差集引用"):
        replace(gap, missing_codes_ref=replace(gap.missing_codes_ref, row_count=2))


def test_summary_keeps_original_transfer_totals_and_current_supplement_totals_separate():
    updated = replace(summary(), current_raw_rows=2, current_silver_rows=2)
    assert updated.verified_source_rows == 1 and updated.current_raw_rows == 2
    partial = replace(
        summary(),
        imported_dates=(),
        import_pending_dates=(D,),
        known_coverage_dates=(),
        coverage_unknown_dates=((D, (), "尚无完整导入事实"),),
        verified_source_rows=0,
        verified_raw_rows=0,
        verified_silver_rows=0,
        current_raw_rows=None,
        current_silver_rows=None,
        date_result_digests=(),
        expected_count_known_dates=0,
        actual_count_known_dates=0,
        matched_count_known_dates=0,
        all_coverage_determined=False,
        total_missing_count=None,
        all_expected_present=None,
    )
    assert not partial.all_coverage_determined and partial.total_missing_count is None
    with pytest.raises(ValueError):
        replace(partial, current_raw_rows=0, current_silver_rows=0)


def test_identity_and_query_digests_follow_literal_lld_projections():
    identity_projection = {
        "host": "approved-host",
        "port": 5432,
        "database": "prod_raw",
        "schema": "raw_tushare",
        "table": "stk_factor_pro",
        "columns": [list(item) for item in SOURCE_SCHEMA],
        "contract_content_digest": SHA,
    }
    identity_sha = content_digest(
        {
            "record_kind": "stk_factor_pro.bootstrap_source_identity",
            "record_version": 1,
            "value": identity_projection,
        }
    )
    assert (
        m.stk_factor_pro_bootstrap_source_identity_digest(source_identity())
        == identity_sha
    )
    query_projection = {
        "approval_digest": SHA,
        "source_identity_digest": identity_sha,
        "contract_content_digest": SHA,
        "source_cutoff_trade_date": "2026-10-16",
        "month_start": "2026-10-15",
        "month_end_exclusive": "2026-10-17",
        "selected_dates": ["2026-10-15", "2026-10-16"],
        "row_upper_bound": 3,
    }
    expected = content_digest(
        {
            "record_kind": "stk_factor_pro.bootstrap_query",
            "record_version": 1,
            "value": query_projection,
        }
    )
    assert (
        m.stk_factor_pro_bootstrap_query_digest(approval(), SHA, month(), (D, NEXT))
        == expected
    )


def test_fragment_and_complete_digests_bind_traceability_but_ignore_completion_time():
    record = source_complete()
    fragment_projection = {
        "relative_path": f"source/month=2026-10/attempt_id={ATTEMPT}/fragment-000001.parquet",
        "file_sha256": SHA,
        "content_sha256": SHA,
        "schema_content_digest": m.stk_factor_pro_schema_digest("raw"),
        "row_count": 1,
        "observed_schema": [list(item) for item in expected_schema("raw")],
        "min_trade_date": "2026-10-15",
        "max_trade_date": "2026-10-15",
        "first_code": "000001.SZ",
        "last_code": "000001.SZ",
    }
    manifest = content_digest(
        {
            "record_kind": "stk_factor_pro.bootstrap_fragments",
            "record_version": 1,
            "value": [
                {
                    "fragment_no": 1,
                    "attempt_id": ATTEMPT,
                    "fragment": fragment_projection,
                }
            ],
        }
    )
    assert m.fragments_manifest_digest(record.fragments) == manifest
    projection = {
        "record_version": 1,
        "operation_id": "operation-a",
        "approval_digest": SHA,
        "source_identity_digest": approval().source_identity_digest,
        "contract_content_digest": SHA,
        "source_cutoff_trade_date": "2026-10-16",
        "month_start": "2026-10-15",
        "month_end_exclusive": "2026-10-17",
        "attempt_id": ATTEMPT,
        "query_scope_digest": record.query_scope_digest,
        "selected_dates": ["2026-10-15", "2026-10-16"],
        "row_upper_bound": 3,
        "trade_date": "2026-10-15",
        "approved_rows": 1,
        "actual_rows": 1,
        "fragments_manifest_digest": manifest,
        "schema_content_digest": m.stk_factor_pro_schema_digest("raw"),
        "date_content_sha256": SHA,
        "date_content_version": 1,
        "close_reason": "next_date",
        "next_trade_date": "2026-10-16",
        "source_empty": False,
    }
    expected = content_digest(
        {
            "record_kind": "stk_factor_pro.bootstrap_source_complete",
            "record_version": 1,
            "value": projection,
        }
    )
    assert m.stk_factor_pro_bootstrap_source_complete_digest(record) == expected
    assert (
        m.stk_factor_pro_bootstrap_source_complete_digest(
            replace(
                record,
                completed_at=NOW + timedelta(minutes=1),
                source_complete_digest=OTHER,
            )
        )
        == expected
    )
    assert (
        m.stk_factor_pro_bootstrap_source_complete_digest(
            replace(record, approved_rows=2, actual_rows=2)
        )
        != expected
    )


def test_intent_digest_has_exact_projection_and_time_does_not_change_identity():
    record = intent()
    projection = {
        "operation_id": "operation-a",
        "approval_digest": SHA,
        "trade_date": "2026-10-15",
        "layer": "raw",
        "source_complete_digest": SHA,
        "raw_file_sha256": None,
        "mode": "replace",
        "prior_file_sha256": None,
        "candidate": {
            "relative_path": "candidates/2026-10-15/raw/part-000.parquet",
            "file_sha256": SHA,
            "content_sha256": SHA,
            "schema_content_digest": m.stk_factor_pro_schema_digest("raw"),
            "row_count": 1,
            "observed_schema": [list(item) for item in expected_schema("raw")],
            "min_trade_date": "2026-10-15",
            "max_trade_date": "2026-10-15",
            "first_code": "000001.SZ",
            "last_code": "000001.SZ",
        },
        "expected_file_sha256": SHA,
    }
    expected = content_digest(
        {
            "record_kind": "stk_factor_pro.bootstrap_publication_intent",
            "record_version": 1,
            "value": projection,
        }
    )
    assert m.stk_factor_pro_bootstrap_intent_digest(record) == expected
    assert (
        m.stk_factor_pro_bootstrap_intent_digest(
            replace(record, created_at=NOW + timedelta(seconds=1))
        )
        == expected
    )


def test_month_and_date_basis_digests_use_separate_literal_projections():
    refs = basis_files()
    encoded_basis = [
        {
            "kind": kind,
            "trade_date": "2026-10-15" if kind == "suspend" else None,
            "file_sha256": SHA,
            "schema_content_digest": SHA,
            "row_count": 1,
            "valid": True,
        }
        for kind in ("calendar", "identity", "lifecycle", "suspend")
    ]
    month_projection = {
        "operation_id": "operation-a",
        "approval_digest": SHA,
        "month_start": "2026-10-15",
        "month_end_exclusive": "2026-10-17",
        "natural_dates": ["2026-10-15", "2026-10-16"],
        "open_dates": ["2026-10-15", "2026-10-16"],
        "closed_dates": [],
        "calendar_unknown_dates": [],
        "basis_files": encoded_basis,
    }
    actual_month = m.stk_factor_pro_bootstrap_month_basis_digest(
        operation_id="operation-a",
        approval_digest=SHA,
        month=month(),
        natural_dates=(D, NEXT),
        open_dates=(D, NEXT),
        closed_dates=(),
        calendar_unknown_dates=(),
        basis_files=refs,
    )
    assert actual_month == content_digest(
        {
            "record_kind": "stk_factor_pro.bootstrap_month_basis",
            "record_version": 1,
            "value": month_projection,
        }
    )
    date_projection = {
        "operation_id": "operation-a",
        "approval_digest": SHA,
        "trade_date": "2026-10-15",
        "is_open": True,
        "source_complete_digest": SHA,
        "source_rows": 1,
        "raw_file_sha256": SHA,
        "silver_file_sha256": SHA,
        "source_empty": False,
        "basis_files": encoded_basis,
    }
    actual_date = m.stk_factor_pro_bootstrap_date_coverage_input_digest(
        operation_id="operation-a",
        approval_digest=SHA,
        trade_date=D,
        is_open=True,
        source_complete_digest=SHA,
        source_rows=1,
        raw_file_sha256=SHA,
        silver_file_sha256=SHA,
        source_empty=False,
        basis_files=refs,
    )
    assert actual_date == content_digest(
        {
            "record_kind": "stk_factor_pro.bootstrap_date_coverage",
            "record_version": 1,
            "value": date_projection,
        }
    )
    assert actual_date != actual_month


def test_codec_strict_json_scalar_and_day_history_phase_remain_unchanged():
    encoded = m.stk_factor_pro_record_to_dict(source_complete())
    for key, value in (
        ("actual_rows", True),
        ("trade_date", "20261015"),
        ("completed_at", "2026-10-16T19:00:00+08:00"),
    ):
        with pytest.raises(ValueError):
            m.parse_stk_factor_pro_record(
                type(source_complete()), {**encoded, key: value}
            )
    assert m.StkFactorProPhase == m.Literal["day", "history"]
    assert len(m.STK_FACTOR_PRO_ACTIVE_RUN_STATUSES) == 5
