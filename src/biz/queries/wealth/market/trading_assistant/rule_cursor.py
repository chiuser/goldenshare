"""Canonical rule keysets; ownership remains a SQL predicate, never a token grant."""
import base64
import json
from datetime import datetime
from uuid import UUID

from src.biz.services.wealth.market.trading_assistant.market_facts import facts_digest
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def encode(document):
    return base64.urlsafe_b64encode(json.dumps(document, sort_keys=True,
        separators=(",", ":")).encode()).decode().rstrip("=")


class RuleCursor:
    def __init__(self, *, owner_id, kind, filters):
        self.identity = dict(v=1, owner=owner_id, kind=kind, filters=facts_digest(filters))

    def encode(self, key):
        return encode(dict(self.identity, key=key))

    def decode(self, value, *, numbered=False, history=False):
        if value is None:
            return None
        try:
            if not value or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
                raise ValueError("Invalid encoding")
            document = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
            if (type(document) is not dict or set(document) != {*self.identity, "key"}
                    or encode(document) != value or type(document["v"]) is not int
                    or type(document["owner"]) is not int
                    or any(document[k] != v for k, v in self.identity.items())):
                raise ValueError("Cursor query differs")
            key = document["key"]
            if history:
                if (type(key) is not list or len(key) != 2 or any(type(v) is not int for v in key)
                        or not 1 <= key[0] <= key[1] <= 9223372036854775807):
                    raise ValueError("Invalid frozen sequence")
                return tuple(key)
            if numbered:
                if type(key) is not int or not 1 <= key <= 9223372036854775807:
                    raise ValueError("Invalid sequence")
                return key
            if type(key) is not list or len(key) != 2 or any(type(v) is not str for v in key):
                raise ValueError("Invalid key")
            at, identity = datetime.fromisoformat(key[0]), UUID(key[1])
            if at.tzinfo is None or str(identity) != key[1]:
                raise ValueError("Invalid timestamp or ID")
            return at, identity
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
            raise WriteProtocolConflict("TA_REQUEST_INVALID") from error
