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
    if (
        set(value) != {"token", "api_name", "params", "fields", "deadline"}
        or value["deadline"] != deadline
        or type(value["token"]) is not str
        or not value["token"].strip()
    ):
        os._exit(126)
    validate_source_input(value["api_name"], value["params"], value["fields"])
    threading.Thread(target=_parent_lifeline, daemon=True).start()
    try:
        result = TushareResource(token=value["token"]).call(
            value["api_name"], value["params"], value["fields"]
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
