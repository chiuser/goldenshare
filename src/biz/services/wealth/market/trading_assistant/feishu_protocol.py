"""Feishu custom-bot text protocol, official guide verified 2026-09-16.

https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot.md
No network, user-supplied arbitrary message, or external response passthrough.
"""
import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import re

from src.biz.schemas.wealth.market.trading_assistant.robot import MAX_ROBOT_KEYWORDS

HOST = "open.feishu.cn"
MAX_MESSAGE_BYTES = 20 * 1024
_ENDPOINT = re.compile(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9_-]+")
_REJECTIONS = {9499: "消息格式不符合飞书要求", 19024: "飞书关键词校验未通过",
    19022: "飞书 IP 白名单校验未通过", 19021: "飞书签名或发送时间校验未通过",
    11232: "飞书请求频率受限"}


class FeishuInputError(ValueError):
    """A local validation error; never contains user input or credentials."""


@dataclass(frozen=True)
class SendOutcome:
    state: str
    reason: str | None
    response_code: int | None = None


def validate_webhook(value: str) -> str:
    if type(value) is not str or not _ENDPOINT.fullmatch(value):
        raise FeishuInputError("请填写有效的飞书机器人地址")
    return value


def text_payload(text: str, *, keywords: tuple[str, ...], signing_secret: str | None, timestamp: int) -> bytes:
    if (type(timestamp) is not int or timestamp < 0 or type(text) is not str or not text
            or len(keywords) > MAX_ROBOT_KEYWORDS or any(type(k) is not str or not k.strip() for k in keywords)
            or (signing_secret is not None and (type(signing_secret) is not str or not signing_secret))):
        raise FeishuInputError("机器人安全配置不正确")
    payload = {"msg_type": "text", "content": {"text": "\n".join((*keywords, text))}}
    if signing_secret is not None:
        key = f"{timestamp}\n{signing_secret}".encode("utf-8")
        payload.update(timestamp=str(timestamp), sign=base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode("ascii"))
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise FeishuInputError("消息超过飞书允许的大小，请检查关键词配置")
    return encoded


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def classify_response(status_code: int, body: bytes) -> SendOutcome:
    unknown = SendOutcome("UNKNOWN", "发送结果待核对，请先查看飞书；不会自动重发")
    # Neither redirects, HTTP errors, nor legacy-only StatusCode prove delivery.
    if status_code != 200 or len(body) > 65536:
        return unknown
    try:
        value = json.loads(body, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError):
        return unknown
    if type(value) is not dict or type(value.get("code")) is not int:
        return unknown
    code = value["code"]
    if code == 0:
        return SendOutcome("SUCCEEDED", None, 0)
    if code in _REJECTIONS:
        return SendOutcome("FAILED", _REJECTIONS[code], code)
    return unknown
