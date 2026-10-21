import json
from decimal import Decimal

import pytest

from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import PagePosition
from orchestrator.tushare_download.download_models import (
    AttemptFailure,
    PageRequest,
    SourcePage,
)
from orchestrator.tushare_download.source_response import parse_http
from orchestrator.tushare_download.unit_memory import UnitMemory

from .fixtures import contract, small_config


def parse(body):
    definition = contract()
    request = PageRequest(
        "daily", definition.field_names, (), PagePosition(0, offset=0), 2
    )
    memory = UnitMemory(small_config())
    result = parse_http(
        body if type(body) is bytes else json.dumps(body).encode(),
        request,
        definition,
        memory,
    )
    return result


@pytest.mark.parametrize(
    "response,expected",
    [
        ({"code": 9, "msg": "请求频率超限", "data": None}, C.RATE_LIMIT),
        ({"code": 9, "msg": "权限不足", "data": None}, C.PERMISSION_OR_PARAMETER),
        ({"code": 9, "msg": "未知"}, C.UNCLASSIFIED_SOURCE),
        ({"code": 0, "data": None}, C.NO_VALID_RESPONSE),
        (
            {"code": 0, "data": {"fields": ["a", "b"], "items": [[1]]}},
            C.SOURCE_PROTOCOL,
        ),
    ],
)
def test_independent_response_order_counterexamples(response, expected):
    # Nonzero 9 is an artificial fixture, never a claimed Tushare error code.
    result = parse(response)
    assert isinstance(result, AttemptFailure) and result.code == expected


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":0,"code":9}',
        b'{"code":true}',
        b"[]",
        b"not-json",
        b'{"code":0,"data":{"fields":["x"],"items":[[NaN]]}}',
        b'{"code":0,"data":{"fields":["x","x"],"items":[[1,2]]}}',
    ],
)
def test_deterministic_protocol_failures(body):
    assert parse(body).code == C.SOURCE_PROTOCOL


def test_empty_valid_fields_and_actual_missing_business_columns_preserve_values():
    empty = parse({"code": 0, "data": {"fields": ["ts_code"], "items": []}})
    assert isinstance(empty, SourcePage) and empty.records == ()
    page = parse(
        b'{"code":0,"data":{"fields":["value","null","big","flag"],"items":[[-0.1234567890123456789,null,12345678901234567890,true]]}}'
    )
    assert page.records[0].as_mapping() == {
        "value": Decimal("-0.1234567890123456789"),
        "null": None,
        "big": 12345678901234567890,
        "flag": True,
    }
    assert page.records[0].fields == ("value", "null", "big", "flag")
    assert (
        parse({"code": 0, "data": {"fields": [], "items": []}}).code
        == C.NO_VALID_RESPONSE
    )
    assert parse({"code": 0, "data": {"fields": ["x"]}}).code == C.SOURCE_PROTOCOL


def test_local_memory_error_is_not_misclassified_as_source_protocol():
    class BrokenMemory:
        def reserve(self, *args):
            raise TypeError("local 429 timeout")

        def release(self, *args):
            pass

    definition = contract()
    request = PageRequest("daily", definition.field_names, (), PagePosition(0), 2)
    with pytest.raises(TypeError, match="local 429 timeout"):
        parse_http(b'{"code":0}', request, definition, BrokenMemory())


@pytest.mark.parametrize("depth", [10, 550, 700])
def test_nested_source_cell_is_standard_protocol_failure(depth):
    # A deliberately malformed scalar cell; literal nesting is independent of
    # the parser and memory-accounting implementation, and under 2KiB.
    body = (
        b'{"code":0,"data":{"fields":["a"],"items":[['
        + b"[" * depth
        + b"0"
        + b"]" * depth
        + b"]]}}"
    )
    assert parse(body).code == C.SOURCE_PROTOCOL


def test_deep_unused_source_attachment_does_not_change_valid_rows():
    body = (
        b'{"code":0,"data":{"fields":["a"],"items":[[7]]},"attachment":'
        + b"[" * 700
        + b"0"
        + b"]" * 700
        + b"}"
    )
    page = parse(body)
    assert isinstance(page, SourcePage) and page.records[0].values == (7,)


def test_deep_attachment_does_not_mask_source_rate_error():
    body = (
        b'{"code":9,"msg":"rate limit","data":' + b"[" * 700 + b"0" + b"]" * 700 + b"}"
    )
    result = parse(body)
    assert isinstance(result, AttemptFailure) and result.code == C.RATE_LIMIT
