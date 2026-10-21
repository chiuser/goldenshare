"""Stable time ordering and one complete, immutable in-memory unit result."""

from __future__ import annotations

import heapq
from datetime import timezone

from .download_models import OrderingFacts, UnitResult, UnitStatistics


class UnitOutput:
    def __init__(self, config, clock):
        self.config, self.clock = config, clock

    def finish_unit(self, buffer, contract, memory, control):
        blocks, ordered = [], []
        block = result_records = result = None
        valid_count = invalid_count = 0
        started = self.clock.monotonic()
        try:
            if contract.ordering.time_field is not None:
                time_rule = contract.time_rule(contract.ordering.time_rule_key)
                width = self.config.sort_block_records
                for start in range(0, len(buffer.records), width):
                    control.raise_if_cancelled()
                    length = min(width, len(buffer.records) - start)
                    memory.reserve("sort_build", length * 2048)
                    block = []
                    for sequence in range(start, start + length):
                        record = buffer.records[sequence]
                        comparable = False
                        key = ()
                        try:
                            index = record.fields.index(contract.ordering.time_field)
                            value = time_rule.parse(record.values[index], source=True)
                            if value.tzinfo is not None:
                                value = value.astimezone(timezone.utc)
                            key = (
                                value.year,
                                value.month,
                                value.day,
                                value.hour,
                                value.minute,
                                value.second,
                            )
                            comparable = True
                        except (ValueError, TypeError):
                            pass
                        valid_count += int(comparable)
                        invalid_count += int(not comparable)
                        block.append((0 if comparable else 1, key, sequence, record))
                    block.sort()
                    memory.attach(("sort_block", start), block)
                    memory.release("sort_build")
                    blocks.append(block)
                memory.attach("ordered_refs", ordered, shallow=True)
                for i, item in enumerate(heapq.merge(*blocks)):
                    if i % width == 0:
                        control.raise_if_cancelled()
                        memory.reserve(
                            "merge_growth",
                            min(width, len(buffer.records) - i) * 16 + 256,
                        )
                    ordered.append(item[3])
                    if (i + 1) % width == 0:
                        memory.refresh_shallow("ordered_refs", ordered)
                        memory.release("merge_growth")
                memory.refresh_shallow("ordered_refs", ordered)
            else:
                ordered = buffer.records
            control.raise_if_cancelled()
            memory.reserve("result_tuple", len(ordered) * 8 + 64)
            result_records = tuple(ordered)
            memory.attach("result_tuple", result_records)
            buffer.counters.sort_seconds += self.clock.monotonic() - started
            c = buffer.counters
            stats = UnitStatistics(
                c.request_count,
                c.retry_count,
                c.successful_response_count,
                c.accepted_page_count,
                c.empty_page_count,
                c.row_count,
                c.split_count,
                self.clock.monotonic() - buffer.started_at,
                c.waiting_seconds,
                c.receive_seconds,
                c.sort_seconds,
            )
            result = UnitResult(
                buffer.unit,
                result_records,
                tuple(buffer.field_sets),
                buffer.request_inputs,
                stats,
                OrderingFacts(
                    contract.ordering.time_field,
                    contract.ordering.rule_version,
                    valid_count,
                    invalid_count,
                ),
                buffer.termination,
            )
            control.raise_if_cancelled()
            return result
        finally:
            if ordered is not buffer.records:
                ordered.clear()
            blocks.clear()
            block = result_records = result = record = item = value = None
