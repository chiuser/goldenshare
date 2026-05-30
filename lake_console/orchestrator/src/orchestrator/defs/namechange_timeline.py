"""Namechange full-snapshot canonicalization rules."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


NAMECHANGE_TIMELINE_RULE_VERSION = "latest_announcement_timeline_v1"


@dataclass(frozen=True)
class NamechangeAdjacentGap:
    ts_code: str
    current_name: str
    current_start_date: date
    current_end_date: date
    next_name: str
    next_start_date: date
    gap_start_date: date
    gap_end_date: date

    def key(self) -> tuple[str, str, date, date, str, date, date, date]:
        return (
            self.ts_code,
            self.current_name,
            self.current_start_date,
            self.current_end_date,
            self.next_name,
            self.next_start_date,
            self.gap_start_date,
            self.gap_end_date,
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "ts_code": self.ts_code,
            "current_name": self.current_name,
            "current_start_date": self.current_start_date.isoformat(),
            "current_end_date": self.current_end_date.isoformat(),
            "next_name": self.next_name,
            "next_start_date": self.next_start_date.isoformat(),
            "gap_start_date": self.gap_start_date.isoformat(),
            "gap_end_date": self.gap_end_date.isoformat(),
        }


KNOWN_NAMECHANGE_ADJACENT_GAPS = (
    NamechangeAdjacentGap(
        ts_code="000022.SZ",
        current_name="深赤湾A",
        current_start_date=date(2006, 10, 9),
        current_end_date=date(2018, 12, 24),
        next_name="招商港口",
        next_start_date=date(2018, 12, 26),
        gap_start_date=date(2018, 12, 25),
        gap_end_date=date(2018, 12, 25),
    ),
)

KNOWN_NAMECHANGE_ADJACENT_GAP_KEYS = {
    gap.key() for gap in KNOWN_NAMECHANGE_ADJACENT_GAPS
}


@dataclass(frozen=True)
class NamechangeEvent:
    ts_code: str
    name: str
    start_date: date
    end_date: date | None
    ann_date: date | None
    change_reason: str


@dataclass(frozen=True)
class NamechangeTimelineResult:
    rows: tuple[dict[str, Any], ...]
    source_row_count: int
    selected_event_count: int
    merged_same_name_count: int
    unresolved_conflict_count: int
    invalid_date_order_count: int
    overlap_count: int
    multi_open_code_count: int
    adjacent_gap_count: int
    known_adjacent_gap_count: int
    unknown_adjacent_gap_count: int
    unresolved_conflict_samples: tuple[dict[str, Any], ...]
    invalid_date_order_samples: tuple[dict[str, Any], ...]
    overlap_samples: tuple[dict[str, Any], ...]
    multi_open_samples: tuple[dict[str, Any], ...]
    adjacent_gap_samples: tuple[dict[str, Any], ...]
    unknown_adjacent_gap_samples: tuple[dict[str, Any], ...]

    @property
    def blocking_conflict_count(self) -> int:
        return (
            self.unresolved_conflict_count
            + self.invalid_date_order_count
            + self.overlap_count
            + self.multi_open_code_count
        )


def build_latest_announcement_namechange_timeline(
    raw_rows: list[dict[str, Any]],
) -> NamechangeTimelineResult:
    """Build one non-overlapping name interval timeline per stock code."""

    events: list[NamechangeEvent] = []
    invalid_samples: list[dict[str, Any]] = []
    for row in raw_rows:
        try:
            event = _normalize_event(row)
        except ValueError as error:
            invalid_samples.append({"reason": str(error), "row": _sample_row(row)})
            continue
        if event.end_date is not None and event.end_date < event.start_date:
            invalid_samples.append(
                {
                    "reason": "end_date_before_start_date",
                    "row": _event_sample(event),
                }
            )
            continue
        events.append(event)

    selected_events, unresolved_samples = _select_latest_announcement_events(events)
    merged_events, merged_count = _merge_adjacent_same_name_events(selected_events)
    rows, final_invalid_samples = _close_intervals(merged_events)
    invalid_samples.extend(final_invalid_samples)

    overlap_samples = _find_overlap_samples(rows)
    multi_open_samples = _find_multi_open_samples(rows)
    gap_samples = _find_adjacent_gap_samples(rows)
    known_gap_count = 0
    unknown_gap_samples: list[dict[str, Any]] = []
    for gap in gap_samples:
        if _gap_key_from_sample(gap) in KNOWN_NAMECHANGE_ADJACENT_GAP_KEYS:
            known_gap_count += 1
        else:
            unknown_gap_samples.append(gap)

    return NamechangeTimelineResult(
        rows=tuple(rows),
        source_row_count=len(raw_rows),
        selected_event_count=len(selected_events),
        merged_same_name_count=merged_count,
        unresolved_conflict_count=len(unresolved_samples),
        invalid_date_order_count=len(invalid_samples),
        overlap_count=len(overlap_samples),
        multi_open_code_count=len(multi_open_samples),
        adjacent_gap_count=len(gap_samples),
        known_adjacent_gap_count=known_gap_count,
        unknown_adjacent_gap_count=len(unknown_gap_samples),
        unresolved_conflict_samples=tuple(unresolved_samples[:20]),
        invalid_date_order_samples=tuple(invalid_samples[:20]),
        overlap_samples=tuple(overlap_samples[:20]),
        multi_open_samples=tuple(multi_open_samples[:20]),
        adjacent_gap_samples=tuple(gap_samples[:20]),
        unknown_adjacent_gap_samples=tuple(unknown_gap_samples[:20]),
    )


def analyze_namechange_silver_rows(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    overlap_samples = _find_overlap_samples(rows)
    multi_open_samples = _find_multi_open_samples(rows)
    gap_samples = _find_adjacent_gap_samples(rows)
    known_gap_count = sum(
        1 for gap in gap_samples if _gap_key_from_sample(gap) in KNOWN_NAMECHANGE_ADJACENT_GAP_KEYS
    )
    unknown_gap_samples = [
        gap for gap in gap_samples if _gap_key_from_sample(gap) not in KNOWN_NAMECHANGE_ADJACENT_GAP_KEYS
    ]
    return {
        "overlap_count": len(overlap_samples),
        "overlap_samples": overlap_samples[:20],
        "multi_open_code_count": len(multi_open_samples),
        "multi_open_samples": multi_open_samples[:20],
        "adjacent_gap_count": len(gap_samples),
        "known_adjacent_gap_count": known_gap_count,
        "unknown_adjacent_gap_count": len(unknown_gap_samples),
        "adjacent_gap_samples": gap_samples[:20],
        "unknown_adjacent_gap_samples": unknown_gap_samples[:20],
    }


def _normalize_event(row: dict[str, Any]) -> NamechangeEvent:
    ts_code = _required_text(row.get("ts_code"), "ts_code")
    name = _required_text(row.get("name"), "name")
    start_date = _parse_required_source_date(row.get("start_date"), "start_date")
    change_reason = _required_text(row.get("change_reason"), "change_reason")
    return NamechangeEvent(
        ts_code=ts_code,
        name=name,
        start_date=start_date,
        end_date=_parse_optional_source_date(row.get("end_date"), "end_date"),
        ann_date=_parse_optional_source_date(row.get("ann_date"), "ann_date"),
        change_reason=change_reason,
    )


def _select_latest_announcement_events(
    events: list[NamechangeEvent],
) -> tuple[list[NamechangeEvent], list[dict[str, Any]]]:
    grouped: dict[tuple[str, date], list[NamechangeEvent]] = defaultdict(list)
    for event in events:
        grouped[(event.ts_code, event.start_date)].append(event)

    selected: list[NamechangeEvent] = []
    unresolved_samples: list[dict[str, Any]] = []
    for key in sorted(grouped):
        candidates = grouped[key]
        latest_ann = max(event.ann_date or date.min for event in candidates)
        latest_candidates = [
            event for event in candidates if (event.ann_date or date.min) == latest_ann
        ]
        with_end_date = [
            event for event in latest_candidates if event.end_date is not None
        ]
        final_candidates = with_end_date or latest_candidates
        unique_candidates = _unique_events(final_candidates)
        if len(unique_candidates) != 1:
            unresolved_samples.append(
                {
                    "ts_code": key[0],
                    "start_date": key[1].isoformat(),
                    "candidate_count": len(unique_candidates),
                    "candidates": [_event_sample(event) for event in unique_candidates[:5]],
                }
            )
            continue
        selected.append(unique_candidates[0])

    return selected, unresolved_samples


def _merge_adjacent_same_name_events(
    events: list[NamechangeEvent],
) -> tuple[list[NamechangeEvent], int]:
    by_code: dict[str, list[NamechangeEvent]] = defaultdict(list)
    for event in events:
        by_code[event.ts_code].append(event)

    merged: list[NamechangeEvent] = []
    merged_count = 0
    for ts_code in sorted(by_code):
        code_events = sorted(
            by_code[ts_code],
            key=lambda event: (event.start_date, event.ann_date or date.min, event.name),
        )
        code_merged: list[NamechangeEvent] = []
        for event in code_events:
            if code_merged and code_merged[-1].name == event.name:
                previous = code_merged[-1]
                merged_end = _merged_end_date(previous.end_date, event.end_date)
                code_merged[-1] = NamechangeEvent(
                    ts_code=previous.ts_code,
                    name=previous.name,
                    start_date=previous.start_date,
                    end_date=merged_end,
                    ann_date=previous.ann_date,
                    change_reason=previous.change_reason,
                )
                merged_count += 1
            else:
                code_merged.append(event)
        merged.extend(code_merged)
    return merged, merged_count


def _close_intervals(
    events: list[NamechangeEvent],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_code: dict[str, list[NamechangeEvent]] = defaultdict(list)
    for event in events:
        by_code[event.ts_code].append(event)

    rows: list[dict[str, Any]] = []
    invalid_samples: list[dict[str, Any]] = []
    for ts_code in sorted(by_code):
        code_events = sorted(by_code[ts_code], key=lambda event: event.start_date)
        for index, event in enumerate(code_events):
            next_start = (
                code_events[index + 1].start_date if index + 1 < len(code_events) else None
            )
            end_date = event.end_date
            if next_start is not None and (
                end_date is None or end_date >= next_start
            ):
                end_date = next_start - timedelta(days=1)
            if end_date is not None and end_date < event.start_date:
                invalid_samples.append(
                    {
                        "reason": "closed_end_date_before_start_date",
                        "row": _event_sample(event),
                        "closed_end_date": end_date.isoformat(),
                    }
                )
                continue
            rows.append(
                {
                    "ts_code": event.ts_code,
                    "name": event.name,
                    "start_date": event.start_date,
                    "end_date": end_date,
                    "ann_date": event.ann_date,
                    "change_reason": event.change_reason,
                }
            )
    return rows, invalid_samples


def _find_overlap_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code = _rows_by_code(rows)
    samples: list[dict[str, Any]] = []
    for ts_code, code_rows in by_code.items():
        sorted_rows = sorted(code_rows, key=lambda row: row["start_date"])
        for previous, current in zip(sorted_rows, sorted_rows[1:], strict=False):
            previous_end = previous["end_date"]
            if previous_end is None or previous_end >= current["start_date"]:
                samples.append(
                    {
                        "ts_code": ts_code,
                        "previous": _timeline_row_sample(previous),
                        "current": _timeline_row_sample(current),
                    }
                )
    return samples


def _find_multi_open_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code = _rows_by_code(rows)
    samples: list[dict[str, Any]] = []
    for ts_code, code_rows in by_code.items():
        open_rows = [row for row in code_rows if row["end_date"] is None]
        if len(open_rows) > 1:
            samples.append(
                {
                    "ts_code": ts_code,
                    "open_interval_count": len(open_rows),
                    "sample_rows": [_timeline_row_sample(row) for row in open_rows[:5]],
                }
            )
    return samples


def _find_adjacent_gap_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code = _rows_by_code(rows)
    samples: list[dict[str, Any]] = []
    for ts_code, code_rows in by_code.items():
        sorted_rows = sorted(code_rows, key=lambda row: row["start_date"])
        for previous, current in zip(sorted_rows, sorted_rows[1:], strict=False):
            previous_end = previous["end_date"]
            if previous_end is None:
                continue
            gap_start = previous_end + timedelta(days=1)
            gap_end = current["start_date"] - timedelta(days=1)
            if gap_start <= gap_end:
                samples.append(
                    {
                        "ts_code": ts_code,
                        "current_name": previous["name"],
                        "current_start_date": previous["start_date"].isoformat(),
                        "current_end_date": previous_end.isoformat(),
                        "next_name": current["name"],
                        "next_start_date": current["start_date"].isoformat(),
                        "gap_start_date": gap_start.isoformat(),
                        "gap_end_date": gap_end.isoformat(),
                    }
                )
    return samples


def _rows_by_code(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_code[str(row["ts_code"])].append(row)
    return by_code


def _gap_key_from_sample(
    sample: dict[str, Any],
) -> tuple[str, str, date, date, str, date, date, date]:
    return (
        str(sample["ts_code"]),
        str(sample["current_name"]),
        _parse_iso_date(str(sample["current_start_date"])),
        _parse_iso_date(str(sample["current_end_date"])),
        str(sample["next_name"]),
        _parse_iso_date(str(sample["next_start_date"])),
        _parse_iso_date(str(sample["gap_start_date"])),
        _parse_iso_date(str(sample["gap_end_date"])),
    )


def _unique_events(events: list[NamechangeEvent]) -> list[NamechangeEvent]:
    return sorted(
        set(events),
        key=lambda event: (
            event.ts_code,
            event.start_date,
            event.ann_date or date.min,
            event.end_date or date.max,
            event.name,
            event.change_reason,
        ),
    )


def _merged_end_date(first: date | None, second: date | None) -> date | None:
    if first is None or second is None:
        return second
    return max(first, second)


def _required_text(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nat", "nan"}:
        return None
    return text


def _parse_required_source_date(value: Any, field_name: str) -> date:
    text = _required_text(value, field_name)
    return _parse_source_date_text(text, field_name)


def _parse_optional_source_date(value: Any, field_name: str) -> date | None:
    text = _optional_text(value)
    if text is None:
        return None
    return _parse_source_date_text(text, field_name)


def _parse_source_date_text(text: str, field_name: str) -> date:
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return _parse_iso_date(text)
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"{field_name} must be YYYYMMDD")
    return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))


def _parse_iso_date(text: str) -> date:
    year, month, day = text.split("-")
    return date(int(year), int(month), int(day))


def _sample_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _sample_value(value) for key, value in row.items()}


def _event_sample(event: NamechangeEvent) -> dict[str, Any]:
    return {
        "ts_code": event.ts_code,
        "name": event.name,
        "start_date": event.start_date.isoformat(),
        "end_date": event.end_date.isoformat() if event.end_date else None,
        "ann_date": event.ann_date.isoformat() if event.ann_date else None,
        "change_reason": event.change_reason,
    }


def _timeline_row_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _sample_value(value) for key, value in row.items()}


def _sample_value(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
