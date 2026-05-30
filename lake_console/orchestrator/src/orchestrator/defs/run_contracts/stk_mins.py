"""Stable contracts for stock minute frequency assets."""

STK_MINS_FREQS = (1, 5, 15, 30, 60)


def normalize_stk_mins_freq(freq: int | str) -> int:
    """Normalize a stock minute frequency to the canonical integer value."""

    try:
        normalized = int(str(freq).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(str(item) for item in STK_MINS_FREQS)
        raise ValueError(f"Unsupported stk_mins freq: {freq!r}. Allowed: {allowed}.") from error

    if normalized not in STK_MINS_FREQS:
        allowed = ", ".join(str(item) for item in STK_MINS_FREQS)
        raise ValueError(f"Unsupported stk_mins freq: {freq!r}. Allowed: {allowed}.")
    return normalized
