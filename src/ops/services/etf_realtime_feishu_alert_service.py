from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib import error, request

from src.foundation.config.settings import Settings, get_settings
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.services.feishu_task_notification_service import build_feishu_signature
from src.utils import truncate_text


class EtfRealtimeFeishuAlertService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        urlopen_fn: Callable[..., Any] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._urlopen_fn = urlopen_fn or request.urlopen
        self._time_fn = time_fn or time.time

    def send_alert(self, alert: EtfRealtimeAlert) -> tuple[str | None, str | None]:
        webhook_url = self._settings.etf_realtime_alert_feishu_webhook_url.strip()
        if not webhook_url:
            return None, "ETF_REALTIME_ALERT_FEISHU_WEBHOOK_URL 未配置"
        payload = self._build_payload(alert)
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        webhook_request = request.Request(
            webhook_url,
            data=request_body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with self._urlopen_fn(webhook_request, timeout=self._settings.ops_task_notify_timeout_seconds) as response:
                response_status = response.status
                response_body = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            return None, f"Feishu HTTP {exc.code}: {truncate_text(response_body, 500)}"
        except error.URLError as exc:
            return None, f"Feishu request failed: {exc.reason}"
        if response_status < 200 or response_status >= 300:
            return None, f"Feishu HTTP {response_status}: {truncate_text(response_body, 500)}"
        message_id, error_message = _parse_feishu_response(response_body)
        return message_id, error_message

    def _build_payload(self, alert: EtfRealtimeAlert) -> dict[str, Any]:
        title = f"ETF成交额异动：{alert.etf_name or alert.ts_code}（{alert.severity}）"
        lines = [
            f"ETF：{alert.ts_code} {alert.etf_name or ''}".strip(),
            f"分组：{alert.group_name}",
            f"窗口：{alert.window_minutes} 分钟，时间：{alert.trade_date} {alert.bucket_end_time}",
            f"当前成交额：{alert.current_amount_yuan} 元",
            f"历史基准：{alert.baseline_amount_yuan} 元",
            f"放量倍数：{alert.ratio}",
        ]
        payload: dict[str, Any] = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [[{"tag": "text", "text": truncate_text("\n".join(lines), 3500) or ""}]],
                    }
                }
            },
        }
        secret = self._settings.etf_realtime_alert_feishu_webhook_secret.strip()
        if secret:
            timestamp = int(self._time_fn())
            payload["timestamp"] = str(timestamp)
            payload["sign"] = build_feishu_signature(timestamp, secret)
        return payload


def _parse_feishu_response(response_body: str) -> tuple[str | None, str | None]:
    if not response_body.strip():
        return None, None
    try:
        body = json.loads(response_body)
    except json.JSONDecodeError:
        return None, None
    code = body.get("code", body.get("StatusCode"))
    if code not in (None, 0, "0"):
        message = body.get("msg", body.get("StatusMessage", response_body))
        return None, f"Feishu rejected message: code={code}, message={message}"
    return body.get("data", {}).get("message_id") if isinstance(body.get("data"), dict) else None, None
