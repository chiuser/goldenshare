import asyncio
import base64
import hashlib
import hmac
import json
import logging

import httpx
import pytest

from src.biz.services.wealth.market.trading_assistant.feishu_protocol import (
    FeishuInputError, classify_response, text_payload, validate_webhook)
from src.biz.services.wealth.market.trading_assistant.feishu_transport import FeishuTransport, public_addresses
from src.biz.services.wealth.market.trading_assistant.notification_policy import TradingAssistantNotificationPolicyV1
import src.biz.services.wealth.market.trading_assistant.feishu_transport as io

URL = "https://open.feishu.cn/open-apis/bot/v2/hook/test-only-token"


@pytest.mark.parametrize("url", [URL + "?q=x", URL + "#x", URL + "/other", URL + "\n",
    URL.replace("https:", "http:"), URL.replace(".cn/", ".cn:443/"),
    URL.replace("open.feishu.cn", "user@open.feishu.cn"), URL.replace("open.feishu.cn", "127.0.0.1"),
    URL.replace("open.feishu.cn", "open.feishu.cn.evil.invalid"), URL.replace("test-only-token", "%2e%2e"),
    URL.replace("test-only-token", ""), " https://open.feishu.cn/open-apis/bot/v2/hook/test"])
def test_reject_unsafe_or_ambiguous_endpoint(url):
    with pytest.raises(FeishuInputError):
        validate_webhook(url)


def test_signature_keywords_and_message_bytes():
    assert validate_webhook(URL) == URL
    raw = text_payload("盘后验证", keywords=("行情", "交易"), signing_secret="demo", timestamp=1599360473)
    value = json.loads(raw)
    assert value["content"]["text"] == "行情\n交易\n盘后验证"
    assert value["timestamp"] == "1599360473"
    assert value["sign"] == base64.b64encode(hmac.new(b"1599360473\ndemo", b"", hashlib.sha256).digest()).decode()
    unsigned = json.loads(text_payload("测试", keywords=(), signing_secret=None, timestamp=1))
    assert set(unsigned) == {"msg_type", "content"}
    with pytest.raises(FeishuInputError):
        text_payload("测" * 7000, keywords=(), signing_secret=None, timestamp=1)
    with pytest.raises(FeishuInputError):
        text_payload("测试", keywords=("a",) * 11, signing_secret=None, timestamp=1)


@pytest.mark.parametrize("status,body,expected", [
    (200,b'{"code":0,"data":{},"msg":"success"}',"SUCCEEDED"),
    *[(200,json.dumps({"code":code,"msg":"secret-never-return"}).encode(),"FAILED") for code in (9499,19024,19022,19021,11232)],
    (200,b'{"StatusCode":0}',"UNKNOWN"), (200,b'{"code":false}',"UNKNOWN"),
    (200,b'{"code":"0"}',"UNKNOWN"), (200,b'{"code":0.0}',"UNKNOWN"),
    (200,b'{"code":0,"code":19021}',"UNKNOWN"), (200,b'[]',"UNKNOWN"),
    (200,b'{"code":999999}',"UNKNOWN"), (200,b'',"UNKNOWN"), (200,b'bad',"UNKNOWN"),
    (302,b'{"code":0}',"UNKNOWN"), (500,b'{"code":0}',"UNKNOWN"), (429,b'{"code":11232}',"UNKNOWN"),
    (200,b'x' * 65537,"UNKNOWN"),
])
def test_strict_outcome_without_raw_response(status,body,expected):
    result = classify_response(status, body)
    assert result.state == expected
    assert "secret-never-return" not in repr(result)


@pytest.mark.parametrize("address", ["127.0.0.1","10.0.0.1","192.168.1.1","169.254.169.254","0.0.0.0",
    "224.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:8.8.8.8", "ff02::1", "not-an-ip"])
def test_reject_all_private_or_ambiguous_dns_results(address):
    with pytest.raises(ValueError):
        public_addresses(["8.8.8.8", address])


class Stream(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        yield self.content


def transport_fixture(monkeypatch, *, error=None, status=200, body=b'{"code":0}'):
    requests, settings = [], []
    async def resolve():
        return ("8.8.8.8",)
    class Transport:
        def __init__(self, **kw):
            settings.append(kw)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *unused):
            pass
        async def handle_async_request(self, request):
            requests.append(request)
            if error:
                raise error
            return httpx.Response(status, stream=Stream(body))
    monkeypatch.setattr(io,"resolve_public_host",resolve)
    monkeypatch.setattr(io.httpx,"AsyncHTTPTransport",Transport)
    return requests, settings


def test_pinned_ip_tls_hostname_proxy_and_redirects(monkeypatch, caplog):
    requests, settings = transport_fixture(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    result = asyncio.run(FeishuTransport(TradingAssistantNotificationPolicyV1()).send(URL,b'{}'))
    assert result.state == "SUCCEEDED"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "8.8.8.8"
    assert request.headers["host"] == request.extensions["sni_hostname"] == "open.feishu.cn"
    assert settings[0]["verify"] is True and settings[0]["trust_env"] is False and settings[0]["retries"] == 0
    assert "test-only-token" not in caplog.text
    requests, _ = transport_fixture(monkeypatch,status=302)
    assert asyncio.run(FeishuTransport(TradingAssistantNotificationPolicyV1()).send(URL,b'{}')).state == "UNKNOWN"
    assert len(requests) == 1


@pytest.mark.parametrize("error,state", [(httpx.ConnectError("private"),"FAILED"),
    (httpx.ConnectTimeout("private"),"FAILED"),(httpx.ReadTimeout("private"),"UNKNOWN"),
    (httpx.WriteError("private"),"UNKNOWN"),(TimeoutError("private"),"UNKNOWN")])
def test_network_errors_are_not_blindly_retried(monkeypatch,error,state):
    requests, _ = transport_fixture(monkeypatch,error=error)
    result = asyncio.run(FeishuTransport(TradingAssistantNotificationPolicyV1()).send(URL,b'{}'))
    assert result.state == state and len(requests) == 1 and "private" not in repr(result)


def test_local_rejection_never_starts_transport(monkeypatch):
    requests, settings = transport_fixture(monkeypatch)
    async def reject():
        raise FeishuInputError("invalid")
    monkeypatch.setattr(io,"resolve_public_host",reject)
    assert asyncio.run(FeishuTransport(TradingAssistantNotificationPolicyV1()).send(URL,b'{}')).state == "FAILED"
    assert not requests and not settings


def test_total_deadline_and_slot_released_after_cancellation(monkeypatch):
    async def exercise():
        started = asyncio.Event()
        class Transport:
            def __init__(self, **unused): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*unused): pass
            async def handle_async_request(self, request):
                started.set()
                await asyncio.Event().wait()
        async def resolve(): return ("8.8.8.8",)
        monkeypatch.setattr(io,"resolve_public_host",resolve)
        monkeypatch.setattr(io.httpx,"AsyncHTTPTransport",Transport)
        policy = TradingAssistantNotificationPolicyV1(total_timeout_ms=50, connect_timeout_ms=10,
            read_timeout_ms=20,pool_timeout_ms=10)
        sender = FeishuTransport(policy)
        assert (await sender.send(URL,b'{}')).state == "UNKNOWN"
        assert sender._slot._value == 1
        started.clear()
        job = asyncio.create_task(sender.send(URL,b'{}'))
        await started.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError): await job
        assert sender._slot._value == 1
    asyncio.run(exercise())


def test_debug_logging_is_private_without_silencing_concurrent_http(monkeypatch, caplog):
    async def exercise():
        inside, release = asyncio.Event(), asyncio.Event()
        class Transport:
            def __init__(self, **unused): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*unused): pass
            async def handle_async_request(self, request):
                logging.getLogger("httpcore.http11").debug("remote malformed bytes %s", URL)
                inside.set()
                await release.wait()
                raise httpx.RemoteProtocolError(URL)
        async def resolve(): return ("8.8.8.8",)
        monkeypatch.setattr(io,"resolve_public_host",resolve)
        monkeypatch.setattr(io.httpx,"AsyncHTTPTransport",Transport)
        sender = FeishuTransport(TradingAssistantNotificationPolicyV1())
        task = asyncio.create_task(sender.send(URL,b'{}'))
        await inside.wait()
        logging.getLogger("httpcore.http11").debug("unrelated HTTP diagnostic")
        release.set()
        assert (await task).state == "UNKNOWN"
        logging.getLogger("httpcore.http11").debug("after private request")
    with caplog.at_level(logging.DEBUG, logger="httpcore.http11"):
        asyncio.run(exercise())
    assert "test-only-token" not in caplog.text
    assert "unrelated HTTP diagnostic" in caplog.text and "after private request" in caplog.text
