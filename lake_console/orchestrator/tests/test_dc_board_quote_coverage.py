from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.asset_guards import dc_board_quote_coverage as coverage
from orchestrator.defs.paths import raw_dc_daily_path, silver_trade_calendar_path


class IsolatedDuckDB:
    def __init__(self):
        self.connections = 0

    @contextmanager
    def connect(self):
        self.connections += 1
        with duckdb.connect(":memory:") as connection:
            yield connection


def write_calendar(root, days):
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE dates(exchange VARCHAR, trade_date DATE, is_open BOOLEAN)")
        connection.executemany("INSERT INTO dates VALUES ('SSE', ?, true)", [(x,) for x in days])
        connection.execute("COPY dates TO ? (FORMAT PARQUET)", [str(path)])


def write_history(root, day, codes=("BK0001.DC",), observed_date=None):
    path = raw_dc_daily_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE quotes(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        connection.executemany("INSERT INTO quotes VALUES (?, ?, -1)",
                               [(x, observed_date or day.replace("-", "")) for x in codes])
        connection.execute("COPY quotes TO ? (FORMAT PARQUET)", [str(path)])
    return path


def evaluate(root, gaps, resource=None):
    return coverage.batch_board_quote_coverage(lake_root=Path(root), gaps_by_date=gaps,
                                               duckdb_resource=resource or IsolatedDuckDB())


def test_no_gap_does_not_open_connection(tmp_path):
    resource = IsolatedDuckDB()
    result = evaluate(tmp_path, {"2026-10-08": ()}, resource)["2026-10-08"]
    assert result.ready
    assert resource.connections == 0
    assert result.metadata()["source_confirmation"] == "not_evaluated"
    assert result.metadata()["reason_code"] == "no_missing_quote"


def test_complete_absence_and_mature_missing_share_one_scan(tmp_path):
    days = ["2024-01-02", "2024-01-03"]
    write_calendar(tmp_path, days)
    for day in days:
        write_history(tmp_path, day)
    resource = IsolatedDuckDB()
    results = evaluate(tmp_path, {"2024-01-03": ("BK1754.DC", "BK0001.DC"),
                                  "2024-01-04": ("BK1754.DC",)}, resource)
    assert resource.connections == 1
    mature = results["2024-01-03"]
    assert not mature.ready
    assert [(x.code, x.state) for x in mature.details] == [
        ("BK0001.DC", coverage.MISSING_OBSERVED_QUOTE),
        ("BK1754.DC", coverage.AWAITING_QUOTE)]
    assert mature.details[0].observed_quote_date == "2024-01-02"
    waiting = results["2024-01-04"]
    assert waiting.ready and waiting.history_complete
    assert waiting.history_end == "2024-01-03"
    assert waiting.metadata()["awaiting_count"] == 1
    assert waiting.metadata()["reason_code"] == coverage.AWAITING_QUOTE
    assert "failed_row_count" not in waiting.metadata()
    assert "failure_samples" not in waiting.metadata()


def test_missing_file_cannot_prove_absence_but_observed_quote_blocks(tmp_path):
    write_calendar(tmp_path, ["2024-01-02", "2024-01-03"])
    write_history(tmp_path, "2024-01-03")
    result = evaluate(tmp_path, {"2024-01-04": ("BK1754.DC", "BK0001.DC")})["2024-01-04"]
    assert not result.ready
    assert result.details[0].state == coverage.MISSING_OBSERVED_QUOTE
    assert result.details[1].state == coverage.HISTORY_UNVERIFIABLE


def test_late_budget_error_discards_matches_without_closing_signatures(tmp_path, monkeypatch):
    write_calendar(tmp_path, ["2024-01-02", "2024-01-03"])
    newest = write_history(tmp_path, "2024-01-03")
    write_history(tmp_path, "2024-01-02")
    monkeypatch.setattr(coverage, "DC_QUOTE_HISTORY_BATCH_FILES", 1)
    monkeypatch.setattr(coverage, "DC_QUOTE_HISTORY_MAX_FILE_BYTES", newest.stat().st_size)
    result = evaluate(tmp_path, {"2024-01-04": ("BK0001.DC", "BK1754.DC")})["2024-01-04"]
    assert "history_budget_exceeded" in result.error
    assert all(detail.state == coverage.HISTORY_UNVERIFIABLE for detail in result.details)
    assert all(detail.observed_quote_date is None for detail in result.details)


@pytest.mark.parametrize("bad_date", ["20240103", "broken"])
def test_wrong_internal_date_is_not_trusted(tmp_path, bad_date):
    write_calendar(tmp_path, ["2024-01-02"])
    write_history(tmp_path, "2024-01-02", observed_date=bad_date)
    result = evaluate(tmp_path, {"2024-01-03": ("BK0001.DC", "BK1754.DC")})["2024-01-03"]
    assert all(x.state == coverage.HISTORY_UNVERIFIABLE for x in result.details)


def test_target_date_quote_is_excluded(tmp_path):
    write_calendar(tmp_path, ["2024-01-02", "2024-01-03"])
    write_history(tmp_path, "2024-01-02")
    write_history(tmp_path, "2024-01-03", ("BK1754.DC",))
    result = evaluate(tmp_path, {"2024-01-03": ("BK1754.DC",)})["2024-01-03"]
    assert result.ready


@pytest.mark.parametrize("constant,value", [
    ("DC_QUOTE_HISTORY_MAX_CODES", 0),
    ("DC_QUOTE_HISTORY_MAX_TARGETS", 0),
    ("DC_QUOTE_HISTORY_MAX_PROJECTED_ROWS", 0),
    ("DC_QUOTE_HISTORY_MAX_FILE_BYTES", 0),
    ("DC_QUOTE_HISTORY_DEADLINE_SECONDS", 0),
])
def test_budget_rejection_is_fail_closed(tmp_path, monkeypatch, constant, value):
    write_calendar(tmp_path, ["2024-01-02"])
    write_history(tmp_path, "2024-01-02")
    monkeypatch.setattr(coverage, constant, value)
    result = evaluate(tmp_path, {"2024-01-03": ("BK1754.DC",)})["2024-01-03"]
    assert not result.ready and result.error


def test_metadata_limit_and_digest_do_not_hide_truncation():
    import json
    result = coverage.BoardQuoteCoverageResult("2026-10-08", tuple(
        coverage.BoardQuoteEvidence(f"BK{i:04}.DC", coverage.AWAITING_QUOTE)
        for i in range(1200)), "2026-10-07", True)
    metadata = result.metadata()
    assert len(json.dumps(metadata, ensure_ascii=False).encode()) <= coverage.DC_QUOTE_COVERAGE_METADATA_BYTES
    assert metadata["metadata_truncated"]
    assert metadata["missing_quote_count"] == 1200
    assert metadata["retained_quote_detail_count"] < 1200
    assert len(metadata["quote_coverage_samples"]) == 5
    assert metadata["evidence_digest"] == result.evidence_digest


def test_changed_file_signature_invalidates_even_positive_evidence(tmp_path, monkeypatch):
    write_calendar(tmp_path, ["2024-01-02"])
    write_history(tmp_path, "2024-01-02")
    original = coverage._signature
    seen = {}
    def changing(path, root):
        signature = original(path, root)
        seen[path] = seen.get(path, 0) + 1
        if "dc_daily" in str(path) and seen[path] > 1:
            return signature[0], signature[1], signature[2] + 1
        return signature
    monkeypatch.setattr(coverage, "_signature", changing)
    result = evaluate(tmp_path, {"2024-01-03": ("BK0001.DC",)})["2024-01-03"]
    assert result.details[0].state == coverage.HISTORY_UNVERIFIABLE
    assert result.error == "history_files_changed"


def test_changed_calendar_invalidates_negative_evidence(tmp_path, monkeypatch):
    write_calendar(tmp_path, ["2024-01-02"])
    write_history(tmp_path, "2024-01-02")
    original = coverage._signature
    seen = [0]
    def changing(path, root):
        signature = original(path, root)
        if path == silver_trade_calendar_path(root):
            seen[0] += 1
            if seen[0] > 1:
                return signature[0], signature[1], signature[2] + 1
        return signature
    monkeypatch.setattr(coverage, "_signature", changing)
    result = evaluate(tmp_path, {"2024-01-03": ("BK1754.DC",)})["2024-01-03"]
    assert not result.ready and result.error == "history_files_changed"


def test_mature_evidence_short_circuits_before_missing_older_file(tmp_path):
    write_calendar(tmp_path, ["2024-01-02", "2024-01-03"])
    write_history(tmp_path, "2024-01-03")
    result = evaluate(tmp_path, {"2024-01-04": ("BK0001.DC",)})["2024-01-04"]
    assert result.details[0].state == coverage.MISSING_OBSERVED_QUOTE
    assert not result.history_complete


def test_necessary_schema_and_identity_failure_cannot_prove_absence(tmp_path):
    write_calendar(tmp_path, ["2024-01-02"])
    path = write_history(tmp_path, "2024-01-02", ("invalid",))
    result = evaluate(tmp_path, {"2024-01-03": ("BK1754.DC",)})["2024-01-03"]
    assert not result.ready
    with duckdb.connect(":memory:") as connection:
        connection.execute("COPY (SELECT 'BK0001.DC' AS ts_code) TO ? (FORMAT PARQUET)", [str(path)])
    assert not evaluate(tmp_path, {"2024-01-03": ("BK1754.DC",)})["2024-01-03"].ready


def test_sql_timeout_cleans_up_timer_and_connection(tmp_path, monkeypatch):
    import threading
    import time
    write_calendar(tmp_path, ["2024-01-02"])
    write_history(tmp_path, "2024-01-02")
    monkeypatch.setattr(coverage, "DC_QUOTE_HISTORY_BATCH_SQL_DEADLINE_SECONDS", 0.02)
    closed = []
    class SlowCalendarDuckDB(IsolatedDuckDB):
        @contextmanager
        def connect(self):
            with duckdb.connect(":memory:") as connection:
                class Proxy:
                    def execute(self, sql, parameters=None):
                        if "exchange='SSE'" in sql:
                            return connection.execute("SELECT sum(i) FROM range(10000000000) t(i)")
                        return connection.execute(sql, parameters) if parameters is not None else connection.execute(sql)
                    def interrupt(self):
                        connection.interrupt()
                try:
                    yield Proxy()
                finally:
                    closed.append(True)
    active_before = {t.ident for t in threading.enumerate()}
    start = time.monotonic()
    result = evaluate(tmp_path, {"2024-01-03": ("BK1754.DC",)}, SlowCalendarDuckDB())["2024-01-03"]
    assert not result.ready and closed == [True]
    assert time.monotonic() - start < 1
    assert all(t.ident in active_before for t in threading.enumerate())
