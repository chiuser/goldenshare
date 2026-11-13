"""Internal, one-request worker. Importing definitions performs no operation."""

import json
import os
import resource
import signal
import struct
import sys
import threading
from decimal import Decimal
from time import perf_counter


def _decimal_json(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("unsupported_source_scalar")


def _parent_lifeline():
    # No extra input is permitted. Parent disappearance ends this request only.
    sys.stdin.buffer.read(1)
    os._exit(125)


def _ths_source_error(failure):
    from orchestrator.defs.source_readiness.moneyflow_transport import source_error
    from orchestrator.tushare_download.download_errors import DownloadErrorCode as Code

    if failure.cleanup_errors or failure.code in (Code.CAPACITY, Code.CLEANUP):
        os._exit(126)
    if failure.code == Code.CANCELLED:
        os._exit(125)
    categories = {
        Code.CONFIGURATION: ("source_or_data_contract", False),
        Code.CONTRACT: ("source_or_data_contract", False),
        Code.INPUT: ("source_or_data_contract", False),
        Code.PERMISSION_OR_PARAMETER: ("source_permission_or_parameter", False),
        Code.RATE_LIMIT: ("rate_limit", True),
        Code.TRANSIENT_SOURCE: ("transient", True),
        Code.NO_VALID_RESPONSE: ("source_response_unclassified", True),
        Code.SOURCE_PROTOCOL: ("source_or_data_contract", False),
        Code.UNCLASSIFIED_SOURCE: ("non_retryable", False),
    }
    category, retryable = categories[failure.code]
    if (
        failure.code == Code.SOURCE_PROTOCOL
        and failure.cause_type in {"BadStatusLine", "LineTooLong"}
    ) or (
        failure.code == Code.UNCLASSIFIED_SOURCE
        and failure.cause_type in {
            "gaierror", "SSLError", "SSLCertVerificationError", "SSLEOFError",
            "SSLZeroReturnError", "SSLWantReadError", "SSLWantWriteError",
            "SSLSyscallError",
        }
    ):
        category, retryable = "transient", True
    return source_error({"category": category, "retryable": retryable})


def _call_ths_http(value):
    from datetime import UTC, datetime

    from orchestrator.defs.resources import TushareResult
    from orchestrator.defs.run_contracts.moneyflow import (
        MONEYFLOW_MAX_RSS_BYTES,
        MONEYFLOW_WORKER_INPUT_MAX_BYTES,
        MONEYFLOW_WORKER_POLL_SECONDS,
    )
    from orchestrator.tushare_download.configuration import ConfigurationSnapshot
    from orchestrator.tushare_download.contracts.moneyflow_ths import (
        MONEYFLOW_THS_CONTRACT,
    )
    from orchestrator.tushare_download.dataset_transport_mapping import (
        BINDINGS,
        DatasetTransportMapping,
    )
    from orchestrator.tushare_download.download_errors import DownloadError
    from orchestrator.tushare_download.download_models import (
        DownloadMode,
        DownloadTask,
        PagePosition,
        RequestCounters,
        SessionCounters,
        UnitCounters,
    )
    from orchestrator.tushare_download.download_session import SessionControl
    from orchestrator.tushare_download.http_transport import HttpProTransport
    from orchestrator.tushare_download.request_builder import RequestBuilder
    from orchestrator.tushare_download.source_transport import SystemClock
    from orchestrator.tushare_download.task_input import validate_task
    from orchestrator.tushare_download.unit_memory import UnitMemory
    from orchestrator.tushare_download.unit_planner import UnitPlanner

    try:
        day = value["params"]["trade_date"]
        contract = MONEYFLOW_THS_CONTRACT
        task = validate_task(
            DownloadTask(
                contract.contract_name, DownloadMode.BY_POINT,
                points=(f"{day[:4]}-{day[4:6]}-{day[6:]}",),
            ),
            contract, MONEYFLOW_WORKER_INPUT_MAX_BYTES,
        )
        unit = UnitPlanner(task, contract).next_unit()
        builder = RequestBuilder(contract)
        request = builder.build_page(
            unit, next(builder.iter_inputs(unit)),
            PagePosition(0, offset=value["params"]["offset"]),
            request_fields=tuple(value["fields"]),
        )
        remaining = value["deadline"] - perf_counter()
        if remaining <= MONEYFLOW_WORKER_POLL_SECONDS:
            os.kill(os.getpid(), signal.SIGALRM)
        config = ConfigurationSnapshot(
            token=value["token"], base_url=value["base_url"],
            unit_memory_limit_bytes=MONEYFLOW_MAX_RSS_BYTES,
            connect_timeout_seconds=min(5.0, remaining),
            read_timeout_seconds=remaining, request_timeout_seconds=remaining,
            max_retries=0, retry_backoff_seconds=(),
            max_request_bytes=MONEYFLOW_WORKER_INPUT_MAX_BYTES,
        )
        transport = HttpProTransport(SystemClock())
        transport.prepare(DatasetTransportMapping(BINDINGS).resolve(contract), config, contract)
        outcome = transport.fetch_page(
            request, config, UnitMemory(config), SessionControl(None, contract.contract_name),
            RequestCounters(SessionCounters(), UnitCounters()), 1,
        )
        if outcome.failure is not None:
            raise _ths_source_error(outcome.failure)
        page = outcome.page
        return TushareResult(
            rows=[record.as_mapping() for record in page.records], columns=page.fields,
            metadata={
                "api_name": value["api_name"], "params": value["params"],
                "fields": value["fields"], "row_count": len(page.records),
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )
    except DownloadError as error:
        raise _ths_source_error(error) from None
    except MemoryError:
        os._exit(126)


def main():
    if len(sys.argv) != 2:
        os._exit(126)
    deadline = float(sys.argv[1])
    remaining = deadline - perf_counter()
    if remaining <= 0:
        os._exit(124)
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    # Arm the OS deadline before importing SDK/resource dependencies.
    from orchestrator.defs.resources import TushareResource
    from orchestrator.defs.run_contracts.moneyflow import (
        MONEYFLOW_WORKER_INPUT_MAX_BYTES,
        MONEYFLOW_WORKER_RESULT_MAX_BYTES,
    )
    from orchestrator.defs.source_readiness.moneyflow_transport import (
        validate_source_input,
    )
    from orchestrator.defs.tushare_request_policy import classify_tushare_error

    data = sys.stdin.buffer.readline(MONEYFLOW_WORKER_INPUT_MAX_BYTES + 1)
    if len(data) > MONEYFLOW_WORKER_INPUT_MAX_BYTES or not data.endswith(b"\n"):
        os._exit(126)
    value = json.loads(data)
    expected_keys = {"token", "api_name", "params", "fields", "deadline"}
    if value.get("api_name") == "moneyflow_ths":
        expected_keys.add("base_url")
    if (
        set(value) != expected_keys
        or value["deadline"] != deadline
        or type(value["token"]) is not str
        or not value["token"].strip()
    ):
        os._exit(126)
    validate_source_input(value["api_name"], value["params"], value["fields"])
    threading.Thread(target=_parent_lifeline, daemon=True).start()
    try:
        result = (
            _call_ths_http(value) if value["api_name"] == "moneyflow_ths"
            else TushareResource(token=value["token"]).call(
                value["api_name"], value["params"], value["fields"]
            )
        )
        response = {
            "ok": True,
            "columns": list(result.columns),
            "rows": result.rows,
            "metadata": result.metadata,
        }
    except Exception as error:  # noqa: BLE001 -- bounded, redacted source-error protocol
        category, retryable = classify_tushare_error(error)
        response = {
            "ok": False,
            "category": category,
            "retryable": retryable,
            "error_type": type(error).__name__,
        }
    body = json.dumps(response, default=_decimal_json, separators=(",", ":")).encode()
    if len(body) + 16 > MONEYFLOW_WORKER_RESULT_MAX_BYTES:
        os._exit(126)
    sys.stdout.buffer.write(struct.pack("!Q", len(body)))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak = peak if sys.platform == "darwin" else peak * 1024
    sys.stdout.buffer.write(struct.pack("!Q", peak))
    sys.stdout.buffer.flush()
    # Avoid interpreter shutdown waiting on the daemon's stdin buffer lock.
    os._exit(0)


if __name__ == "__main__":
    main()
