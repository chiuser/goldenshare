"""LLD21.13 step 3: real HTTP/parser, temporary SQL, independent literal results.

Small projected inputs follow the existing lifecycle/suspend/identity producer
columns used by calculate_stk_factor_pro_coverage. A separate case uses complete
producer-shaped Parquet and the archived one-stock/five-day true source sample.
All HTTP replies are local; no source credentials, formal instance or lake writes.
"""

import json
from dataclasses import replace
from datetime import date
from unittest.mock import patch

import pytest

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as readiness
from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    prepare_stk_factor_pro_coverage_inputs,
    release_stk_factor_pro_coverage_inputs,
)
from orchestrator.defs.source_readiness import stk_factor_pro as probe
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.download_errors import (
    DownloadCancelled,
    DownloadError,
)
from orchestrator.tushare_download.download_errors import (
    DownloadErrorCode as Code,
)
from orchestrator.tushare_download.download_models import DownloadControl
from orchestrator.tushare_download.source_transport import SystemClock
from tests.stk_factor_pro_history_test_support import saved_real_rows
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.tushare_download.fixtures import FakeClock
from tests.tushare_download.test_tushare_download_http_integration import (
    Reply,
    localhost_source,
    success,
)

T = date(2026, 10, 16)
A, B, C, ALIAS = "000001.SZ", "600000.SH", "000002.SZ", "000013.SZ"
SOURCE_DAY = "20261016"


def inputs(conn, *, listed=(A, B), optional=(B,), suspended=(), mappings=None):
    conn.execute(
        "CREATE TEMP TABLE life(ts_code VARCHAR,list_date DATE,delist_date DATE)"
    )
    conn.execute(
        "INSERT INTO life SELECT unnest(?::VARCHAR[]),DATE '2000-01-01',NULL", [listed]
    )
    # B listed on Thursday; it is mandatory on Friday unless this case explicitly
    # moves its listing to Friday to exercise the optional first day.
    conn.execute("UPDATE life SET list_date=DATE '2026-10-15' WHERE ts_code=?", [B])
    conn.execute(
        "UPDATE life SET list_date=? WHERE ts_code IN (SELECT unnest(?::VARCHAR[]))",
        [T, optional],
    )
    conn.execute(
        "CREATE TEMP TABLE susp(ts_code VARCHAR,trade_date DATE,suspend_type VARCHAR,suspend_timing VARCHAR)"
    )
    conn.execute(
        "INSERT INTO susp SELECT unnest(?::VARCHAR[]),?::DATE,'S',NULL", [suspended, T]
    )
    conn.execute(
        "CREATE TEMP TABLE identity(source_ts_code VARCHAR,latest_ts_code VARCHAR,valid_from DATE,valid_to DATE)"
    )
    mappings = tuple((c, c) for c in {*listed, C}) if mappings is None else mappings
    conn.execute(
        "INSERT INTO identity SELECT unnest(?::VARCHAR[]),unnest(?::VARCHAR[]),DATE '1990-01-01',NULL",
        [tuple(x for x, _ in mappings), tuple(y for _, y in mappings)],
    )
    return {
        "trade_date": T,
        "is_open": True,
        "unknown_input_kinds": (),
        "reason": "",
        "relations": {"lifecycle": "life", "suspend": "susp", "identity": "identity"},
    }


def run(conn, prepared, url, *, clock=None, control=None, **config_changes):
    return probe.probe_stk_factor_pro_source(
        conn,
        target_trade_date=T,
        coverage_inputs=prepared,
        config=replace(
            ConfigurationSnapshot(token="local-test-only", base_url=url),
            **config_changes,
        ),
        clock=clock or SystemClock(),
        control=control or DownloadControl(),
    )


def assert_released(conn):
    assert not conn.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name='stk_factor_pro_source_probe'"
    ).fetchone()[0]


@pytest.mark.parametrize(
    "listed,optional,suspended,actual,expected",
    [
        ((A, B), (B,), (), (A,), (True, 1, 1, 0, 0, 1, 0)),
        ((A, B), (B,), (), (A, B), (True, 1, 1, 0, 0, 1, 1)),
        ((A, B), (), (), (A,), (False, 2, 1, 1, 0, 0, 0)),
        ((A, B), (B,), (), (), (False, 1, 0, 1, 0, 1, 0)),
        ((A, B), (B,), (), (A, C), (False, 1, 2, 0, 1, 1, 0)),
        ((A, B, C), (B,), (C,), (A, C), (False, 1, 2, 0, 1, 1, 0)),
    ],
)
def test_exact_codes_first_day_and_next_day(
    tmp_path, listed, optional, suspended, actual, expected
):
    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: success([[c, SOURCE_DAY] for c in actual])) as (
            url,
            requests,
        ),
    ):
        prepared = inputs(conn, listed=listed, optional=optional, suspended=suspended)
        result = run(conn, prepared, url)
        counts = result.coverage_counts
        assert (
            result.ready,
            counts.expected_count,
            counts.actual_count,
            counts.missing_count,
            counts.extra_count,
            result.optional_count,
            result.optional_present_count,
        ) == expected
        assert result.source_row_count == result.source_code_count == len(actual)
        assert result.request_count == result.page_count == 1
        assert result.error_code is None
        assert result.optional_sample_codes == ((B,) if optional else ())
        assert result.elapsed_ms > 0
        _, payload, _ = requests[0]
        assert payload == {
            "api_name": "stk_factor_pro",
            "token": "local-test-only",
            "fields": "ts_code,trade_date",
            "params": {"trade_date": SOURCE_DAY, "limit": 10000, "offset": 0},
        }
        assert_released(conn)


@pytest.mark.parametrize("size", [10000, 10001])
def test_full_page_requires_terminal_page_and_fixed_capacity(tmp_path, size):
    codes = tuple(f"{i:06d}.SZ" for i in range(1, size + 1))

    def respond(payload, _):
        offset = payload["params"]["offset"]
        return success([[c, SOURCE_DAY] for c in codes[offset : offset + 10000]])

    with connection(tmp_path) as conn, localhost_source(respond) as (url, requests):
        prepared = inputs(conn, listed=codes, optional=())
        result = run(conn, prepared, url)
        assert result.ready
        assert result.source_row_count == result.source_code_count == size
        assert result.coverage_counts.expected_count == size
        assert result.coverage_counts.actual_count == size
        assert result.request_count == result.page_count == 2
        assert [p[1]["params"] for p in requests] == [
            {"trade_date": SOURCE_DAY, "limit": 10000, "offset": n} for n in (0, 10000)
        ]
        assert_released(conn)


@pytest.mark.parametrize("second", ["duplicate", "failure", "empty", "schema", "date"])
def test_full_equal_first_page_cannot_hide_later_failure(tmp_path, second):
    codes = tuple(f"{i:06d}.SZ" for i in range(1, 10001))

    def respond(_, number):
        if number == 1:
            return success([[c, SOURCE_DAY] for c in codes])
        if second == "duplicate":
            return success([[codes[0], SOURCE_DAY]])
        if second == "schema":
            return Reply(
                200,
                b'{"code":0,"data":{"fields":["ts_code","close"],"items":[["000001.SZ",1]]}}',
            )
        if second == "date":
            return success([[C, "20261015"]])
        return Reply(503, b"unavailable") if second == "failure" else success()

    with connection(tmp_path) as conn, localhost_source(respond) as (url, requests):
        prepared = inputs(conn, listed=codes, optional=())
        with patch.object(
            probe,
            "calculate_stk_factor_pro_coverage",
            wraps=probe.calculate_stk_factor_pro_coverage,
        ) as calculate:
            result = run(conn, prepared, url)
        assert result.ready is (second == "empty")
        assert result.request_count == len(requests) == 2
        assert calculate.call_count == (1 if second == "empty" else 0)
        if second != "empty":
            assert result.coverage_counts is None and result.source_code_count is None
            assert result.error_code == (
                Code.TRANSIENT_SOURCE if second == "failure" else Code.SOURCE_PROTOCOL
            )
        assert_released(conn)


@pytest.mark.parametrize(
    "reply,code",
    [
        (
            Reply(200, b'{"code":9,"msg":"permission denied"}'),
            Code.PERMISSION_OR_PARAMETER,
        ),
        (Reply(429, b"limited"), Code.RATE_LIMIT),
        (Reply(200, b"invalid json"), Code.SOURCE_PROTOCOL),
        (success([[A, "20261015"]]), Code.SOURCE_PROTOCOL),
        (success([[A, None]]), Code.SOURCE_PROTOCOL),
        (success([[None, SOURCE_DAY]]), Code.SOURCE_PROTOCOL),
        (success([["", SOURCE_DAY]]), Code.SOURCE_PROTOCOL),
        (success([[1, SOURCE_DAY]]), Code.SOURCE_PROTOCOL),
        (success([[A, SOURCE_DAY], [A, SOURCE_DAY]]), Code.SOURCE_PROTOCOL),
        (
            Reply(
                200,
                json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "fields": ["ts_code", "trade_date", "close"],
                            "items": [[A, SOURCE_DAY, 1]],
                        },
                    }
                ).encode(),
            ),
            Code.SOURCE_PROTOCOL,
        ),
        (
            Reply(200, b'{"code":0,"data":{"fields":["ts_code"],"items":[]}}'),
            Code.SOURCE_PROTOCOL,
        ),
        (Reply(200, b'{"code":0,"data":null}'), Code.NO_VALID_RESPONSE),
    ],
)
def test_bad_source_never_becomes_empty_success_or_retries(tmp_path, reply, code):
    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: reply) as (url, requests),
    ):
        prepared = inputs(conn)
        with patch.object(
            probe,
            "calculate_stk_factor_pro_coverage",
            wraps=probe.calculate_stk_factor_pro_coverage,
        ) as calculate:
            result = run(conn, prepared, url)
        assert not result.ready and result.error_code == code
        assert result.request_count == len(requests) == 1
        assert result.coverage_counts is None and result.source_code_count is None
        assert not calculate.called
        assert_released(conn)


def test_reordered_fields_and_identity_alias_are_not_filtered(tmp_path):
    reply = Reply(
        200,
        json.dumps(
            {
                "code": 0,
                "data": {
                    "fields": ["trade_date", "ts_code"],
                    "items": [[SOURCE_DAY, ALIAS]],
                },
            }
        ).encode(),
    )
    with connection(tmp_path) as conn, localhost_source(lambda *_: reply) as (url, _):
        prepared = inputs(conn, mappings=((A, A), (B, B), (ALIAS, A)))
        result = run(conn, prepared, url)
        assert result.ready and result.coverage_counts.actual_count == 1


def test_unknown_identity_is_not_discarded(tmp_path):
    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: success([[A, SOURCE_DAY], [C, SOURCE_DAY]])) as (
            url,
            _,
        ),
    ):
        result = run(conn, inputs(conn, mappings=((A, A), (B, B))), url)
        assert not result.ready and result.error_code is None
        assert result.source_code_count == 2
        assert result.coverage_counts.expected_count is None
        assert result.coverage_counts.identity_unmapped_count == 1


@pytest.mark.parametrize("kind", ["unknown", "closed"])
def test_unready_inputs_do_not_request_or_create_probe_table(tmp_path, kind):
    with connection(tmp_path) as conn:
        prepared = inputs(conn)
        prepared.update(
            {"unknown_input_kinds": ("lifecycle",), "reason": "missing lifecycle"}
            if kind == "unknown"
            else {"is_open": False}
        )
        with patch.object(probe.HttpProTransport, "fetch_page") as fetch:
            result = run(conn, prepared, "http://127.0.0.1")
        assert not result.ready and not fetch.called
        assert result.request_count == result.page_count == 0
        assert result.coverage_counts is None
        assert_released(conn)


@pytest.mark.parametrize(
    "elapsed,ready,requests_expected",
    [(40, True, 2), (44.95, False, 1), (45, False, 1)],
)
def test_pages_share_one_deadline(
    tmp_path, monkeypatch, elapsed, ready, requests_expected
):
    codes = tuple(f"{i:06d}.SZ" for i in range(1, 10001))
    clock, configurations = FakeClock(), []
    fetch = probe.HttpProTransport.fetch_page

    def timed(self, request, config, *args):
        configurations.append(config)
        result = fetch(self, request, config, *args)
        if len(configurations) == 1:
            clock.seconds += elapsed
        return result

    monkeypatch.setattr(probe.HttpProTransport, "fetch_page", timed)
    with (
        connection(tmp_path) as conn,
        localhost_source(
            lambda _, n: (
                success([[c, SOURCE_DAY] for c in codes]) if n == 1 else success()
            )
        ) as (url, requests),
    ):
        result = run(conn, inputs(conn, listed=codes, optional=()), url, clock=clock)
        assert result.ready is ready
        assert len(requests) == requests_expected
        if ready:
            last = configurations[1]
            assert (
                last.connect_timeout_seconds,
                last.read_timeout_seconds,
                last.request_timeout_seconds,
            ) == (5, 5, 5)
        else:
            assert result.error_code == Code.TRANSIENT_SOURCE
            assert result.coverage_counts is None
        assert_released(conn)


@pytest.mark.parametrize(
    "cancel,source_failure", [(False, False), (True, False), (False, True)]
)
def test_close_failure_never_turns_green_or_replaces_cancellation(
    tmp_path, monkeypatch, cancel, source_failure
):
    close, clear = probe.HttpProTransport.close, probe.UnitMemory.clear
    cleared = []

    def close_failure(self):
        close(self)
        raise DownloadError(Code.CLEANUP)

    def cleared_memory(self):
        clear(self)
        cleared.append(not self._roots and not self._nodes)

    monkeypatch.setattr(probe.HttpProTransport, "close", close_failure)
    monkeypatch.setattr(probe.UnitMemory, "clear", cleared_memory)
    with (
        connection(tmp_path) as conn,
        localhost_source(
            lambda *_: (
                Reply(503, b"unavailable")
                if source_failure
                else success([[A, SOURCE_DAY]])
            )
        ) as (url, requests),
    ):
        prepared = inputs(conn)
        if cancel:
            with pytest.raises(DownloadCancelled) as caught:
                run(
                    conn,
                    prepared,
                    url,
                    control=DownloadControl(is_cancelled=lambda: True),
                )
            assert caught.value.__notes__
            assert not requests
        else:
            result = run(conn, prepared, url)
            assert not result.ready
            assert result.error_code == (
                Code.TRANSIENT_SOURCE if source_failure else Code.CLEANUP
            )
            if source_failure:
                assert "清理同时失败" in result.reason
        assert cleared == [True]
        assert_released(conn)


def test_reuses_prepared_keys_and_never_reads_technical_factor_files(tmp_path):
    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: success([[A, SOURCE_DAY]])) as (url, _),
    ):
        prepared = inputs(conn)
        with patch.object(
            readiness,
            "_prepare_stk_factor_pro_expected_keys",
            wraps=readiness._prepare_stk_factor_pro_expected_keys,
        ) as expected:
            for _ in range(2):
                with patch(
                    "pathlib.Path.open",
                    side_effect=AssertionError("probe must not open files"),
                ):
                    result = run(conn, prepared, url)
                assert result.ready
                assert_released(conn)
        assert expected.call_count == 1


def test_archived_source_projection_with_real_preparation_and_http(tmp_path):
    # batch1 README: 000001.SZ, 2026-10-12..16, five complete 261-field rows.
    projected = [
        [values[0], values[1]]
        for values in saved_real_rows()
        if values[1] == SOURCE_DAY
    ]
    assert projected == [["000001.SZ", "20261016"]]
    with connection(tmp_path) as conn:
        lake, inherited, known = tmp_path / "lake", {}, {}
        upstream(conn, lake, (T,), codes=(A,))
        prepared = prepare_stk_factor_pro_coverage_inputs(
            conn,
            lake_root=lake,
            trade_date=T,
            inherited_facts=inherited,
            known_records=known,
        )
        assert prepared["unknown_input_kinds"] == ()
        with localhost_source(lambda *_: success(projected)) as (url, requests):
            result = run(conn, prepared, url)
        assert result.ready and result.request_count == len(requests) == 1
        assert (
            result.source_row_count,
            result.coverage_counts.expected_count,
            result.coverage_counts.actual_count,
        ) == (1, 1, 1)
        release_stk_factor_pro_coverage_inputs(conn, inherited_facts=inherited)
        assert_released(conn)


def test_oversized_page_is_not_trusted(tmp_path):
    with (
        connection(tmp_path) as conn,
        localhost_source(
            lambda *_: success([[f"{i:06d}.SZ", SOURCE_DAY] for i in range(1, 10002)])
        ) as (url, requests),
    ):
        result = run(conn, inputs(conn), url)
        assert not result.ready and result.error_code == Code.SOURCE_PROTOCOL
        assert result.coverage_counts is None and len(requests) == 1
        assert_released(conn)


def test_ambiguous_identity_stays_unknown(tmp_path):
    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: success([[ALIAS, SOURCE_DAY]])) as (url, _),
    ):
        result = run(
            conn, inputs(conn, mappings=((A, A), (B, B), (ALIAS, A), (ALIAS, B))), url
        )
        assert not result.ready and result.coverage_counts.expected_count is None
        assert result.coverage_counts.identity_ambiguous_count == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_real_waiting_response_timeout_or_cancel_closes_handles(
    tmp_path, monkeypatch, cancel
):
    from threading import Event

    instances = []
    transport_class = probe.HttpProTransport

    def transport(clock):
        instance = transport_class(clock)
        instances.append(instance)
        return instance

    monkeypatch.setattr(probe, "HttpProTransport", transport)
    with (
        connection(tmp_path) as conn,
        localhost_source(
            lambda *_: Reply(200, success([[A, SOURCE_DAY]]).body, wait=Event())
        ) as (url, requests),
    ):
        prepared = inputs(conn)
        settings = {
            "connect_timeout_seconds": 0.05,
            "read_timeout_seconds": 0.1,
            "request_timeout_seconds": 0.5,
            "poll_interval_seconds": 0.005,
        }
        if cancel:
            with pytest.raises(DownloadCancelled):
                run(
                    conn,
                    prepared,
                    url,
                    control=DownloadControl(is_cancelled=lambda: bool(requests)),
                    **settings,
                )
        else:
            result = run(conn, prepared, url, **settings)
            assert not result.ready and result.error_code == Code.TRANSIENT_SOURCE
            assert result.request_count == 1 and result.coverage_counts is None
        assert len(requests) == 1 and instances[0]._handles == []
        assert_released(conn)


def test_cleanup_time_counts_against_deadline(tmp_path, monkeypatch):
    clock = FakeClock()
    close = probe.HttpProTransport.close

    def slow_close(self):
        close(self)
        clock.seconds += 45

    monkeypatch.setattr(probe.HttpProTransport, "close", slow_close)
    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: success([[A, SOURCE_DAY]])) as (url, _),
    ):
        result = run(conn, inputs(conn), url, clock=clock)
        assert not result.ready and result.error_code == Code.TRANSIENT_SOURCE
        assert result.elapsed_ms == 45000
        assert_released(conn)


def test_local_sql_error_propagates_and_still_releases(tmp_path):
    class BrokenInsert:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, parameters=None):
            if sql.startswith("INSERT INTO stk_factor_pro_source_probe"):
                raise RuntimeError("local SQL fault")
            return (
                self.conn.execute(sql)
                if parameters is None
                else self.conn.execute(sql, parameters)
            )

    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: success([[A, SOURCE_DAY]])) as (url, _),
    ):
        prepared = inputs(conn)
        with pytest.raises(RuntimeError, match="local SQL fault"):
            run(BrokenInsert(conn), prepared, url)
        assert_released(conn)


@pytest.mark.parametrize("budget", ["response", "memory"])
def test_existing_capacity_limits_cannot_return_ready(tmp_path, budget):
    reply = success([[A, SOURCE_DAY]])
    base = ConfigurationSnapshot(token="local-test-only", base_url="http://127.0.0.1")
    changes = (
        {"max_response_bytes": len(reply.body) - 1}
        if budget == "response"
        else {
            "unit_memory_limit_bytes": base.working_reserve_bytes
            + base.max_request_bytes
        }
    )
    with (
        connection(tmp_path) as conn,
        localhost_source(lambda *_: reply) as (url, requests),
    ):
        result = run(conn, inputs(conn), url, **changes)
        assert not result.ready and result.error_code == Code.CAPACITY
        assert result.coverage_counts is None and result.source_code_count is None
        assert len(requests) == (1 if budget == "response" else 0)
        assert_released(conn)
