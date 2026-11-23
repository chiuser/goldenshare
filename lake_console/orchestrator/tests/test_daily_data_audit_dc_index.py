"""Isolated native events using the existing DC check and Tushare field contracts."""

from datetime import date, datetime, timedelta
from functools import partial

import dagster as dg
import duckdb
import pytest
from dagster._core.remote_origin import (
    RegisteredCodeLocationOrigin,
    RemoteRepositoryOrigin,
)

from orchestrator.defs.daily_data_audit import board_jobs, dc_index_review, jobs
from orchestrator.defs.daily_data_audit.evidence import read_summary
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    build_dc_board_tushare_source_snapshot,
)
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.contracts import CONTRACTS
from orchestrator.tushare_download.dataset_transport_mapping import (
    BINDINGS,
    DatasetTransportMapping,
)
from orchestrator.tushare_download.download_api import _build_downloader
from orchestrator.tushare_download.download_errors import DownloadErrorCode
from orchestrator.tushare_download.download_models import AttemptFailure
from tests.tushare_download.fixtures import FakeClock, ScriptTransport

BASE = date(2026, 11, 19)
DAY = date(2026, 11, 20)
AFTER_WEEKEND = date(2026, 11, 23)
CONCEPT = "概念板块"
BASE_BOARDS = [
    {"category": "行业板块", "code": "BK0001.DC", "name": "制造"},
    {"category": CONCEPT, "code": "BK0002.DC", "name": "示例旧概念"},
    {"category": "地域板块", "code": "BK0003.DC", "name": "浙江"},
]
NEW_BOARDS = [
    BASE_BOARDS[0],
    BASE_BOARDS[2],
    {"category": CONCEPT, "code": "BK0004.DC", "name": "示例新概念"},
]


def _raw_day(instance, day, *, boards=None, fingerprint=None, passed=True):
    partitions = dg.StaticPartitionsDefinition([day.isoformat()])

    @dg.asset(name="raw_tushare_dc_index", partitions_def=partitions)
    def raw():
        fields = (
            {"goldenshare/tushare_source_fingerprint": fingerprint}
            if fingerprint
            else {}
        )
        return dg.MaterializeResult(metadata=fields)

    @dg.asset_check(
        asset=raw, name="raw_tushare_dc_index_core_check", partitions_def=partitions
    )
    def check():
        fields = (
            {"goldenshare/board_classification_codes": dg.MetadataValue.json(boards)}
            if boards is not None
            else {}
        )
        return dg.AssetCheckResult(passed=passed, metadata=fields)

    return dg.materialize(
        [raw, check],
        instance=instance,
        partition_key=day.isoformat(),
    ).run_id


def _parquet(root, connection, path_builder, day, rows, fields):
    path = path_builder(root, day.isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    column_types = {
        "pct_change": "DOUBLE",
        "leading_pct": "DOUBLE",
        "total_mv": "DOUBLE",
        "turnover_rate": "DOUBLE",
        "up_num": "BIGINT",
        "down_num": "BIGINT",
        "open": "DOUBLE",
        "high": "DOUBLE",
        "low": "DOUBLE",
        "close": "DOUBLE",
        "pre_close": "DOUBLE",
        "change": "DOUBLE",
        "vol": "DOUBLE",
        "amount": "DOUBLE",
        "pct_chg": "DOUBLE",
        "swing": "DOUBLE",
        "volume_ratio": "DOUBLE",
        "turnover_rate_f": "DOUBLE",
        "pe": "DOUBLE",
        "pb": "DOUBLE",
    }
    columns = ", ".join(
        f'"{field}" {column_types.get(field, "VARCHAR")}' for field in fields
    )
    connection.execute(f"CREATE OR REPLACE TABLE source_rows ({columns})")
    marks = ", ".join("?" for _ in fields)
    connection.executemany(
        f"INSERT INTO source_rows VALUES ({marks})",
        [[row.get(field) for field in fields] for row in rows],
    )
    connection.execute("COPY source_rows TO ? (FORMAT PARQUET)", [str(path)])


def _history_files(root, day, boards, *, wrong_fingerprint=False):
    day_key = day.strftime("%Y%m%d")
    index_rows = [
        {
            "idx_type": b["category"],
            "ts_code": b["code"],
            "name": b["name"],
            "trade_date": day_key,
        }
        for b in boards
    ]
    daily_rows = [
        {
            "category": b["category"],
            "ts_code": b["code"],
            "name": b["name"],
            "trade_date": day_key,
        }
        for b in boards
    ]
    # Independent expectations are the literal board lists. Use the existing production
    # publisher's fingerprint to create the native release metadata for those records.
    fingerprint = build_dc_board_tushare_source_snapshot(
        trade_date=day.isoformat(),
        index_rows=index_rows,
        daily_rows=daily_rows,
    ).source_fingerprint
    with duckdb.connect() as connection:
        # Historic files may store ISO DATE values, which normalize to the source's YYYYMMDD.
        _parquet(
            root,
            connection,
            raw_dc_index_path,
            day,
            [{**row, "trade_date": day.isoformat()} for row in index_rows],
            DC_INDEX_FIELDS,
        )
        _parquet(root, connection, raw_dc_daily_path, day, daily_rows, DC_DAILY_FIELDS)
    return "fingerprint-no-longer-matches" if wrong_fingerprint else fingerprint


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    calendar = silver_trade_calendar_path(root)
    calendar.parent.mkdir(parents=True)
    with duckdb.connect() as connection:
        connection.execute(
            """COPY (SELECT * FROM (VALUES
               ('SSE', DATE '2026-11-20', true, DATE '2026-11-19'),
               ('SSE', DATE '2026-11-21', false, DATE '2026-11-20'),
               ('SSE', DATE '2026-11-23', true, DATE '2026-11-20')
            ) AS calendar(exchange, trade_date, is_open, pretrade_date)) TO ? (FORMAT PARQUET)""",
            [str(calendar)],
        )
    monkeypatch.setattr(dc_index_review, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(
        dc_index_review,
        "connect_configured_duckdb",
        partial(
            connect_configured_duckdb, DuckDBConnectionSettings(temp_directory=tmp_path)
        ),
    )
    monkeypatch.setattr(board_jobs, "sleep", lambda _: None)
    monkeypatch.setattr(
        board_jobs.TushareDownloader,
        "load",
        lambda: pytest.fail("unexpected source request"),
    )
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    with dg.instance_for_test(temp_dir=str(instance_dir)) as instance:
        yield instance, root


def _confirm(instance, day, review_version=None, *, historical=False):
    return board_jobs.daily_data_audit_board_confirm_job.execute_in_process(
        instance=instance,
        raise_on_error=False,
        run_config={
            "ops": {
                "save_dc_index_standard": {
                    "config": {
                        "business_date": day.isoformat(),
                        "review_version": review_version,
                        "requested_by": "operator",
                        "use_history": historical,
                    }
                }
            }
        },
    )


def _baseline(instance, root):
    fingerprint = _history_files(root, BASE, BASE_BOARDS)
    _raw_day(instance, BASE, fingerprint=fingerprint)
    result = _confirm(instance, BASE, historical=True)
    assert result.success, "\n".join(
        event.event_specific_data.error.to_string()
        for event in result.get_step_failure_events()
    )
    return dc_index_review.read_dc_index_standard(instance, BASE, run_id=result.run_id)


def _get_review(instance, day=DAY, previous=BASE):
    return dc_index_review.read_board_review(
        instance, day, previous_trade_date=previous
    )


def _recheck(instance, version, *, retry=None, deadline=None):
    deadline = deadline or datetime.now(dc_index_review.SHANGHAI) + timedelta(
        minutes=10
    )
    return board_jobs.daily_data_audit_board_recheck_job.execute_in_process(
        instance=instance,
        raise_on_error=False,
        run_config={
            "ops": {
                "recheck_dc_index": {
                    "config": {
                        "business_date": DAY.isoformat(),
                        "review_version": version,
                        "retry_run_id": retry,
                        "deadline": deadline.isoformat(),
                    }
                }
            }
        },
    )


def _use_source(monkeypatch, responder):
    calls = []
    clock = FakeClock()
    downloader = _build_downloader(
        ConfigurationSnapshot("isolated-token", "http://127.0.0.1:1"),
        ContractRegistry(CONTRACTS),
        DatasetTransportMapping(BINDINGS),
        lambda binding, current_clock: ScriptTransport(responder, calls),
        clock,
        clock.sleep,
    )
    monkeypatch.setattr(board_jobs.TushareDownloader, "load", lambda: downloader)
    return calls


def test_legacy_baseline_and_unchanged_daily_copy_are_native_and_metadata_only(
    isolated, monkeypatch
):
    instance, root = isolated
    baseline = _baseline(instance, root)
    assert sorted(baseline["boards"], key=lambda board: board["code"]) == BASE_BOARDS
    assert baseline["reference_version"] is None
    assert baseline["requested_by"] == "operator"
    assert (
        instance.get_run_by_id(baseline["version"]).tags["audit/business_date"]
        == "2026-11-19"
    )
    monkeypatch.setattr(
        dc_index_review,
        "_read_historical_boards",
        lambda *args: pytest.fail(
            "metadata-only path must never open historical board files"
        ),
    )
    assert _get_review(instance, BASE, None)["standard"] == baseline
    renamed = [{**b, "name": "更新名称"} for b in BASE_BOARDS]
    raw_run = _raw_day(instance, DAY, boards=renamed)
    review = _get_review(instance)
    assert review["added"] == review["removed"] == []
    assert review["can_confirm"]
    result = _confirm(instance, DAY, review["review_version"])
    assert result.success
    standard = dc_index_review.read_dc_index_standard(instance, DAY)
    assert standard["version"] == result.run_id
    assert standard["reference_version"] == baseline["version"]
    assert standard["raw_run_id"] == raw_run
    assert sorted(standard["boards"], key=lambda board: board["code"]) == renamed
    assert _get_review(instance)["state"] == "ready"
    assert not _confirm(instance, DAY, review["review_version"]).success
    assert dc_index_review.read_dc_index_standard(instance, DAY) == standard


def test_history_needs_same_fingerprint_and_preceding_trading_day(isolated):
    instance, root = isolated
    _baseline(instance, root)
    fingerprint = _history_files(root, DAY, BASE_BOARDS, wrong_fingerprint=True)
    _raw_day(instance, DAY, fingerprint=fingerprint)
    assert not _confirm(instance, DAY, historical=True).success
    after_fingerprint = _history_files(root, AFTER_WEEKEND, BASE_BOARDS)
    _raw_day(instance, AFTER_WEEKEND, fingerprint=after_fingerprint)
    assert not _confirm(instance, AFTER_WEEKEND, historical=True).success
    assert _get_review(instance, AFTER_WEEKEND, DAY)["state"] == "reference_missing"
    _raw_day(instance, DAY, fingerprint=_history_files(root, DAY, BASE_BOARDS))
    assert _confirm(instance, DAY, historical=True).success
    assert _confirm(instance, AFTER_WEEKEND, historical=True).success
    assert _get_review(instance, AFTER_WEEKEND, DAY)["state"] == "ready"


@pytest.mark.parametrize(
    "boards",
    [
        NEW_BOARDS,
        [*BASE_BOARDS, {"category": "行业板块", "code": "BK0010.DC", "name": "新行业"}],
    ],
    ids=["concept-change", "industry-change"],
)
def test_history_with_list_changes_requires_explicit_review_version(isolated, boards, monkeypatch):
    instance, root = isolated
    baseline = _baseline(instance, root)
    fingerprint = _history_files(root, DAY, boards)
    raw_run = _raw_day(instance, DAY, fingerprint=fingerprint)

    monkeypatch.setattr(jobs, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(jobs, "read_calendar", lambda *_: {BASE: True, DAY: True})

    def read_candidate(use_history):
        assert jobs.daily_data_audit_summary_job.execute_in_process(
            instance=instance, run_config={"ops": {"generate_data_audit_summary": {"config": {
                "business_date": DAY.isoformat(), "use_board_history": use_history,
            }}}},
        ).success
        return next(
            row["board_review"] for row in read_summary(instance, DAY)["rows"]
            if row["scope"]["asset_key"] == "raw_tushare_dc_index"
        )

    assert read_candidate(False)["review_version"] is None
    review = read_candidate(True)
    version = review["review_version"]
    assert version and review["used_history"] and (review["added"] or review["removed"])
    assert dc_index_review.read_board_review(
        instance, DAY, previous_trade_date=BASE, historical_candidate=review,
    )["review_version"] == version
    assert not _confirm(instance, DAY, historical=True).success
    assert dc_index_review.read_dc_index_standard(instance, DAY) is None
    assert not _confirm(instance, DAY, "stale-version", historical=True).success

    confirmed = _confirm(instance, DAY, version, historical=True)
    assert confirmed.success
    standard = dc_index_review.read_dc_index_standard(instance, DAY)
    assert standard["raw_run_id"] == raw_run
    assert standard["reference_version"] == baseline["version"]
    assert standard["review_version"] == version


def test_old_check_does_not_prove_a_replaced_raw_publication(isolated):
    instance, root = isolated
    _baseline(instance, root)
    _raw_day(instance, DAY, boards=BASE_BOARDS)
    stale = _get_review(instance)
    _raw_day(instance, DAY, boards=NEW_BOARDS, passed=False)
    assert _get_review(instance)["review_version"] is None
    assert not _confirm(instance, DAY, stale["review_version"]).success


def test_source_recheck_only_concept_deltas_and_retry_failed_interface(
    isolated, monkeypatch
):
    instance, root = isolated
    _baseline(instance, root)
    additional_industry = {
        "category": "行业板块",
        "code": "BK0010.DC",
        "name": "新行业",
    }
    _raw_day(instance, DAY, boards=[*NEW_BOARDS, additional_industry])
    review = _get_review(instance)
    assert {b["code"] for b in review["added"]} == {"BK0004.DC", "BK0010.DC"}
    assert [b["code"] for b in review["removed"]] == ["BK0002.DC"]
    version = review["review_version"]

    def respond(request, attempt):
        params = dict(request.params)
        assert params["trade_date"] == "20261120"
        assert params["offset"] == 0 and params["limit"] == 5000
        assert params["ts_code"] in {"BK0002.DC", "BK0004.DC"}
        if request.api_name == "dc_index":
            assert params["idx_type"] == CONCEPT
            assert {"trade_date", "ts_code", "name", "idx_type"} <= set(request.fields)
            if params["ts_code"] == "BK0002.DC":
                values = {
                    "trade_date": "20261120",
                    "ts_code": "BK0002.DC",
                    "name": "示例旧概念",
                    "idx_type": CONCEPT,
                }
                return (tuple(values.get(field) for field in request.fields),)
        elif params["ts_code"] == "BK0004.DC":
            assert request.fields == ("trade_date", "ts_code", "con_code", "name")
            return AttemptFailure(DownloadErrorCode.PERMISSION_OR_PARAMETER)
        return ()

    calls = _use_source(monkeypatch, respond)
    run = _recheck(instance, version)
    assert run.success
    assert len(calls) == 4
    result = dc_index_review.read_dc_index_recheck(
        instance, DAY, version, run_id=run.run_id
    )
    assert result["has_confirmed_gap"]
    old, new = result["results"]
    assert old["confirmed_gap"] and old["member"]["status"] == "not_returned"
    assert new["classification"]["status"] == "not_returned"
    assert new["member"]["status"] == "failed"
    assert not _get_review(instance)["can_confirm"]
    assert not _confirm(instance, DAY, version).success

    calls = _use_source(
        monkeypatch,
        lambda request, attempt: (("20261120", "BK0004.DC", "600001.SH", "成分股"),),
    )
    retry = _recheck(instance, version, retry=run.run_id)
    assert retry.success
    assert [(req.api_name, dict(req.params)["ts_code"]) for req in calls] == [
        ("dc_member", "BK0004.DC")
    ]
    retried = dc_index_review.read_dc_index_recheck(instance, DAY, version)
    assert retried["results"][0] == old
    assert retried["results"][1]["classification"] == new["classification"]
    assert retried["results"][1]["member"]["count"] == 1
    assert retried["has_confirmed_gap"]
    assert not _confirm(instance, DAY, version).success

    _raw_day(instance, DAY, boards=[*BASE_BOARDS, NEW_BOARDS[-1]])
    fixed = _get_review(instance)
    assert fixed["review_version"] != version
    assert fixed["can_confirm"] and fixed["recheck"] is None
    assert not _confirm(instance, DAY, version).success
    assert _confirm(instance, DAY, fixed["review_version"]).success


@pytest.mark.parametrize("retry_failed_only", [False, True], ids=["fresh", "retry"])
def test_recheck_clears_gap_only_with_new_classification_evidence(
    isolated, monkeypatch, retry_failed_only
):
    instance, root = isolated
    _baseline(instance, root)
    _raw_day(instance, DAY, boards=NEW_BOARDS)
    version = _get_review(instance)["review_version"]

    def source_has_board(request, attempt):
        if (
            request.api_name == "dc_index"
            and dict(request.params)["ts_code"] == "BK0002.DC"
        ):
            fields = {
                "trade_date": "20261120",
                "ts_code": "BK0002.DC",
                "name": "示例旧概念",
                "idx_type": "概念板块",
            }
            return (tuple(fields.get(field) for field in request.fields),)
        return ()

    _use_source(monkeypatch, source_has_board)
    initial = _recheck(instance, version)
    assert initial.success
    earlier = dc_index_review.read_dc_index_recheck(instance, DAY, version)
    proven, _ = earlier["results"]
    assert proven["code"] == "BK0002.DC"
    assert earlier["has_confirmed_gap"]
    assert not _confirm(instance, DAY, version).success

    def source_fails_classification(request, attempt):
        if (
            request.api_name == "dc_index"
            and dict(request.params)["ts_code"] == "BK0002.DC"
        ):
            return AttemptFailure(DownloadErrorCode.PERMISSION_OR_PARAMETER)
        return ()

    _use_source(monkeypatch, source_fails_classification)
    failed = _recheck(instance, version)
    assert failed.success
    after_failure = dc_index_review.read_dc_index_recheck(instance, DAY, version)
    failed_item, _ = after_failure["results"]
    assert after_failure["has_confirmed_gap"]
    assert failed_item["classification"]["status"] == "failed"
    assert (
        failed_item["classification"]["last_successful_result"]
        == proven["classification"]
    )
    assert not _get_review(instance)["can_confirm"]

    calls = _use_source(monkeypatch, lambda request, attempt: ())
    completed = _recheck(
        instance, version, retry=failed.run_id if retry_failed_only else None
    )
    assert completed.success
    if retry_failed_only:
        assert [(req.api_name, dict(req.params)["ts_code"]) for req in calls] == [
            ("dc_index", "BK0002.DC")
        ]
    else:
        assert [req.api_name for req in calls] == ["dc_index", "dc_member"] * 2
    latest = dc_index_review.read_dc_index_recheck(instance, DAY, version)
    item, _ = latest["results"]
    assert item["classification"]["status"] == "not_returned"
    assert "last_successful_result" not in item["classification"]
    if retry_failed_only:
        assert item["member"] == failed_item["member"]
    assert not item["confirmed_gap"] and not latest["has_confirmed_gap"]
    assert _get_review(instance)["can_confirm"]
    assert _confirm(instance, DAY, version).success


def test_expired_queue_request_saves_retryable_results_without_loading_source(isolated):
    instance, root = isolated
    _baseline(instance, root)
    _raw_day(instance, DAY, boards=NEW_BOARDS)
    version = _get_review(instance)["review_version"]
    expired = datetime.now(dc_index_review.SHANGHAI) - timedelta(seconds=1)
    run = _recheck(instance, version, deadline=expired)
    assert run.success
    result = dc_index_review.read_dc_index_recheck(instance, DAY, version)
    assert result["request_count"] == 0
    assert not result["has_confirmed_gap"]
    assert [
        result["results"][i][endpoint]["status"]
        for i in range(2)
        for endpoint in ("classification", "member")
    ] == ["failed"] * 4


def test_request_cap_covers_page_and_retry_attempts(isolated, monkeypatch):
    instance, root = isolated
    _baseline(instance, root)
    _raw_day(instance, DAY, boards=NEW_BOARDS)
    version = _get_review(instance)["review_version"]
    monkeypatch.setattr(board_jobs, "DC_BOARD_MAX_REQUESTS_PER_PARTITION", 2)
    calls = _use_source(
        monkeypatch,
        lambda request, _: (
            AttemptFailure(DownloadErrorCode.RATE_LIMIT)
            if request.api_name == "dc_index"
            else ()
        ),
    )
    run = _recheck(instance, version)
    assert run.success
    result = dc_index_review.read_dc_index_recheck(instance, DAY, version)
    assert [call.api_name for call in calls] == ["dc_index", "dc_index"]
    assert result["request_count"] == 2
    assert result["retry_count"] == 1
    assert result["results"][0]["classification"]["status"] == "failed"


def test_member_pagination_preserves_empty_terminal_page_as_complete(monkeypatch):
    def respond(req, attempt):
        if dict(req.params)["offset"] == 0:
            return tuple(
                ("20261120", "BK0002.DC", f"{number:06}.SH", "示例")
                for number in range(5000)
            )
        return ()

    calls = _use_source(monkeypatch, respond)
    budget = board_jobs._RecheckBudget(
        datetime.now(dc_index_review.SHANGHAI) + timedelta(minutes=2)
    )
    monkeypatch.setattr(board_jobs, "sleep", lambda _: None)
    item = board_jobs._request_source(
        board_jobs.TushareDownloader.load(),
        board_jobs.DC_MEMBER_REVIEW_CONTRACT,
        DAY,
        "BK0002.DC",
        budget,
    )
    assert item["status"] == "success" and item["count"] == 5000
    assert [dict(call.params)["offset"] for call in calls] == [0, 5000]


def test_source_placeholder_is_not_accepted_as_an_effective_board(monkeypatch):
    def respond(request, attempt):
        values = {
            "trade_date": "20261120",
            "ts_code": "BK1675.DC",
            "name": "历史新高",
            "idx_type": "概念板块",
            "leading": "-",
            "pct_change": 0,
        }
        return (tuple(values.get(field) for field in request.fields),)

    _use_source(monkeypatch, respond)
    budget = board_jobs._RecheckBudget(
        datetime.now(dc_index_review.SHANGHAI) + timedelta(minutes=2)
    )
    item = board_jobs._request_source(
        board_jobs.TushareDownloader.load(),
        board_jobs.DC_INDEX_REVIEW_CONTRACT,
        DAY,
        "BK1675.DC",
        budget,
    )
    assert item["status"] == "not_returned" and item["count"] == 0


def test_pending_scope_blocks_repeat_submission(isolated):
    instance, _ = isolated
    job = "daily_data_audit_board_recheck_job"
    run = instance.create_run_for_job(
        board_jobs.daily_data_audit_board_recheck_job,
        status=dg.DagsterRunStatus.QUEUED,
        remote_job_origin=RemoteRepositoryOrigin(
            RegisteredCodeLocationOrigin("isolated"), "repository"
        ).get_job_origin(job),
        run_config={
            "ops": {
                "recheck_dc_index": {
                    "config": {
                        "business_date": "2026-11-20",
                        "review_version": "review-one",
                        "deadline": "2026-11-23T20:00:00+08:00",
                    }
                }
            }
        },
        tags={
            "audit/business_date": "2026-11-20",
            "audit/review_version": "review-one",
        },
    )
    active = dc_index_review.find_active_board_run(instance, DAY, "review-one", job)
    assert active.run_id == run.run_id
    assert (
        dc_index_review.find_active_board_run(instance, DAY, "review-two", job) is None
    )
    assert (
        dc_index_review.find_active_board_run(instance, BASE, "review-one", job) is None
    )
    assert dc_index_review.read_dc_index_recheck(instance, DAY, "review-one") is None


@pytest.mark.parametrize("bad_field", ["business_date", "version", "review_version"])
def test_standard_reader_rejects_mislabeled_native_output(isolated, bad_field):
    instance, _ = isolated

    @dg.op(out=dg.Out(dg.Nothing))
    def fabricated_standard(context):
        context.add_output_metadata(
            {
                "dc_index_standard": dg.MetadataValue.json(
                    {
                        "business_date": DAY.isoformat(),
                        "version": context.run_id,
                        "review_version": "review-one",
                        "boards": BASE_BOARDS,
                        bad_field: "mismatch",
                    }
                ),
            }
        )

    @dg.job(name="daily_data_audit_board_confirm_job")
    def mismatched():
        fabricated_standard()

    run = mismatched.execute_in_process(
        instance=instance,
        tags={
            "audit/business_date": DAY.isoformat(),
            "audit/review_version": "review-one",
        },
    )
    assert run.success
    assert (
        dc_index_review.read_dc_index_standard(instance, DAY, run_id=run.run_id) is None
    )


def test_retry_does_not_start_when_backoff_would_exhaust_deadline(monkeypatch):
    _calls = _use_source(
        monkeypatch,
        lambda request, attempt: AttemptFailure(
            DownloadErrorCode.RATE_LIMIT, retry_after_at=120
        ),
    )
    budget = board_jobs._RecheckBudget(
        datetime.now(dc_index_review.SHANGHAI) + timedelta(minutes=2)
    )
    result = board_jobs._request_source(
        board_jobs.TushareDownloader.load(),
        board_jobs.DC_INDEX_REVIEW_CONTRACT,
        DAY,
        "BK0002.DC",
        budget,
    )
    assert result["status"] == "failed" and "超时" in result["message"]
    assert budget.request_count == len(_calls) == 1
