"""Private credential encryption; no environment, database or network access.

The persistence layer must enforce (key_id, nonce) uniqueness, including across
candidate and confirmed config objects. Activation decrypts and re-encrypts with
the CONFIG identity; ciphertext cannot simply be moved to another owner/object.
"""
from dataclasses import dataclass, field
import json
import os
from types import MappingProxyType
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialError(ValueError):
    def __init__(self):
        super().__init__("凭据处理失败")


@dataclass(frozen=True, slots=True)
class CredentialEnvelope:
    key_id: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)
    algorithm_version: str = "AES256_GCM_V1"


def _aad(owner_id: int, object_type: str, object_id: UUID) -> bytes:
    if type(owner_id) is not int or owner_id <= 0 or object_type not in ("CANDIDATE", "CONFIG") or not isinstance(object_id, UUID):
        raise CredentialError()
    return json.dumps(dict(schemaVersion=1, ownerId=owner_id,
        objectType=object_type, objectId=str(object_id)), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class CredentialCipher:
    def __init__(self, active_key_id: str, keys: dict[str, bytes]):
        if (not isinstance(active_key_id, str) or active_key_id not in keys or not keys
                or any(not isinstance(k, str) or not k or type(v) is not bytes or len(v) != 32 for k, v in keys.items())):
            raise CredentialError()
        # A copy prevents mutation by the configuration loader or caller.
        self._keys = MappingProxyType(dict(keys))
        self._active_key_id = active_key_id

    def encrypt(self, owner_id: int, object_type: str, object_id: UUID, plaintext: bytes) -> CredentialEnvelope:
        associated = _aad(owner_id, object_type, object_id)
        if type(plaintext) is not bytes:
            raise CredentialError()
        nonce = os.urandom(12)
        encrypted = AESGCM(self._keys[self._active_key_id]).encrypt(nonce, plaintext, associated)
        return CredentialEnvelope(self._active_key_id, nonce, encrypted)

    def decrypt(self, owner_id: int, object_type: str, object_id: UUID, envelope: CredentialEnvelope) -> bytes:
        associated = _aad(owner_id, object_type, object_id)
        if (not isinstance(envelope, CredentialEnvelope) or envelope.algorithm_version != "AES256_GCM_V1"
                or type(envelope.nonce) is not bytes or len(envelope.nonce) != 12
                or type(envelope.ciphertext) is not bytes or len(envelope.ciphertext) < 16):
            raise CredentialError()
        try:
            return AESGCM(self._keys[envelope.key_id]).decrypt(envelope.nonce, envelope.ciphertext, associated)
        except (KeyError, InvalidTag, ValueError, TypeError):
            # Never preserve a library error containing credential material.
            raise CredentialError() from None
