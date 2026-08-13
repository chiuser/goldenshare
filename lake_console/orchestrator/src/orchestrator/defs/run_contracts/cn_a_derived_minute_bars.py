"""Canonical CN A-share minute-bar window contract."""

from __future__ import annotations

from dataclasses import dataclass

AUCTION_ANCHOR_ROLE = "auction_anchor"
REGULAR_SOURCE_ROLE = "regular"
CN_A_GOLD_MINUTE_FREQS = (1, 5, 15, 30, 60, 90, 120)
CN_A_DERIVED_MINUTE_FREQS = (90, 120)
CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET = {
    1: 1,
    5: 1,
    15: 5,
    30: 5,
    60: 30,
    90: 30,
    120: 60,
}
CN_A_GOLD_MINUTE_CLOSE_TIME = "15:00:00"
CN_A_GOLD_MINUTE_IGNORED_SOURCE_END_TIME = "15:30:00"
_CN_A_GOLD_EXCHANGES = frozenset({"SSE", "SZSE", "BSE", "XSHG", "XSHE"})


@dataclass(frozen=True, slots=True)
class CanonicalGoldMinuteWindow:
    target_freq: int
    source_freq: int
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
        return self.expected_regular_source_count + self.expected_anchor_source_count


def _clock_range(start: str, end: str, step_minutes: int) -> tuple[str, ...]:
    start_hour, start_minute, _ = (int(part) for part in start.split(":"))
    end_hour, end_minute, _ = (int(part) for part in end.split(":"))
    current = start_hour * 60 + start_minute
    last = end_hour * 60 + end_minute
    values: list[str] = []
    while current <= last:
        hour, minute = divmod(current, 60)
        values.append(f"{hour:02d}:{minute:02d}:00")
        current += step_minutes
    return tuple(values)


def _source_session_times(source_freq: int) -> tuple[str, ...]:
    if source_freq == 1:
        return (
            *_clock_range("09:30:00", "11:30:00", 1),
            *_clock_range("13:01:00", "15:00:00", 1),
        )
    if source_freq == 5:
        return (
            "09:30:00",
            *_clock_range("09:35:00", "11:30:00", 5),
            *_clock_range("13:05:00", "15:00:00", 5),
        )
    if source_freq == 30:
        return (
            "09:30:00",
            "10:00:00",
            "10:30:00",
            "11:00:00",
            "11:30:00",
            "13:30:00",
            "14:00:00",
            "14:30:00",
            "15:00:00",
        )
    if source_freq == 60:
        return (
            "09:30:00",
            "10:30:00",
            "11:30:00",
            "14:00:00",
            "15:00:00",
        )
    raise RuntimeError(f"unsupported canonical Gold source frequency: {source_freq}.")


def _build_windows(target_freq: int) -> tuple[CanonicalGoldMinuteWindow, ...]:
    source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[target_freq]
    source_times = _source_session_times(source_freq)
    if target_freq == 1:
        return tuple(
            CanonicalGoldMinuteWindow(
                target_freq=1,
                source_freq=1,
                window_id=index,
                target_time=source_time,
                regular_source_times=(source_time,),
            )
            for index, source_time in enumerate(source_times, start=1)
        )

    regular_times = tuple(time for time in source_times if time != "09:30:00")
    source_rows_per_window = target_freq // source_freq
    windows: list[CanonicalGoldMinuteWindow] = []
    for offset in range(0, len(regular_times), source_rows_per_window):
        window_times = regular_times[offset : offset + source_rows_per_window]
        windows.append(
            CanonicalGoldMinuteWindow(
                target_freq=target_freq,
                source_freq=source_freq,
                window_id=len(windows) + 1,
                target_time=window_times[-1],
                regular_source_times=window_times,
                auction_anchor_time="09:30:00" if not windows else None,
            )
        )
    return tuple(windows)


CN_A_GOLD_MINUTE_WINDOWS = {
    target_freq: _build_windows(target_freq) for target_freq in CN_A_GOLD_MINUTE_FREQS
}


def _normalize_frequency(value: object, *, allowed: tuple[int, ...], label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must not be boolean.")  # noqa: TRY004
    text = str(value).strip().lower().removesuffix("min").removesuffix("m")
    try:
        normalized = int(text)
    except ValueError as error:
        raise ValueError(f"invalid {label}: {value!r}.") from error
    if normalized not in allowed:
        allowed_text = ", ".join(str(freq) for freq in allowed)
        raise ValueError(f"{label} must be one of {allowed_text}; got {value!r}.")
    return normalized


def normalize_cn_a_gold_minute_freq(value: object) -> int:
    return _normalize_frequency(
        value,
        allowed=CN_A_GOLD_MINUTE_FREQS,
        label="canonical Gold minute frequency",
    )


def normalize_cn_a_derived_minute_freq(value: object) -> int:
    return _normalize_frequency(
        value,
        allowed=CN_A_DERIVED_MINUTE_FREQS,
        label="derived minute frequency",
    )


def canonical_gold_minute_windows(
    value: object,
) -> tuple[CanonicalGoldMinuteWindow, ...]:
    return CN_A_GOLD_MINUTE_WINDOWS[normalize_cn_a_gold_minute_freq(value)]


def expected_gold_minute_times(exchange: object, value: object) -> tuple[str, ...]:
    normalized_exchange = str(exchange).strip().upper()
    if normalized_exchange not in _CN_A_GOLD_EXCHANGES:
        raise ValueError(f"unsupported CN A-share exchange: {exchange!r}.")
    return tuple(window.target_time for window in canonical_gold_minute_windows(value))


def expected_canonical_gold_source_times(value: object) -> tuple[str, ...]:
    """Return the exact in-session source timestamps consumed by a Gold target."""

    return tuple(
        dict.fromkeys(
            source_time
            for (
                source_time,
                _source_role,
                _window_id,
                _target_time,
                _expected_regular_count,
                _expected_anchor_count,
            ) in canonical_gold_minute_window_rows(value)
        )
    )


def canonical_gold_minute_window_rows(
    value: object,
) -> tuple[tuple[str, str, int, str, int, int], ...]:
    rows: list[tuple[str, str, int, str, int, int]] = []
    for window in canonical_gold_minute_windows(value):
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


def canonical_gold_minute_window_map_sql(value: object) -> str:
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
        ) in canonical_gold_minute_window_rows(value)
    )
    return f"""
  SELECT
    CAST(source_time AS VARCHAR) AS source_time,
    CAST(source_role AS VARCHAR) AS source_role,
    CAST(window_id AS INTEGER) AS window_id,
    CAST(target_time AS VARCHAR) AS target_time,
    CAST(expected_regular_count AS INTEGER) AS expected_regular_count,
    CAST(expected_anchor_count AS INTEGER) AS expected_anchor_count
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


def cn_a_derived_minute_windows(
    value: object,
) -> tuple[CanonicalGoldMinuteWindow, ...]:
    return canonical_gold_minute_windows(normalize_cn_a_derived_minute_freq(value))


def cn_a_derived_minute_target_times(value: object) -> tuple[str, ...]:
    return tuple(window.target_time for window in cn_a_derived_minute_windows(value))


def cn_a_derived_minute_window_rows(
    value: object,
) -> tuple[tuple[str, str, int, str, int, int], ...]:
    return canonical_gold_minute_window_rows(normalize_cn_a_derived_minute_freq(value))


def cn_a_derived_minute_window_map_sql(value: object) -> str:
    return canonical_gold_minute_window_map_sql(
        normalize_cn_a_derived_minute_freq(value)
    )


def cn_a_gold_minute_ignored_source_time_predicate_sql(
    *,
    trade_time_column: str,
) -> str:
    identifier_parts = str(trade_time_column).strip().split(".")
    if not identifier_parts or any(
        not part or not part.replace("_", "").isalnum() for part in identifier_parts
    ):
        raise ValueError(
            f"invalid Gold minute trade-time column: {trade_time_column!r}."
        )
    return (
        f"strftime({trade_time_column}, '%H:%M:%S') > "
        f"'{CN_A_GOLD_MINUTE_CLOSE_TIME}' AND "
        f"strftime({trade_time_column}, '%H:%M:%S') <= "
        f"'{CN_A_GOLD_MINUTE_IGNORED_SOURCE_END_TIME}'"
    )


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
    for target_freq, windows in CN_A_GOLD_MINUTE_WINDOWS.items():
        if not windows:
            raise RuntimeError(
                f"canonical Gold minute contract is empty: {target_freq}."
            )
        if len({window.window_id for window in windows}) != len(windows):
            raise RuntimeError(f"duplicate canonical minute window id: {target_freq}.")
        if len({window.target_time for window in windows}) != len(windows):
            raise RuntimeError(
                f"duplicate canonical minute target time: {target_freq}."
            )
        mapped_times: list[str] = []
        for window in windows:
            if window.target_freq != target_freq:
                raise RuntimeError("canonical minute target frequency is inconsistent.")
            if window.target_time != window.regular_source_times[-1]:
                raise RuntimeError(
                    "canonical minute target must close its regular window."
                )
            if target_freq == 1 and window.auction_anchor_time is not None:
                raise RuntimeError("1m must preserve 09:30 as a regular bar.")
            if target_freq != 1 and "09:30:00" in window.regular_source_times:
                raise RuntimeError("non-1m 09:30 must only be an auction anchor.")
            mapped_times.extend(window.regular_source_times)
            if window.auction_anchor_time is not None:
                mapped_times.append(window.auction_anchor_time)
        if len(mapped_times) != len(set(mapped_times)):
            raise RuntimeError(f"canonical source times are duplicated: {target_freq}.")
        if windows[-1].target_time != CN_A_GOLD_MINUTE_CLOSE_TIME:
            raise RuntimeError(
                f"canonical minute session must end at 15:00: {target_freq}."
            )


_validate_contract()


__all__ = [
    "AUCTION_ANCHOR_ROLE",
    "CN_A_DERIVED_MINUTE_FREQS",
    "CN_A_GOLD_MINUTE_CLOSE_TIME",
    "CN_A_GOLD_MINUTE_FREQS",
    "CN_A_GOLD_MINUTE_IGNORED_SOURCE_END_TIME",
    "CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET",
    "CN_A_GOLD_MINUTE_WINDOWS",
    "REGULAR_SOURCE_ROLE",
    "CanonicalGoldMinuteWindow",
    "canonical_gold_minute_window_map_sql",
    "canonical_gold_minute_window_rows",
    "canonical_gold_minute_windows",
    "cn_a_derived_minute_completion_predicate",
    "cn_a_derived_minute_target_times",
    "cn_a_derived_minute_window_map_sql",
    "cn_a_derived_minute_window_rows",
    "cn_a_derived_minute_windows",
    "cn_a_gold_minute_ignored_source_time_predicate_sql",
    "expected_gold_minute_times",
    "normalize_cn_a_derived_minute_freq",
    "normalize_cn_a_gold_minute_freq",
]
