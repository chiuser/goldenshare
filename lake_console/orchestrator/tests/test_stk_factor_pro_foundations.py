"""First-batch pure foundations; no formal instance, source or Lake writes.

Field expectations come independently from local Tushare doc328. Calendar and
set-count examples below are literal, manually checkable LLD examples.
"""

import ast
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from orchestrator.defs import partitions, paths
from orchestrator.defs.run_contracts import stk_factor_pro as contracts
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STK_FACTOR_PRO_SCHEMA,
    SILVER_STOCK_FACTOR_PRO_SCHEMA,
)
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)
from orchestrator.tushare_download.download_models import (
    DownloadMode,
    DownloadStatus,
    DownloadSummary,
    DownloadUnit,
    OrderingFacts,
    SourceRecord,
    TerminationSummary,
    UnitResult,
    UnitStatistics,
)
from orchestrator.tushare_download.source_contract import SourceKind

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOC = (
    PROJECT_ROOT
    / "docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md"
)
MONDAY = date(2026, 10, 26)
FRIDAY = date(2026, 10, 23)
THURSDAY = date(2026, 10, 22)
CALENDAR = (THURSDAY, FRIDAY, MONDAY)
HASH_A = "a" * 64
HASH_B = "b" * 64


def documented_fields():
    """Read the independent source table, never the implementation's field list."""
    section = SOURCE_DOC.read_text().split("## 输出参数", 1)[1].split("## ", 1)[0]
    result = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells[1] in ("str", "float"):
            result.append((cells[0], cells[1], cells[3]))
    assert len(result) == 261
    assert result[:2] == [
        ("ts_code", "str", "股票代码"),
        ("trade_date", "str", "交易日期"),
    ]
    assert all(source_type == "float" for _, source_type, _ in result[2:])
    return tuple(result)


def expected_schema(layer):
    return tuple(
        (
            name,
            "DATE"
            if layer == "silver" and name == "trade_date"
            else "VARCHAR"
            if source_type == "str"
            else "DOUBLE",
        )
        for name, source_type, _ in documented_fields()
    )


def today_config(**overrides):
    return {
        "execution_day": "2026-10-26",
        "target_trade_date": "2026-10-26",
        "purpose": "today",
        "scheduled_slot": 0,
        **overrides,
    }


def bootstrap_config(**overrides):
    return {
        "execution_day": "2026-10-25",
        "target_trade_date": "2026-10-23",
        "purpose": "bootstrap_supplement",
        "scheduled_slot": None,
        "bootstrap_operation_id": "approved-bootstrap",
        "expected_bootstrap_approval_digest": HASH_A,
        "expected_bootstrap_date_result_digest": HASH_B,
        **overrides,
    }


def parse(config, *, key=None, calendar=CALENDAR):
    return contracts.parse_stk_factor_pro_run_input(
        config,
        key or config["target_trade_date"],
        calendar,
    )


def identity(**overrides):
    return contracts.RunIdentity(
        **{
            "creator_run_id": "run-1",
            "source_run_id": None,
            "execution_day": MONDAY,
            "target_trade_date": MONDAY,
            "previous_trade_date": FRIDAY,
            "purpose": "today",
            "scheduled_slot": 0,
            "submission_no": None,
            "business_attempt": None,
            **overrides,
        }
    )


def comparison(**overrides):
    return contracts.StkFactorProComparison(
        **{
            "expected_rows": 2,
            "actual_rows": 2,
            "missing_key_count": 0,
            "unexpected_key_count": 0,
            "changed_row_count": 0,
            "changed_field_counts": (("open", 0), ("close", 0)),
            **overrides,
        }
    )


def file_audit(**overrides):
    return contracts.StkFactorProFileAudit(
        **{
            "trade_date": MONDAY,
            "layer": "raw",
            "path": Path("/private/tmp/stk-factor-raw.parquet"),
            "file_sha256": HASH_A,
            "observed_schema": expected_schema("raw"),
            "row_count": 2,
            "invalid_key_count": 0,
            "duplicate_key_count": 0,
            "invalid_date_count": 0,
            "invalid_numeric_count": 0,
            "comparison": comparison(),
            "passed": True,
            "diagnostics_path": None,
            **overrides,
        }
    )


def raw_coverage(**overrides):
    return contracts.StkFactorProRawCoverage(
        **{
            "target_trade_date": MONDAY,
            "complete": True,
            "raw_check_passed": True,
            "raw_file_sha256": HASH_A,
            "lifecycle_file_sha256": HASH_B,
            "suspend_file_sha256": HASH_B,
            "identity_file_sha256": HASH_B,
            "expected_count": 2,
            "actual_count": 2,
            "missing_count": 0,
            "missing_sample_codes": (),
            "reason": "complete",
            "raw_materialization_storage_id": 17,
            "raw_check_storage_id": 18,
            "missing_codes_ref": None,
            **overrides,
        }
    )


def target_silver(**overrides):
    return contracts.StkFactorProTargetSilver(
        **{
            "target_trade_date": MONDAY,
            "ready": True,
            "silver_file_sha256": HASH_B,
            "current_raw_file_sha256": HASH_A,
            "source_raw_file_sha256": HASH_A,
            "silver_materialization_storage_id": 21,
            "silver_check_execution_id": 7,
            "reason": "ready",
            **overrides,
        }
    )


def test_source_and_local_schemas_follow_independent_doc328():
    expected = documented_fields()
    assert tuple(field.name for field in STK_FACTOR_PRO_CONTRACT.fields) == tuple(
        name for name, _, _ in expected
    )
    assert tuple(
        field.description for field in STK_FACTOR_PRO_CONTRACT.fields
    ) == tuple(description for _, _, description in expected)
    assert tuple(field.source_kind for field in STK_FACTOR_PRO_CONTRACT.fields) == (
        SourceKind.STRING,
        SourceKind.STRING,
        *((SourceKind.NUMBER,) * 259),
    )
    assert all(field.nullable for field in STK_FACTOR_PRO_CONTRACT.fields[2:])
    for layer, schema in (
        ("raw", RAW_TUSHARE_STK_FACTOR_PRO_SCHEMA),
        ("silver", SILVER_STOCK_FACTOR_PRO_SCHEMA),
    ):
        assert tuple((field.name, field.type) for field in schema) == expected_schema(
            layer
        )
        assert all(field.description for field in schema)
        assert all(
            field.description == description
            for field, (_, _, description) in zip(schema, expected, strict=True)
            if layer == "raw" or field.name != "trade_date"
        )
    assert not {"fetched_at", "api_name", "raw_payload"} & {
        name for name, _, _ in expected
    }
    with pytest.raises(TypeError):
        contracts.STK_FACTOR_PRO_RAW_COLUMN_TYPES["trade_date"] = "DATE"


def test_schema_digest_uses_independent_literal_mapping():
    for layer in ("raw", "silver"):
        # The existing content-digest format tags strings [1,value] and integers
        # [2,decimal-text]. Build that documented representation literally here,
        # without calling canonical_content/content_digest from the implementation.
        payload = {
            "record_kind": [1, "stk_factor_pro.local_schema"],
            "record_version": [2, "1"],
            "value": [
                {"name": [1, name], "type": [1, kind]}
                for name, kind in expected_schema(layer)
            ],
        }
        expected = sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        assert contracts.stk_factor_pro_schema_digest(layer) == expected
    with pytest.raises(ValueError):
        contracts.stk_factor_pro_schema_digest("gold")


def test_run_input_eight_fields_frozen_and_three_purposes():
    value = parse(today_config())
    assert tuple(field.name for field in fields(value)) == (
        "execution_day",
        "target_trade_date",
        "purpose",
        "scheduled_slot",
        "submission_no",
        "bootstrap_operation_id",
        "expected_bootstrap_approval_digest",
        "expected_bootstrap_date_result_digest",
    )
    assert value.execution_day == MONDAY and value.target_trade_date == MONDAY
    with pytest.raises(FrozenInstanceError):
        value.scheduled_slot = 9
    previous = parse(
        today_config(
            purpose="previous_day",
            target_trade_date="2026-10-23",
            submission_no=1,
        )
    )
    assert previous.target_trade_date == FRIDAY
    assert parse(bootstrap_config()).execution_day == date(2026, 10, 25)
    assert parse(today_config(scheduled_slot=9)).scheduled_slot == 9


@pytest.mark.parametrize(
    "value",
    [
        "20261026",
        "2026-1-26",
        "2026-10-2",
        "2026-02-30",
        "2026-10-26T00:00:00",
        "２０２６-１０-２６",
        " 2026-10-26",
        20261026,
        MONDAY,
        datetime(2026, 10, 26, tzinfo=timezone.utc),
        None,
    ],
)
def test_dates_reject_implicit_conversion(value):
    with pytest.raises(ValueError):
        parse(today_config(execution_day=value))


@pytest.mark.parametrize(
    "overrides",
    [
        {"scheduled_slot": True},
        {"scheduled_slot": -1},
        {"scheduled_slot": 10},
        {"scheduled_slot": 0.0},
        {"scheduled_slot": "0"},
        {"scheduled_slot": None},
        {"submission_no": 1},
        {"purpose": "manual_repair"},
        {"bootstrap_operation_id": "other"},
        {"expected_bootstrap_approval_digest": HASH_A},
        {"expected_bootstrap_date_result_digest": HASH_B},
        {"token": "never-read"},
        {"fields": "close"},
        {"limit": 1},
        {"offset": 0},
        {"target_trade_date": "2026-10-23"},
        {"execution_day": "2026-10-25"},
    ],
)
def test_auto_input_rejects_unknown_fields_and_wrong_combinations(overrides):
    with pytest.raises(ValueError):
        parse(today_config(**overrides))


@pytest.mark.parametrize("submission", [None, False, 0, 11, "1", 1.0])
def test_previous_day_requires_real_submission_integer(submission):
    with pytest.raises(ValueError):
        parse(
            today_config(
                purpose="previous_day",
                target_trade_date="2026-10-23",
                submission_no=submission,
            )
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"bootstrap_operation_id": None},
        {"bootstrap_operation_id": "../bad"},
        {"expected_bootstrap_approval_digest": None},
        {"expected_bootstrap_date_result_digest": "A" * 64},
        {"scheduled_slot": 0},
        {"submission_no": 1},
        {"target_trade_date": "2026-10-25"},
    ],
)
def test_bootstrap_requires_complete_authorization_shape(overrides):
    with pytest.raises(ValueError):
        parse(bootstrap_config(**overrides))


def test_input_requires_explicit_slot_valid_calendar_and_partition():
    config = today_config()
    del config["scheduled_slot"]
    with pytest.raises(ValueError):
        parse(config)
    assert contracts.STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA["scheduled_slot"].is_required
    for bad_calendar in (
        (),
        [THURSDAY, FRIDAY, MONDAY],
        (MONDAY, FRIDAY),
        (FRIDAY, FRIDAY),
        (MONDAY,),
    ):
        with pytest.raises(ValueError):
            parse(today_config(), calendar=bad_calendar)
    with pytest.raises(ValueError):
        parse(today_config(), key="2026-10-23")
    with pytest.raises(ValueError):
        parse(
            today_config(
                purpose="previous_day", target_trade_date="2026-10-22", submission_no=1
            )
        )


def test_identity_and_finite_history_reasons():
    contract = contracts.ContractIdentity("stk_factor_pro", "1", HASH_A, "1")
    assert contract.contract_name == "stk_factor_pro"
    for name, version, digest, processing in (
        ("stk_factor_pro@1", "1", HASH_A, "1"),
        ("stk_factor_pro", "2", HASH_A, "1"),
        ("stk_factor_pro", "1", "bad", "1"),
        ("stk_factor_pro", "1", HASH_A, "2"),
    ):
        with pytest.raises(ValueError):
            contracts.ContractIdentity(name, version, digest, processing)
    assert tuple(int(reason) for reason in contracts.HistoryPlanReason) == (
        1,
        2,
        3,
        4,
        5,
        6,
    )
    assert identity().previous_trade_date == FRIDAY
    assert (
        identity(
            purpose="previous_day",
            target_trade_date=FRIDAY,
            previous_trade_date=THURSDAY,
            submission_no=2,
            business_attempt=1,
        ).business_attempt
        == 1
    )
    for overrides in (
        {"creator_run_id": "../bad"},
        {"previous_trade_date": MONDAY},
        {"execution_day": datetime(2026, 10, 26, tzinfo=timezone.utc)},
        {"business_attempt": True},
        {"purpose": "manual_repair"},
        {"target_trade_date": FRIDAY},
    ):
        with pytest.raises(ValueError):
            identity(**overrides)
    assert (
        identity(purpose="manual_repair", scheduled_slot=None).purpose
        == "manual_repair"
    )


def test_day_source_is_current_call_carrier_without_serialized_download_cache():
    # Real downloader model shapes; no transport/session or invented SDK result.
    unit = DownloadUnit(
        1,
        "unit-1",
        "stk_factor_pro",
        "1",
        HASH_A,
        DownloadMode.BY_POINT,
        None,
        "2026-10-26",
        None,
        (),
        (),
    )
    result = UnitResult(
        unit,
        (),
        (),
        (),
        UnitStatistics(1, 0, 1, 1, 1, 0, 0, 0.1, 0, 0.1, 0),
        OrderingFacts("trade_date", "1", 0, 0),
        TerminationSummary(2, True, 1, None),
    )
    summary = DownloadSummary(
        "task-1",
        DownloadStatus.SUCCEEDED,
        1,
        1,
        1,
        0,
        0,
        1,
        0,
        1,
        True,
        0.1,
        None,
        (),
        0,
        None,
        0,
    )
    source = contracts.VerifiedDaySource(
        identity(),
        contracts.ContractIdentity("stk_factor_pro", "1", HASH_A, "1"),
        result,
        summary,
        "stk_factor_pro_day_source",
        HASH_A,
        HASH_B,
    )
    assert source.unit_result is result and source.summary is summary
    # The doc328 MACD field permits negative indicators; a source NULL is kept.
    # Foundation carriers do not impose business cleaning on those values.
    record = SourceRecord(
        ("ts_code", "trade_date", "macd_bfq", "pe"),
        ("000001.SZ", "20261026", Decimal("-1.25"), None),
        0,
    )
    retained = replace(source, unit_result=replace(result, records=(record,)))
    assert retained.unit_result.records[0].values == (
        "000001.SZ",
        "20261026",
        Decimal("-1.25"),
        None,
    )
    with pytest.raises(TypeError):
        replace(source, unit_result={"records": []})
    with pytest.raises(ValueError):
        replace(source, raw_relation="external_relation")


def test_file_check_results_cannot_claim_green_for_inconsistent_evidence():
    assert file_audit().passed
    assert file_audit(
        layer="silver",
        observed_schema=expected_schema("silver"),
    ).passed
    assert not file_audit(duplicate_key_count=1, passed=False).passed
    for overrides in (
        {"duplicate_key_count": 1},
        {"invalid_key_count": True},
        {"row_count": 1},
        {"passed": False},
        {"observed_schema": expected_schema("silver")},
        {"comparison": comparison(expected_rows=3, missing_key_count=1)},
        {
            "comparison": comparison(
                changed_row_count=1, changed_field_counts=(("close", 1),)
            )
        },
    ):
        with pytest.raises(ValueError):
            file_audit(**overrides)
    for overrides in (
        {"actual_rows": True},
        {"missing_key_count": -1},
        {"changed_field_counts": (("trade_date", 1),)},
        {"changed_field_counts": (("close", 1), ("open", 1))},
        {"changed_field_counts": (("open", 0), ("open", 0))},
    ):
        with pytest.raises(ValueError):
            comparison(**overrides)


def test_coverage_distinguishes_file_correctness_missing_and_unknown():
    assert raw_coverage().complete is True
    partial = raw_coverage(
        complete=False,
        expected_count=2,
        actual_count=1,
        missing_count=1,
        missing_sample_codes=("000002.SZ",),
        reason="missing",
    )
    assert partial.raw_check_passed and partial.complete is False
    unknown = raw_coverage(
        complete=None,
        expected_count=None,
        actual_count=None,
        missing_count=None,
        lifecycle_file_sha256=None,
        reason="upstream unavailable",
    )
    assert unknown.complete is None and unknown.expected_count is None
    missing_file = raw_coverage(
        complete=False,
        raw_check_passed=False,
        raw_file_sha256=None,
        raw_materialization_storage_id=None,
        raw_check_storage_id=None,
        actual_count=0,
        missing_count=2,
        missing_sample_codes=("000001.SZ", "000002.SZ"),
    )
    assert missing_file.actual_count == 0
    for overrides in (
        {"actual_count": 0},
        {"expected_count": True},
        {"raw_check_passed": False},
        {"lifecycle_file_sha256": None},
        {"raw_materialization_storage_id": None},
        {"raw_check_storage_id": True},
        {"missing_count": 1},
        {"complete": 1},
        {"missing_sample_codes": ("000002.SZ", "000001.SZ")},
    ):
        with pytest.raises(ValueError):
            raw_coverage(**overrides)


def test_comparison_counts_reject_impossible_row_and_field_combinations():
    # Literal set example: expected {A,B,C}, actual {A,B,D,E}; A/B both change.
    valid = contracts.StkFactorProComparison(3, 4, 1, 2, 2, (("open", 2), ("close", 1)))
    assert valid.changed_row_count == 2 and valid.missing_key_count == 1
    # Omitting zero fields is valid; explicitly retaining zero fields is also valid.
    assert contracts.StkFactorProComparison(1, 1, 0, 0, 0, ()).changed_row_count == 0
    assert (
        contracts.StkFactorProComparison(
            1, 1, 0, 0, 1, (("open", 0), ("close", 1))
        ).changed_row_count
        == 1
    )
    for values in (
        (0, 0, 1, 0, 0, ()),  # One missing key from an empty expected set.
        (1, 1, 0, 2, 0, ()),  # More extra keys than actual rows.
        (2, 1, 0, 0, 0, ()),  # The two sides disagree on matched count.
        (1, 1, 0, 0, 2, (("open", 2),)),  # Two changed rows from only one matched row.
        (2, 2, 0, 0, 1, (("open", 2),)),  # A field changes more often than any row.
        (1, 1, 0, 0, 1, ()),  # A claimed changed row has no changed field.
    ):
        with pytest.raises(ValueError):
            contracts.StkFactorProComparison(*values)


def test_coverage_samples_cannot_exceed_known_missing_or_mapping_counts():
    for value in (
        # Equal sets and successful identity mapping cannot have an unmapped sample.
        (2, 2, 2, 0, 0, 0, 0, ("000001.SZ",), (), "known"),
        # Unknown coverage can retain real mapping diagnostics, but not overcount them.
        (None, None, None, None, None, 1, 0, ("000001.SZ", "000002.SZ"), (), "unknown"),
        (None, None, None, None, None, 0, 1, (), ("000001.SZ", "000002.SZ"), "unknown"),
    ):
        with pytest.raises(ValueError):
            contracts.StkFactorProCoverageCounts(*value)
    with pytest.raises(ValueError):
        raw_coverage(
            complete=False,
            missing_count=1,
            missing_sample_codes=("000001.SZ", "000002.SZ"),
        )
    unknown = contracts.StkFactorProCoverageCounts(
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        ("000001.SZ",),
        ("000002.SZ",),
        "无法取得完整异常计数",
    )
    assert unknown.expected_count is None
    assert (
        raw_coverage(
            complete=False,
            missing_count=1,
            missing_sample_codes=("000001.SZ",),
        ).missing_count
        == 1
    )


def test_coverage_counts_compare_sets_not_just_equal_totals():
    # Expected {A,B}, actual {A,C}: both total2 but one missing and one extra.
    value = contracts.StkFactorProCoverageCounts(2, 2, 1, 1, 1, 0, 0, (), (), "known")
    assert value.missing_count == 1 and value.extra_count == 1
    unknown = contracts.StkFactorProCoverageCounts(
        None,
        None,
        None,
        None,
        None,
        1,
        0,
        ("unmapped",),
        (),
        "identity unavailable",
    )
    assert unknown.actual_count is None
    for overrides in (
        {"expected_count": 3},
        {"matched_count": True},
        {"extra_count": None},
        {"identity_unmapped_count": 1},
        {"identity_ambiguous_count": None},
    ):
        with pytest.raises(ValueError):
            replace(value, **overrides)


def test_silver_readiness_requires_matching_current_raw_and_real_record_ids():
    assert target_silver().ready
    assert not target_silver(
        ready=False,
        silver_file_sha256=None,
        source_raw_file_sha256=None,
        silver_materialization_storage_id=None,
        silver_check_execution_id=None,
        reason="missing",
    ).ready
    for overrides in (
        {"source_raw_file_sha256": HASH_B},
        {"silver_file_sha256": None},
        {"silver_materialization_storage_id": None},
        {"silver_check_execution_id": False},
        {"ready": 1},
    ):
        with pytest.raises(ValueError):
            target_silver(**overrides)


def test_pure_paths_and_dedicated_partition_name(tmp_path):
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    assert paths.raw_stk_factor_pro_path(lake_root, "2026-10-26") == (
        lake_root / "raw/tushare/stk_factor_pro/trade_date=2026-10-26/data.parquet"
    )
    assert paths.silver_stock_factor_pro_path(lake_root, "2026-10-26") == (
        lake_root / "silver/stock_factor_pro/trade_date=2026-10-26/data.parquet"
    )
    run_root = paths.stk_factor_pro_run_staging_root(
        staging_root, "run-1", "2026-10-26"
    )
    assert (
        run_root == staging_root / "stk_factor_pro/trade_date=2026-10-26/run_id=run-1"
    )
    reference = contracts.RecordRef("run-1", "history/plan.json", HASH_A)
    assert paths.stk_factor_pro_record_path(
        run_root, reference, expected_run_id="run-1"
    ) == (run_root / "history/plan.json")
    assert not lake_root.exists() and not staging_root.exists()
    assert (
        partitions.cn_a_stock_factor_pro_trade_days.name
        == "cn_a_stock_factor_pro_trade_days"
    )
    assert (
        partitions.cn_a_stock_factor_pro_trade_days
        is not partitions.cn_a_stock_trade_days
    )
    template = paths.raw_stk_factor_pro_path(Path("data_lake"), "{partition_key}")
    assert "trade_date={partition_key}/data.parquet" in template.as_posix()


@pytest.mark.parametrize(
    "relative",
    [
        "",
        ".",
        "../secret",
        "history/../secret",
        "/private/tmp/outside",
        "history//plan",
        "history/./plan",
        "history\\plan",
        "history/plan/",
        "history/\x00plan",
    ],
)
def test_record_reference_rejects_noncanonical_and_escaping_paths(relative):
    with pytest.raises(ValueError):
        contracts.RecordRef("run-1", relative, HASH_A)


def test_paths_reject_wrong_run_identity_retired_roots_and_day_cache(tmp_path):
    for root in (
        Path("/Volumes/datasource/data_lake"),
        Path("/Volumes/datasource/data_lake/raw/nested"),
        Path("/Volumes/datasource/goldenshare-tushare-lake"),
        Path("/Volumes/datasource/goldenshare-tushare-lake/nested"),
    ):
        with pytest.raises(ValueError):
            paths.stk_factor_pro_run_staging_root(root, "run-1", "2026-10-26")
    for path_function in (
        paths.raw_stk_factor_pro_path,
        paths.silver_stock_factor_pro_path,
    ):
        with pytest.raises(ValueError):
            path_function(
                Path("/Volumes/datasource/goldenshare-tushare-lake"), "2026-10-26"
            )
        with pytest.raises(ValueError):
            path_function(tmp_path, "20261026")
    with pytest.raises(ValueError):
        paths.stk_factor_pro_run_staging_root(tmp_path, "../bad", "2026-10-26")
    run_root = tmp_path / "run_id=run-1"
    for creator, relative, expected in (
        ("run-2", "history/plan.json", "run-1"),
        ("run-1", "history/plan.json", "run-2"),
        ("run-1", "source/day/part.parquet", "run-1"),
    ):
        with pytest.raises(ValueError):
            paths.stk_factor_pro_record_path(
                run_root,
                contracts.RecordRef(creator, relative, HASH_A),
                expected_run_id=expected,
            )


def test_paths_reject_existing_symlink_escape(tmp_path):
    run_root = tmp_path / "staging/run_id=run-1"
    run_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (run_root / "history").symlink_to(outside, target_is_directory=True)
    reference = contracts.RecordRef("run-1", "history/plan.json", HASH_A)
    with pytest.raises(ValueError):
        paths.stk_factor_pro_record_path(run_root, reference, expected_run_id="run-1")
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    (lake_root / "raw").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        paths.raw_stk_factor_pro_path(lake_root, "2026-10-26")


def test_contract_imports_remain_local_and_schema_has_no_second_field_table():
    source = Path(contracts.__file__).read_text()
    tree = ast.parse(source)
    module_imports = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert not any(
        name.startswith(("src.", "qtf.", "wealth.", "prod.")) for name in module_imports
    )
    schema_file = (
        ORCHESTRATOR_ROOT
        / "src/orchestrator/defs/run_contracts/asset_column_schemas.py"
    )
    schema_tree = ast.parse(schema_file.read_text())
    # The two schemas are generated from the source contract, not a copied literal list.
    for node in schema_tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id
            in {
                "RAW_TUSHARE_STK_FACTOR_PRO_SCHEMA",
                "SILVER_STOCK_FACTOR_PRO_SCHEMA",
            }
            for target in node.targets
        ):
            assert "STK_FACTOR_PRO_CONTRACT.fields" in ast.unparse(node.value)


def test_foundation_module_imports_have_no_external_side_effects():
    script = r"""
import importlib
import os
import pathlib
import socket
import dagster
import duckdb
import psycopg2

def forbidden(*args, **kwargs):
    raise AssertionError("foundation import performed external I/O")

# Import dependencies before blocking the capabilities under examination.
# These four modules themselves must not use any of these capabilities.
pathlib.Path.mkdir = forbidden
os.mkdir = forbidden
socket.create_connection = forbidden
socket.socket.connect = forbidden
duckdb.connect = forbidden
psycopg2.connect = forbidden
dagster.DagsterInstance.get = forbidden
dagster.DagsterInstance.add_dynamic_partitions = forbidden
for name in (
    "orchestrator.defs.run_contracts.stk_factor_pro",
    "orchestrator.defs.run_contracts.asset_column_schemas",
    "orchestrator.defs.paths",
    "orchestrator.defs.partitions",
):
    importlib.import_module(name)
print("pure imports passed")
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=ORCHESTRATOR_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "pure imports passed"
