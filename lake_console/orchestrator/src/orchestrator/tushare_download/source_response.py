"""Parse transport protocol only: successful business omissions remain source facts."""

from __future__ import annotations

import json
from decimal import Decimal

from .download_errors import DownloadErrorCode as Code
from .download_models import AttemptFailure, SourcePage, SourceRecord
from .source_contract import valid_scalar

_PERMISSION = (
    "没有权限",
    "无权限",
    "权限不足",
    "permission denied",
    "unauthorized",
    "forbidden",
    "invalid parameter",
    "参数错误",
    "积分不足",
    "接口不支持",
)
_RATE = ("频率超限", "请求频率", "rate limit", "too many requests", "500次/分钟", "429")
_TRANSIENT = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "502",
    "503",
    "504",
)


class _ProtocolError(ValueError):
    pass


def classify_source_message(message) -> Code:
    # These markers are copied from the current classify_tushare_error semantics.
    # The caller must already have established that this is a source API failure.
    text = message.lower() if type(message) is str else ""
    for markers, code in (
        (_PERMISSION, Code.PERMISSION_OR_PARAMETER),
        (_RATE, Code.RATE_LIMIT),
        (_TRANSIENT, Code.TRANSIENT_SOURCE),
    ):
        if any(marker in text for marker in markers):
            return code
    return Code.UNCLASSIFIED_SOURCE


def http_status_failure(status: int, retry_after_at=None):
    if 200 <= status < 300:
        return None
    code = (
        Code.PERMISSION_OR_PARAMETER
        if status in (400, 401, 403)
        else Code.RATE_LIMIT
        if status == 429
        else Code.TRANSIENT_SOURCE
        if 500 <= status < 600
        else Code.UNCLASSIFIED_SOURCE
    )
    return AttemptFailure(code, source_status=status, retry_after_at=retry_after_at)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _ProtocolError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_):
    raise _ProtocolError("nonfinite JSON constant")


def _metadata(root, path):
    if path is None:
        return None
    value = root
    for key in path:
        if type(value) is not dict or key not in value:
            return None
        value = value[key]
    if value is not None and (type(value) is not int or value < 0):
        raise _ProtocolError("invalid reliable pagination value")
    return value


def _page(root, request, contract, memory):
    data = root.get("data")
    if data is None or data == {}:
        return AttemptFailure(Code.NO_VALID_RESPONSE)
    if type(data) is not dict:
        raise _ProtocolError("invalid data object")
    names, items = data.get("fields"), data.get("items")
    if (names is None or names == []) and (items is None or items == []):
        return AttemptFailure(Code.NO_VALID_RESPONSE)
    if (
        type(names) is not list
        or not names
        or any(type(n) is not str or not n for n in names)
        or len(set(names)) != len(names)
    ):
        raise _ProtocolError("invalid field list")
    if type(items) is not list or (
        request.expected_limit is not None and len(items) > request.expected_limit
    ):
        raise _ProtocolError("invalid item list or page length")
    shape = tuple(names)
    if shape == request.fields:
        shape = request.fields
    records = []
    try:
        memory.reserve("page_conversion", len(items) * (1024 + 32 * len(shape)) + 256)
        for row in items:
            if (
                type(row) is not list
                or len(row) != len(shape)
                or not all(valid_scalar(v) for v in row)
            ):
                raise _ProtocolError("field/value shape mismatch")
            records.append(
                SourceRecord(shape, tuple(row), request.position.request_input_index)
            )
        p = contract.pagination
        return SourcePage(
            shape,
            tuple(records),
            _metadata(root, p.reliable_total_path),
            _metadata(root, p.reliable_next_offset_path),
        )
    finally:
        memory.release("page_conversion")
        records = row = items = data = root = None


def parse_http(body: bytes, request, contract, memory):
    text = root = page = None
    try:
        if not body:
            return AttemptFailure(Code.NO_VALID_RESPONSE)
        memory.reserve("json_decode", len(body) * 64)
        invalid = False
        try:
            text = body.decode("utf-8")
        except UnicodeError:
            invalid = True
        if invalid:
            return AttemptFailure(Code.SOURCE_PROTOCOL)
        memory.attach("response_text", text)
        try:
            root = json.loads(
                text,
                parse_int=int,
                parse_float=Decimal,
                object_pairs_hook=_pairs,
                parse_constant=_constant,
            )
        except (ValueError, RecursionError):
            invalid = True
        if invalid:
            return AttemptFailure(Code.SOURCE_PROTOCOL)
        memory.attach("response_json", root)
        memory.unreserve("json_decode")
        if type(root) is not dict or type(root.get("code")) is not int:
            return AttemptFailure(Code.SOURCE_PROTOCOL)
        # Failure envelopes need not contain successful data. This precedes _page.
        if root["code"] != 0:
            return AttemptFailure(
                classify_source_message(root.get("msg")), source_code=root["code"]
            )
        try:
            page = _page(root, request, contract, memory)
        except _ProtocolError:
            invalid = True
        if invalid:
            return AttemptFailure(Code.SOURCE_PROTOCOL)
        if isinstance(page, SourcePage):
            memory.attach("source_page", page)
        return page
    finally:
        for label in ("json_decode", "response_text", "response_json"):
            memory.release(label)
        body = text = root = page = None
