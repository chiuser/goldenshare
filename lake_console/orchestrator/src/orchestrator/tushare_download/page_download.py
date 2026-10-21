"""Serial same-page retry, offset traversal and internal range splitting."""

from __future__ import annotations

from .download_errors import DownloadError
from .download_errors import DownloadErrorCode as Code
from .download_models import (
    CompletedUnitBuffer,
    DownloadStage,
    PagePosition,
    ProgressFacts,
    RequestCounters,
    TerminationSummary,
    UnitCounters,
)
from .download_models import DownloadProgressEvent as Event
from .request_builder import RequestBuilder
from .retry_policy import RetryPolicy


class PageDownloader:
    def __init__(self, config, transport, memory, counters, clock, sleep_fn):
        self.config, self.transport, self.memory = config, transport, memory
        self.counters, self.clock = counters, clock
        self.retry_policy = RetryPolicy(config, clock, sleep_fn)

    def _fetch(self, request, unit, counts, control, progress):
        outcome = None
        try:
            for attempt in range(1, self.config.max_retries + 2):
                control.set_location(
                    DownloadStage.SOURCE, unit.unit_id, request.position, attempt
                )
                control.raise_if_cancelled()
                outcome = self.transport.fetch_page(
                    request, self.config, self.memory, control, counts, attempt
                )
                control.raise_if_cancelled()
                if outcome.page is not None:
                    return outcome.page, attempt
                failure = outcome.failure
                if not self.retry_policy.can_retry(failure, attempt):
                    raise self.retry_policy.to_download_error(
                        failure, attempt, location=control.error_location()
                    )
                now = self.clock.monotonic()
                retry_at = self.retry_policy.retry_at(failure, attempt, now)
                control.set_location(
                    DownloadStage.BACKOFF, unit.unit_id, request.position, attempt
                )
                progress.publish(
                    Event.RETRY_SCHEDULED,
                    ProgressFacts(
                        unit,
                        counts.unit.row_count,
                        request.position,
                        attempt,
                        next_attempt_number=attempt + 1,
                        retry_delay_seconds=max(0.0, retry_at - now),
                        error_code=failure.code,
                    ),
                )
                control.raise_if_cancelled()
                counts.unit.waiting_seconds += self.retry_policy.wait_until(
                    retry_at, control
                )
                outcome = None
            raise RuntimeError("retry iteration ended without an outcome")
        finally:
            outcome = None

    @staticmethod
    def _terminal(page, request, policy, seen, control):
        size = len(page.records)
        invalid = False
        if policy.strategy == 1:
            proven_complete = page.total is not None and page.total == size
            invalid = (page.total is not None and page.total != size) or (
                policy.truncation_limit is not None
                and size >= policy.truncation_limit
                and not proven_complete
            )
            terminal = True
        else:
            invalid = (
                not policy.short_page_ends
                and not policy.empty_page_ends
                and page.total is None
            )
            if page.next_offset is not None:
                invalid = (
                    invalid
                    or page.next_offset != request.position.offset + policy.offset_step
                )
            if page.total is not None:
                invalid = (
                    invalid
                    or page.total < seen
                    or (
                        seen < page.total
                        and (
                            size == 0
                            or (
                                size < policy.effective_limit and policy.short_page_ends
                            )
                        )
                    )
                )
                terminal = seen == page.total
            else:
                terminal = (size == 0 and policy.empty_page_ends) or (
                    0 < size < policy.effective_limit and policy.short_page_ends
                )
        if invalid:
            raise DownloadError(Code.SOURCE_PROTOCOL, details=control.error_location())
        return terminal

    def _accept(self, buffer, page):
        count = buffer.counters.accepted_page_count + 1
        self.memory.attach(("accepted_page", count), page.records)
        self.memory.reserve("append_records", len(page.records) * 16 + 256)
        buffer.records.extend(page.records)
        self.memory.refresh_shallow("unit_records", buffer.records)
        self.memory.release("append_records")
        buffer.field_sets.setdefault(page.fields, page.fields)
        self.memory.refresh_shallow("field_shapes", buffer.field_sets)
        buffer.counters.accepted_page_count += 1
        buffer.counters.empty_page_count += int(not page.records)
        buffer.counters.row_count += len(page.records)

    def download_unit(self, unit, contract, control, progress):
        buffer = CompletedUnitBuffer(unit, UnitCounters(), self.clock.monotonic())
        counts = RequestCounters(self.counters, buffer.counters)
        builder, policy = RequestBuilder(contract), contract.pagination
        inputs, scopes = [], []
        page = request = request_input = None
        accepted_scopes, last_position = 0, None
        try:
            self.memory.attach("unit_records", buffer.records, shallow=True)
            self.memory.attach("field_shapes", buffer.field_sets, shallow=True)
            self.memory.attach("request_inputs", inputs, shallow=True)
            for input_index, request_input in enumerate(builder.iter_inputs(unit)):
                control.raise_if_cancelled()
                self.memory.attach(("request_input", input_index), request_input)
                inputs.append(request_input)
                self.memory.refresh_shallow("request_inputs", inputs)
                scopes.append(unit.time_range if policy.strategy == 3 else None)
                while scopes:
                    control.raise_if_cancelled()
                    span = scopes.pop()
                    offset = policy.offset_start if policy.strategy != 1 else None
                    position = PagePosition(input_index, span, offset)
                    request = builder.build_page(unit, request_input, position)
                    page, attempt = self._fetch(
                        request, unit, counts, control, progress
                    )
                    split = (
                        contract.time_rule(policy.split_time_rule_key).split(span)
                        if policy.strategy == 3
                        and len(page.records) == policy.effective_limit
                        else None
                    )
                    if split is not None:
                        received = len(page.records)
                        buffer.counters.split_count += 1
                        self.memory.release("source_page")
                        page = None
                        scopes.extend((split[1], split[0]))
                        progress.publish(
                            Event.PAGE_COMPLETED,
                            ProgressFacts(
                                unit,
                                buffer.counters.row_count,
                                position,
                                attempt,
                                received,
                                False,
                            ),
                        )
                        control.raise_if_cancelled()
                        continue
                    seen = 0
                    while True:
                        seen += len(page.records)
                        terminal = self._terminal(page, request, policy, seen, control)
                        self._accept(buffer, page)
                        last_position = request.position
                        progress.publish(
                            Event.PAGE_COMPLETED,
                            ProgressFacts(
                                unit,
                                buffer.counters.row_count,
                                request.position,
                                attempt,
                                len(page.records),
                                True,
                            ),
                        )
                        control.raise_if_cancelled()
                        self.memory.release("source_page")
                        page = None
                        if terminal:
                            accepted_scopes += 1
                            break
                        position = PagePosition(
                            input_index,
                            span,
                            request.position.offset + policy.offset_step,
                        )
                        request = builder.build_page(unit, request_input, position)
                        page, attempt = self._fetch(
                            request, unit, counts, control, progress
                        )
            self.memory.reserve("input_tuple", len(inputs) * 8 + 64)
            buffer.request_inputs = tuple(inputs)
            self.memory.attach("input_tuple", buffer.request_inputs)
            buffer.termination = TerminationSummary(
                policy.strategy, True, accepted_scopes, last_position
            )
            control.raise_if_cancelled()
            return buffer
        except BaseException:
            buffer.clear()
            self.memory.clear()
            raise
        finally:
            inputs.clear()
            scopes.clear()
            page = request = request_input = None
