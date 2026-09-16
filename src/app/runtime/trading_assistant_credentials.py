"""Load deployment-owned keys once; never create keys or alter file permissions."""
import base64
import json
import os
from pathlib import Path
import stat

from src.biz.services.wealth.market.trading_assistant.credential_cipher import CredentialCipher, CredentialError


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CredentialError()
        result[key] = value
    return result


def load_credential_cipher(path: str | None) -> CredentialCipher | None:
    """Missing or unsafe deployment config disables credentials, not accounting.

    Validate the opened descriptor (not a separate stat/open sequence). Keys may
    be owned by the service uid or root, but must never be group/world-readable.
    No raw exception or key material is logged or returned to an API.
    """
    if not path:
        return None
    try:
        if not Path(path).is_absolute():
            raise CredentialError()
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                    or metadata.st_uid not in (0, os.geteuid()) or metadata.st_nlink != 1):
                raise CredentialError()
            # Deployment keyring is bounded independently of user input.
            raw = stream.read(65537)
            if len(raw) > 65536:
                raise CredentialError()
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if type(data) is not dict or set(data) != {"activeKeyId", "keys"} or type(data["keys"]) is not dict:
            raise CredentialError()
        keys = {}
        for key_id, encoded in data["keys"].items():
            if type(encoded) is not str:
                raise CredentialError()
            keys[key_id] = base64.b64decode(encoded, validate=True)
        return CredentialCipher(data["activeKeyId"], keys)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return None
