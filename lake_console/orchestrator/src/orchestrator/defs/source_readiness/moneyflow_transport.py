"""One owned, abortable process per moneyflow source attempt; no lake writes."""

import json
import logging
import math
import os
import selectors
import signal
import struct
import subprocess
import sys
from time import perf_counter

from requests import Response
from requests.exceptions import HTTPError

from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_RSS_BYTES,
    MONEYFLOW_MKT_DC_FIELDS,
    MONEYFLOW_PAGE_SIZE,
    MONEYFLOW_REQUEST_TIMEOUT_SECONDS,
    MONEYFLOW_WORKER_CLEANUP_SECONDS,
    MONEYFLOW_WORKER_INPUT_MAX_BYTES,
    MONEYFLOW_WORKER_POLL_SECONDS,
    MONEYFLOW_WORKER_RESULT_MAX_BYTES,
    MONEYFLOW_WORKER_RSS_SAMPLE_SECONDS,
    MoneyflowContractError,
    moneyflow_peak_rss_bytes,
)
from orchestrator.defs.run_contracts.moneyflow_daily import (
    daily_fields,
    daily_request_scopes,
)
from orchestrator.defs.source_readiness import moneyflow_request_worker
from orchestrator.defs.tushare_errors import TushareResponseError
from orchestrator.defs.tushare_request_policy import classify_tushare_error


def validate_source_input(api_name, params, fields):
    expected = (
        MONEYFLOW_MKT_DC_FIELDS
        if api_name == "moneyflow_mkt_dc"
        else daily_fields(api_name)
    )
    if tuple(fields) != expected or not isinstance(params, dict):
        raise MoneyflowContractError("source_worker_input")
    if set(params) - {"trade_date", "limit", "offset", "content_type"}:
        raise MoneyflowContractError("source_worker_input")
    day = params.get("trade_date")
    if not isinstance(day, str) or len(day) != 8 or not day.isdecimal():
        raise MoneyflowContractError("source_worker_input")
    if (
        params.get("limit") != MONEYFLOW_PAGE_SIZE
        or type(params.get("offset")) is not int
        or params["offset"] < 0
    ):
        raise MoneyflowContractError("source_worker_input")
    scopes = (
        (None,) if api_name == "moneyflow_mkt_dc" else daily_request_scopes(api_name)
    )
    if params.get("content_type") not in scopes:
        raise MoneyflowContractError("source_worker_input")


def source_error(value):
    """Reconstruct only literal categories, never deserialize remote exceptions."""
    category = value.get("category")
    if category == "source_or_data_contract":
        error = ValueError("source_or_data_contract")
    elif category == "non_retryable":
        error = PermissionError("source_non_retryable")
    elif category == "source_response_unclassified":
        error = TushareResponseError("source_response_unclassified")
    elif category in {"source_permission_or_parameter", "rate_limit", "transient"}:
        response = Response()
        response.status_code = {
            "source_permission_or_parameter": 403,
            "rate_limit": 429,
            "transient": 503,
        }[category]
        error = HTTPError("source_error", response=response)
    else:
        raise MoneyflowContractError("source_worker_error_contract")
    if type(value.get("retryable")) is not bool or classify_tushare_error(error) != (
        category,
        value["retryable"],
    ):
        raise MoneyflowContractError("source_worker_error_contract")
    return error


def _environment():
    names = {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "VIRTUAL_ENV",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {key: value for key, value in os.environ.items() if key in names}


def _pair_rss(process):
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "pid=,rss=", "-p", f"{os.getpid()},{process.pid}"],
            capture_output=True,
            timeout=MONEYFLOW_WORKER_POLL_SECONDS,
            check=True,
        )
        values = {
            int(pid): int(rss) * 1024
            for pid, rss in (line.split() for line in result.stdout.splitlines())
        }
        if process.poll() is not None:
            return  # The complete frame's peak is required before accepting a page.
        if set(values) != {os.getpid(), process.pid} or min(values.values()) <= 0:
            raise ValueError("missing_pid")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise MoneyflowContractError("source_worker_rss_unavailable") from error
    if sum(values.values()) > MONEYFLOW_MAX_RSS_BYTES:
        raise MoneyflowContractError("memory_budget_exceeded")


def _close_worker(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=MONEYFLOW_WORKER_CLEANUP_SECONDS / 2)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=MONEYFLOW_WORKER_CLEANUP_SECONDS / 2)
            except subprocess.TimeoutExpired as error:
                raise MoneyflowContractError("source_worker_cleanup_failed") from error
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            stream.close()


def call_moneyflow_source(
    tushare,
    api_name,
    params,
    fields,
    *,
    deadline,
    check_cancel=lambda: None,
    _command=None,
):
    """Internal test command seam is never exposed by resource/config/CLI."""
    from orchestrator.defs.resources import TushareResult

    check_cancel()
    validate_source_input(api_name, params, fields)
    token = getattr(tushare, "token", None)
    if type(token) is not str or not token.strip():
        raise MoneyflowContractError("source_worker_token")
    if (
        os.name != "posix"
        or not math.isfinite(deadline)
        or not all(
            hasattr(signal, name) for name in ("SIGALRM", "ITIMER_REAL", "setitimer")
        )
        or not os.access("/bin/ps", os.X_OK)
    ):
        raise MoneyflowContractError("source_worker_platform_or_deadline")
    started = perf_counter()
    if deadline - started <= MONEYFLOW_REQUEST_TIMEOUT_SECONDS:
        raise MoneyflowContractError("request_budget_exceeded")
    work_deadline = min(
        started + MONEYFLOW_REQUEST_TIMEOUT_SECONDS - MONEYFLOW_WORKER_CLEANUP_SECONDS,
        deadline - MONEYFLOW_WORKER_CLEANUP_SECONDS,
    )
    payload = (
        json.dumps(
            {
                "token": token.strip(),
                "api_name": api_name,
                "params": params,
                "fields": list(fields),
                "deadline": work_deadline,
            },
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    if len(payload) > MONEYFLOW_WORKER_INPUT_MAX_BYTES:
        raise MoneyflowContractError("source_worker_input_bytes")
    command = (_command(work_deadline) if callable(_command) else _command) or [
        sys.executable,
        "-B",
        "-m",
        moneyflow_request_worker.__name__,
        str(work_deadline),
    ]
    # No credential or business row enters argv or an intermediate file.
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_environment(),
        close_fds=True,
    )
    data, sent, expected, eof, last_rss = bytearray(), 0, None, False, 0.0
    try:
        with selectors.DefaultSelector() as selector:
            for stream, events in (
                (process.stdin, selectors.EVENT_WRITE),
                (process.stdout, selectors.EVENT_READ),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, events)
            while True:
                check_cancel()
                now = perf_counter()
                if now >= work_deadline:
                    raise MoneyflowContractError("source_total_deadline")
                if now - last_rss >= MONEYFLOW_WORKER_RSS_SAMPLE_SECONDS:
                    _pair_rss(process)
                    last_rss = now
                    check_cancel()
                status = process.poll()
                if status is not None and eof:
                    if status != 0:
                        raise MoneyflowContractError(
                            "source_total_deadline"
                            if status == -signal.SIGALRM
                            else "source_worker_failed"
                        )
                    break
                for key, _ in selector.select(
                    max(
                        0,
                        min(
                            MONEYFLOW_WORKER_POLL_SECONDS,
                            work_deadline - perf_counter(),
                        ),
                    )
                ):
                    check_cancel()
                    if key.fileobj is process.stdin:
                        sent += os.write(
                            process.stdin.fileno(), payload[sent : sent + 64 * 1024]
                        )
                        if sent == len(payload):
                            selector.unregister(
                                process.stdin
                            )  # Keep stdin open as the lifeline.
                    else:
                        part = os.read(process.stdout.fileno(), 64 * 1024)
                        if not part:
                            eof = True
                            selector.unregister(process.stdout)
                        data.extend(part)
                        if len(data) > MONEYFLOW_WORKER_RESULT_MAX_BYTES:
                            raise MoneyflowContractError("source_worker_result_bytes")
                        if expected is None and len(data) >= 8:
                            expected = struct.unpack("!Q", data[:8])[0] + 16
                            if not 16 < expected <= MONEYFLOW_WORKER_RESULT_MAX_BYTES:
                                raise MoneyflowContractError(
                                    "source_worker_result_bytes"
                                )
                        if expected is not None and len(data) > expected:
                            raise MoneyflowContractError("source_worker_result_frame")
        if expected is None or len(data) != expected:
            raise MoneyflowContractError("source_worker_result_frame")
        peak = struct.unpack("!Q", data[-8:])[0]
        if (
            not 0 < peak <= MONEYFLOW_MAX_RSS_BYTES
            or peak + moneyflow_peak_rss_bytes() > MONEYFLOW_MAX_RSS_BYTES
        ):
            raise MoneyflowContractError("memory_budget_exceeded")
        value = json.loads(data[8:-8])
        if not isinstance(value, dict) or type(value.get("ok")) is not bool:
            raise MoneyflowContractError("source_worker_result_contract")
        logging.getLogger(__name__).info(
            "moneyflow request ended api=%s elapsed_ms=%.1f child_peak_rss_bytes=%s pair_peak_upper_bytes=%s",
            api_name,
            (perf_counter() - started) * 1000,
            peak,
            peak + moneyflow_peak_rss_bytes(),
        )
        if not value["ok"]:
            raise source_error(value)
        if (
            set(value) != {"ok", "columns", "rows", "metadata"}
            or not isinstance(value["rows"], list)
            or not isinstance(value["metadata"], dict)
            or not isinstance(value["columns"], list)
        ):
            raise MoneyflowContractError("source_worker_result_contract")
        return TushareResult(
            rows=value["rows"],
            columns=tuple(value["columns"]),
            metadata=value["metadata"],
        )
    except (BrokenPipeError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MoneyflowContractError("source_worker_result_contract") from error
    finally:
        _close_worker(process)
