from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import os
from pathlib import Path
from time import perf_counter

import duckdb
import pytest

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsDatePlan,
    MajorIndexMinsSourcePlan,
    MajorIndexMinsSourceWindow,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_stage import (
    source_window_parquet_path,
)
from orchestrator.defs.bootstrap.major_index_mins_silver_fallback import (
    MajorIndexMinsHistoricalFallbackError,
    write_major_index_mins_fallback_sample,
    write_major_index_mins_fallback_samples,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MajorIndexMinsContractError,
    MajorIndexMinsHistoricalFallbackRule,
    major_index_mins_historical_fallback_fingerprint,
    major_index_mins_historical_fallback_rule,
    major_index_mins_session_times,
)


class _CountingMemoryDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def connect(self):
        self.connection_count += 1
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


def _published_rule(
    trade_date: str,
    target_freq: str,
) -> MajorIndexMinsHistoricalFallbackRule:
    rule = major_index_mins_historical_fallback_rule(
        trade_date=trade_date,
        target_freq=target_freq,
    )
    assert rule is not None
    return rule


def _source_rows(
    *,
    trade_date: str,
    code: str,
    source_freq: str,
    mutation: str | None = None,
) -> list[tuple[object, ...]]:
    source_times = list(
        major_index_mins_session_times(
            exchange="XSHG",
            source_freq=source_freq,
        )
    )
    if mutation == "missing_time":
        source_times.remove("10:00:00")
    if mutation == "extra_time":
        source_times.append("12:00:00")

    rows: list[tuple[object, ...]] = []
    for index, source_time in enumerate(source_times):
        value = float(index + 1)
        row_code = "999999.SH" if mutation == "wrong_code" else code
        row_freq = "15min" if mutation == "wrong_freq" else source_freq
        row_date = "2025-07-10" if mutation == "wrong_date" else trade_date
        high = value - 1.0 if mutation == "invalid_ohlc" else value + 0.5
        volume = -value if mutation == "negative_volume" else value * 10
        rows.append(
            (
                row_code,
                row_freq,
                f"{row_date} {source_time}",
                value,
                value + 0.25,
                high,
                value - 0.5,
                volume,
                value * 100,
                None,
                value + 0.125,
            )
        )
    if mutation == "duplicate_key":
        rows.append(rows[0])
    return rows


def _write_source_file(
    connection,
    *,
    path: Path,
    rows: list[tuple[object, ...]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute("DROP TABLE IF EXISTS source_rows")
    connection.execute(
        """
        CREATE TEMP TABLE source_rows (
          ts_code VARCHAR,
          freq VARCHAR,
          trade_time TIMESTAMP,
          open DOUBLE,
          close DOUBLE,
          high DOUBLE,
          low DOUBLE,
          vol DOUBLE,
          amount DOUBLE,
          exchange VARCHAR,
          vwap DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.execute(
        copy_query_to_parquet(
            "SELECT * FROM source_rows ORDER BY ts_code, trade_time",
            path,
        )
    )


def _source_fixture(
    root: Path,
    *,
    rules: tuple[MajorIndexMinsHistoricalFallbackRule, ...],
    mutation: tuple[str, str, str, str] | None = None,
) -> tuple[MajorIndexMinsDatePlan, MajorIndexMinsSourcePlan]:
    dates = tuple(sorted({rule.trade_date for rule in rules}))
    date_plan = MajorIndexMinsDatePlan(
        start_date=dates[0],
        end_date=dates[-1],
        expected_trade_dates=dates,
        fingerprint="d" * 64,
    )
    source_codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rule in rules:
        source_codes[(rule.trade_date, rule.source_freq)].update(rule.target_codes)

    windows: list[MajorIndexMinsSourceWindow] = []
    total_rows = 0
    with duckdb.connect(":memory:") as connection:
        for (trade_date, source_freq), codes in sorted(source_codes.items()):
            source_times = major_index_mins_session_times(
                exchange="XSHG",
                source_freq=source_freq,
            )
            for code in sorted(codes):
                mutation_name = (
                    mutation[3]
                    if mutation is not None
                    and mutation[:3] == (trade_date, source_freq, code)
                    else None
                )
                rows = _source_rows(
                    trade_date=trade_date,
                    code=code,
                    source_freq=source_freq,
                    mutation=mutation_name,
                )
                window = MajorIndexMinsSourceWindow(
                    window_id=f"fixture-{trade_date}-{source_freq}-{code}",
                    ts_code=code,
                    source_freq=source_freq,
                    trade_dates=(trade_date,),
                    start_datetime=f"{trade_date} {source_times[0]}",
                    end_datetime=f"{trade_date} {source_times[-1]}",
                    expected_row_count=len(source_times),
                )
                _write_source_file(
                    connection,
                    path=source_window_parquet_path(root, date_plan, window),
                    rows=rows,
                )
                windows.append(window)
                total_rows += len(source_times)
    request_counts = Counter(window.source_freq for window in windows)
    return date_plan, MajorIndexMinsSourcePlan(
        windows=tuple(windows),
        fingerprint="s" * 64,
        expected_row_count=total_rows,
        request_count_by_frequency=dict(request_counts),
    )


def _output_rows(path: Path, code: str) -> list[tuple[object, ...]]:
    with duckdb.connect(":memory:") as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?, hive_partitioning=false) "
            "WHERE ts_code = ? ORDER BY trade_time",
            [str(path), code],
        ).fetchall()


def test_published_fallback_contract_is_exact_and_versioned() -> None:
    assert len(MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES) == 15
    assert sum(
        len(rule.target_codes) for rule in MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES
    ) == 130
    assert len(
        {
            (rule.trade_date, rule.source_freq)
            for rule in MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES
        }
    ) == 10
    assert all(
        not code.endswith(".BJ")
        for rule in MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES
        for code in rule.target_codes
    )
    assert (
        major_index_mins_historical_fallback_fingerprint()
        == "3063c0b9034a2439ff6ac54479b24c643df456077f36e8c77b874ab02f88d561"
    )
    assert major_index_mins_historical_fallback_rule(
        trade_date="2025-07-11",
        target_freq="15min",
    ) == _published_rule("2025-07-11", "15min")
    assert (
        major_index_mins_historical_fallback_rule(
            trade_date="2025-07-10",
            target_freq="15min",
        )
        is None
    )


def test_fallback_contract_rejects_bj_invalid_mapping_and_empty_scope() -> None:
    with pytest.raises(MajorIndexMinsContractError, match="must not include a BJ"):
        MajorIndexMinsHistoricalFallbackRule(
            trade_date="2025-07-11",
            target_freq="15min",
            source_freq="5min",
            target_codes=("899050.BJ",),
            reason_code="native_15m_source_empty",
        )
    with pytest.raises(MajorIndexMinsContractError, match="unsupported.*mapping"):
        MajorIndexMinsHistoricalFallbackRule(
            trade_date="2025-07-11",
            target_freq="60min",
            source_freq="15min",
            target_codes=("000001.SH",),
            reason_code="native_60m_source_empty",
        )
    with pytest.raises(MajorIndexMinsContractError, match="non-empty and unique"):
        MajorIndexMinsHistoricalFallbackRule(
            trade_date="2025-07-11",
            target_freq="15min",
            source_freq="5min",
            target_codes=(),
            reason_code="native_15m_source_empty",
        )


def test_1m_to_5m_fallback_preserves_opening_and_lunch_boundaries(
    tmp_path: Path,
) -> None:
    rule = _published_rule("2010-09-02", "5min")
    staging_root = tmp_path / "source"
    output_root = tmp_path / "output"
    date_plan, source_plan = _source_fixture(
        staging_root,
        rules=(rule,),
    )
    resource = _CountingMemoryDuckDB()

    result = write_major_index_mins_fallback_sample(
        staging_root=staging_root,
        output_root=output_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=resource,
        rule=rule,
        run_id="p7b-1m-to-5m",
    )

    assert resource.connection_count == 1
    assert result.source_mode == "derived_fallback"
    assert result.reason_code == "native_5m_source_empty"
    assert result.source_row_count == 6 * 241
    assert result.output_row_count == 6 * 49
    rows = _output_rows(result.target_path, "000001.SH")
    assert len(rows) == 49
    assert rows[0][2].strftime("%H:%M:%S") == "09:30:00"
    assert rows[0][3:11] == (
        1.0,
        1.25,
        1.5,
        0.5,
        10.0,
        100.0,
        "XSHG",
        None,
    )
    assert rows[1][2].strftime("%H:%M:%S") == "09:35:00"
    assert rows[1][3:9] == (2.0, 6.25, 6.5, 1.5, 200.0, 2000.0)
    observed_times = tuple(row[2].strftime("%H:%M:%S") for row in rows)
    assert "11:30:00" in observed_times
    assert "13:05:00" in observed_times
    assert "12:00:00" not in observed_times


@pytest.mark.parametrize(
    ("target_freq", "expected_per_code"),
    (("15min", 17), ("30min", 9), ("60min", 5)),
)
def test_5m_fallback_generates_exact_target_session(
    tmp_path: Path,
    target_freq: str,
    expected_per_code: int,
) -> None:
    rule = _published_rule("2025-07-11", target_freq)
    staging_root = tmp_path / "source"
    date_plan, source_plan = _source_fixture(staging_root, rules=(rule,))

    result = write_major_index_mins_fallback_sample(
        staging_root=staging_root,
        output_root=tmp_path / "output",
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=_CountingMemoryDuckDB(),
        rule=rule,
        run_id=f"p7b-5m-to-{target_freq}",
    )

    assert result.output_row_count == len(rule.target_codes) * expected_per_code
    rows = _output_rows(result.target_path, rule.target_codes[0])
    assert tuple(row[2].strftime("%H:%M:%S") for row in rows) == (
        major_index_mins_session_times(
            exchange="XSHG",
            source_freq=target_freq,
        )
    )
    assert all(row[10] is None for row in rows)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_time",
        "extra_time",
        "duplicate_key",
        "wrong_code",
        "wrong_freq",
        "wrong_date",
        "invalid_ohlc",
        "negative_volume",
    ),
)
def test_invalid_finer_source_fails_before_target_write(
    tmp_path: Path,
    mutation: str,
) -> None:
    rule = _published_rule("2025-07-11", "15min")
    code = rule.target_codes[0]
    staging_root = tmp_path / "source"
    date_plan, source_plan = _source_fixture(
        staging_root,
        rules=(rule,),
        mutation=(rule.trade_date, rule.source_freq, code, mutation),
    )

    with pytest.raises(
        MajorIndexMinsHistoricalFallbackError,
        match="failed the finer-frequency contract",
    ):
        write_major_index_mins_fallback_sample(
            staging_root=staging_root,
            output_root=tmp_path / "output",
            date_plan=date_plan,
            source_plan=source_plan,
            duckdb_resource=_CountingMemoryDuckDB(),
            rule=rule,
            run_id=f"p7b-invalid-{mutation}",
        )

    assert not (tmp_path / "output").exists()


def test_unpublished_scope_cannot_expand_output(tmp_path: Path) -> None:
    published = _published_rule("2025-07-11", "15min")
    narrowed = MajorIndexMinsHistoricalFallbackRule(
        trade_date=published.trade_date,
        target_freq=published.target_freq,
        source_freq=published.source_freq,
        target_codes=published.target_codes[:-1],
        reason_code=published.reason_code,
    )
    date_plan = MajorIndexMinsDatePlan(
        start_date=published.trade_date,
        end_date=published.trade_date,
        expected_trade_dates=(published.trade_date,),
        fingerprint="d" * 64,
    )
    source_plan = MajorIndexMinsSourcePlan(
        windows=(),
        fingerprint="s" * 64,
        expected_row_count=0,
        request_count_by_frequency={},
    )

    with pytest.raises(
        MajorIndexMinsHistoricalFallbackError,
        match="not in the published contract",
    ):
        write_major_index_mins_fallback_sample(
            staging_root=tmp_path / "source",
            output_root=tmp_path / "output",
            date_plan=date_plan,
            source_plan=source_plan,
            duckdb_resource=_CountingMemoryDuckDB(),
            rule=narrowed,
            run_id="p7b-unpublished",
        )


def test_existing_conflicting_target_is_preserved(tmp_path: Path) -> None:
    rule = _published_rule("2025-07-11", "15min")
    staging_root = tmp_path / "source"
    output_root = tmp_path / "output"
    date_plan, source_plan = _source_fixture(staging_root, rules=(rule,))
    resource = _CountingMemoryDuckDB()
    first = write_major_index_mins_fallback_sample(
        staging_root=staging_root,
        output_root=output_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=resource,
        rule=rule,
        run_id="p7b-first",
    )
    replacement = first.target_path.with_name("replacement.parquet")
    with duckdb.connect(":memory:") as connection:
        relation = (
            "SELECT * REPLACE (amount + 1.0 AS amount) "
            f"FROM {read_parquet(first.target_path, hive_partitioning=False)}"
        )
        connection.execute(
            copy_query_to_parquet(relation, replacement),
        )
    os.replace(replacement, first.target_path)
    conflicting_bytes = first.target_path.read_bytes()

    with pytest.raises(
        MajorIndexMinsHistoricalFallbackError,
        match="target conflicts with computed rows",
    ):
        write_major_index_mins_fallback_sample(
            staging_root=staging_root,
            output_root=output_root,
            date_plan=date_plan,
            source_plan=source_plan,
            duckdb_resource=resource,
            rule=rule,
            run_id="p7b-conflict",
        )
    assert first.target_path.read_bytes() == conflicting_bytes
    assert not tuple(first.target_path.parent.glob(".*.tmp"))


def test_full_published_batch_reuses_source_partitions_and_is_idempotent(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "source"
    output_root = tmp_path / "output"
    report_path = tmp_path / "report.json"
    date_plan, source_plan = _source_fixture(
        staging_root,
        rules=MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES,
    )
    resource = _CountingMemoryDuckDB()
    started_at = perf_counter()

    report = write_major_index_mins_fallback_samples(
        staging_root=staging_root,
        output_root=output_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=resource,
        output_path=report_path,
        run_id="p7b-full",
    )

    assert report.should_stop is False
    assert report.rule_count == 15
    assert report.expanded_scope_count == 130
    assert report.source_partition_count == 10
    assert report.source_row_count == 5_072
    assert report.output_row_count == 1_482
    assert report.written_count == 15
    assert report.reused_count == 0
    assert report.duckdb_connection_count == 1
    assert report.source_request_count == 0
    assert report.dagster_event_query_count == 0
    assert resource.connection_count == 1
    assert report_path.is_file()
    assert (perf_counter() - started_at) * 1000 < 30_000
    assert MAJOR_INDEX_MINS_SOURCE_COLUMNS[-1] == "vwap"
    assert all(
        row[10] is None
        for result in report.results
        for row in _output_rows(result.target_path, result.target_codes[0])[:1]
    )

    second = write_major_index_mins_fallback_samples(
        staging_root=staging_root,
        output_root=output_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=resource,
        output_path=tmp_path / "report-second.json",
        run_id="p7b-full-second",
    )
    assert second.should_stop is False
    assert second.written_count == 0
    assert second.reused_count == 15
    assert resource.connection_count == 2

    source_window_parquet_path(
        staging_root,
        date_plan,
        source_plan.windows[0],
    ).unlink()
    failed = write_major_index_mins_fallback_samples(
        staging_root=staging_root,
        output_root=output_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=resource,
        output_path=tmp_path / "report-failed.json",
        run_id="p7b-full-failed",
    )
    assert failed.should_stop is True
    assert failed.stop_reason_codes == ("historical_fallback_failed",)
    assert failed.failure_samples
    assert failed.source_request_count == 0
    assert failed.dagster_event_query_count == 0
    assert resource.connection_count == 3
