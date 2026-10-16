"""Two-frequency HTTP source capture with durable pages and a terminable attempt."""

from __future__ import annotations

import csv
import json
import multiprocessing
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from orchestrator.defs.io.stock_period_raw import (
    _BUDGET,
    atomic_json,
    check_cancel,
    file_digest,
    file_version,
    read_json,
    safe_path,
    storage_record,
    storage_reserve,
)
from orchestrator.defs.run_contracts.stock_period import (
    DEFAULT_POLICY,
    FIELDS,
    VERSION,
    digest,
    intent_id,
    request_params,
    validate_rows,
)


@dataclass(frozen=True)
class PeriodHttpConfig:
    """DG process configuration, confined to the two period Raw assets."""

    token: str = field(repr=False)
    base_url: str = "https://api.tushare.pro"
    max_calls_per_minute: int = 280

    def __post_init__(self):
        if not self.token.strip():
            raise ValueError("period_token_missing")
        url = urlsplit(self.base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.netloc
            or url.username
            or url.password
        ):
            raise ValueError("period_http_url_invalid")
        if type(self.max_calls_per_minute) is not int or self.max_calls_per_minute < 0:
            raise ValueError("period_http_rate_invalid")

    @classmethod
    def from_environment(cls, *, token=None, base_url=None):
        try:
            rate = int(os.environ.get("TUSHARE_MAX_CALLS_PER_MINUTE", "280"))
        except ValueError:
            raise ValueError("period_http_rate_invalid") from None
        return cls(
            token=os.environ.get("TUSHARE_TOKEN", "").strip()
            if token is None
            else token.strip(),
            base_url=os.environ.get("TUSHARE_BASE_URL", cls.base_url).strip()
            if base_url is None
            else base_url,
            max_calls_per_minute=rate,
        )

    def public(self):
        url = urlsplit(self.base_url)
        return {
            "endpoint": url._replace(query="", fragment="").geturl(),
            "endpoint_hash": digest(self.base_url),
            "max_calls_per_minute": self.max_calls_per_minute,
        }


class PeriodResponseError(ValueError):
    def __init__(self, reason, body):
        super().__init__(reason)
        self.body = body


def _http_attempt(send, base_url, token, params, policy, parent_pid):
    """Same POST envelope/config as Prod. Decimal decoding is specific to these Raw assets."""

    def guard():
        while True:
            if os.getppid() != parent_pid:
                os._exit(70)
            time.sleep(0.2)

    threading.Thread(target=guard, daemon=True).start()
    try:
        import requests
        from requests.adapters import HTTPAdapter

        with requests.Session() as session:
            session.mount("http://", HTTPAdapter(max_retries=0))
            session.mount("https://", HTTPAdapter(max_retries=0))
            with session.post(
                base_url,
                json={
                    "api_name": "stk_week_month_adj",
                    "token": token,
                    "params": params,
                    "fields": ",".join(FIELDS),
                },
                stream=True,
                allow_redirects=False,
                timeout=(5, policy.timeout_seconds),
                headers={"Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                if 300 <= response.status_code < 400:
                    raise ValueError("period_http_redirect")
                body = bytearray()
                for block in response.iter_content(65536):
                    if len(body) + len(block) > policy.response_bytes:
                        body.extend(block[: policy.response_bytes - len(body)])
                        send.send(
                            ("contract", "period_response_budget_exceeded", bytes(body))
                        )
                        return
                    body.extend(block)
                send.send(("ok", bytes(body)))
    except ValueError as exc:
        send.send(("contract", str(exc)))
    except Exception as exc:  # noqa: BLE001 -- Never serialize credentials or response bodies in diagnostics.
        send.send(("transport", type(exc).__name__))
    finally:
        send.close()


class HttpPage:
    def __init__(
        self,
        *,
        token=None,
        base_url=None,
        policy=DEFAULT_POLICY,
        cancel=lambda: False,
        progress=lambda _: None,
    ):
        settings = PeriodHttpConfig.from_environment(token=token, base_url=base_url)
        self.token = settings.token
        self.base_url = settings.base_url
        self.public_config = settings.public()
        self.interval = (
            60 / settings.max_calls_per_minute
            if settings.max_calls_per_minute > 0
            else 0
        )
        self.next_request = 0.0
        self.policy = policy
        self.cancel = cancel
        self.progress = progress

    def __call__(self, params):
        for attempt in range(self.policy.retries + 1):
            while time.monotonic() < self.next_request:
                check_cancel(self.cancel)
                time.sleep(0.05)
            check_cancel(self.cancel)
            ctx = multiprocessing.get_context("spawn")
            receive, send = ctx.Pipe(duplex=False)
            worker = ctx.Process(
                target=_http_attempt,
                args=(
                    send,
                    self.base_url,
                    self.token,
                    params,
                    self.policy,
                    os.getpid(),
                ),
                daemon=True,
            )
            started = time.monotonic()
            emitted = started
            self.next_request = started + self.interval
            previous = signal.getsignal(signal.SIGTERM)

            def terminated(signum, frame):
                raise SystemExit(128 + signum)

            main = threading.current_thread() is threading.main_thread()
            if main:
                signal.signal(signal.SIGTERM, terminated)
            try:
                worker.start()
                self.progress(
                    {"stage": "source_worker_started", "worker_pid": worker.pid}
                )
                send.close()
                while not receive.poll(0.2):
                    check_cancel(self.cancel)
                    if time.monotonic() - emitted >= self.policy.progress_seconds:
                        self.progress(
                            {
                                "stage": "request",
                                "offset": params["offset"],
                                "attempt": attempt + 1,
                            }
                        )
                        emitted = time.monotonic()
                    if time.monotonic() - started >= self.policy.timeout_seconds:
                        raise TimeoutError("period_source_deadline")
                    if not worker.is_alive():
                        raise ConnectionError("period_source_worker_exited")
                result = receive.recv()
                check_cancel(self.cancel)
                if result[0] == "ok":
                    return result[1]
                if result[0] == "contract":
                    if len(result) == 3:
                        raise PeriodResponseError(result[1], result[2])
                    raise ValueError(result[1])
                raise ConnectionError("period_source_transport_failure")
            except (ConnectionError, TimeoutError, EOFError):
                if attempt == self.policy.retries:
                    raise
            finally:
                send.close()
                if worker.pid is not None:
                    if worker.is_alive():
                        worker.terminate()
                    worker.join(1)
                    if worker.is_alive():
                        worker.kill()
                        worker.join(1)
                receive.close()
                if main:
                    signal.signal(signal.SIGTERM, previous)
            until = time.monotonic() + 2**attempt
            while time.monotonic() < until:
                check_cancel(self.cancel)
                time.sleep(0.05)
        raise RuntimeError("period_source_unreachable")


def _save_body(unit, body, *, transport, limit):
    """Retain a bounded response before validating; secrets never enter evidence."""
    path = safe_path(unit / "attempts" / (uuid4().hex + ".json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    retained = body[:limit]
    secret = getattr(transport, "token", "")
    redacted = bool(secret and secret.encode() in retained)
    if redacted:
        retained = retained.replace(secret.encode(), b"[REDACTED]")[:limit]
    storage_reserve(len(retained))
    with path.open("xb") as handle:
        handle.write(retained)
        handle.flush()
        os.fsync(handle.fileno())
    storage_record(path)
    return path, {"truncated": len(retained) < len(body), "redacted": redacted}


def _decode_page(body, *, freq, code, period, listed, aliases, seen, limit):
    try:
        envelope = json.loads(body, parse_float=Decimal)
    except (ValueError, UnicodeError):
        raise ValueError("period_source_json_invalid") from None
    if (
        not isinstance(envelope, dict)
        or envelope.get("code") != 0
        or not isinstance(envelope.get("data"), dict)
    ):
        raise ValueError("period_source_api_error")
    data = envelope["data"]
    fields, items = data.get("fields"), data.get("items")
    if not isinstance(items, list) or len(items) > limit:
        raise ValueError("period_source_page_invalid")
    keys = validate_rows(fields, items, freq=freq, code=code, period=period)
    if keys & seen:
        raise ValueError("period_source_repeated_page")
    accepted = []
    for row in items:
        stock = row[0]
        if stock in aliases and aliases[stock] != stock and aliases[stock] in listed:
            raise ValueError("period_source_retired_alias")
        if stock not in listed:
            continue
        from orchestrator.defs.run_contracts.stock_period import admitted_code

        admitted_code(stock, listed, aliases)
        accepted.append(row)
    asofs = [r[2] for r in accepted if r[2] is not None]
    facts = {
        "rows": len(items),
        "kept_rows": len(accepted),
        "excluded_rows": len(items) - len(accepted),
        "keys": sorted(keys),
        "minimum_asof": min(asofs) if asofs else None,
        "maximum_asof": max(asofs) if asofs else None,
        "null_asof": len(asofs) != len(accepted),
    }
    return accepted, facts


def capture_unit(
    *,
    work,
    request_id,
    freq,
    listed,
    aliases,
    transport,
    policy=DEFAULT_POLICY,
    code=None,
    period=None,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """Persist responses first. Only verified pages/units become reusable inputs."""
    if not listed:
        raise ValueError("period_listed_scope_empty")
    # Admission precedes any source call or evidence directory creation.
    request_params(
        freq=freq,
        code=code,
        period=period,
        policy=policy,
        listed=listed,
        aliases=aliases,
    )
    identity = {
        "version": VERSION,
        "intent_id": intent_id(request_id),
        "freq": freq,
        "code": code,
        "period": period,
        "policy": policy.payload(),
        "fields": list(FIELDS),
        "scope_hash": digest({"listed": sorted(listed), "aliases": aliases}),
        "transport": getattr(transport, "public_config", None),
    }
    unit_base = safe_path(Path(work) / digest(identity))
    unit_base.mkdir(parents=True, exist_ok=True)
    active_path = unit_base / "active_chain.json"
    unit = unit_base
    if active_path.exists():
        import re

        chain = read_json(active_path).get("chain", "")
        if not re.fullmatch(r"[0-9a-f]{32}", chain):
            raise ValueError("period_source_chain_changed")
        unit = safe_path(unit_base / "chains" / chain)
        if not (unit / "identity.json").is_file():
            raise ValueError("period_source_chain_changed")
    identity_path = unit / "identity.json"
    if identity_path.exists() and read_json(identity_path) != identity:
        raise ValueError("period_unit_identity_changed")
    if not identity_path.exists():
        atomic_json(identity_path, identity)
    complete = unit / "complete.json"
    if not complete.exists():
        receipts = list(unit.glob("*.receipt.json"))
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if any(
            datetime.fromtimestamp(
                read_json(p)["captured_at_ns"] / 1e9, ZoneInfo("Asia/Shanghai")
            ).date()
            != today
            for p in receipts
        ):
            # Keep every old page/receipt at its original path. Only the active
            # unfinished chain changes; no old fingerprint is rewritten.
            chain = uuid4().hex
            unit = safe_path(unit_base / "chains" / chain)
            unit.mkdir(parents=True)
            identity_path = unit / "identity.json"
            atomic_json(identity_path, identity)
            atomic_json(active_path, {"chain": chain})
            complete = unit / "complete.json"
    if complete.exists():
        saved = read_json(complete)
        if saved["identity"] != identity or saved.get("receipt_hash") != digest(
            {k: v for k, v in saved.items() if k != "receipt_hash"}
        ):
            raise ValueError("period_unit_identity_changed")
        for page in saved["pages"]:
            csvpath = Path(page["csv"])
            if page["raw_version"] != file_version(
                csvpath.with_suffix(".json")
            ) or page["csv_version"] != file_version(csvpath):
                raise ValueError("period_saved_page_changed")
        check_cancel(cancel)
        return saved
    offset, kept, total_bytes, excluded = 0, 0, 0, 0
    seen, pages, minimum_asof, maximum_asof, null_asof = set(), [], None, None, False
    while True:
        check_cancel(cancel)
        params = request_params(
            freq=freq,
            code=code,
            period=period,
            offset=offset,
            policy=policy,
            listed=listed,
            aliases=aliases,
        )
        receipt = unit / f"{offset}.receipt.json"
        raw, csvpath = unit / f"{offset}.json", unit / f"{offset}.csv"
        if receipt.exists():
            page = read_json(receipt)
            if (
                page.get("receipt_hash")
                != digest({k: v for k, v in page.items() if k != "receipt_hash"})
                or page["params"] != params
                or page["raw_version"] != file_version(raw)
                or page["csv_version"] != file_version(csvpath)
            ):
                raise ValueError("period_saved_page_changed")
            if set(map(tuple, page["keys"])) & seen:
                raise ValueError("period_source_repeated_page")
        else:
            evidence, flags = None, {}
            try:
                try:
                    storage_reserve(2 * policy.response_bytes)
                    body = transport(params)
                except PeriodResponseError as error:
                    evidence, flags = _save_body(
                        unit,
                        error.body,
                        transport=transport,
                        limit=min(
                            policy.response_bytes,
                            max(0, policy.unit_bytes - total_bytes),
                        ),
                    )
                    flags["truncated"] = True
                    raise
                evidence, flags = _save_body(
                    unit,
                    body,
                    transport=transport,
                    limit=min(
                        policy.response_bytes, max(0, policy.unit_bytes - total_bytes)
                    ),
                )
                if flags["redacted"]:
                    raise ValueError("period_source_response_contains_secret")
                if len(body) > policy.response_bytes:
                    raise ValueError("period_response_budget_exceeded")
                if total_bytes + len(body) > policy.unit_bytes:
                    raise ValueError("period_source_unit_budget_exceeded")
                accepted, facts = _decode_page(
                    body,
                    freq=freq,
                    code=code,
                    period=period,
                    listed=listed,
                    aliases=aliases,
                    seen=seen,
                    limit=policy.page_limit,
                )
            except (ValueError, ConnectionError, TimeoutError, EOFError) as error:
                reason = (
                    str(error)
                    if isinstance(error, ValueError)
                    and str(error).startswith("period_")
                    else "period_source_transport_failure"
                )
                atomic_json(
                    unit / "attempts" / (uuid4().hex + ".failure.json"),
                    {
                        "unit_id": digest(identity),
                        "params": params,
                        "offset": offset,
                        "captured_at_ns": time.time_ns(),
                        "reason_code": reason,
                        "body": str(evidence) if evidence else None,
                        **flags,
                    },
                )
                raise
            os.replace(evidence, raw)
            budget = _BUDGET.get()
            if budget is not None:
                budget.moved(evidence, raw)
            tmpcsv = safe_path(csvpath.with_suffix(".csv.tmp"))
            storage_reserve(len(body) + 1024)
            with tmpcsv.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(FIELDS)
                writer.writerows(accepted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmpcsv, csvpath)
            storage_record(csvpath)
            page = {
                "params": params,
                **facts,
                "bytes": len(body),
                "csv": str(csvpath),
                "captured_at_ns": time.time_ns(),
                "raw_version": file_version(raw),
                "csv_version": file_version(csvpath),
                "raw_sha256": file_digest(raw),
                "csv_sha256": file_digest(csvpath),
            }
            page["receipt_hash"] = digest(page)
            atomic_json(receipt, page)
        seen.update(map(tuple, page["keys"]))
        total_bytes += page["bytes"]
        kept += page["kept_rows"]
        excluded += page["excluded_rows"]
        null_asof |= page["null_asof"]
        if page["minimum_asof"]:
            minimum_asof = min(v for v in (minimum_asof, page["minimum_asof"]) if v)
        if page["maximum_asof"]:
            maximum_asof = max(v for v in (maximum_asof, page["maximum_asof"]) if v)
        pages.append({k: v for k, v in page.items() if k != "keys"})
        progress(
            {
                "stage": "source_page_complete",
                "freq": freq,
                "code": code,
                "period": period,
                "pages": len(pages),
                "source_rows": len(seen),
                "kept_rows": kept,
            }
        )
        check_cancel(cancel)
        if page["rows"] < policy.page_limit:
            break
        offset += policy.page_limit
    if not kept:
        atomic_json(
            unit / "empty.failure.json",
            {"reason_code": "period_source_empty", "unit_id": digest(identity)},
        )
        raise ValueError("period_source_empty")
    result = {
        "identity": identity,
        "pages": pages,
        "source_rows": len(seen),
        "rows": kept,
        "excluded_rows": excluded,
        "minimum_asof": None if null_asof else minimum_asof,
        "maximum_asof": maximum_asof,
    }
    result["receipt_hash"] = digest(result)
    atomic_json(complete, result)
    return result
