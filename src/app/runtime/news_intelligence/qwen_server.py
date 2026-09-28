from __future__ import annotations

from contextlib import AbstractContextManager
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from .model_process import ModelProcessError, assert_loopback_url


class QwenLoopbackServer(AbstractContextManager["QwenLoopbackServer"]):
    def __init__(
        self,
        *,
        server_binary: Path,
        model_path: Path,
        lock_path: Path,
        port: int,
        startup_timeout_seconds: float = 60.0,
    ) -> None:
        if not 1024 <= port <= 65535:
            raise ValueError("port must be between 1024 and 65535")
        self._server_binary = server_binary
        self._model_path = model_path
        self._lock_path = lock_path
        self._port = port
        self._startup_timeout = startup_timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._lock_descriptor: int | None = None
        self.base_url = f"http://127.0.0.1:{port}"
        assert_loopback_url(self.base_url)

    def __enter__(self) -> "QwenLoopbackServer":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_descriptor = os.open(
            self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        try:
            os.write(self._lock_descriptor, str(os.getpid()).encode("ascii"))
            self._process = subprocess.Popen(
                (
                    "nice",
                    "-n",
                    "10",
                    str(self._server_binary),
                    "--model",
                    str(self._model_path),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self._port),
                    "--threads",
                    "4",
                    "--threads-batch",
                    "4",
                    "--ctx-size",
                    "2048",
                    "--parallel",
                    "1",
                    "--batch-size",
                    "128",
                    "--ubatch-size",
                    "128",
                    "--no-webui",
                    "--log-disable",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            self._wait_until_ready()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def completion(
        self,
        *,
        prompt: str,
        grammar: str,
        max_tokens: int,
        timeout_seconds: float,
    ) -> dict[str, object]:
        if self._process is None or self._process.poll() is not None:
            raise ModelProcessError("Qwen loopback server is not running")
        request = Request(
            f"{self.base_url}/completion",
            data=json.dumps(
                {
                    "prompt": prompt,
                    "n_predict": max_tokens,
                    "temperature": 0,
                    "seed": 42,
                    "grammar": grammar,
                    "cache_prompt": False,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read())
        if not isinstance(payload, dict):
            raise ModelProcessError("Qwen response must be an object")
        return payload

    def completion_json(
        self,
        *,
        prompt: str,
        grammar: str,
        max_tokens: int,
        timeout_seconds: float,
        required_fields: frozenset[str],
    ) -> dict[str, object]:
        payload = self.completion(
            prompt=prompt,
            grammar=grammar,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        try:
            content = payload["content"]
            parsed = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ModelProcessError(
                "Qwen response does not contain valid structured JSON"
            ) from exc
        if not isinstance(parsed, dict) or not required_fields.issubset(parsed):
            raise ModelProcessError("Qwen structured JSON is missing required fields")
        return parsed

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            if self._process is not None and self._process.poll() is None:
                os.killpg(self._process.pid, signal.SIGTERM)
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self._process.pid, signal.SIGKILL)
                    self._process.wait(timeout=5)
        finally:
            if self._lock_descriptor is not None:
                os.close(self._lock_descriptor)
            self._lock_path.unlink(missing_ok=True)
        return False

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self._startup_timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                _, stderr = self._process.communicate()
                raise ModelProcessError(
                    f"Qwen server exited during startup: {stderr[-2000:]}"
                )
            try:
                with urlopen(f"{self.base_url}/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except (URLError, TimeoutError) as exc:
                last_error = exc
                time.sleep(0.2)
        raise ModelProcessError(f"Qwen server did not become healthy: {last_error}")
