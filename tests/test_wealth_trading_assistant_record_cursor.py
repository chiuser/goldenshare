"""Record keysets cannot be reused after filters or read versions change."""
import base64
import json

import pytest

from src.biz.queries.wealth.market.trading_assistant.record_cursor import RecordCursor
from src.biz.queries.wealth.market.trading_assistant.record_lists import _parse_key
from src.biz.schemas.wealth.market.trading_assistant.common import ReadContext
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def cursor(context="abc", kind="TRADE", filters=None):
    return RecordCursor(kind=kind, filters=filters or {"accountMode":"ALL"},
        context=ReadContext(accounts=[], targetThrough="2026-09-11T15:00:00+08:00", contextToken=context))


KEY = dict(date="2026-09-11", recordedAt="2026-09-11T08:00:00+00:00", recordId="00000000-0000-0000-0000-000000000001")
parse = lambda key: _parse_key(key, False)


def test_bound_cursor_and_canonical_encoding():
    token = cursor().encode(KEY)
    assert cursor().decode(token, validate_key=parse) == parse(KEY)
    assert cursor().decode(None, validate_key=parse) is None
    for other in (cursor(kind="CASH_FLOW"), cursor(filters={"accountMode":"SINGLE"})):
        with pytest.raises(WriteProtocolConflict) as error:
            other.decode(token, validate_key=parse)
        assert error.value.code == "TA_REQUEST_INVALID"
    with pytest.raises(WriteProtocolConflict) as error:
        cursor(context="def").decode(token, validate_key=parse)
    assert error.value.code == "TA_READ_CONTEXT_CHANGED"


@pytest.mark.parametrize("patch", [{"date":"2026-02-30"}, {"recordId":"x"}, {"recordedAt":"2026-09-11"},
    {"recordId":True}, {"extra":"x"}])
def test_invalid_last_key(patch):
    with pytest.raises(WriteProtocolConflict):
        cursor().decode(cursor().encode({**KEY, **patch}), validate_key=parse)


@pytest.mark.parametrize("document", [[], {}, {"v":True}, "hello", None])
def test_invalid_cursor_document(document):
    token = base64.urlsafe_b64encode(json.dumps(document).encode()).decode().rstrip("=")
    with pytest.raises(WriteProtocolConflict):
        cursor().decode(token, validate_key=parse)


def test_noncanonical_and_extra_keys_rejected():
    token = cursor().encode(KEY)
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    for altered in (" " + raw, raw.replace('"v":1', '"v":1,"v":1'), raw.replace('"v":1', '"v":1,"extra":0')):
        value = base64.urlsafe_b64encode(altered.encode()).decode().rstrip("=")
        with pytest.raises(WriteProtocolConflict):
            cursor().decode(value, validate_key=parse)
