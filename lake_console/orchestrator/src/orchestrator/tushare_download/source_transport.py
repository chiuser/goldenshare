"""Single-attempt transport contract and explicit production composition."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol

from .download_errors import require
from .download_models import AttemptOutcome


class SystemClock:
    @staticmethod
    def monotonic():
        return time.monotonic()

    @staticmethod
    def utc_now():
        return datetime.now(timezone.utc)


class SourceTransport(Protocol):
    def prepare(self, binding, config, contract) -> None: ...
    def fetch_page(
        self, request, config, memory, control, counters, attempt_number
    ) -> AttemptOutcome: ...
    def close(self) -> None: ...


def transport_factory(binding, clock):
    if binding.kind == 1:
        from .http_transport import HttpProTransport

        return HttpProTransport(clock)
    require(binding.kind == 2)
    from .sdk_transport import SDK_ADAPTERS, SdkTransport

    factory = SDK_ADAPTERS.get(binding.adapter_key)
    require(factory is not None)
    return SdkTransport(factory, clock)
