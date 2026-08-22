from __future__ import annotations

import math
from collections.abc import Mapping


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    if any(not key or not math.isfinite(value) for key, value in values.items()):
        raise ValueError("percentile ranks require non-empty keys and finite values")

    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    if len(ordered) == 1:
        return {ordered[0][0]: 50.0}

    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_rank = (index + end) / 2.0
        percentile = average_rank / (len(ordered) - 1) * 100.0
        for cursor in range(index, end + 1):
            ranks[ordered[cursor][0]] = percentile
        index = end + 1
    return {key: ranks[key] for key in sorted(ranks)}


def percentile_flags(ranks: Mapping[str, float], *, threshold: float) -> dict[str, bool]:
    if not math.isfinite(threshold) or threshold < 0 or threshold > 100:
        raise ValueError("ranking threshold must be within [0, 100]")
    return {key: value >= threshold for key, value in sorted(ranks.items())}
