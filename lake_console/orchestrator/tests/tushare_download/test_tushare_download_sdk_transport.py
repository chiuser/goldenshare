from dataclasses import replace
from decimal import Decimal

import pytest

from orchestrator.tushare_download import DownloadError, DownloadTask
from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.dataset_transport_mapping import (
    DatasetTransportMapping,
    TransportBinding,
)
from orchestrator.tushare_download.download_api import _build_downloader
from orchestrator.tushare_download.download_models import SourcePage, SourceRecord
from orchestrator.tushare_download.sdk_transport import (
    SDK_ADAPTERS,
    SdkMethod,
    SdkTransport,
)

from .fixtures import FakeClock, contract, small_config


def sdk_downloader(call, *, close=None, installed_versions=("0.1.0",), parser=None):
    # A private normal SDK method substitute, NOT a verified Tushare method.
    clients, transports = [], []

    def create(config):
        client = {"closed": False}
        clients.append(client)
        return client

    def parse(raw, request, definition, memory):
        if parser is not None:
            return parser(raw, request, definition, memory)
        return SourcePage(
            ("trade_date", "close"),
            tuple(
                SourceRecord(
                    ("trade_date", "close"),
                    tuple(row),
                    request.position.request_input_index,
                )
                for row in raw
            ),
        )

    def finish(client):
        client["closed"] = True
        if close:
            close(client)

    method = SdkMethod("orchestrator", create, call, parse, finish)
    definition = contract(strategy=1)
    binding = TransportBinding(
        definition.dataset_id,
        definition.source_api_name,
        2,
        "private_fixture",
        "1",
        installed_versions,
        None,
    )
    clock = FakeClock()

    def factory(binding, current_clock):
        value = SdkTransport(lambda: method, current_clock)
        transports.append(value)
        return value

    downloader = _build_downloader(
        small_config(),
        ContractRegistry((definition,)),
        DatasetTransportMapping((binding,)),
        factory,
        clock,
        clock.sleep,
    )
    return downloader, clients, transports


def test_sdk_normal_instances_closed_independently_and_scalar_precision_preserved():
    downloader, clients, _ = sdk_downloader(
        lambda client, request: (("20180718", Decimal("1.234567890123456789")),)
    )
    with downloader.download(
        DownloadTask("fixture.daily@1", M.BY_OBJECT, objects=("A", "B"))
    ) as session:
        results = list(session)
    assert (
        len(clients) == 2
        and clients[0] is not clients[1]
        and all(c["closed"] for c in clients)
    )
    assert results[0].records[0].as_mapping()["close"] == Decimal(
        "1.234567890123456789"
    )
    assert (
        session.summary.request_count == session.summary.successful_response_count == 2
    )
    assert SDK_ADAPTERS == {}  # This test did not register any real method.


def test_sdk_source_exception_is_classified_without_retaining_secret_or_exception_chain():
    def call(client, request):
        raise Exception("权限不足 secret-isolated-credential")  # noqa: TRY002 - mirrors the normal SDK generic source error.

    downloader, clients, _ = sdk_downloader(call)
    with (
        pytest.raises(DownloadError) as caught,
        downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)) as session,
    ):
        next(session)
    assert caught.value.code == C.PERMISSION_OR_PARAMETER and clients[0]["closed"]
    assert caught.value.__context__ is caught.value.__cause__ is None
    assert "secret-isolated" not in str(caught.value)
    assert session.summary.request_count == 1


def test_successful_sdk_response_with_close_failure_counts_success_but_never_delivers_or_retries():
    def broken_close(client):
        raise OSError("local 429")

    downloader, clients, _ = sdk_downloader(
        lambda client, request: (("20180718", Decimal(1)),), close=broken_close
    )
    events = []
    with (
        pytest.raises(DownloadError) as caught,
        downloader.download(
            DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=events.append
        ) as session,
    ):
        next(session)
    assert caught.value.code == C.CLEANUP
    assert (
        session.summary.request_count == session.summary.successful_response_count == 1
    )
    assert (
        session.summary.delivered_units == session.summary.retry_count == 0
        and events == []
    )
    assert len(clients) == 1


def test_unapproved_sdk_version_fails_before_client_creation_or_source_call():
    downloader, clients, _ = sdk_downloader(
        lambda client, request: (), installed_versions=("never-installed",)
    )
    with (
        pytest.raises(DownloadError) as caught,
        downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)),
    ):
        pass
    assert caught.value.code == C.CONTRACT and clients == []


@pytest.mark.parametrize("invalid", [True, -1, "1"])
def test_sdk_reliable_metadata_cannot_use_bool_negative_or_text(invalid):
    def parser(raw, request, definition, memory):
        return SourcePage(("trade_date",), (), total=invalid)

    downloader, clients, _ = sdk_downloader(lambda client, request: (), parser=parser)
    with (
        pytest.raises(DownloadError) as caught,
        downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)) as session,
    ):
        next(session)
    assert caught.value.code == C.SOURCE_PROTOCOL and clients[0]["closed"]
    assert (
        session.summary.request_count == 1
        and session.summary.successful_response_count == 0
    )


def test_sdk_receive_time_excludes_parser_and_close_time():
    downloader, _, _ = sdk_downloader(lambda client, request: ())
    with downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)) as session:
        original = session._transport._method

        def call(client, request):
            downloader._clock.seconds += 3
            return ()

        def parse(raw, request, definition, memory):
            downloader._clock.seconds += 5
            return original.parse(raw, request, definition, memory)

        def close(client):
            downloader._clock.seconds += 7
            original.close_client(client)

        session._transport._method = replace(
            original, call=call, parse=parse, close_client=close
        )
        result = next(session)
    assert result.statistics.receive_seconds == 3
    assert result.statistics.elapsed_seconds == 15
