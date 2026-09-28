from __future__ import annotations

from collections.abc import Iterable, Sequence
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import urlparse


class ModelProcessError(RuntimeError):
    pass


class SerializedModelProcess:
    """Run one bounded JSONL model stage with process-group cleanup."""

    def __init__(self, *, lock_path: Path) -> None:
        self._lock_path = lock_path

    def run(
        self,
        command: Sequence[str],
        requests: Iterable[dict[str, object]],
        *,
        timeout_seconds: float,
        environment: dict[str, str] | None = None,
    ) -> tuple[dict[str, object], ...]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        payload = "".join(
            json.dumps(item, ensure_ascii=False) + "\n" for item in requests
        )
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            process = subprocess.Popen(
                tuple(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(payload, timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _terminate_process_group(process)
                raise ModelProcessError(
                    f"model stage timed out after {timeout_seconds}s"
                ) from exc
            if process.returncode != 0:
                raise ModelProcessError(
                    f"model stage exited {process.returncode}: {stderr[-2000:]}"
                )
            responses = []
            for line_number, line in enumerate(stdout.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ModelProcessError(
                        f"model stage returned invalid JSON on line {line_number}"
                    ) from exc
                if not isinstance(value, dict):
                    raise ModelProcessError(
                        f"model stage response line {line_number} is not an object"
                    )
                responses.append(value)
            return tuple(responses)
        finally:
            os.close(descriptor)
            self._lock_path.unlink(missing_ok=True)


def assert_loopback_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("model server URL must use a loopback host")


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 5.0
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
    finally:
        process.wait(timeout=5)
