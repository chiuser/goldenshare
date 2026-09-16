"""SEC-01/02/03/04: real AES-GCM and isolated deployment files, no network."""
import base64
from dataclasses import replace
import json
from uuid import uuid4

import pytest

from src.app.runtime.trading_assistant_credentials import load_credential_cipher
from src.biz.services.wealth.market.trading_assistant.credential_cipher import CredentialCipher, CredentialError

KEY = bytes(range(32))
SECRET = b'{"webhook":"https://example.invalid/private","signingSecret":"test-only"}'


def test_roundtrip_binding_tampering_and_no_secret_repr():
    cipher = CredentialCipher("a", {"a": KEY})
    identity = uuid4()
    encrypted = cipher.encrypt(1, "CANDIDATE", identity, SECRET)
    assert cipher.decrypt(1, "CANDIDATE", identity, encrypted) == SECRET
    assert b"private" not in encrypted.ciphertext
    assert "test-only" not in repr(cipher) + repr(encrypted)
    for owner, kind, obj, value in [
        (2, "CANDIDATE", identity, encrypted), (1, "CONFIG", identity, encrypted),
        (1, "CANDIDATE", uuid4(), encrypted),
        (1, "CANDIDATE", identity, replace(encrypted, ciphertext=encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1]))),
        (1, "CANDIDATE", identity, replace(encrypted, key_id="missing")),
        (1, "CANDIDATE", identity, replace(encrypted, algorithm_version="other")),
        (1, "CANDIDATE", identity, replace(encrypted, nonce=b"short")),
    ]:
        with pytest.raises(CredentialError, match="^凭据处理失败$"):
            cipher.decrypt(owner, kind, obj, value)


def test_new_nonces_activation_and_retained_old_keys():
    keys = {"old": KEY}
    old = CredentialCipher("old", keys)
    identity = uuid4()
    values = [old.encrypt(1, "CANDIDATE", identity, SECRET) for _ in range(200)]
    assert len({v.nonce for v in values}) == 200
    keys["old"] = b"x" * 32  # cannot mutate an already constructed cipher
    current = CredentialCipher("new", {"old": KEY, "new": b"y" * 32})
    clear = current.decrypt(1, "CANDIDATE", identity, values[0])
    config_id = uuid4()
    active = current.encrypt(1, "CONFIG", config_id, clear)
    assert active.key_id == "new" and active.nonce != values[0].nonce
    assert current.decrypt(1, "CONFIG", config_id, active) == SECRET
    assert old.decrypt(1, "CANDIDATE", identity, values[0]) == SECRET


@pytest.mark.parametrize("owner,kind,obj", [(True,"CONFIG",uuid4()), (0,"CONFIG",uuid4()), (1,"OTHER",uuid4()), (1,"CONFIG","not-uuid")])
def test_invalid_associated_identity(owner, kind, obj):
    with pytest.raises(CredentialError):
        CredentialCipher("a", {"a": KEY}).encrypt(owner, kind, obj, SECRET)


def key_file(tmp_path, data=None):
    path = tmp_path / "keys.json"
    path.write_text(data if data is not None else json.dumps({"activeKeyId":"a","keys":{"a":base64.b64encode(KEY).decode()}}))
    path.chmod(0o600)
    return path


def test_safe_file_and_absent_config(tmp_path):
    path = key_file(tmp_path)
    assert isinstance(load_credential_cipher(str(path)), CredentialCipher)
    assert load_credential_cipher(None) is None
    assert load_credential_cipher("") is None
    assert load_credential_cipher("relative/key.json") is None
    assert load_credential_cipher(str(tmp_path / "missing")) is None
    assert load_credential_cipher(str(tmp_path)) is None


@pytest.mark.parametrize("data", ["[]", "null", "broken", '{"keys":{}}',
    '{"activeKeyId":"a","keys":{"a":"!"}}', '{"activeKeyId":"a","keys":{"a":"YQ=="}}',
    '{"activeKeyId":"a","keys":{"a":123}}', '{"activeKeyId":[],"keys":{}}',
    '{"activeKeyId":"a","activeKeyId":"b","keys":{}}', "x" * 65537, "[" * 2000 + "]" * 2000])
def test_bad_key_file_disables_credentials_without_leaking(tmp_path, data, caplog):
    assert load_credential_cipher(str(key_file(tmp_path, data))) is None
    assert not caplog.records


def test_unsafe_permissions_symlinks_and_wrong_key(tmp_path):
    path = key_file(tmp_path)
    path.chmod(0o640)
    assert load_credential_cipher(str(path)) is None
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    assert load_credential_cipher(str(link)) is None
    identity = uuid4()
    value = CredentialCipher("a", {"a":KEY}).encrypt(1,"CONFIG",identity,SECRET)
    with pytest.raises(CredentialError):
        CredentialCipher("a", {"a":b"z" * 32}).decrypt(1,"CONFIG",identity,value)
