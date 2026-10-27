"""Fresh-worker acceptance profile and independent observer gold samples."""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from orchestrator.defs.anns_d_checkpoint import announcement_file_fingerprint
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from tests.anns_d_measurement_support import (
    AnnouncementMeasurement,
    normalized_peak_rss,
)


def test_sha_observer_counts_real_reads_not_fsync_open(tmp_path):
    path = tmp_path / "literal.bin"
    path.write_bytes(b"abcde")
    observer = AnnouncementMeasurement(tmp_path)
    with observer.installed():
        assert announcement_file_fingerprint(path) == {
            "size": 5,
            "sha256": "36bbe50ed96841d10443bcb670d6554f0a34b761be67ec9c4a8ad2c0c44ca42c",
        }
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    counts = observer.spans[0].counts
    assert counts["sha_file_reads"] == 1 and counts["sha_read_bytes"] == 5
    assert counts["other_python_binary_read_bytes"] == 0


def test_sql_observer_keeps_real_results_and_independent_setup_counts(tmp_path):
    source, target = tmp_path / "literal.json", tmp_path / "one.parquet"
    raw = '[{"value":1}]'
    source.write_text(raw)
    observer = AnnouncementMeasurement(tmp_path)
    settings = DuckDBConnectionSettings(
        temp_directory=tmp_path / "spill", memory_limit="64MB", threads=1,
        max_temp_directory_size="16MB",
    )
    with observer.installed(), connect_configured_duckdb(settings) as connection:
        connection.execute("SET autoinstall_known_extensions=false")
        connection.execute("SET autoload_known_extensions=false")
        connection.read_json(str(source)).create_view("literal")
        assert connection.execute("SELECT value FROM literal").fetchone() == (1,)
        connection.execute("COPY (SELECT value FROM literal) TO ? (FORMAT PARQUET)", [str(target)])
    span = observer.spans[0]
    assert span.counts["execute_calls"] == 5
    assert span.counts["setup_sql_calls"] == 3
    assert span.counts["business_sql_calls"] == 2
    assert span.counts["read_json_calls"] == span.counts["relation_create_view_calls"] == 1
    assert span.inputs["literal.json"]["size_bytes"] == len(raw.encode())
    assert span.counts["parquet_copy_outputs"] == 1
    assert span.counts["parquet_copy_output_size_bytes"] == target.stat().st_size


def test_sql_observer_preserves_the_real_exception(tmp_path):
    observer = AnnouncementMeasurement(tmp_path)
    with observer.installed(), connect_configured_duckdb(DuckDBConnectionSettings(
        temp_directory=tmp_path / "spill", memory_limit="64MB", threads=1,
        max_temp_directory_size="16MB",
    )) as connection, pytest.raises(duckdb.CatalogException):
        connection.execute("SELECT * FROM table_that_does_not_exist")
    assert observer.spans[0].counts["business_sql_calls"] == 1


@pytest.mark.parametrize("platform,expected", [("darwin", 7), ("linux", 7168), ("unknown", None)])
def test_peak_rss_uses_absolute_platform_units(platform, expected):
    assert normalized_peak_rss(7, platform) == expected


def test_control_work_and_independent_verification_are_separate(tmp_path):
    observer = AnnouncementMeasurement(tmp_path)
    observer._span().counts["execute_calls"] += 1
    with observer.attempt("initial", run_id="literal-run"):
        observer._span().counts["execute_calls"] += 2
    assert [(span.attempt, span.phase, span.run_id, span.counts["execute_calls"])
            for span in observer.spans] == [
        ("verification", "verification", None, 1),
        ("initial", "execution_control", "literal-run", 2),
    ]


def test_check_phase_uses_existing_context_and_materialization_identity(tmp_path, monkeypatch):
    from orchestrator.defs.checks import anns_d_checks as checks

    observer = AnnouncementMeasurement(tmp_path)
    sentinel = object()
    monkeypatch.setattr(checks, "evaluate_announcement_check", lambda *_args, **_kwargs: sentinel)
    record = SimpleNamespace(asset_materialization=SimpleNamespace(metadata={
        "goldenshare/announcement_identity": SimpleNamespace(value={"window_id": "literal-window"}),
    }))
    with observer.installed(), observer.attempt("checks_only", run_id="literal-child"):
        assert checks.evaluate_announcement_check(
            SimpleNamespace(run=SimpleNamespace(run_id="literal-child")), None,
            day="2023-06-09", reconciliation=False, target_record=record,
        ) is sentinel
    assert [(span.phase, span.run_id, span.window_id) for span in observer.spans] == [
        ("file_check", "literal-child", "literal-window"),
    ]


def _counts(report, attempt):
    result = Counter()
    for span in report["spans"]:
        if span["attempt"] == attempt and span["phase"] != "verification":
            result.update(span["counts"])
    return result


def test_fresh_worker_acceptance_measurements(tmp_path):
    report = tmp_path / "announcement-measurements.json"
    environment = {key: value for key, value in os.environ.items() if key not in (
        "DAGSTER_HOME", "TUSHARE_TOKEN",
    )}
    result = subprocess.run(
        [sys.executable, "-B", "-c", (
            "from pathlib import Path; import sys; "
            "from tests.anns_d_measurement_support import run_announcement_measurements; "
            "r=run_announcement_measurements(Path(sys.argv[1])); "
            "raise SystemExit(r['pytest_exit_code'])"
        ), str(report)],
        cwd=Path(__file__).parents[1], env=environment,
        capture_output=True, text=True, check=False,
    )
    (tmp_path / "announcement-measurements.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(report.read_text())
    assert len(document["outcomes"]) == 2 and all(
        item["outcome"] == "passed" for item in document["outcomes"]
    )
    assert document["measurement_boundaries"]["physical_disk_read_bytes"] is None
    assert document["temporary_data_cleaned"]
    assert document["worker_peak_rss"]["bytes"] > 0
    assert _counts(document, "prepare")["requests_claimed"] == 1
    assert _counts(document, "normal")["requests_claimed"] == 2
    assert _counts(document, "normal")["parquet_copy_outputs"] == 3
    assert _counts(document, "normal")["formal_parquet_renames"] == 1
    assert _counts(document, "initial")["requests_claimed"] == 9
    assert _counts(document, "resume")["requests_claimed"] == 1
    assert _counts(document, "resume")["formal_parquet_renames"] == 1
    assert _counts(document, "resume")["parquet_copy_outputs"] == 2
    for key in ("requests_claimed", "parquet_copy_outputs", "formal_parquet_renames"):
        assert _counts(document, "checks_only")[key] == 0
    for span in document["spans"]:
        counts = span["counts"]
        assert counts.get("execute_calls", 0) == (
            counts.get("setup_sql_calls", 0) + counts.get("business_sql_calls", 0)
        )
