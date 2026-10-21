"""Synchronous, one-attempt HTTP; no hidden retries, workers or global SDK changes."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
from dataclasses import replace
from decimal import Decimal
from urllib.parse import urlsplit

from .download_errors import DownloadError, ErrorDetails, require
from .download_errors import DownloadErrorCode as Code
from .download_models import AttemptFailure, AttemptOutcome, CleanupIssue, SourcePage
from .retry_policy import retry_after_at
from .source_response import http_status_failure, parse_http


def encode_request(value, limit):
    parts, used = [], 0

    def append(text):
        nonlocal used
        require(len(text) <= limit, Code.CAPACITY)
        raw = text.encode("utf-8")
        used += len(raw)
        require(used <= limit, Code.CAPACITY)
        parts.append(raw)

    def visit(item):
        if item is None:
            append("null")
        elif type(item) is bool:
            append("true" if item else "false")
        elif type(item) is str:
            require(len(item) <= limit, Code.CAPACITY)
            append(json.dumps(item, ensure_ascii=False))
        elif type(item) is int:
            append(str(item))
        elif type(item) is Decimal:
            require(item.is_finite(), Code.INPUT)
            append(str(item))
        elif type(item) is dict:
            append("{")
            for i, (key, val) in enumerate(item.items()):
                require(type(key) is str, Code.INPUT)
                if i:
                    append(",")
                visit(key)
                append(":")
                visit(val)
            append("}")
        elif type(item) in (list, tuple):
            append("[")
            for i, val in enumerate(item):
                if i:
                    append(",")
                visit(val)
            append("]")
        else:
            raise DownloadError(Code.INPUT)

    visit(value)
    return b"".join(parts)


def _io(operation):
    # Only an actual source IO call belongs inside this catch. Never controls,
    # callbacks, local parsing, allocation or resource closing.
    try:
        return operation(), None
    except (TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
        failure = AttemptFailure(Code.TRANSIENT_SOURCE, cause_type=type(error).__name__)
    except socket.gaierror as error:
        failure = AttemptFailure(
            Code.TRANSIENT_SOURCE
            if error.errno == socket.EAI_AGAIN
            else Code.UNCLASSIFIED_SOURCE,
            cause_type=type(error).__name__,
        )
    except (http.client.BadStatusLine, http.client.LineTooLong) as error:
        failure = AttemptFailure(Code.SOURCE_PROTOCOL, cause_type=type(error).__name__)
    except ssl.SSLError as error:
        failure = AttemptFailure(
            Code.UNCLASSIFIED_SOURCE, cause_type=type(error).__name__
        )
    except http.client.ImproperConnectionState:
        raise
    except http.client.HTTPException as error:
        failure = AttemptFailure(
            Code.UNCLASSIFIED_SOURCE, cause_type=type(error).__name__
        )
    except (PermissionError, FileNotFoundError, IsADirectoryError):
        raise
    except OSError as error:
        failure = AttemptFailure(
            Code.UNCLASSIFIED_SOURCE, cause_type=type(error).__name__
        )
    return None, failure


class HttpProTransport:
    def __init__(self, clock):
        self.clock = clock
        self.last_cleanup_errors = ()
        self._handles = []
        self.binding = self.contract = None

    def prepare(self, binding, config, contract):
        require(binding.kind == 1 and binding.adapter_key == "http_pro")
        require(binding.source_api_name == contract.source_api_name)
        self.binding, self.contract = binding, contract

    def _close_owned(self):
        failed, issues = [], []
        for owner, resource in self._handles:
            try:
                resource.close()
            except Exception as error:  # noqa: BLE001 - attempt every owned resource, retain sanitized cleanup facts.
                issues.append(CleanupIssue(owner, type(error).__name__))
                failed.append((owner, resource))
        self._handles = failed
        return tuple(issues)

    def close(self):
        issues = self._close_owned()
        if issues:
            raise DownloadError(
                Code.CLEANUP, details=ErrorDetails(cleanup_errors=issues)
            )

    def fetch_page(self, request, config, memory, control, counters, attempt_number):
        self.last_cleanup_errors = ()
        page = failure = None
        try:
            outcome = self._perform(
                request, config, memory, control, counters, attempt_number
            )
            if isinstance(outcome, SourcePage):
                page = outcome
                counters.mark_response_success()
            else:
                failure = outcome
        except MemoryError:
            raise DownloadError(Code.CAPACITY) from None
        finally:
            self.last_cleanup_errors = self._close_owned()
            for label in (
                "request_body",
                "body_buffer",
                "read_block",
                "body_growth",
                "body_copy",
                "response_body",
            ):
                memory.release(label)
            outcome = None
        try:
            if self.last_cleanup_errors:
                failure = (
                    replace(failure, cleanup_errors=self.last_cleanup_errors)
                    if failure
                    else AttemptFailure(
                        Code.CLEANUP, cleanup_errors=self.last_cleanup_errors
                    )
                )
                page = None
                memory.release("source_page")
            return AttemptOutcome(page=page, failure=failure)
        finally:
            page = failure = None

    def _perform(self, request, config, memory, control, counters, attempt_number):
        connection = response = read_socket = body = chunk = buffer = None

        def io(operation):
            started = self.clock.monotonic()
            try:
                return _io(operation)
            finally:
                counters.unit.receive_seconds += self.clock.monotonic() - started

        try:
            control.raise_if_cancelled()
            payload = {
                "api_name": request.api_name,
                "token": config.token,
                "params": dict(request.params),
                "fields": ",".join(request.fields),
            }
            memory.reserve("request_encoding", config.max_request_bytes * 4)
            body = encode_request(payload, config.max_request_bytes)
            memory.attach("request_body", body)
            memory.unreserve("request_encoding")
            url = urlsplit(config.base_url)
            path = url.path or "/"
            if self.binding.http_path_rule == "api_name":
                path = path.rstrip("/") + "/" + request.api_name
            if url.query:
                path += "?" + url.query
            deadline = self.clock.monotonic() + config.request_timeout_seconds

            def timeout(stage_limit):
                remaining = deadline - self.clock.monotonic()
                return min(stage_limit, remaining)

            connection_class = (
                http.client.HTTPSConnection
                if url.scheme == "https"
                else http.client.HTTPConnection
            )
            connection = connection_class(
                url.hostname, url.port, timeout=timeout(config.connect_timeout_seconds)
            )
            self._handles.append(("http_connection", connection))
            control.raise_if_cancelled()
            counters.mark_sent(attempt_number)
            _, failure = io(
                lambda: connection.request(
                    "POST",
                    path,
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                    },
                )
            )
            if failure:
                return failure
            # getresponse() can detach the connection's socket for a closing
            # response. Keep the same socket reference to update the live reader;
            # ownership and closing still belong to response/connection.
            read_socket = connection.sock

            def before_read():
                control.raise_if_cancelled()
                remaining = timeout(config.read_timeout_seconds)
                if remaining <= 0:
                    return AttemptFailure(
                        Code.TRANSIENT_SOURCE, cause_type="TimeoutError"
                    )
                if read_socket is not None and (
                    response is None or not response.isclosed()
                ):
                    read_socket.settimeout(remaining)
                return None

            failure = before_read()
            if failure:
                return failure
            response, failure = io(connection.getresponse)
            if failure:
                return failure
            self._handles.insert(0, ("http_response", response))
            control.raise_if_cancelled()
            earliest_retry = retry_after_at(
                response.getheader("Retry-After"), self.clock
            )
            failure = http_status_failure(response.status, earliest_retry)
            if failure:
                return failure
            expected = None
            if not response.chunked:
                header = response.getheader("Content-Length")
                if header is not None:
                    if not header or not all("0" <= c <= "9" for c in header):
                        return AttemptFailure(Code.SOURCE_PROTOCOL)
                    significant = header.lstrip("0") or "0"
                    require(
                        len(significant) <= len(str(config.max_response_bytes)),
                        Code.CAPACITY,
                    )
                    expected = int(significant)
                    require(expected <= config.max_response_bytes, Code.CAPACITY)
            buffer = bytearray()
            memory.attach("body_buffer", buffer, shallow=True)
            while True:
                failure = before_read()
                if failure:
                    return failure
                memory.reserve("read_block", 65536 + 64)
                chunk, failure = io(lambda: response.read1(65536))
                if failure:
                    return failure
                memory.attach("read_block", chunk)
                control.raise_if_cancelled()
                if self.clock.monotonic() >= deadline:
                    return AttemptFailure(
                        Code.TRANSIENT_SOURCE, cause_type="TimeoutError"
                    )
                if not chunk:
                    if expected is not None and len(buffer) != expected:
                        return AttemptFailure(
                            Code.TRANSIENT_SOURCE, cause_type="IncompleteRead"
                        )
                    break
                require(
                    len(buffer) + len(chunk) <= config.max_response_bytes, Code.CAPACITY
                )
                memory.reserve("body_growth", len(chunk) * 2 + 256)
                buffer.extend(chunk)
                memory.refresh_shallow("body_buffer", buffer)
                memory.unreserve("body_growth")
                memory.release("read_block")
                chunk = None
            memory.reserve("body_copy", len(buffer) + 64)
            body = bytes(buffer)
            memory.attach("response_body", body)
            memory.release("body_copy")
            memory.release("body_buffer")
            buffer = None
            control.raise_if_cancelled()
            result = parse_http(body, request, self.contract, memory)
            return result
        finally:
            memory.release("request_encoding")
            payload = body = chunk = buffer = None
            response = read_socket = connection = result = None
