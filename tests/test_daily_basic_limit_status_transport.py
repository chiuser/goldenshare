"""The real bounded HTTP decoder, using the observed 19-field row on loopback."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import threading
import time
from unittest.mock import Mock

import pytest

from src.foundation.clients.bounded_tushare_call import BoundedTushareError, call_bounded
from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.ingestion.daily_basic_limit_status import DailyBasicLimitStatusService
from src.foundation.ingestion.errors import IngestionSourceError
from src.foundation.ingestion.run_errors import IngestionCanceledError
from tests.test_daily_basic_limit_status import SOURCE_FIELDS, SOURCE_ROW
from tests.test_daily_basic_limit_status_backfill import CONFIG, DOWNLOAD_FIELDS, payload

pytest_plugins = ("tests.test_daily_basic_limit_status_backfill",)


def wire(row=SOURCE_ROW, fields=SOURCE_FIELDS):
    return json.dumps({"code": 0, "msg": "", "data": {
        "fields": list(fields), "items": [[row[field] for field in fields]],
    }}).encode()


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        requests = []

        def log_message(self, *args):
            pass

        def do_POST(self):
            Handler.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            try:
                if self.path == "/slow":
                    for _ in range(100):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(.05)
                else:
                    request = Handler.requests[-1]
                    fields = (DOWNLOAD_FIELDS if request["api_name"] == "daily_basic"
                              and request["fields"] == ",".join(DOWNLOAD_FIELDS) else SOURCE_FIELDS)
                    self.wfile.write(b"bad-json" if self.path == "/invalid" else wire(fields=fields))
            except (BrokenPipeError, ConnectionResetError):
                pass  # A deliberately canceled/expired client closes this fixture connection.

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", Handler.requests
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def invoke(url, **overrides):
    return call_bounded(base_url=url, payload={"api_name": "daily_basic", "token": "test-placeholder",
        "fields": ",".join(SOURCE_FIELDS), "params": {"trade_date": "20261110", "limit": 6000, "offset": 0}},
        maximum=overrides.pop("maximum", None), timeout=overrides.pop("timeout", 3),
        check=overrides.pop("check", lambda: None), tick=overrides.pop("tick", lambda: None),
        response_contract="daily_basic/v1", **overrides)


@pytest.mark.parametrize("fields", [SOURCE_FIELDS, DOWNLOAD_FIELDS])
def test_real_client_returns_requested_fields_without_coercing_status(server, fields):
    url, requests = server
    client = TushareHttpClient(token="test-placeholder", base_url=url)
    result = client.call_bounded(api_name="daily_basic", params={"trade_date": "20261110", "limit": 6000, "offset": 0},
        fields=fields, maximum=None, timeout=3, check=lambda: None, tick=lambda: None,
        before_request=lambda: None, response_contract="daily_basic/v1")
    assert len(result) == 1 and tuple(result[0]) == fields
    assert result[0]["limit_status"] == 4 and type(result[0]["limit_status"]) is int
    assert requests[0]["fields"] == ",".join(fields)
    assert requests[0]["params"] == {"trade_date": "20261110", "limit": 6000, "offset": 0}


def test_daily_contract_does_not_enforce_bytes_but_rejects_invalid_json(server):
    url, requests = server
    result = invoke(url, maximum=len(wire()) - 1)
    assert result[0] == "rows" and len(result[1]) == 1
    assert invoke(url + "/invalid")[:2] == ("bounded_error", "daily_basic.source_payload_invalid")
    assert len(requests) == 2  # No hidden retry.


@pytest.mark.parametrize("contract,api,prefix", [
    (None, "anns_d", "anns_d"),
    ("stock_weekly_adj/v1", "stk_week_month_adj", "weekly_adj"),
    ("index_period_raw/v1", "index_weekly", "index_period_raw"),
])
def test_other_contracts_still_stop_before_decoding_an_oversized_body(server, contract, api, prefix):
    # The daily-shaped fixture is deliberately not a valid old-contract payload:
    # its byte limit must stop delivery before any JSON/business validation.
    url, requests = server
    result = call_bounded(base_url=url, payload={"api_name": api, "params": {}, "fields": ""},
        maximum=len(wire()) - 1, timeout=3, check=lambda: None, tick=lambda: None, response_contract=contract)
    assert result[:2] == ("bounded_error", f"{prefix}.response_size_exceeded")
    assert len(requests) == 1


def test_request_cancellation_and_deadline_clean_up_the_existing_child(server):
    url, requests = server
    baseline = {child.pid for child in multiprocessing.active_children()}
    ticks = []

    def check():
        if requests:
            raise IngestionCanceledError("cancel after HTTP acceptance")

    with pytest.raises(IngestionCanceledError):
        invoke(url + "/slow", check=check, tick=lambda: ticks.append(True))
    assert {child.pid for child in multiprocessing.active_children()} == baseline
    with pytest.raises(BoundedTushareError) as caught:
        invoke(url + "/slow", timeout=1, tick=lambda: ticks.append(True))
    assert caught.value.code == "daily_basic.source_deadline_exceeded"
    assert ticks
    assert {child.pid for child in multiprocessing.active_children()} == baseline


@pytest.mark.parametrize("api,fields", [
    ("anns_d", SOURCE_FIELDS), ("daily_basic", SOURCE_FIELDS[:-1]),
    ("daily_basic", ("ts_code", "trade_date", "close")),
    ("daily_basic", tuple(reversed(DOWNLOAD_FIELDS))),
])
def test_both_contract_boundaries_reject_misbound_requests_before_network(api, fields):
    client = TushareHttpClient(token="test-placeholder", base_url="http://unused.invalid")
    with pytest.raises(BoundedTushareError) as outer:
        client.call_bounded(api_name=api, params={}, fields=fields, maximum=1, timeout=1,
            check=lambda: None, tick=lambda: None, before_request=lambda: None, response_contract="daily_basic/v1")
    with pytest.raises(BoundedTushareError) as inner:
        call_bounded(base_url="http://unused.invalid", payload={"api_name": api, "fields": ",".join(fields)},
            maximum=1, timeout=1, check=lambda: None, tick=lambda: None, response_contract="daily_basic/v1")
    assert outer.value.code == inner.value.code == "daily_basic.delivery_contract_mismatch"


def test_full_page_has_one_empty_terminator_and_short_page_stops_without_another_request():
    connector = Mock()
    row = {field: SOURCE_ROW[field] for field in DOWNLOAD_FIELDS}
    connector.call_bounded.side_effect = [[row] * 6000, []]
    value = DailyBasicLimitStatusService(session_factory=None, connector=connector)
    result = value._fetch(payload(serving_count=6000), config=CONFIG, check=lambda: None, observe=lambda *a, **k: None)
    assert len(result) == 6000
    assert [call.kwargs["params"]["offset"] for call in connector.call_bounded.call_args_list] == [0, 6000]
    assert all(call.kwargs["params"]["limit"] == 6000 for call in connector.call_bounded.call_args_list)
    assert all(call.kwargs["fields"] == DOWNLOAD_FIELDS for call in connector.call_bounded.call_args_list)
    connector.call_bounded.reset_mock(side_effect=True)
    connector.call_bounded.return_value = [row]
    assert value._fetch(payload(), config=CONFIG, check=lambda: None, observe=lambda *a, **k: None) == [row]
    assert connector.call_bounded.call_count == 1


def test_more_full_pages_than_frozen_target_allows_cannot_publish():
    connector = Mock()
    connector.call_bounded.return_value = [{field: SOURCE_ROW[field] for field in DOWNLOAD_FIELDS}] * 6000
    value = DailyBasicLimitStatusService(session_factory=None, connector=connector)
    with pytest.raises(IngestionSourceError) as caught:
        value._fetch(payload(), config=CONFIG, check=lambda: None, observe=lambda *a, **k: None)
    assert caught.value.structured_error.error_code == "daily_basic_limit_status.pagination_incomplete"
    assert connector.call_bounded.call_count == 1


def test_three_field_http_to_two_table_transaction(database, server, monkeypatch):
    from src.foundation.connectors.tushare_connector import TushareSourceConnector
    from tests.test_daily_basic_limit_status_backfill import read_rows, source_rows

    engine, factory = database
    url, requests = server
    rows = source_rows()
    body = json.dumps({"code": 0, "msg": "", "data": {"fields": list(DOWNLOAD_FIELDS),
        "items": [[row[field] for field in DOWNLOAD_FIELDS] for row in rows]}}).encode()
    monkeypatch.setitem(globals(), "wire", lambda **kwargs: body)
    connector = TushareSourceConnector(TushareHttpClient(token="test-placeholder", base_url=url))
    value = DailyBasicLimitStatusService(session_factory=factory, connector=connector)
    result = value.execute_day(payload(), config=CONFIG,
                               check=lambda: None, observe=lambda *a, **k: None)
    assert (result["rows_fetched"], result["rows_saved"], result["raw_changed"], result["serving_changed"]) == (2, 2, 2, 2)
    assert len(requests) == 1
    assert requests[0]["fields"] == "ts_code,trade_date,limit_status"
    for persisted in read_rows(engine):
        assert [row["limit_status"] for row in persisted] == [4, 0, None, None]
        assert all(row["pe"] == -17 and row["close"] is None for row in persisted)


def test_pre_listing_missing_row_over_real_http_keeps_null(before_listing_database, server, monkeypatch):
    from src.foundation.connectors.tushare_connector import TushareSourceConnector
    from tests.test_daily_basic_limit_status_backfill import PRE_LISTING_DAY, read_rows

    engine, factory = before_listing_database
    url, requests = server
    # Actual Tushare wire shape; the returned stock/status is an artificial valid
    # row. The missing target and its dates use the independent LLD §22 evidence.
    body = json.dumps({"code": 0, "msg": "", "data": {
        "fields": ["ts_code", "trade_date", "limit_status"],
        "items": [["000001.SZ", "20181224", 0]],
    }}).encode()
    monkeypatch.setitem(globals(), "wire", lambda **kwargs: body)
    connector = TushareSourceConnector(TushareHttpClient(token="test-placeholder", base_url=url))
    value = DailyBasicLimitStatusService(session_factory=factory, connector=connector)
    result = value.execute_day(payload(PRE_LISTING_DAY), config=CONFIG,
                               check=lambda: None, observe=lambda *a, **k: None)
    assert (result["rows_fetched"], result["rows_saved"], result["raw_changed"], result["serving_changed"]) == (1, 2, 1, 1)
    assert result["null_before_listing_codes"] == ["920964.BJ"]
    assert len(requests) == 1 and requests[0]["fields"] == "ts_code,trade_date,limit_status"
    assert requests[0]["params"] == {"trade_date": "20181224", "limit": 6000, "offset": 0}
    for rows in read_rows(engine):
        assert {(row["ts_code"], row["limit_status"]) for row in rows
                if row["trade_date"] == PRE_LISTING_DAY} == {("000001.SZ", 0), ("920964.BJ", None)}
