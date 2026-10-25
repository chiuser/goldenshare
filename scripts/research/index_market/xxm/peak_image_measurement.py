"""Conservative measurements of visible columns, never reconstructed values.

Picture thresholds describe pixels, not filters on financial indicator peaks.
Bright hand-drawn ink at a measurement interruption censors that column.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from statistics import median

from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner


@dataclass(frozen=True)
class MeasurementSpec:
    name: str = "baseline"
    zero_y: int = 833
    x_start: int = 980
    x_end: int = 1385
    y_end: int = 1000
    green_delta: int = 15
    seed_depth: int = 14
    max_gap: int = 2


SPECS = (
    MeasurementSpec(),
    MeasurementSpec(name="axis_minus_one", zero_y=832, green_delta=12),
    MeasurementSpec(name="axis_plus_one", zero_y=834, green_delta=18),
)
# Independently located from the administrator's circles, before measurement.
REGIONS = {"blue": (1045, 1123), "orange": (1124, 1210), "red": (1270, 1385)}


def is_green(rgb: tuple[int, int, int], delta: int) -> bool:
    red, green, blue = rgb
    return (70 <= red <= 220 and 70 <= blue <= 220 and green >= 100
            and green - red >= delta and green - blue >= delta)


def is_ink(rgb: tuple[int, int, int]) -> bool:
    red, green, blue = rgb
    return green >= 160 and red < 70 and blue < 70


def measure_columns(image, spec: MeasurementSpec) -> dict:
    """Accept an RGB getpixel/size object; usable with literal test pixels."""
    width, height = image.size
    if not (0 <= spec.x_start < spec.x_end <= width and
            0 <= spec.zero_y < spec.y_end < height):
        raise ValueError("Measurement ROI outside image")
    columns = []
    for x in range(spec.x_start, spec.x_end):
        seeds = [y for y in range(spec.zero_y + 1,
                                 min(spec.zero_y + spec.seed_depth, spec.y_end) + 1)
                 if is_green(image.getpixel((x, y)), spec.green_delta)]
        if len(seeds) < 2:
            continue
        first = seeds[0]
        last, gaps, censored = first, 0, False
        for y in range(first, spec.y_end + 1):
            rgb = image.getpixel((x, y))
            if is_ink(rgb):
                censored = True
                break
            if is_green(rgb, spec.green_delta):
                last, gaps = y, 0
            else:
                gaps += 1
                if gaps > spec.max_gap:
                    censored = any(is_ink(image.getpixel((x, z)))
                                   for z in range(y, min(y + 3, spec.y_end) + 1))
                    break
        columns.append(dict(x=x, length=last - spec.zero_y,
                            censored=censored, reached_limit=last == spec.y_end))

    groups: list[list[dict]] = []
    for column in columns:
        if not groups or column["x"] != groups[-1][-1]["x"] + 1:
            groups.append([])
        groups[-1].append(column)
    bars = []
    for group in groups:
        hidden = any(c["censored"] or c["reached_limit"] for c in group)
        bars.append(dict(
            x_first=group[0]["x"], x_last=group[-1]["x"],
            x=float(median(c["x"] for c in group)),
            length_px=None if hidden else float(median(c["length"] for c in group)),
            visible_length_px=float(median(c["length"] for c in group)),
            censored=hidden,
        ))
    spacing = median(b["x"] - a["x"] for a, b in zip(bars, bars[1:])) if len(bars) > 1 else None
    turns, gaps, scanner, previous_x = [], [], LocalExtremaScanner(), None
    for index, bar in enumerate(bars):
        x = bar["x"]
        disconnected = previous_x is not None and spacing is not None and x - previous_x > 1.75 * spacing
        if disconnected:
            gaps.append(dict(after_x=previous_x, before_x=x, meaning="missing or other-colour bars; not filled"))
        if disconnected or bar["censored"]:
            scanner = LocalExtremaScanner()
        if not bar["censored"]:
            point = scanner.step(f"{index:06d}", Decimal(str(bar["length_px"])))
            if point is not None:
                record = point.record()
                record["x_first"] = bars[int(point.first_at)]["x"]
                record["x_last"] = bars[int(point.last_at)]["x"]
                turns.append(record)
        previous_x = x
    return dict(spec=asdict(spec), bars=bars, gaps=gaps, turns=turns,
                censored_bars=sum(b["censored"] for b in bars),
                rawIndicatorValuesAvailable=False,
                fullSequenceVerified=bool(bars) and not gaps and not any(b["censored"] for b in bars))


def measure_original(path: Path) -> dict:
    # Keep the detector and its tests free of optional desktop dependencies.
    from PIL import Image

    with Image.open(path) as original:
        if original.size != (2218, 1466):
            raise ValueError("Changed original picture dimensions")
        image = original.convert("RGB")
    variants = [measure_columns(image, spec) for spec in SPECS]
    for variant in variants:
        variant["regions"] = {
            name: dict(
                bars=sum(lo <= b["x"] <= hi for b in variant["bars"]),
                censored=sum(lo <= b["x"] <= hi and b["censored"] for b in variant["bars"]),
                measuredMaxima=[t for t in variant["turns"]
                                if t["kind"] == "MAX" and lo <= t["x_first"] <= hi],
            ) for name, (lo, hi) in REGIONS.items()
        }
    return dict(
        variants=variants, regions=REGIONS,
        independentThreePeakValidation=False,
        limitation="Pixels are approximate. Hidden columns and gaps are never interpolated; manual ink is not an indicator value.",
    )
