from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.ops.services.feishu_task_notification_service import FeishuTaskNotificationService, build_feishu_signature
from src.ops.services.task_run_completion_service import TaskRunCompletionSummary


class FakeResponse:
    def __init__(self, *, status: int = 200, body: str = '{"code":0}') -> None:
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")


def build_settings(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "ops_task_notify_feishu_enabled": True,
        "goldenshare_feishu_webhook_url": "https://open.feishu.cn/test",
        "goldenshare_feishu_webhook_secret": "secret",
        "ops_task_notify_timeout_seconds": 5,
        "ops_public_base_url": "https://ops.example",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def build_summary() -> TaskRunCompletionSummary:
    return TaskRunCompletionSummary(
        task_run_id=42,
        title="股票日线",
        task_type_label="数据维护",
        status_label="成功",
        trigger_source_label="手动",
        time_scope_label="2026-05-29",
        duration_label="12秒",
        progress_label="1/1",
        rows_label="读取 10，写入 10，拒绝 0",
        issue_summary=None,
        detail_url="https://ops.example/app/ops/tasks/42",
    )


def test_build_feishu_signature_matches_existing_algorithm() -> None:
    assert build_feishu_signature(1717040000, "secret") == "Z3crSkklA8UfQNgJeDck5szvUcIqfhb9lzQdsmWatkU="


def test_send_task_completion_builds_post_payload_with_signature() -> None:
    captured = {}

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    service = FeishuTaskNotificationService(
        settings=build_settings(),
        urlopen_fn=fake_urlopen,
        time_fn=lambda: 1717040000,
    )

    sent = service.send_task_completion(build_summary())

    assert sent is True
    assert captured["url"] == "https://open.feishu.cn/test"
    assert captured["timeout"] == 5
    payload = captured["payload"]
    assert payload["msg_type"] == "post"
    assert payload["timestamp"] == "1717040000"
    assert payload["sign"] == "Z3crSkklA8UfQNgJeDck5szvUcIqfhb9lzQdsmWatkU="
    text = payload["content"]["post"]["zh_cn"]["content"][0][0]["text"]
    assert "任务 ID：#42" in text
    assert "数据量：读取 10，写入 10，拒绝 0" in text
    assert "任务详情：https://ops.example/app/ops/tasks/42" in text


def test_send_task_completion_skips_when_enabled_but_secret_missing(caplog) -> None:
    calls = []
    service = FeishuTaskNotificationService(
        settings=build_settings(goldenshare_feishu_webhook_secret=""),
        urlopen_fn=lambda *args, **kwargs: calls.append(args),
    )

    sent = service.send_task_completion(build_summary())

    assert sent is False
    assert calls == []
    assert "webhook URL or secret is missing" in caplog.text


def test_send_task_completion_raises_on_feishu_business_error() -> None:
    service = FeishuTaskNotificationService(
        settings=build_settings(),
        urlopen_fn=lambda *args, **kwargs: FakeResponse(body='{"code":999,"msg":"bad"}'),
        time_fn=lambda: 1717040000,
    )

    with pytest.raises(RuntimeError, match="Feishu webhook rejected message"):
        service.send_task_completion(build_summary())
