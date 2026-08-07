"""Shared CN A-share 90m/120m derived minute-bar contract."""

from __future__ import annotations

from dataclasses import dataclass


AUCTION_ANCHOR_ROLE = "auction_anchor"
REGULAR_SOURCE_ROLE = "regular"
CN_A_DERIVED_MINUTE_FREQS = (90, 120)


@dataclass(frozen=True, slots=True)
class DerivedMinuteWindow:
    target_freq: int
    window_id: int
    target_time: str
    regular_source_times: tuple[str, ...]
    auction_anchor_time: str | None = None

    @property
    def expected_regular_source_count(self) -> int:
        return len(self.regular_source_times)

    @property
    def expected_anchor_source_count(self) -> int:
        return 1 if self.auction_anchor_time is not None else 0

    @property
    def expected_source_count(self) -> int:
        return (
            self.expected_regular_source_count
            + self.expected_anchor_source_count
        )


CN_A_DERIVED_MINUTE_WINDOWS = {
    90: (
        DerivedMinuteWindow(
            target_freq=90,
            window_id=1,
            target_time="11:00:00",
            auction_anchor_time="09:30:00",
            regular_source_times=("10:00:00", "10:30:00", "11:00:00"),
        ),
        DerivedMinuteWindow(
            target_freq=90,
            window_id=2,
            target_time="14:00:00",
            regular_source_times=("11:30:00", "13:30:00", "14:00:00"),
        ),
        DerivedMinuteWindow(
            target_freq=90,
            window_id=3,
            target_time="15:00:00",
            regular_source_times=("14:30:00", "15:00:00"),
        ),
    ),
    120: (
        DerivedMinuteWindow(
            target_freq=120,
            window_id=1,
            target_time="11:30:00",
            auction_anchor_time="09:30:00",
            regular_source_times=("10:30:00", "11:30:00"),
        ),
        DerivedMinuteWindow(
            target_freq=120,
            window_id=2,
            target_time="15:00:00",
            regular_source_times=("14:00:00", "15:00:00"),
        ),
    ),
}


def normalize_cn_a_derived_minute_freq(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("derived minute frequency must not be boolean.")
    text = str(value).strip().lower().removesuffix("min").removesuffix("m")
    try:
        normalized = int(text)
    except ValueError as error:
        raise ValueError(f"invalid derived minute frequency: {value!r}.") from error
    if normalized not in CN_A_DERIVED_MINUTE_FREQS:
        allowed = ", ".join(str(freq) for freq in CN_A_DERIVED_MINUTE_FREQS)
        raise ValueError(
            f"derived minute frequency must be one of {allowed}; got {value!r}."
        )
    return normalized


def cn_a_derived_minute_windows(value: object) -> tuple[DerivedMinuteWindow, ...]:
    return CN_A_DERIVED_MINUTE_WINDOWS[normalize_cn_a_derived_minute_freq(value)]


def cn_a_derived_minute_target_times(value: object) -> tuple[str, ...]:
    return tuple(window.target_time for window in cn_a_derived_minute_windows(value))


def cn_a_derived_minute_window_rows(
    value: object,
) -> tuple[tuple[str, str, int, str, int, int], ...]:
    rows: list[tuple[str, str, int, str, int, int]] = []
    for window in cn_a_derived_minute_windows(value):
        if window.auction_anchor_time is not None:
            rows.append(
                (
                    window.auction_anchor_time,
                    AUCTION_ANCHOR_ROLE,
                    window.window_id,
                    window.target_time,
                    window.expected_regular_source_count,
                    window.expected_anchor_source_count,
                )
            )
        rows.extend(
            (
                source_time,
                REGULAR_SOURCE_ROLE,
                window.window_id,
                window.target_time,
                window.expected_regular_source_count,
                window.expected_anchor_source_count,
            )
            for source_time in window.regular_source_times
        )
    return tuple(rows)


def cn_a_derived_minute_window_map_sql(value: object) -> str:
    value_rows = ",\n    ".join(
        "("
        f"'{source_time}', '{source_role}', {window_id}, '{target_time}', "
        f"{expected_regular_count}, {expected_anchor_count}"
        ")"
        for (
            source_time,
            source_role,
            window_id,
            target_time,
            expected_regular_count,
            expected_anchor_count,
        ) in cn_a_derived_minute_window_rows(value)
    )
    return f"""
  SELECT *
  FROM (
    VALUES
    {value_rows}
  ) AS rows(
    source_time,
    source_role,
    window_id,
    target_time,
    expected_regular_count,
    expected_anchor_count
  )
"""


def cn_a_derived_minute_completion_predicate(
    *,
    regular_row_count_column: str,
    regular_time_count_column: str,
    anchor_row_count_column: str,
    anchor_time_count_column: str,
    expected_regular_count_column: str,
    expected_anchor_count_column: str,
) -> str:
    return (
        f"{regular_row_count_column} = {expected_regular_count_column} "
        f"AND {regular_time_count_column} = {expected_regular_count_column} "
        f"AND {anchor_row_count_column} = {expected_anchor_count_column} "
        f"AND {anchor_time_count_column} = {expected_anchor_count_column}"
    )


def _validate_contract() -> None:
    for target_freq, windows in CN_A_DERIVED_MINUTE_WINDOWS.items():
        if not windows:
            raise RuntimeError(f"derived minute contract is empty: {target_freq}.")
        window_ids = tuple(window.window_id for window in windows)
        target_times = tuple(window.target_time for window in windows)
        if len(window_ids) != len(set(window_ids)):
            raise RuntimeError(f"duplicate derived minute window id: {target_freq}.")
        if len(target_times) != len(set(target_times)):
            raise RuntimeError(f"duplicate derived minute target time: {target_freq}.")
        for window in windows:
            if window.target_freq != target_freq:
                raise RuntimeError("derived minute target frequency is inconsistent.")
            source_times = (
                *((window.auction_anchor_time,) if window.auction_anchor_time else ()),
                *window.regular_source_times,
            )
            if len(source_times) != len(set(source_times)):
                raise RuntimeError("derived minute source times must be unique per window.")
            if window.target_time != window.regular_source_times[-1]:
                raise RuntimeError("derived minute target must be the last regular source time.")


_validate_contract()


__all__ = [
    "AUCTION_ANCHOR_ROLE",
    "CN_A_DERIVED_MINUTE_FREQS",
    "CN_A_DERIVED_MINUTE_WINDOWS",
    "DerivedMinuteWindow",
    "REGULAR_SOURCE_ROLE",
    "cn_a_derived_minute_completion_predicate",
    "cn_a_derived_minute_target_times",
    "cn_a_derived_minute_window_map_sql",
    "cn_a_derived_minute_window_rows",
    "cn_a_derived_minute_windows",
    "normalize_cn_a_derived_minute_freq",
]
