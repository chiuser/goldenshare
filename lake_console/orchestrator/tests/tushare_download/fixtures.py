"""Fixture fields follow local Tushare doc 27; modes/pages/errors are explicit synthetic cases.

These definitions are private to tests and are never placed in production registries.
The daily example rows are literal values from doc 27 or deliberately artificial
negative cases. No fixture claims to prove the live source's pagination behavior.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.dataset_transport_mapping import (
    DatasetTransportMapping,
    TransportBinding,
)
from orchestrator.tushare_download.download_api import _build_downloader
from orchestrator.tushare_download.download_models import (
    AttemptFailure,
    AttemptOutcome,
    DownloadMode,
    SourcePage,
    SourceRecord,
)
from orchestrator.tushare_download.source_contract import (
    ModeRule,
    OrderingRule,
    PaginationRule,
    ParameterRule,
    SourceDatasetContract,
    SourceField,
    SourceKind,
    TimeRule,
)

DAILY_NAMES = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)
DAY = TimeRule("day", "1", "YYYY-MM-DD", "YYYYMMDD", "trade_date")


def contract(*, limit=2, strategy=2, modes=None, ordering=True):
    if modes is None:
        modes = (
            ModeRule(DownloadMode.SNAPSHOT, allowed_filters=("exchange", "extra")),
            ModeRule(
                DownloadMode.BY_POINT,
                point_param="trade_date",
                allowed_filters=("exchange", "extra"),
                allow_empty_points=True,
            ),
            ModeRule(
                DownloadMode.BY_OBJECT, object_param="ts_code", allow_empty_objects=True
            ),
            ModeRule(
                DownloadMode.BY_OBJECT_POINT,
                object_param="ts_code",
                point_param="trade_date",
                allow_empty_objects=True,
                allow_empty_points=True,
            ),
            ModeRule(
                DownloadMode.BY_OBJECT_RANGE,
                object_param="ts_code",
                range_start_param="start_date",
                range_end_param="end_date",
                allow_empty_objects=True,
                allow_empty_object_ranges=True,
            ),
            ModeRule(
                DownloadMode.BY_RANGE,
                range_start_param="start_date",
                range_end_param="end_date",
            ),
        )
    p = (
        PaginationRule()
        if strategy == 1
        else PaginationRule(
            strategy,
            limit,
            0,
            limit,
            "limit",
            "offset",
            split_time_rule_key="day" if strategy == 3 else None,
        )
    )
    return SourceDatasetContract(
        "fixture.daily@1",
        "fixture_daily",
        "1",
        "daily",
        tuple(
            SourceField(
                n,
                SourceKind.STRING if i < 2 else SourceKind.NUMBER,
                description="doc27",
            )
            for i, n in enumerate(DAILY_NAMES)
        ),
        tuple(
            ParameterRule(n, SourceKind.STRING)
            for n in (
                "ts_code",
                "trade_date",
                "start_date",
                "end_date",
                "exchange",
                "extra",
            )
        ),
        modes,
        p,
        (DAY,),
        OrderingRule("trade_date", "day") if ordering else OrderingRule(),
        ("local-doc:27; synthetic mode and pagination fixture",),
    )


def rows(day="20180718", *, count=1, code="000001.SZ"):
    # First literal row's values are independently documented in local doc 27.
    row = (
        code,
        day,
        Decimal("8.75"),
        Decimal("8.85"),
        Decimal("8.69"),
        Decimal("8.70"),
        Decimal("8.72"),
        Decimal("-0.02"),
        Decimal("-0.23"),
        Decimal("525152.77"),
        Decimal("460697.377"),
    )
    return (row,) * count


class FakeClock:
    def __init__(self):
        self.seconds = 0.0
        self.waits = []

    def monotonic(self):
        return self.seconds

    def utc_now(self):
        return datetime(2026, 10, 22, tzinfo=timezone.utc) + timedelta(
            seconds=self.seconds
        )

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.seconds += seconds


class ScriptTransport:
    """Replaces only transport, preserving the declared send/success counting boundary."""

    def __init__(self, responder, calls):
        self.responder, self.calls = responder, calls
        self.closed = 0
        self.last_cleanup_errors = ()
        self.contract = None

    def prepare(self, binding, config, definition):
        self.contract = definition

    def fetch_page(self, request, config, memory, control, counters, attempt_number):
        control.raise_if_cancelled()
        counters.mark_sent(attempt_number)
        self.calls.append(request)
        result = self.responder(request, attempt_number)
        if isinstance(result, AttemptFailure):
            return AttemptOutcome(failure=result)
        if isinstance(result, SourcePage):
            page = result
        else:
            page = SourcePage(
                request.fields,
                tuple(
                    SourceRecord(
                        request.fields,
                        tuple(values),
                        request.position.request_input_index,
                    )
                    for values in result
                ),
            )
        memory.attach("source_page", page)
        counters.mark_response_success()
        return AttemptOutcome(page=page)

    def close(self):
        self.closed += 1


def build(
    responder=lambda request, attempt: (),
    *,
    definition=None,
    config=None,
    clock=None,
    factory=None,
):
    definition = definition or contract()
    config = config or ConfigurationSnapshot("isolated-token", "http://127.0.0.1:1")
    clock = clock or FakeClock()
    calls, transports = [], []

    def create(binding, current_clock):
        value = (
            factory(binding, current_clock)
            if factory
            else ScriptTransport(responder, calls)
        )
        transports.append(value)
        return value

    registry = ContractRegistry((definition,))
    bindings = DatasetTransportMapping(
        (TransportBinding(definition.dataset_id, definition.source_api_name),)
    )
    downloader = _build_downloader(
        config, registry, bindings, create, clock, clock.sleep
    )
    return downloader, calls, transports, clock


def small_config(**changes):
    return replace(
        ConfigurationSnapshot("isolated-token", "http://127.0.0.1:1"),
        unit_memory_limit_bytes=4 * 1024 * 1024,
        working_reserve_bytes=1024,
        max_request_bytes=4096,
        max_response_bytes=65536,
        **changes,
    )
