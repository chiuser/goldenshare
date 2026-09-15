import copy
import fcntl
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from orchestrator.defs.bootstrap import daily_basic_history as history
from orchestrator.defs.bootstrap.daily_basic_history_cli import (
    history_parser,
    run_history_cli,
)
from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_TYPES,
    DailyBasicValidationError,
)
from orchestrator.defs.paths import raw_daily_basic_path
from orchestrator.defs.prod_db.daily_basic import (
    DailyBasicHistorySource,
    daily_basic_history_query,
)

DAYS = ["2024-12-31", "2025-01-02"]


def source_evidence():
    return {
        "columns": [
            [
                n,
                "text"
                if n == "ts_code"
                else "date"
                if n == "trade_date"
                else "numeric",
                "NO" if i < 2 else "YES",
                None
                if i < 2
                else int(DAILY_BASIC_TYPES[n].split("(")[1].split(",")[0]),
                None if i < 2 else 4,
            ]
            for i, n in enumerate(DAILY_BASIC_FIELDS)
        ],
        "primary_key": ["ts_code", "trade_date"],
        "indexes": [],
        "explain": [[{"Plan": {"Node Type": "Index Scan"}}]] * 2,
    }


@pytest.fixture
def plan(tmp_path):
    calendar = tmp_path / "calendar.parquet"
    calendar.write_bytes(b"calendar identity fixture")
    return history.make_history_plan(
        start=DAYS[0],
        end=DAYS[-1],
        batch_id="fixture",
        lake_root=tmp_path / "lake",
        staging_root=tmp_path / "staging",
        calendar_path=calendar,
        dates=DAYS,
        source_evidence=source_evidence(),
        cost_evidence={},
        limits={
            "max_source_rows": 50000,
            "max_source_seconds": 60,
            "max_stage_seconds": 60,
            "max_spill_bytes": 100000000,
        },
    )


def rows(code="000001.SZ"):
    return [
        (
            code,
            d.replace("-", ""),
            Decimal("1.2345"),
            None,
            Decimal("-2.0000"),
            *([Decimal(0)] * 13),
        )
        for d in DAYS
    ]


class Source:
    def __init__(self, values=None, fail_at=None):
        self.values = rows() if values is None else values
        self.calls = 0
        self.fail_at = fail_at

    def inspect(self, start, end):
        return source_evidence()

    def fetch_page(self, start, end, last):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("source disconnected")
        return [
            r
            for r in self.values
            if last is None
            or (r[0], f"{r[1][:4]}-{r[1][4:6]}-{r[1][6:]}") > tuple(last)
        ][: history.HISTORY_BATCH_SIZE]


def prepared(plan):
    history.export_daily_basic_history(plan, Source(), apply=True)
    history.build_daily_basic_history(plan, apply=True)
    return history.audit_daily_basic_history(plan)


def test_roundtrip_build_audit_promote_idempotence(plan):
    audit = prepared(plan)
    assert audit["rows"] == 2
    assert len(audit["files"]) == 2
    result = history.promote_daily_basic_history(plan, audit, apply=True)
    assert len(result["files"]) == 2
    again = history.promote_daily_basic_history(plan, audit, apply=True)
    assert result["files"] == again["files"]
    assert history.export_daily_basic_history(plan, Source(), apply=True)["frozen"]
    with history._connection(plan, readonly=True) as connection:
        path = raw_daily_basic_path(Path(plan["lake_root"]), DAYS[0])
        row = connection.execute(
            "SELECT close, turnover_rate, turnover_rate_f FROM read_parquet(?, hive_partitioning=false)",
            [str(path)],
        ).fetchone()
        assert row == (Decimal("1.2345"), None, Decimal("-2.0000"))
        assert [
            (r[0], r[1])
            for r in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                [str(path)],
            ).fetchall()
        ] == list(DAILY_BASIC_TYPES.items())


def test_plan_and_unapproved_export_write_nothing(plan):
    assert not Path(plan["staging_root"]).exists()
    with pytest.raises(DailyBasicValidationError, match="apply_required"):
        history.export_daily_basic_history(plan, Source())
    plan = history.seal_history_report({**plan, "limits": None})
    with pytest.raises(DailyBasicValidationError, match="budget_not_frozen"):
        history.export_daily_basic_history(plan, Source(), apply=True)
    assert not Path(plan["staging_root"]).exists()


@pytest.mark.parametrize("mutation", ["add_before", "delete", "change"])
def test_resume_rechecks_prior_keys(plan, mutation):
    with pytest.raises(RuntimeError):
        history.export_daily_basic_history(plan, Source(fail_at=2), apply=True)
    modified = rows()
    if mutation == "add_before":
        modified = rows("000000.SZ") + modified
    elif mutation == "delete":
        modified = modified[:1]
    else:
        modified[0] = (*modified[0][:2], Decimal(2), *modified[0][3:])
    with pytest.raises(DailyBasicValidationError, match="source_changed"):
        history.export_daily_basic_history(plan, Source(modified), apply=True)
    assert not Path(plan["lake_root"]).exists()


def test_resume_and_checkpoint_corruption(plan):
    with pytest.raises(RuntimeError):
        history.export_daily_basic_history(plan, Source(fail_at=2), apply=True)
    state = history.export_daily_basic_history(plan, Source(), apply=True)
    assert state["rows"] == 2
    Path(state["chunks"][0]["path"]).write_bytes(b"corrupt")
    with pytest.raises(DailyBasicValidationError, match="chunk_changed"):
        history.export_daily_basic_history(plan, Source(), apply=True)


@pytest.mark.parametrize(
    "value", [Decimal("1.00001"), Decimal("1e20"), float("nan"), Decimal("Infinity")]
)
def test_no_precision_loss(plan, value):
    bad = rows()
    bad[0] = (*bad[0][:2], value, *bad[0][3:])
    with pytest.raises(DailyBasicValidationError):
        history.export_daily_basic_history(plan, Source(bad), apply=True)
    assert not Path(plan["lake_root"]).exists()


@pytest.mark.parametrize(
    "values",
    [
        [],
        [rows()[0], rows()[0]],
        [(*rows()[0][:1], "20250101", *rows()[0][2:])],
        [(None, *rows()[0][1:])],
    ],
)
def test_bad_keys_and_calendar(plan, values):
    with pytest.raises(DailyBasicValidationError):
        history.export_daily_basic_history(plan, Source(values), apply=True)


def test_missing_calendar_day_stops_build(plan):
    history.export_daily_basic_history(plan, Source(rows()[:1]), apply=True)
    with pytest.raises(DailyBasicValidationError, match="calendar_source_difference"):
        history.build_daily_basic_history(plan, apply=True)


def test_second_pass_source_change(plan):
    source = Source()
    fetch = source.fetch_page

    def changed(*args):
        if source.calls == 2:
            source.values += rows("999999.SZ")
        return fetch(*args)

    source.fetch_page = changed
    with pytest.raises(DailyBasicValidationError, match="source_changed"):
        history.export_daily_basic_history(plan, source, apply=True)


def test_stale_report_candidate_and_target_conflict(plan):
    audit = prepared(plan)
    bad = copy.deepcopy(audit)
    bad["rows"] += 1
    with pytest.raises(DailyBasicValidationError, match="fingerprint"):
        history.promote_daily_basic_history(plan, bad, apply=True)
    target = raw_daily_basic_path(Path(plan["lake_root"]), DAYS[0])
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing data must not be overwritten")
    with pytest.raises(duckdb.Error):
        history.promote_daily_basic_history(plan, audit, apply=True)
    assert target.read_bytes() == b"existing data must not be overwritten"


def test_candidate_change_rejected(plan):
    audit = prepared(plan)
    Path(audit["files"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(DailyBasicValidationError, match="candidate_changed"):
        history.promote_daily_basic_history(plan, audit, apply=True)
    assert not Path(plan["lake_root"]).exists()


def test_shared_daily_lock_blocks_promotion(plan):
    audit = prepared(plan)
    lock = Path(plan["staging_root"]) / "daily_basic" / "locks" / f"{DAYS[0]}.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            history.promote_daily_basic_history(plan, audit, apply=True)
    assert not Path(plan["lake_root"]).exists()


def test_partial_promote_resumes(plan):
    audit = prepared(plan)
    original = history.os.replace

    def fail_second(src, dst):
        if str(dst).startswith(plan["lake_root"]) and DAYS[1] in str(dst):
            raise OSError("disk interrupted")
        original(src, dst)

    with (
        patch.object(history.os, "replace", side_effect=fail_second),
        pytest.raises(OSError),
    ):
        history.promote_daily_basic_history(plan, audit, apply=True)
    assert raw_daily_basic_path(Path(plan["lake_root"]), DAYS[0]).is_file()
    assert (
        len(history.promote_daily_basic_history(plan, audit, apply=True)["files"]) == 2
    )


def test_keyset_and_readonly_source():
    sql, params = daily_basic_history_query(DAYS[0], DAYS[-1], ("000001.SZ", DAYS[0]))
    assert "SELECT *" not in sql
    assert "OFFSET" not in sql
    assert params["last_date"] == date(2024, 12, 31)
    assert params["batch_size"] == 10000
    assert all(n not in sql for n in ("api_name", "raw_payload", "fetched_at"))
    resource = MagicMock()
    cursor = resource.connect_readonly_transaction.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.description = [(n,) for n in DAILY_BASIC_FIELDS]
    cursor.fetchmany.return_value = rows()
    assert DailyBasicHistorySource(resource).fetch_page(*DAYS) == rows()
    assert cursor.execute.call_args_list[0].args == (
        "SET LOCAL statement_timeout = %s",
        (10000,),
    )
    cursor.fetchmany.assert_called_once_with(10000)


def test_cli_defaults_no_write(plan, tmp_path):
    parser = history_parser()
    args = parser.parse_args(
        ["export", "--report", "/private/tmp/daily_basic_test_report.json"]
    )
    with pytest.raises(DailyBasicValidationError, match="plan_required"):
        run_history_cli(args)
    p = tmp_path / "plan.json"
    history.save_history_report(p, plan)
    args.plan = p
    with pytest.raises(DailyBasicValidationError, match="formal_roots_only"):
        run_history_cli(args)
    assert not Path(plan["staging_root"]).exists()


def test_report_json_identity(plan, tmp_path):
    path = tmp_path / "plan.json"
    history.save_history_report(path, plan)
    assert history.load_history_report(path) == plan
    value = json.loads(path.read_text())
    value["end"] = DAYS[0]
    path.write_text(json.dumps(value))
    with pytest.raises(DailyBasicValidationError, match="fingerprint"):
        history.load_history_report(path)


def test_multiple_batches_and_duplicate_at_boundary(plan):
    values = [r for index in range(5001) for r in rows(f"{index:06d}.SZ")]
    source = Source(values)
    state = history.export_daily_basic_history(plan, source, apply=True)
    assert [c["rows"] for c in state["chunks"]] == [10000, 2]
    assert source.calls == 6
    assert len(state["chunks"]) == 2


def test_repeated_boundary_key_rejected(plan):
    source = Source()
    source.fetch_page = lambda *args: rows()
    with pytest.raises(DailyBasicValidationError, match="key_or_calendar"):
        history.export_daily_basic_history(plan, source, apply=True)


def test_budget_and_changed_calendar(plan):
    limited = history.seal_history_report(
        {**plan, "limits": {**plan["limits"], "max_source_rows": 1}}
    )
    with pytest.raises(DailyBasicValidationError, match="row_budget"):
        history.export_daily_basic_history(limited, Source(), apply=True)
    Path(plan["calendar_path"]).write_bytes(b"changed")
    with pytest.raises(DailyBasicValidationError, match="calendar_changed"):
        history.export_daily_basic_history(plan, Source(), apply=True)


def test_stage_interruption_retains_candidate_and_can_resume(plan):
    history.export_daily_basic_history(plan, Source(), apply=True)
    original = history.save_history_report

    def fail_build_checkpoint(path, value):
        if Path(path).name == "build.json":
            raise OSError("checkpoint interrupted")
        return original(path, value)

    with (
        patch.object(history, "save_history_report", side_effect=fail_build_checkpoint),
        pytest.raises(OSError),
    ):
        history.build_daily_basic_history(plan, apply=True)
    assert len(history.build_daily_basic_history(plan, apply=True)["files"]) == 2
    assert history.audit_daily_basic_history(plan)["passed"]


def test_data_change_with_new_file_hash_still_fails_value_audit(plan):
    prepared(plan)
    workspace = history._workspace(plan)
    build = history.load_history_report(workspace / "build.json")
    item = build["files"][0]
    path = Path(item["path"])
    altered = rows()[:1]
    altered[0] = (*altered[0][:2], Decimal(99), *altered[0][3:])
    normalized, _ = history._canonical_page(altered, plan, None)
    with history._connection(plan) as connection:
        candidate = path.with_suffix(".altered")
        history._write_chunk(connection, normalized, candidate)
        history.os.replace(candidate, path)
    item["sha256"] = history.file_sha256(path)
    history.save_history_report(workspace / "build.json", build)
    with pytest.raises(DailyBasicValidationError, match="value_difference"):
        history.audit_daily_basic_history(plan)


def test_inspect_never_executes_business_select():
    resource = MagicMock()
    cursor = resource.connect_readonly_transaction.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = ([{"Plan": {"Node Type": "Index Scan"}}],)
    result = DailyBasicHistorySource(resource).inspect(*DAYS)
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    business = [sql for sql in statements if "FROM raw_tushare.daily_basic" in sql]
    assert len(business) == 2
    assert all(sql.startswith("EXPLAIN (FORMAT JSON)") for sql in business)
    assert all("ANALYZE" not in sql and "SELECT *" not in sql for sql in statements)
    assert result["business_rows_read"] == 0


def test_active_code_does_not_import_history():
    root = Path(__file__).parents[1] / "src/orchestrator/defs"
    for directory in (
        "assets",
        "checks",
        "sensors",
        "asset_guards",
        "source_readiness",
    ):
        for path in (root / directory).glob("*daily_basic*.py"):
            text = path.read_text()
            assert "bootstrap" not in text
            assert "prod_db.daily_basic" not in text
    cli = (root / "bootstrap/daily_basic_history_cli.py").read_text()
    for forbidden in (
        "report_runless_asset_event",
        "add_dynamic_partitions",
        "execute_in_process",
        "materialize(",
    ):
        assert forbidden not in cli


def test_expired_source_response_rejected(plan):
    with (
        patch.object(history, "monotonic", side_effect=[0, 0, 61]),
        pytest.raises(DailyBasicValidationError, match="elapsed_budget"),
    ):
        history.export_daily_basic_history(plan, Source(), apply=True)


def test_equal_content_different_encoding_is_preserved(plan):
    audit = prepared(plan)
    item = audit["files"][0]
    target = raw_daily_basic_path(Path(plan["lake_root"]), item["date"])
    target.parent.mkdir(parents=True)
    with history._connection(plan) as connection:
        connection.execute(
            f"COPY (SELECT {history.COLUMNS} FROM {history.read_parquet(Path(item['path']), hive_partitioning=False)}) "
            "TO ? (FORMAT PARQUET, COMPRESSION UNCOMPRESSED)",
            [str(target)],
        )
    old_hash = history.file_sha256(target)
    assert old_hash != item["sha256"]
    history.promote_daily_basic_history(plan, audit, apply=True)
    assert history.file_sha256(target) == old_hash


def test_source_schema_change_stops_before_export(plan):
    source = Source()
    evidence = source_evidence()
    evidence["primary_key"] = ["trade_date", "ts_code"]
    source.inspect = lambda *args: evidence
    with pytest.raises(DailyBasicValidationError, match="source_schema_changed"):
        history.export_daily_basic_history(plan, source, apply=True)
    assert source.calls == 0
    assert not Path(plan["staging_root"]).exists()


def test_cross_device_refused(plan):
    audit = prepared(plan)
    target = raw_daily_basic_path(Path(plan["lake_root"]), DAYS[0])
    original = Path.stat

    def changed_device(path, *args, **kwargs):
        stat = original(path, *args, **kwargs)
        if path == target.parent:
            return history.os.stat_result((*stat[:2], stat.st_dev + 1, *stat[3:]))
        return stat

    with (
        patch.object(Path, "stat", changed_device),
        pytest.raises(DailyBasicValidationError, match="cross_device"),
    ):
        history.promote_daily_basic_history(plan, audit, apply=True)
    assert not target.exists()


def test_partition_fragment_compaction_is_date_local(plan):
    folder = history._workspace(plan) / "fragments"
    folder.mkdir(parents=True)
    with history._connection(plan) as connection:
        for index, code in enumerate(("000002.SZ", "000001.SZ")):
            values, _ = history._canonical_page(rows(code)[:1], plan, None)
            history._write_chunk(connection, values, folder / f"part-{index}.parquet")
        path = history._compact_history_partition(connection, folder)
        assert path.name == "part-000.parquet"
        values = connection.execute(
            f"SELECT ts_code FROM {history.read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
        assert values == [("000001.SZ",), ("000002.SZ",)]
        assert (folder / "part-0.parquet").is_file()
        assert (folder / "part-1.parquet").is_file()
