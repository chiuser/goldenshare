"""Canonical record keysets bound to query, filters and the complete read basis."""
import base64
import json

from src.biz.services.wealth.market.trading_assistant.market_facts import facts_digest
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def _encode(document):
    return base64.urlsafe_b64encode(json.dumps(document, sort_keys=True,
        separators=(",", ":")).encode()).decode().rstrip("=")


class RecordCursor:
    def __init__(self, *, kind, filters, context):
        self.identity = dict(v=1, queryKind=kind, filterDigest=facts_digest(filters),
                             contextDigest=facts_digest(context.model_dump()))

    def encode(self, key):
        return _encode(dict(self.identity, lastKey=key))

    def decode(self, cursor, *, validate_key):
        if cursor is None:
            return None
        try:
            if not isinstance(cursor, str) or not cursor or any(
                    c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in cursor):
                raise ValueError("Invalid cursor encoding")
            document = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if not isinstance(document, dict) or set(document) != {*self.identity, "lastKey"}:
                raise ValueError("Invalid cursor keys")
            if _encode(document) != cursor or type(document["v"]) is not int:
                raise ValueError("Noncanonical cursor")
            if any(document[key] != self.identity[key] for key in ("v", "queryKind", "filterDigest")):
                raise ValueError("Cursor query changed")
            result = validate_key(document["lastKey"])
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
            raise WriteProtocolConflict("TA_REQUEST_INVALID") from error
        if document["contextDigest"] != self.identity["contextDigest"]:
            raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
        return result
