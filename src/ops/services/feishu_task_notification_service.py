from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable
from urllib import error, request

from src.foundation.config.settings import Settings, get_settings
from src.ops.services.task_run_completion_service import TaskRunCompletionSummary
from src.utils import truncate_text


LOGGER = logging.getLogger(__name__)
DEFAULT_TEXT_MAX_LENGTH = 3500


def build_feishu_signature(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class FeishuTaskNotificationService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        urlopen_fn: Callable[..., Any] | None = None,
        time_fn: Callable[[], float] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.urlopen_fn = urlopen_fn or request.urlopen
        self.time_fn = time_fn or time.time
        self.logger = logger or LOGGER

    def send_task_completion(self, summary: TaskRunCompletionSummary) -> bool:
        if not self.settings.ops_task_notify_feishu_enabled:
            return False
        webhook_url = self.settings.goldenshare_feishu_webhook_url.strip()
        secret = self.settings.goldenshare_feishu_webhook_secret.strip()
        if not webhook_url or not secret:
            self.logger.warning("Feishu task notification is enabled but webhook URL or secret is missing.")
            return False

        timestamp = int(self.time_fn())
        payload = self.build_payload(summary, timestamp=timestamp, secret=secret)
        self._post_payload(webhook_url, payload)
        return True

    @staticmethod
    def build_payload(summary: TaskRunCompletionSummary, *, timestamp: int, secret: str) -> dict[str, Any]:
        return {
            "timestamp": str(timestamp),
            "sign": build_feishu_signature(timestamp, secret),
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"任务完成：{summary.title}（{summary.status_label}）",
                        "content": [[{"tag": "text", "text": FeishuTaskNotificationService._message_text(summary)}]],
                    }
                }
            },
        }

    @staticmethod
    def _message_text(summary: TaskRunCompletionSummary) -> str:
        lines = [
            f"任务 ID：#{summary.task_run_id}",
            f"任务名称：{summary.title}",
            f"任务类型：{summary.task_type_label}",
            f"最终状态：{summary.status_label}",
            f"发起方式：{summary.trigger_source_label}",
            f"处理范围：{summary.time_scope_label}",
            f"执行耗时：{summary.duration_label}",
            f"处理进度：{summary.progress_label}",
            f"数据量：{summary.rows_label}",
        ]
        if summary.issue_summary:
            lines.append(f"问题摘要：{summary.issue_summary}")
        if summary.detail_url:
            lines.append(f"任务详情：{summary.detail_url}")
        return truncate_text("\n".join(lines), DEFAULT_TEXT_MAX_LENGTH) or ""

    def _post_payload(self, webhook_url: str, payload: dict[str, Any]) -> None:
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        webhook_request = request.Request(
            webhook_url,
            data=request_body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with self.urlopen_fn(webhook_request, timeout=self.settings.ops_task_notify_timeout_seconds) as response:
                response_status = response.status
                response_body = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Feishu webhook returned HTTP {exc.code}: {truncate_text(response_body, 500)}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Feishu webhook request failed: {exc.reason}") from exc

        if response_status < 200 or response_status >= 300:
            raise RuntimeError(f"Feishu webhook returned HTTP {response_status}: {truncate_text(response_body, 500)}")
        self._raise_for_feishu_error(response_body)

    @staticmethod
    def _raise_for_feishu_error(response_body: str) -> None:
        if not response_body.strip():
            return
        try:
            body = json.loads(response_body)
        except json.JSONDecodeError:
            return

        code = body.get("code", body.get("StatusCode"))
        if code in (None, 0, "0"):
            return
        message = body.get("msg", body.get("StatusMessage", response_body))
        raise RuntimeError(f"Feishu webhook rejected message: code={code}, message={message}")
