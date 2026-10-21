"""Normal, instance-local SDK adapter infrastructure; no unverified method is registered."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, is_dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from types import MappingProxyType

from .download_errors import DownloadError, ErrorDetails, require
from .download_errors import DownloadErrorCode as Code
from .download_models import (
    AttemptFailure,
    AttemptOutcome,
    CleanupIssue,
    SourcePage,
    SourceRecord,
)
from .source_contract import valid_scalar
from .source_response import classify_source_message


@dataclass(frozen=True, slots=True)
class SdkMethod:
    """A method's reviewed normal construction, source call, parsing and disposal."""

    distribution: str
    create_client: Callable
    call: Callable
    parse: Callable
    close_client: Callable | None = None


SDK_ADAPTERS = MappingProxyType({})


def _call_source(method, client, request):
    try:
        return method.call(client, request), None
    except (
        PermissionError,
        FileNotFoundError,
        IsADirectoryError,
        ValueError,
        TypeError,
    ):
        raise
    except (TimeoutError, ConnectionError) as error:
        failure = AttemptFailure(Code.TRANSIENT_SOURCE, cause_type=type(error).__name__)
    except Exception as error:  # noqa: BLE001 - catch only the registered SDK's actual source invocation.
        # Only the actual SDK source invocation is caught here, not parsing,
        # construction, cancellation checks, observers or closing.
        failure = AttemptFailure(
            classify_source_message(f"{type(error).__name__}: {error}"),
            cause_type=type(error).__name__,
        )
    return None, failure


class SdkTransport:
    def __init__(self, adapter_factory, clock):
        self._factory, self.clock = adapter_factory, clock
        self._client = self._method = self.contract = None
        self.last_cleanup_errors = ()

    def prepare(self, binding, config, contract):
        method = self._factory()
        require(isinstance(method, SdkMethod) and binding.kind == 2)
        installed = None
        try:
            installed = version(method.distribution)
        except PackageNotFoundError:
            pass
        require(installed is not None and installed in binding.allowed_sdk_versions)
        require(binding.source_api_name == contract.source_api_name)
        self._method, self.contract = method, contract

    def _close_owned(self):
        if self._client is None:
            return ()
        try:
            if self._method.close_client is not None:
                self._method.close_client(self._client)
        except Exception as error:  # noqa: BLE001 - closing failure is recorded without masking the primary error.
            return (CleanupIssue("sdk_client", type(error).__name__),)
        self._client = None
        return ()

    def close(self):
        issues = self._close_owned()
        if issues:
            raise DownloadError(
                Code.CLEANUP, details=ErrorDetails(cleanup_errors=issues)
            )

    def fetch_page(self, request, config, memory, control, counters, attempt_number):
        self.last_cleanup_errors = ()
        raw = page = failure = None
        try:
            control.raise_if_cancelled()
            self._client = self._method.create_client(config)
            control.raise_if_cancelled()
            counters.mark_sent(attempt_number)
            started = self.clock.monotonic()
            try:
                raw, failure = _call_source(self._method, self._client, request)
            finally:
                counters.unit.receive_seconds += self.clock.monotonic() - started
            control.raise_if_cancelled()
            if failure is None:
                # Registered methods must document the normal object's __sizeof__
                # and temporary-conversion estimate. Do not walk arbitrary __dict__.
                finite_container = type(raw) in (tuple, list, dict) or is_dataclass(raw)
                memory.attach("sdk_return", raw, shallow=not finite_container)
                memory.reserve("sdk_conversion", max(1024, raw.__sizeof__()) * 4)
                page = self._method.parse(raw, request, self.contract, memory)
                if isinstance(page, AttemptFailure):
                    failure, page = page, None
                else:
                    valid = (
                        isinstance(page, SourcePage)
                        and type(page.fields) is tuple
                        and bool(page.fields)
                        and all(type(n) is str and bool(n) for n in page.fields)
                        and len(set(page.fields)) == len(page.fields)
                        and type(page.records) is tuple
                    )
                    valid = valid and all(
                        v is None or (type(v) is int and v >= 0)
                        for v in (page.total, page.next_offset)
                    )
                    valid = valid and (
                        request.expected_limit is None
                        or len(page.records) <= request.expected_limit
                    )
                    valid = valid and all(
                        isinstance(r, SourceRecord)
                        and r.fields == page.fields
                        and type(r.values) is tuple
                        and len(r.values) == len(r.fields)
                        and r.request_input_index
                        == request.position.request_input_index
                        and all(valid_scalar(v) for v in r.values)
                        for r in page.records
                    )
                    if not valid:
                        failure, page = AttemptFailure(Code.SOURCE_PROTOCOL), None
                    else:
                        memory.attach("source_page", page)
                        counters.mark_response_success()
        except MemoryError:
            raise DownloadError(Code.CAPACITY) from None
        finally:
            self.last_cleanup_errors = self._close_owned()
            memory.release("sdk_return")
            memory.release("sdk_conversion")
            raw = None
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
