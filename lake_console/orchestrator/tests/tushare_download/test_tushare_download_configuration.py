import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from orchestrator.tushare_download import (
    DownloadError,
    DownloadErrorCode,
    TushareDownloader,
    configuration,
)
from orchestrator.tushare_download.configuration import (
    ConfigurationSnapshot,
    read_tushare_connection,
)


def test_two_keys_only_and_old_invalid_rate_ignored():
    visited = []

    class Values(dict):
        def get(self, key, default=None):
            visited.append(key)
            assert key in {"TUSHARE_TOKEN", "TUSHARE_BASE_URL"}
            return super().get(key, default)

    values = Values(
        TUSHARE_TOKEN="  isolated  ", TUSHARE_MAX_CALLS_PER_MINUTE="not-a-number"
    )
    assert read_tushare_connection(values) == ("isolated", "https://api.tushare.pro")
    assert visited == ["TUSHARE_TOKEN", "TUSHARE_BASE_URL"]
    assert values["TUSHARE_TOKEN"] == "  isolated  "


@pytest.mark.parametrize(
    "token,url",
    [
        ("", "https://source.invalid"),
        ("  ", "https://source.invalid"),
        ("x", ""),
        ("x", "file:///tmp/no"),
        ("x", "https://"),
        ("x", "https://a:b@source.invalid"),
        ("x", "https://source.invalid:bad"),
    ],
)
def test_bad_connection_is_sanitized_configuration_failure(token, url):
    with pytest.raises(DownloadError) as caught:
        read_tushare_connection({"TUSHARE_TOKEN": token, "TUSHARE_BASE_URL": url})
    assert caught.value.code == DownloadErrorCode.CONFIGURATION
    assert "source.invalid" not in str(caught.value)
    assert caught.value.__context__ is None


def test_public_load_really_calls_extraction_and_freezes_each_instance(monkeypatch):
    seen = []

    def read(environ):
        seen.append(True)
        return f"secret-{len(seen)}", "http://127.0.0.1:1"

    monkeypatch.setattr(configuration, "read_tushare_connection", read)
    a, b = TushareDownloader.load(), TushareDownloader.load()
    # Snapshot validation also uses the same pure validator, so focus on actual values.
    assert a._config.token != b._config.token
    assert "secret" not in repr(a._config)
    with pytest.raises(FrozenInstanceError):
        a._config.token = "changed"
    assert list(inspect.signature(TushareDownloader.load).parameters) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"max_retries": True},
        {"unit_memory_limit_bytes": 1},
        {"connect_timeout_seconds": float("nan")},
        {"retry_backoff_seconds": ()},
    ],
)
def test_invalid_technical_values_rejected(changes):
    with pytest.raises(DownloadError) as caught:
        ConfigurationSnapshot("x", "https://source.invalid", **changes)
    assert caught.value.code == DownloadErrorCode.CONFIGURATION


def test_fresh_public_import_does_not_read_environment_or_start_execution():
    # The child belongs to this isolation test, never to the component. Use the
    # installed current environment; no PYTHONPATH or package synchronization.
    code = """
import http.client, os, socket, subprocess, threading
def forbidden(*args, **kwargs):
    raise AssertionError('import attempted configuration, network or execution')
original_get = os.environ.get
def get(key, default=None):
    if key.startswith('TUSHARE_'):
        forbidden()
    return original_get(key, default)
os.environ.get = get
socket.socket = forbidden
subprocess.Popen = forbidden
threading.Thread.start = forbidden
import orchestrator.tushare_download
"""
    outcome = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert outcome.returncode == 0, outcome.stderr
