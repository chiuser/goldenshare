"""Bounded, cancellable Tushare requests and complete daily page capture."""

import json
import multiprocessing
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    announcement_file_fingerprint,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementError,
    announcement_date,
    announcement_dates,
    announcement_rows_digest,
    normalize_announcement_rows,
)


def announcement_request(day, offset, policy):
    announcement_dates(day, day)
    parsed = announcement_date(day)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise AnnouncementError("announcement_invalid_offset")
    return {
        "ann_date": parsed.strftime("%Y%m%d"),
        "limit": policy.page_size,
        "offset": offset,
    }


def _stop_orphan_request(parent_pid):
    while os.getppid() == parent_pid:
        time.sleep(0.5)
    os._exit(1)


def _announcement_json_value(value):
    from pandas import NA, NaT

    if value is NA or value is NaT:
        return None
    # Unknown objects remain an invalid type, rather than becoming business strings.
    return {"unsupported_source_type": type(value).__name__}


def _announcement_resource_worker(token, params, output, signal):
    # The parent only reads a small signal. Large responses are never sent via IPC.
    threading.Thread(
        target=_stop_orphan_request, args=(os.getppid(),), daemon=True
    ).start()
    try:
        from orchestrator.defs.resources import TushareResource

        response = TushareResource(token=token).call(
            "anns_d", params, ANNOUNCEMENT_FIELDS
        )
        with open(output, "x", encoding="utf-8") as stream:
            # Preserve SDK NaN evidence until the parent restores transport nulls.
            json.dump(
                {"columns": response.columns, "rows": response.rows},
                stream,
                ensure_ascii=False,
                default=_announcement_json_value,
            )
            stream.flush()
            os.fsync(stream.fileno())
        signal.send("ok")
    except Exception:  # noqa: BLE001 -- Never send SDK secrets or response bodies over IPC.
        signal.send("announcement_source_call_failed")
    finally:
        signal.close()


class AnnouncementProcessCall:
    def __init__(self, token, directory, policy, worker=_announcement_resource_worker):
        self.token, self.directory, self.policy, self.worker = (
            token,
            Path(directory),
            policy,
            worker,
        )

    def __call__(self, params, control):
        self.directory.mkdir(parents=True, exist_ok=True)
        output = self.directory / f"call-{uuid.uuid4().hex}.json"
        context = multiprocessing.get_context("spawn")
        receiving, sending = context.Pipe(duplex=False)
        process = context.Process(
            target=self.worker, args=(self.token, params, str(output), sending)
        )
        try:
            process.start()
            sending.close()
            deadline = time.monotonic() + self.policy.call_timeout
            while not receiving.poll(0.1):
                control.check()
                if time.monotonic() >= deadline:
                    raise AnnouncementError("announcement_source_timeout")
                if not process.is_alive():
                    raise AnnouncementError("announcement_source_process_exit")
                if time.monotonic() - control.last_report >= 5:
                    control.progress(phase="source_call")
            control.check()
            try:
                status = receiving.recv()
            except EOFError:
                raise AnnouncementError("announcement_source_process_exit") from None
            if status != "ok":
                raise AnnouncementError("announcement_source_call_failed")
            response = json.loads(output.read_text())
            control.check()
            return response["rows"], tuple(response["columns"])
        finally:
            sending.close()
            receiving.close()
            if process.pid:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=self.policy.cancel_grace / 2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=self.policy.cancel_grace / 2)


@dataclass(frozen=True)
class AnnouncementCapturedDay:
    day: str
    pages: tuple[Path, ...]
    rows: int
    last_offset: int
    last_page_rows: int
    requests: int


def capture_announcement_day(day, call, store, checkpoint, control, budget, policy):
    """Incomplete captures restart in a new attempt; complete evidence is reused."""
    control.check()
    document = checkpoint.document
    if document.get("capture_complete"):
        page_evidence = document["pages"]
        if (
            not page_evidence
            or document["last_page_rows"] >= policy.page_size
            or document["source_rows"] != sum(page["rows"] for page in page_evidence)
        ):
            raise AnnouncementError("announcement_capture_incomplete")
        pages = tuple(Path(page["path"]) for page in page_evidence)
        for page, evidence in zip(pages, document["pages"], strict=True):
            if announcement_file_fingerprint(page) != evidence["fingerprint"]:
                raise AnnouncementError("announcement_capture_changed")
        return AnnouncementCapturedDay(
            day,
            pages,
            document["source_rows"],
            document["last_offset"],
            document["last_page_rows"],
            document["requests"],
        )
    attempt = store.directory / f"capture-{uuid.uuid4().hex}"
    attempt.mkdir(parents=True)
    checkpoint.save(
        phase="capturing", capture_complete=False, attempt=str(attempt), pages=[]
    )
    pages, evidence, seen = [], [], set()
    offset = requests = 0
    control.wait(policy.interval_seconds)
    while True:
        control.check()
        params = announcement_request(day, offset, policy)
        for retry in range(policy.max_attempts):
            if requests >= policy.max_day_requests:
                raise AnnouncementError("announcement_day_budget")
            requests = budget.claim(control, day)
            try:
                raw_rows, columns = call(params, control)
                break
            except AnnouncementError as exc:
                if (
                    str(exc)
                    not in (
                        "announcement_source_timeout",
                        "announcement_source_call_failed",
                        "announcement_source_process_exit",
                    )
                    or retry + 1 == policy.max_attempts
                ):
                    raise
            finally:
                budget.finish()
        control.check()
        # Invalid responses remain in their attempt directory instead of being filtered.
        raw_path = attempt / f"offset-{offset}.json"
        with raw_path.open("x", encoding="utf-8") as stream:
            json.dump(
                {"columns": columns, "rows": raw_rows},
                stream,
                ensure_ascii=False,
                default=_announcement_json_value,
            )
        rows = normalize_announcement_rows(raw_rows, columns, day=day, sdk=True)
        if len(rows) > policy.page_size:
            raise AnnouncementError("announcement_oversized_page")
        digest = announcement_rows_digest(rows)
        if rows and digest in seen:
            raise AnnouncementError("announcement_repeated_page")
        seen.add(digest)
        page = store.write_page(
            rows, attempt / f"page-{len(pages):05d}.parquet", control
        )
        pages.append(page)
        evidence.append(
            {
                "path": str(page),
                "rows": len(rows),
                "offset": offset,
                "fingerprint": announcement_file_fingerprint(page),
            }
        )
        complete = len(rows) < policy.page_size
        checkpoint.save(
            phase="captured" if complete else "capturing",
            pages=evidence,
            capture_complete=complete,
            source_rows=offset + len(rows),
            last_offset=offset,
            last_page_rows=len(rows),
            requests=requests,
        )
        control.progress(
            phase="captured" if complete else "capturing",
            day=day,
            offset=offset,
            page_count=len(pages),
            rows_captured=offset + len(rows),
            requests_used=requests,
        )
        if complete:
            return AnnouncementCapturedDay(
                day, tuple(pages), offset + len(rows), offset, len(rows), requests
            )
        offset += len(rows)
