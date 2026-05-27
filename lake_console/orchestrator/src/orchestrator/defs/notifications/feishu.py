import base64
import hashlib
import hmac
import json
import time
from urllib import error, request

import dagster as dg


FEISHU_WEBHOOK_URL_ENV_VAR = "GOLDENSHARE_FEISHU_WEBHOOK_URL"
FEISHU_WEBHOOK_SECRET_ENV_VAR = "GOLDENSHARE_FEISHU_WEBHOOK_SECRET"
DAGSTER_WEB_URL_ENV_VAR = "GOLDENSHARE_DAGSTER_WEB_URL"
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 5.0
DEFAULT_TEXT_MAX_LENGTH = 3500


def build_feishu_signature(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def truncate_text(text: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text

    suffix = "\n...[truncated]"
    if max_length <= len(suffix):
        return text[:max_length]
    return text[: max_length - len(suffix)] + suffix


class FeishuWebhookResource(dg.ConfigurableResource):
    webhook_url_env_var: str = FEISHU_WEBHOOK_URL_ENV_VAR
    webhook_secret_env_var: str = FEISHU_WEBHOOK_SECRET_ENV_VAR
    dagster_web_url_env_var: str = DAGSTER_WEB_URL_ENV_VAR
    timeout_seconds: float = DEFAULT_WEBHOOK_TIMEOUT_SECONDS
    text_max_length: int = DEFAULT_TEXT_MAX_LENGTH

    def run_url(self, run_id: str) -> str | None:
        base_url = (dg.EnvVar(self.dagster_web_url_env_var).get_value(default="") or "").strip()
        if not base_url:
            return None
        return f"{base_url.rstrip('/')}/runs/{run_id}"

    def send_text(self, text: str) -> None:
        webhook_url = (dg.EnvVar(self.webhook_url_env_var).get_value(default="") or "").strip()
        if not webhook_url:
            raise RuntimeError(f"Missing {self.webhook_url_env_var}; cannot send Feishu alert.")

        payload: dict[str, object] = {
            "msg_type": "text",
            "content": {"text": truncate_text(text, self.text_max_length)},
        }
        secret = (dg.EnvVar(self.webhook_secret_env_var).get_value(default="") or "").strip()
        if secret:
            timestamp = int(time.time())
            payload["timestamp"] = str(timestamp)
            payload["sign"] = build_feishu_signature(timestamp, secret)

        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        webhook_request = request.Request(
            webhook_url,
            data=request_body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with request.urlopen(webhook_request, timeout=self.timeout_seconds) as response:
                response_status = response.status
                response_body = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Feishu webhook returned HTTP {exc.code}: {truncate_text(response_body, 500)}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Feishu webhook request failed: {exc.reason}") from exc

        if response_status < 200 or response_status >= 300:
            raise RuntimeError(
                f"Feishu webhook returned HTTP {response_status}: "
                f"{truncate_text(response_body, 500)}"
            )
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
