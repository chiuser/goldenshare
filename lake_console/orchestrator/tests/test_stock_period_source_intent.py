"""DG-only HTTP configuration, durable source evidence and explicit refresh identities."""

import builtins
import json
from pathlib import Path

import pytest

from orchestrator.defs.run_contracts.stock_period import FIELDS, VERSION, execution_id
from orchestrator.defs.stock_period_source import (
    HttpPage,
    PeriodHttpConfig,
    capture_unit,
)


def payload(*, value="1.2500", fields=FIELDS):
    return json.dumps(
        {
            "code": 0,
            "data": {
                "fields": list(fields),
                "items": [["000001.SZ", "20261016", "20261015", "week"] + [value] * 17],
            },
        }
    ).encode()


def capture(work, transport, **overrides):
    return capture_unit(
        work=work,
        request_id="explicit-work",
        freq="week",
        code="000001.SZ",
        listed={"000001.SZ"},
        aliases={},
        transport=transport,
        **overrides,
    )


def test_dg_environment_does_not_import_prod_or_read_root_env(monkeypatch, tmp_path):
    env = tmp_path / "prod.env"
    env.write_text("TUSHARE_TOKEN=wrong-source\nTUSHARE_BASE_URL=http://wrong-source\n")
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(env))
    monkeypatch.setenv("TUSHARE_TOKEN", "dg-test-secret")
    monkeypatch.setenv("TUSHARE_BASE_URL", "http://127.0.0.1:9/period")
    monkeypatch.setenv("TUSHARE_MAX_CALLS_PER_MINUTE", "120")
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith(("src.", "pydantic_settings"))
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    client = HttpPage()
    assert client.token == "dg-test-secret" and client.interval == 0.5
    assert client.base_url == "http://127.0.0.1:9/period"
    assert "dg-test-secret" not in json.dumps(client.public_config)
    assert "dg-test-secret" not in repr(PeriodHttpConfig.from_environment())
    monkeypatch.delenv("TUSHARE_TOKEN")
    with pytest.raises(ValueError, match="token_missing"):
        HttpPage()


@pytest.mark.parametrize("rate", ["not-a-number", "-1"])
def test_invalid_rate_is_not_silently_unlimited(monkeypatch, rate):
    monkeypatch.setenv("TUSHARE_MAX_CALLS_PER_MINUTE", rate)
    with pytest.raises(ValueError, match="rate_invalid"):
        HttpPage(token="offline")


def test_defaults_and_explicit_overrides(monkeypatch):
    for name in ("TUSHARE_TOKEN", "TUSHARE_BASE_URL", "TUSHARE_MAX_CALLS_PER_MINUTE"):
        monkeypatch.delenv(name, raising=False)
    config = PeriodHttpConfig.from_environment(token="offline")
    assert (
        config.base_url == "https://api.tushare.pro"
        and config.max_calls_per_minute == 280
    )
    monkeypatch.setenv("TUSHARE_MAX_CALLS_PER_MINUTE", "0")
    assert HttpPage(token="offline", base_url="http://127.0.0.1:9").interval == 0
    for url in ("file:///tmp/period", "http://user:secret@localhost/period", "missing"):
        with pytest.raises(ValueError, match="url_invalid"):
            HttpPage(token="offline", base_url=url)


@pytest.mark.parametrize(
    "body,reason",
    [
        (b"{incomplete", "period_source_json_invalid"),
        (payload(fields=FIELDS[:-1]), "period_source_fields_invalid"),
        (payload(value="1.23456"), "period_source_decimal_invalid"),
    ],
)
def test_failed_response_retained_without_success_receipt(tmp_path, body, reason):
    with pytest.raises(ValueError, match=reason):
        capture(tmp_path, lambda _: body)
    failures = list(tmp_path.glob("*/attempts/*.failure.json"))
    assert len(failures) == 1
    evidence = json.loads(failures[0].read_text())
    assert (
        evidence["reason_code"] == reason
        and Path(evidence["body"]).read_bytes() == body
    )
    assert evidence["params"] == {
        "freq": "week",
        "ts_code": "000001.SZ",
        "limit": 6000,
        "offset": 0,
    }
    assert not list(tmp_path.glob("*/complete.json"))
    assert not list(tmp_path.glob("*/*.receipt.json")) and not list(
        tmp_path.glob("*/*.csv")
    )


def test_failed_evidence_redacts_secret_and_transport_errors(tmp_path):
    class Echo:
        token = "offline-secret-never-store"

        def __call__(self, _):
            return json.dumps({"code": -1, "message": self.token}).encode()

    with pytest.raises(ValueError, match="contains_secret"):
        capture(tmp_path / "echo", Echo())
    for p in (tmp_path / "echo").rglob("*"):
        if p.is_file():
            assert Echo.token.encode() not in p.read_bytes()
    failure = json.loads(
        next((tmp_path / "echo").glob("*/attempts/*.failure.json")).read_text()
    )
    assert failure["redacted"] is True

    def timeout(_):
        raise TimeoutError("unsafe credential text")

    with pytest.raises(TimeoutError):
        capture(tmp_path / "timeout", timeout)
    failure = json.loads(
        next((tmp_path / "timeout").glob("*/attempts/*.failure.json")).read_text()
    )
    assert (
        failure["body"] is None
        and failure["reason_code"] == "period_source_transport_failure"
    )
    assert "unsafe credential text" not in json.dumps(failure)


def test_bounded_failure_evidence(tmp_path):
    from orchestrator.defs.run_contracts.stock_period import StockPeriodPolicy

    with pytest.raises(ValueError, match="response_budget"):
        capture(
            tmp_path, lambda _: payload(), policy=StockPeriodPolicy(response_bytes=32)
        )
    failure = json.loads(next(tmp_path.glob("*/attempts/*.failure.json")).read_text())
    assert failure["truncated"] is True and Path(failure["body"]).stat().st_size == 32


def test_new_refresh_and_resume_have_different_cache_rules(tmp_path, monkeypatch):
    import orchestrator.defs.stock_period_source as source

    calls = []

    def transport(params):
        calls.append(params)
        return payload()

    kw = {
        "work": tmp_path,
        "freq": "week",
        "code": "000001.SZ",
        "listed": {"000001.SZ"},
        "aliases": {},
        "transport": transport,
    }
    first = capture_unit(**kw, request_id="refresh-1")
    second = capture_unit(**kw, request_id="refresh-2")
    assert (
        len(calls) == 2
        and first["identity"]["intent_id"] != second["identity"]["intent_id"]
    )
    monkeypatch.setattr(
        source,
        "_decode_page",
        lambda *a, **kw: pytest.fail("completed page recalculated"),
    )
    assert capture_unit(**kw, request_id="refresh-1") == first
    assert len(calls) == 2
    # Complete unit receipts are metadata, not an in-memory copy of all source row keys.
    assert all("keys" not in p for p in first["pages"])
    assert set(calls[0]) == {"freq", "ts_code", "limit", "offset"}


def test_manual_history_requires_id_and_legacy_manifest_is_rejected():
    from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig
    from orchestrator.defs.run_contracts.stock_period import verify_execution

    for request in (
        {"intent": "history", "stock_codes": ["000001.SZ"]},
        {"intent": "history", "request_id": " "},
    ):
        with pytest.raises(ValueError, match="intent_id_required"):
            StockPeriodRawConfig(**request)
    assert (
        StockPeriodRawConfig(intent="history", request_id="new-action").request_id
        == "new-action"
    )
    assert execution_id("new-action") != execution_id("another-action")
    with pytest.raises(ValueError):
        verify_execution(
            {"identity": {"intent": {"version": "stock-period-source-v1"}}}, "unused"
        )
    assert VERSION == "stock-period-source-v2"


def test_empty_scope_refuses_before_directory_or_request(tmp_path):
    work = tmp_path / "not-created"
    with pytest.raises(ValueError, match="listed_scope_empty"):
        capture_unit(
            work=work,
            request_id="empty-scope",
            freq="week",
            period="2026-10-16",
            listed=set(),
            aliases={},
            transport=lambda _: pytest.fail("empty-scope request"),
        )
    assert not work.exists()
