from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from src.foundation.clients.local_lake.major_index_mins_reader import (  # noqa: E402
    IndexMinuteReadRequest,
    IndexMinuteRequestError,
    IndexMinuteSourceContractError,
    MajorIndexMinsLakeReader,
)


def _write_gold_bars(
    root: Path,
    *,
    trade_date: date = date(2026, 8, 11),
    freq: int = 5,
    code: str = "000001.SH",
    rows: list[tuple] | None = None,
) -> Path:
    target = (
        root
        / "gold/quote/major_index_mins"
        / f"freq={freq}"
        / f"trade_date={trade_date.isoformat()}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or [
        (
            code,
            f"{freq}min",
            f"{trade_date} 09:35:00",
            10.0,
            10.2,
            10.3,
            9.9,
            100.0,
            1000.0,
            "SSE",
            10.1,
        ),
        (
            code,
            f"{freq}min",
            f"{trade_date} 09:40:00",
            10.2,
            10.4,
            10.5,
            10.1,
            110.0,
            1100.0,
            "SSE",
            10.3,
        ),
        (
            code,
            f"{freq}min",
            f"{trade_date} 09:45:00",
            10.4,
            10.6,
            10.7,
            10.3,
            120.0,
            1200.0,
            "SSE",
            10.5,
        ),
    ]
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
              ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
              open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
              vol DOUBLE, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
            """
        )
        normalized_rows = [
            (
                item[0],
                freq,
                trade_date,
                item[2],
                item[3],
                item[5],
                item[6],
                item[4],
                item[7],
                item[8],
                item[9],
                item[10],
            )
            for item in rows
        ]
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, CAST(? AS TIMESTAMP), ?, ?, ?, ?, ?, ?, ?, ?)",
            normalized_rows,
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def _write_gold(
    root: Path, *, trade_date: date = date(2026, 8, 11), freq: int = 5
) -> Path:
    target = (
        root
        / "gold/indicator/major_index_mins_technical"
        / f"freq={freq}"
        / f"trade_date={trade_date.isoformat()}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE indicators (
              ts_code VARCHAR, freq SMALLINT, trade_date DATE, trade_time TIMESTAMP,
              ma_5 DOUBLE, ma_10 DOUBLE, ma_20 DOUBLE, ma_30 DOUBLE,
              ma_60 DOUBLE, ma_90 DOUBLE, ma_250 DOUBLE,
              boll_mid DOUBLE, boll_upper DOUBLE, boll_lower DOUBLE,
              macd_dif DOUBLE, macd_dea DOUBLE, macd DOUBLE,
              kdj_k DOUBLE, kdj_d DOUBLE, kdj_j DOUBLE,
              observation_count INTEGER, params_key VARCHAR, indicator_version INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO indicators VALUES (
              '000001.SH', ?, DATE '2026-08-11', TIMESTAMP '2026-08-11 09:35:00',
              1, 2, 3, 4, 5, 6, NULL, 3, 4, 2, .1, .2, -.2,
              50, 45, 60, 120,
              'ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3', 1
            )
            """, [freq]
        )
        connection.execute("COPY indicators TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def test_reader_reads_gold_bar_schema_and_partition_date(tmp_path: Path) -> None:
    _write_gold_bars(tmp_path)
    page = MajorIndexMinsLakeReader(tmp_path).read_bars(
        IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
    )

    assert page.count == 3
    assert page.scanned_file_count == 1
    assert page.rows[0]["trade_date"] == date(2026, 8, 11)
    assert page.rows[0]["freq"] == 5
    assert set(page.rows[0]) == {
        "ts_code",
        "freq",
        "trade_date",
        "trade_time",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "exchange",
    }


@pytest.mark.parametrize("freq", [1, 5, 15, 30, 60, 90, 120])
def test_reader_supports_all_frozen_frequencies(tmp_path: Path, freq: int) -> None:
    _write_gold_bars(tmp_path, freq=freq)
    page = MajorIndexMinsLakeReader(tmp_path).read_bars(
        IndexMinuteReadRequest("000001.SH", freq, None, date(2026, 8, 11), 10, None)
    )

    assert page.count == 3
    assert {row["freq"] for row in page.rows} == {freq}


def test_reader_does_not_fall_back_to_silver_bar_files(tmp_path: Path) -> None:
    gold_path = _write_gold_bars(tmp_path)
    silver_path = tmp_path / (
        "silver/quote/major_index_mins/freq=5min/trade_date=2026-08-11/part-000.parquet"
    )
    silver_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.replace(silver_path)

    page = MajorIndexMinsLakeReader(tmp_path).read_bars(
        IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
    )

    assert page.rows == ()
    assert page.scanned_file_count == 0


@pytest.mark.parametrize("forbidden_time", ["09:30:00", "15:01:00", "15:30:00"])
def test_reader_rejects_forbidden_non_one_minute_times(
    tmp_path: Path,
    forbidden_time: str,
) -> None:
    _write_gold_bars(
        tmp_path,
        rows=[
            (
                "000001.SH",
                "5min",
                f"2026-08-11 {forbidden_time}",
                1,
                1,
                1,
                1,
                1,
                1,
                "SSE",
                1,
            )
        ],
    )

    with pytest.raises(IndexMinuteSourceContractError):
        MajorIndexMinsLakeReader(tmp_path).read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
        )


def test_reader_cursor_is_dataset_and_request_bound(tmp_path: Path) -> None:
    _write_gold_bars(tmp_path)
    _write_gold(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 2, None)

    first = reader.read_bars(request)
    second = reader.read_bars(replace(request, cursor=first.next_cursor))

    assert first.has_more is True
    assert first.next_cursor
    assert {row["trade_time"] for row in first.rows}.isdisjoint(
        {row["trade_time"] for row in second.rows}
    )
    with pytest.raises(IndexMinuteRequestError):
        reader.read_indicators(replace(request, cursor=first.next_cursor))


def test_reader_reads_gold_indicators_and_preserves_nulls(tmp_path: Path) -> None:
    _write_gold(tmp_path)
    page = MajorIndexMinsLakeReader(tmp_path).read_indicators(
        IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
    )

    assert page.count == 1
    assert page.rows[0]["ma_250"] is None
    assert page.rows[0]["observation_count"] == 120


def test_reader_rejects_partition_date_mismatch_and_duplicate_time_key(
    tmp_path: Path,
) -> None:
    mismatch = [
        ("000001.SH", "5min", "2026-08-10 09:35:00", 1, 1, 1, 1, 1, 1, "SSE", 1),
    ]
    _write_gold_bars(tmp_path, rows=mismatch)
    reader = MajorIndexMinsLakeReader(tmp_path)
    with pytest.raises(IndexMinuteSourceContractError):
        reader.read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
        )

    duplicate_root = tmp_path / "duplicate"
    duplicate = [
        ("000001.SH", "5min", "2026-08-11 09:35:00", 1, 1, 1, 1, 1, 1, "SSE", 1),
        ("000001.SH", "5min", "2026-08-11 09:35:00", 1, 1, 1, 1, 1, 1, "SSE", 1),
    ]
    _write_gold_bars(duplicate_root, rows=duplicate)
    with pytest.raises(IndexMinuteSourceContractError):
        MajorIndexMinsLakeReader(duplicate_root).read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
        )


@pytest.mark.parametrize("invalid_value", [None, float("nan"), float("inf")])
def test_reader_rejects_null_or_non_finite_required_bar_values(
    tmp_path: Path,
    invalid_value: float | None,
) -> None:
    rows = [
        (
            "000001.SH",
            "5min",
            "2026-08-11 09:35:00",
            invalid_value,
            10.2,
            10.3,
            9.9,
            100.0,
            1000.0,
            "SSE",
            10.1,
        ),
    ]
    _write_gold_bars(tmp_path, rows=rows)

    with pytest.raises(IndexMinuteSourceContractError):
        MajorIndexMinsLakeReader(tmp_path).read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
        )


def test_reader_ignores_staging_and_rejects_symlink_escape(tmp_path: Path) -> None:
    staging = tmp_path / "gold/quote/major_index_mins/_staging/run/part-000.parquet"
    staging.parent.mkdir(parents=True)
    staging.write_bytes(b"not parquet")
    page = MajorIndexMinsLakeReader(tmp_path).read_bars(
        IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
    )
    assert page.rows == ()

    external = tmp_path.parent / f"{tmp_path.name}-external.parquet"
    external.write_bytes(b"external")
    try:
        link = (
            tmp_path
            / "gold/quote/major_index_mins/freq=5/trade_date=2026-08-11/part-000.parquet"
        )
        link.parent.mkdir(parents=True)
        link.symlink_to(external)
        with pytest.raises(IndexMinuteSourceContractError):
            MajorIndexMinsLakeReader(tmp_path).read_bars(
                IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
            )
    finally:
        external.unlink(missing_ok=True)


def test_reader_rejects_symlink_even_when_target_stays_inside_lake(
    tmp_path: Path,
) -> None:
    target = tmp_path / "gold/quote/major_index_mins/internal.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"internal")
    link = (
        tmp_path
        / "gold/quote/major_index_mins/freq=5/trade_date=2026-08-11/part-000.parquet"
    )
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    with pytest.raises(IndexMinuteSourceContractError, match="符号链接"):
        MajorIndexMinsLakeReader(tmp_path).read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
        )


def test_reader_rejects_invalid_schema_and_request(tmp_path: Path) -> None:
    target = (
        tmp_path
        / "gold/quote/major_index_mins/freq=5/trade_date=2026-08-11/part-000.parquet"
    )
    target.parent.mkdir(parents=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("CREATE TABLE invalid (ts_code VARCHAR, freq INTEGER)")
        connection.execute("INSERT INTO invalid VALUES ('000001.SH', 5)")
        connection.execute("COPY invalid TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()

    reader = MajorIndexMinsLakeReader(tmp_path)
    with pytest.raises(IndexMinuteSourceContractError):
        reader.read_bars(IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None))
    with pytest.raises(IndexMinuteRequestError):
        reader.read_bars(
            IndexMinuteReadRequest("../../secret", 5, None, None, 10, None)
        )
    with pytest.raises(IndexMinuteRequestError):
        reader.read_bars(IndexMinuteReadRequest("000001.SH", 7, None, None, 10, None))
    with pytest.raises(IndexMinuteRequestError):
        reader.read_bars(
            IndexMinuteReadRequest(
                "000001.SH", 5, date(2026, 8, 12), date(2026, 8, 11), 10, None
            )
        )


def test_reader_rejects_queries_that_require_more_than_5000_partitions(
    tmp_path: Path,
) -> None:
    _write_gold_bars(tmp_path, freq=120)

    with pytest.raises(IndexMinuteRequestError, match="5000"):
        MajorIndexMinsLakeReader(tmp_path).read_bars(
            IndexMinuteReadRequest("000001.SH", 120, None, None, 10_000, None)
        )
def test_complete_history_preserves_paging_and_rejects_clipping(tmp_path: Path, monkeypatch) -> None:
    from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteHistoryBudgetError

    _write_gold_bars(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest("000001.SH", 5, None, None, 2, None)
    paged = reader.read_bars(request)
    assert paged.count == 2 and paged.has_more
    original_connect = duckdb.connect
    observed = []
    def bounded_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        observed.append(connection.execute("SELECT current_setting('threads'), current_setting('memory_limit')").fetchone())
        return connection
    monkeypatch.setattr(duckdb, "connect", bounded_connect)
    complete = reader.read_complete_history(request, dataset="bars", timeout_seconds=5)
    assert observed[0] == (2, "488.2 MiB")
    assert complete.count == 3 and not complete.has_more and complete.next_cursor is None
    assert [row["trade_time"] for row in complete.rows] == sorted(row["trade_time"] for row in complete.rows)
    with pytest.raises(IndexMinuteHistoryBudgetError):
        reader.read_complete_history(request, dataset="bars", max_rows=2, timeout_seconds=5)
    with pytest.raises(IndexMinuteRequestError):
        reader.read_complete_history(IndexMinuteReadRequest("000001.SH",5,None,None,2,paged.next_cursor), dataset="bars", timeout_seconds=5)


def test_history_signature_detects_atomic_revision_and_ignores_staging(tmp_path: Path) -> None:
    target = _write_gold_bars(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest("000001.SH",5,None,None,1000,None)
    before = reader.history_source_signature(request, dataset="bars")
    replacement = target.with_suffix(".candidate")
    replacement.write_bytes(target.read_bytes())
    replacement.replace(target)
    assert reader.history_source_signature(request, dataset="bars") != before
    before = reader.history_source_signature(request, dataset="bars")
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging/fake.parquet").write_text("not a source")
    assert reader.history_source_signature(request, dataset="bars") == before


def test_history_signature_checks_each_file_once_and_refreshes_next_request(tmp_path, monkeypatch):
    import os
    target = _write_gold_bars(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', 5, None, None, 1000, None)
    original_stat = os.stat
    calls = []
    def observe(path, *args, **kwargs):
        if Path(path) == target:
            calls.append(kwargs.get('follow_symlinks', True))
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, 'stat', observe)
    before = reader.history_source_signature(request, dataset='bars')
    assert calls == [False]
    replacement = target.with_suffix('.candidate')
    replacement.write_bytes(target.read_bytes())
    replacement.replace(target)
    after = reader.history_source_signature(request, dataset='bars')
    assert calls == [False, False] and before != after


@pytest.mark.parametrize('dataset', ['bars', 'indicators'])
def test_p4_batch1_prepared_history_skips_second_discovery_and_link_checks(tmp_path, dataset):
    from src.foundation.clients.local_lake import major_index_mins_reader as module
    from unittest.mock import patch

    (_write_gold_bars if dataset == 'bars' else _write_gold)(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', 5, None, None, 1000, None)
    with patch.object(module, '_enumerate_partitions', wraps=module._enumerate_partitions) as enumerate_parts:
        reader.history_source_signature(request, dataset=dataset)
        assert enumerate_parts.call_count == 1
        with patch.object(module, '_contains_symlink', wraps=module._contains_symlink) as contains_link:
            with patch.object(Path, 'is_symlink', autospec=True, side_effect=Path.is_symlink) as path_link:
                page = reader.read_complete_history(request, dataset=dataset, timeout_seconds=5)
        assert enumerate_parts.call_count == 1
        assert contains_link.call_count == path_link.call_count == 0
    assert [row['trade_time'].isoformat() for row in page.rows] == (
        ['2026-08-11T09:35:00', '2026-08-11T09:40:00', '2026-08-11T09:45:00']
        if dataset == 'bars' else ['2026-08-11T09:35:00'])
    if dataset == 'bars':
        assert [row['close'] for row in page.rows] == [10.2, 10.4, 10.6]
    else:
        assert [(r['macd_dif'], r['macd_dea'], r['macd'], r['ma_250']) for r in page.rows] == [(0.1, 0.2, -0.2, None)]


@pytest.mark.parametrize('dataset', ['bars', 'indicators'])
def test_p4_batch1_empty_prepared_history_does_not_rediscover_or_connect(tmp_path, monkeypatch, dataset):
    from unittest.mock import patch
    from src.foundation.clients.local_lake import major_index_mins_reader as module

    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', 5, None, None, 1000, None)
    with patch.object(module, '_enumerate_partitions', wraps=module._enumerate_partitions) as enumerate_parts:
        assert reader.history_source_signature(request, dataset=dataset) == ()
        assert enumerate_parts.call_count == 1
        monkeypatch.setattr(duckdb, 'connect', lambda *a, **kw: pytest.fail('empty prepared list opened DuckDB'))
        page = reader.read_complete_history(request, dataset=dataset, timeout_seconds=5)
        assert enumerate_parts.call_count == 1
    assert page.rows == () and page.count == page.scanned_file_count == 0
    assert not page.has_more and page.next_cursor is None
    assert reader._prepared_history_partitions == {}


@pytest.mark.parametrize('changed', ['dataset', 'freq', 'start_date', 'end_date'])
def test_p4_batch1_prepared_history_is_bound_to_original_key(tmp_path, changed):
    from unittest.mock import patch
    from src.foundation.clients.local_lake import major_index_mins_reader as module

    _write_gold_bars(tmp_path)
    _write_gold(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', 5, None, None, 1000, None)
    original_key = ('bars', 5, None, None)
    reader.history_source_signature(request, dataset='bars')
    dataset = 'indicators' if changed == 'dataset' else 'bars'
    if changed == 'freq':
        request = replace(request, freq=15)  # This frequency has no files.
    elif changed == 'start_date':
        request = replace(request, start_date=date(2026, 8, 11))
    elif changed == 'end_date':
        request = replace(request, end_date=date(2026, 8, 11))
    with patch.object(module, '_enumerate_partitions', wraps=module._enumerate_partitions) as enumerate_parts:
        page = reader.read_complete_history(request, dataset=dataset, timeout_seconds=5)
        assert enumerate_parts.call_count == 1
        assert enumerate_parts.call_args.kwargs == dict(dataset=dataset, freq=request.freq,
            start_date=request.start_date, end_date=request.end_date, cursor=None)
    assert original_key in reader._prepared_history_partitions
    if changed == 'freq':
        assert page.rows == ()
    elif changed == 'dataset':
        assert [r['macd_dif'] for r in page.rows] == [0.1]
    else:
        assert [r['close'] for r in page.rows] == [10.2, 10.4, 10.6]


def test_p4_batch1_prepared_history_success_is_consumed_once(tmp_path):
    from unittest.mock import patch
    from src.foundation.clients.local_lake import major_index_mins_reader as module

    _write_gold_bars(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', 5, None, None, 1000, None)
    with patch.object(module, '_enumerate_partitions', wraps=module._enumerate_partitions) as enumerate_parts:
        reader.history_source_signature(request, dataset='bars')
        first = reader.read_complete_history(request, dataset='bars', timeout_seconds=5)
        assert enumerate_parts.call_count == 1 and reader._prepared_history_partitions == {}
        second = reader.read_complete_history(request, dataset='bars', timeout_seconds=5)
        assert enumerate_parts.call_count == 2
    assert first.rows == second.rows
    assert [r['close'] for r in second.rows] == [10.2, 10.4, 10.6]


def test_p4_batch1_prepared_history_failure_cleans_up_and_next_call_rediscovers(tmp_path, monkeypatch):
    from unittest.mock import Mock, patch
    from src.foundation.clients.local_lake import major_index_mins_reader as module

    _write_gold_bars(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', 5, None, None, 1000, None)
    key = ('bars', 5, None, None)
    marker = IndexMinuteSourceContractError('injected first query error')
    real_connect, real_timer, real_query = duckdb.connect, module.Timer, module._query_rows
    connections, timers, queries = [], [], []

    class ObservedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.closes = 0

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def close(self):
            self.closes += 1
            return self.connection.close()

    def connect(*args, **kwargs):
        connection = ObservedConnection(real_connect(*args, **kwargs))
        connections.append(connection)
        return connection

    def timer(*args, **kwargs):
        value = real_timer(*args, **kwargs)
        value.cancel = cancel_wrapper = Mock(wraps=value.cancel)
        timers.append((value, cancel_wrapper))
        return value

    def fail_first_query(*args, **kwargs):
        assert key not in reader._prepared_history_partitions
        assert len(connections) == 1  # The actual method has opened its connection.
        queries.append(1)
        raise marker

    monkeypatch.setattr(duckdb, 'connect', connect)
    monkeypatch.setattr(module, 'Timer', timer)
    with patch.object(module, '_enumerate_partitions', wraps=module._enumerate_partitions) as enumerate_parts:
        reader.history_source_signature(request, dataset='bars')
        assert enumerate_parts.call_count == 1
        monkeypatch.setattr(module, '_query_rows', fail_first_query)
        with pytest.raises(IndexMinuteSourceContractError) as error:
            reader.read_complete_history(request, dataset='bars', timeout_seconds=5)
        assert error.value is marker and queries == [1]
        assert enumerate_parts.call_count == 1 and key not in reader._prepared_history_partitions
        assert connections[0].closes == timers[0][1].call_count == 1
        monkeypatch.setattr(module, '_query_rows', real_query)
        # Explicit new request after the failed call has exited; no new signature.
        page = reader.read_complete_history(request, dataset='bars', timeout_seconds=5)
        assert enumerate_parts.call_count == 2
    assert len(connections) == len(timers) == 2
    assert connections[1].closes == timers[1][1].call_count == 1
    assert all(not value.is_alive() or value.finished.is_set() for value, _ in timers)
    assert reader._prepared_history_partitions == {}
    assert [r['close'] for r in page.rows] == [10.2, 10.4, 10.6]
    assert [r['trade_time'].isoformat() for r in page.rows] == [
        '2026-08-11T09:35:00', '2026-08-11T09:40:00', '2026-08-11T09:45:00']


@pytest.mark.parametrize('entrypoint', ['signature', 'direct'])
@pytest.mark.parametrize('location', ['inside', 'outside'])
@pytest.mark.parametrize('link_kind', ['file', 'partition'])
def test_p4_batch1_first_history_discovery_still_rejects_links(tmp_path, entrypoint, location, link_kind):
    root = tmp_path / 'lake'
    target = _write_gold_bars(root)
    request = IndexMinuteReadRequest('000001.SH', 5, None, None, 1000, None)

    def invoke(reader):
        if entrypoint == 'signature':
            return reader.history_source_signature(request, dataset='bars')
        return reader.read_complete_history(request, dataset='bars', timeout_seconds=5)

    legal = invoke(MajorIndexMinsLakeReader(root))
    if entrypoint == 'signature':
        assert len(legal) == 1
    else:
        assert [r['close'] for r in legal.rows] == [10.2, 10.4, 10.6]
    moved = (root if location == 'inside' else tmp_path / 'outside') / 'moved'
    moved.parent.mkdir(parents=True, exist_ok=True)
    link = target if link_kind == 'file' else target.parent
    link.rename(moved)
    link.symlink_to(moved, target_is_directory=link_kind == 'partition')
    with pytest.raises(IndexMinuteSourceContractError, match='符号链接'):
        invoke(MajorIndexMinsLakeReader(root))


def _rewrite_fixture_with_foreign_row(path: Path, replacement: str) -> None:
    """Only rewrite pytest's isolated fixture; never a formal Lake file."""
    candidate = path.with_suffix('.fixture.parquet')
    connection = duckdb.connect(database=':memory:')
    try:
        connection.execute(f"""COPY (
            SELECT * FROM read_parquet($fixture, hive_partitioning=false)
            UNION ALL
            SELECT * REPLACE ('399001.SZ' AS ts_code {replacement})
            FROM read_parquet($fixture, hive_partitioning=false) LIMIT 4
        ) TO $output (FORMAT PARQUET)""", {"fixture": str(path), "output": str(candidate)})
    finally:
        connection.close()
    candidate.replace(path)


@pytest.mark.parametrize('dataset,invalid', [
    ('bars', ", CAST('NaN' AS DOUBLE) AS open"),
    ('bars', ", CAST('Infinity' AS DOUBLE) AS close"),
    ('bars', ", CAST(NULL AS DOUBLE) AS amount"),
    ('bars', ", '' AS exchange"),
    ('bars', ", 1 AS freq"),
    ('bars', ", DATE '2026-08-12' AS trade_date"),
    ('bars', ", TIMESTAMP '2026-08-11 15:01:00' AS trade_time"),
    ('indicators', ", CAST(1 AS SMALLINT) AS freq"),
    ('indicators', ", DATE '2026-08-12' AS trade_date"),
    ('indicators', ", TIMESTAMP '2026-08-11 09:30:00' AS trade_time"),
    ('indicators', ", '' AS params_key"),
    ('indicators', ", 0 AS indicator_version"),
    ('indicators', ", 0 AS observation_count"),
])
@pytest.mark.parametrize('freq', [60, 90, 120])
def test_complete_history_checks_contract_of_other_indices(tmp_path, dataset, invalid, freq):
    path = (_write_gold_bars if dataset == 'bars' else _write_gold)(tmp_path, freq=freq)
    _rewrite_fixture_with_foreign_row(path, invalid)
    request = IndexMinuteReadRequest('000001.SH', freq, None, None, 10, None)
    columns = ('close',) if dataset == 'bars' else ('macd_dif', 'macd_dea', 'macd')
    for selection in (None, columns):
        with pytest.raises(IndexMinuteSourceContractError):
            MajorIndexMinsLakeReader(tmp_path).read_complete_history(request, dataset=dataset, timeout_seconds=5, value_columns=selection)
    # A missing target must not hide corrupt rows belonging to another index.
    with pytest.raises(IndexMinuteSourceContractError):
        MajorIndexMinsLakeReader(tmp_path).read_complete_history(replace(request, ts_code='000300.SH'), dataset=dataset, timeout_seconds=5, value_columns=columns)


@pytest.mark.parametrize('dataset', ['bars', 'indicators'])
@pytest.mark.parametrize('freq', [60, 90, 120])
def test_complete_history_preserves_target_with_other_indices(tmp_path, dataset, freq):
    path = (_write_gold_bars if dataset == 'bars' else _write_gold)(tmp_path, freq=freq)
    request = IndexMinuteReadRequest('000001.SH', freq, None, None, 10, None)
    reader = MajorIndexMinsLakeReader(tmp_path)
    before = reader.read_complete_history(request, dataset=dataset, timeout_seconds=5)
    _rewrite_fixture_with_foreign_row(path, '')
    after = reader.read_complete_history(request, dataset=dataset, timeout_seconds=5)
    assert after.rows == before.rows
    assert reader.read_complete_history(replace(request, ts_code='000300.SH'), dataset=dataset, timeout_seconds=5).rows == ()


@pytest.mark.parametrize('dataset', ['bars', 'indicators'])
@pytest.mark.parametrize('freq', [60, 90, 120])
def test_complete_history_projection_preserves_all_keys_values_and_budget(tmp_path, dataset, freq):
    from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteHistoryBudgetError

    (_write_gold_bars if dataset == 'bars' else _write_gold)(tmp_path, freq=freq)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', freq, None, None, 1, None)
    full = reader.read_complete_history(request, dataset=dataset, timeout_seconds=5)
    values = ('close',) if dataset == 'bars' else ('macd_dif', 'macd_dea', 'macd')
    keys = ('ts_code', 'freq', 'trade_date', 'trade_time', *values)
    projected = reader.read_complete_history(request, dataset=dataset, timeout_seconds=5, value_columns=values)
    assert len(full.rows[0]) == (11 if dataset == 'bars' else 23)
    assert projected.rows == tuple({key: row[key] for key in keys} for row in full.rows)
    assert projected.count == full.count and projected.scanned_file_count == full.scanned_file_count
    assert not projected.has_more and projected.next_cursor is None
    if dataset == 'bars':
        with pytest.raises(IndexMinuteHistoryBudgetError):
            reader.read_complete_history(request, dataset=dataset, timeout_seconds=5, max_rows=2, value_columns=values)


@pytest.mark.parametrize('dataset', ['bars', 'indicators'])
@pytest.mark.parametrize('columns', [('unknown',), ('vwap',), ('trade_date',), ('macd', 'macd'), ("close; DROP TABLE x",), ()])
def test_complete_history_projection_rejects_invalid_columns_even_for_empty_source(tmp_path, dataset, columns):
    with pytest.raises(IndexMinuteRequestError):
        MajorIndexMinsLakeReader(tmp_path).read_complete_history(
            IndexMinuteReadRequest('000001.SH', 60, None, None, 10, None),
            dataset=dataset, timeout_seconds=5, value_columns=columns,
        )


@pytest.mark.parametrize('freq', [60, 90, 120])
def test_complete_history_pair_matches_sequential_projection_with_halved_resources(tmp_path, monkeypatch, freq):
    _write_gold_bars(tmp_path, freq=freq)
    _write_gold(tmp_path, freq=freq)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest('000001.SH', freq, None, None, 1, None)
    expected = tuple(reader.read_complete_history(request, dataset=dataset, value_columns=columns, timeout_seconds=5)
                     for dataset, columns in (('bars', ('close',)), ('indicators', ('macd_dif', 'macd_dea', 'macd'))))
    original_connect = duckdb.connect
    observed = []
    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        observed.append(connection.execute("SELECT current_setting('threads'), current_setting('memory_limit')").fetchone())
        return connection
    monkeypatch.setattr(duckdb, 'connect', connect)
    actual = reader.read_complete_history_pair(request, timeout_seconds=5,
        bar_value_columns=('close',), indicator_value_columns=('macd_dif', 'macd_dea', 'macd'))
    assert [page.rows for page in actual] == [page.rows for page in expected]
    assert observed == [(1, '244.1 MiB'), (1, '244.1 MiB')]


def test_complete_history_pair_overlaps_reads_and_waits_for_cleanup_on_error(tmp_path, monkeypatch):
    from threading import Event

    reader = MajorIndexMinsLakeReader(tmp_path)
    started = {dataset: Event() for dataset in ('bars', 'indicators')}
    cleaned = {dataset: Event() for dataset in started}
    marker = IndexMinuteSourceContractError('invalid bars')
    timeouts = []
    def read(*args, dataset, timeout_seconds, duckdb_config, **kwargs):
        started[dataset].set()
        try:
            assert started['indicators' if dataset == 'bars' else 'bars'].wait(2)
            assert duckdb_config == {'threads': '1', 'memory_limit': '256MB'}
            timeouts.append(timeout_seconds)
            if dataset == 'bars':
                raise marker
            raise IndexMinuteSourceContractError('invalid indicators')
        finally:
            cleaned[dataset].set()
    monkeypatch.setattr(reader, '_read_complete_history', read)
    with pytest.raises(IndexMinuteSourceContractError) as error:
        reader.read_complete_history_pair(IndexMinuteReadRequest('000001.SH', 60, None, None, 10, None), timeout_seconds=3)
    assert error.value is marker
    assert all(event.is_set() for event in cleaned.values())
    assert len(timeouts) == 2 and all(0 < timeout <= 3 for timeout in timeouts)


def test_complete_history_pair_does_not_start_expired_reads(tmp_path, monkeypatch):
    from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteHistoryBudgetError

    reader = MajorIndexMinsLakeReader(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('expired pair must not open a connection')
    monkeypatch.setattr(reader, '_read_complete_history', forbidden)
    with pytest.raises(IndexMinuteHistoryBudgetError):
        reader.read_complete_history_pair(IndexMinuteReadRequest('000001.SH', 60, None, None, 10, None), timeout_seconds=0)
