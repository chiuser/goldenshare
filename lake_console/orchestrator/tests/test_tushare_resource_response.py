"""Real installed SDK with an HTTP substitute; no network or real credentials."""

import json

import pytest
import requests

from orchestrator.defs.resources import TushareResource, TushareResponseError


@pytest.fixture
def http_reply(monkeypatch):
    calls = []

    def install(status=200, payload=None, body=None, error=None):
        def post(url, **kwargs):
            assert kwargs["json"]["token"] == "isolated-test-token"
            calls.append((url, kwargs))
            if error:
                raise error
            response = requests.Response()
            response.status_code = status
            response._content = (
                body.encode() if body is not None else json.dumps(payload).encode()
            )
            return response

        monkeypatch.setattr(requests, "post", post)
        return calls

    install(error=AssertionError("HTTP substitute not configured"))
    return install


def call_resource(fields=("ts_code", "close")):
    return TushareResource(token="isolated-test-token").call(
        "daily", {"trade_date": "20260909"}, fields
    )


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 502, 503, 504])
def test_http_error_cannot_become_empty_data(http_reply, status):
    calls = http_reply(status=status, body="service unavailable")
    with pytest.raises(TushareResponseError, match="no response fields") as error:
        call_resource()
    assert len(calls) == 1
    assert "isolated-test-token" not in str(error.value)


@pytest.mark.parametrize("items", [[], [["600000.SH", 10.25]]])
def test_declared_empty_and_nonempty_results_are_preserved(http_reply, items):
    calls = http_reply(
        payload={
            "code": 0,
            "msg": "",
            "data": {"fields": ["ts_code", "close"], "items": items},
        }
    )
    result = call_resource()
    assert result.columns == ("ts_code", "close")
    assert result.rows == (
        [] if not items else [{"ts_code": "600000.SH", "close": 10.25}]
    )
    assert result.metadata["row_count"] == len(items)
    assert calls[0][1]["json"]["fields"] == "ts_code,close"
    assert "isolated-test-token" not in json.dumps(result.metadata)


@pytest.mark.parametrize(
    "payload,body,error,expected_error,message",
    [
        (
            {"code": -2001, "msg": "permission denied", "data": None},
            None,
            None,
            Exception,
            "permission denied",
        ),
        (None, "not-json", None, ValueError, "Expecting value"),
        (
            {"code": 0, "data": {"fields": [], "items": []}},
            None,
            None,
            TushareResponseError,
            "no response fields",
        ),
        (
            None,
            None,
            requests.Timeout("source timeout"),
            requests.Timeout,
            "source timeout",
        ),
        (
            None,
            None,
            requests.ConnectionError("source connection failed"),
            requests.ConnectionError,
            "source connection failed",
        ),
    ],
)
def test_api_protocol_and_transport_failures_do_not_return_data(
    http_reply, payload, body, error, expected_error, message
):
    calls = http_reply(payload=payload, body=body, error=error)
    with pytest.raises(expected_error, match=message):
        call_resource()
    assert len(calls) == 1
