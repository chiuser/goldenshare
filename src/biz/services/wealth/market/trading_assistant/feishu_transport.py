"""One bounded request to a validated public IP, with original host TLS identity.

App owns a single instance per process. Only an already-persisted send attempt
may call send; DB rate limiting/selection belongs to the notification worker.
No httpx.Client is used: its request log includes the secret webhook path.
"""
import asyncio
import ipaddress
import socket
from time import monotonic

import httpx

from .feishu_protocol import HOST, MAX_MESSAGE_BYTES, FeishuInputError, SendOutcome, classify_response, validate_webhook
from .notification_policy import TradingAssistantNotificationPolicyV1
from .notification_log_guard import install_notification_log_guard, private_notification_io


def public_addresses(addresses):
    result = []
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if (not address.is_global or address.is_multicast or address.is_reserved
                or (isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None)):
            raise FeishuInputError("飞书目标地址校验未通过")
        if str(address) not in result:
            result.append(str(address))
    if not result:
        raise FeishuInputError("飞书目标地址校验未通过")
    return tuple(result)


async def resolve_public_host():
    values = await asyncio.get_running_loop().getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
    return public_addresses([value[4][0] for value in values])


class FeishuTransport:
    def __init__(self, policy: TradingAssistantNotificationPolicyV1):
        self.policy = policy
        self._slot = asyncio.Semaphore(policy.max_inflight_per_process)
        install_notification_log_guard()

    async def send(self, webhook: str, payload: bytes) -> SendOutcome:
        with private_notification_io():
            return await self._send(webhook, payload)

    async def _send(self, webhook: str, payload: bytes) -> SendOutcome:
        started = False
        deadline = monotonic() + self.policy.total_timeout_ms / 1000
        try:
            validate_webhook(webhook)
            if type(payload) is not bytes or len(payload) > MAX_MESSAGE_BYTES:
                raise FeishuInputError("消息格式不正确")
            async with asyncio.timeout(self.policy.pool_timeout_ms / 1000):
                await self._slot.acquire()
        except (FeishuInputError, TimeoutError):
            return SendOutcome("FAILED", "本次发送尚未开始，请稍后重试")
        try:
            async with asyncio.timeout(max(0, deadline - monotonic())):
                async with asyncio.timeout(self.policy.connect_timeout_ms / 1000):
                    addresses = await resolve_public_host()
                # A literal IP avoids a second DNS answer between validation and
                # connect. SNI retains the original name and certificate checks.
                endpoint = httpx.URL(webhook).copy_with(host=addresses[0])
                timeout = dict(connect=self.policy.connect_timeout_ms / 1000,
                    read=self.policy.read_timeout_ms / 1000, write=self.policy.read_timeout_ms / 1000,
                    pool=self.policy.pool_timeout_ms / 1000)
                request = httpx.Request("POST", endpoint, content=payload,
                    headers={"Host": HOST, "Content-Type": "application/json", "Accept-Encoding": "identity"},
                    extensions={"sni_hostname": HOST, "timeout": timeout})
                async with httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0,
                        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)) as transport:
                    started = True
                    response = await transport.handle_async_request(request)
                    try:
                        content = bytearray()
                        async for part in response.aiter_raw():
                            content.extend(part)
                            if len(content) > 65536:
                                return SendOutcome("UNKNOWN", "响应无法核验，请先查看飞书；不会自动重发")
                        return classify_response(response.status_code, bytes(content))
                    finally:
                        await response.aclose()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # TLS/TCP failed before the HTTP request body could be transmitted.
            return SendOutcome("FAILED", "未能建立飞书连接，本次消息未发送")
        except (TimeoutError, httpx.HTTPError, OSError, ValueError):
            return SendOutcome("UNKNOWN" if started else "FAILED",
                "发送结果待核对，不会自动重发" if started else "目标校验或连接准备失败，本次消息未发送")
        finally:
            self._slot.release()
