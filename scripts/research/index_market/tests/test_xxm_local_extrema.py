"""Independent literal and batch-mathematical checks, plan 12.92 / LLD 70.

The 8/6 example is the approved proposal, not a financial/software gold label.
The real 31.406... and 16.824... anchors were read before implementation and
are documented in LLD 70.2. No expected value is emitted by the scanner.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from itertools import product

import pytest

from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner, scan_values
from scripts.research.index_market.xxm.local_extrema_study import (
    CASES, literal_anchor_checks, read_case, summarize_case, validate_rows,
)
from scripts.research.index_market.xxm.peak_image_measurement import (
    MeasurementSpec, is_green, is_ink, measure_columns,
)


def view(points):
    return [(p.kind, p.value, p.first_index, p.last_index, p.confirmed_index) for p in points]


@pytest.mark.parametrize("values, expected", [
    ([2, 5, 8, 6, 3, 4, 6, 4], [("MAX", 8, 2, 2, 3), ("MIN", 3, 4, 4, 5), ("MAX", 6, 6, 6, 7)]),
    ([-2, -5, -8, -6, -3, -4, -6, -4], [("MIN", -8, 2, 2, 3), ("MAX", -3, 4, 4, 5), ("MIN", -6, 6, 6, 7)]),
    ([1, 4, 4, 4, 2], [("MAX", 4, 1, 3, 4)]),
    ([4, 1, 1, 3], [("MIN", 1, 1, 2, 3)]),
    ([1, 1, 4, 2], [("MAX", 4, 2, 2, 3)]),
    ([-2, -1, 0, 0, -1, -2], [("MAX", 0, 2, 3, 4)]),
    ([1, 3, -1, -3, 2], [("MAX", 3, 1, 1, 2), ("MIN", -3, 3, 3, 4)]),
    ([], []), ([1], []), ([1, 1], []), ([1, 2, 3], []), ([3, 2, 1], []),
    ([4, 4, 2, 1], []),
])
def test_independent_literal_turns(values, expected):
    assert view(scan_values(values)) == expected


def test_tiny_reversals_are_preserved_without_threshold_or_float_rounding():
    points = scan_values(["0", "1", "0.999999999999999999", "1", "0"])
    assert view(points) == [
        ("MAX", Decimal("1"), 1, 1, 2),
        ("MIN", Decimal("0.999999999999999999"), 2, 2, 3),
        ("MAX", Decimal("1"), 3, 3, 4),
    ]


def test_pending_tail_is_not_a_confirmed_peak_and_confirmation_is_later():
    scanner = LocalExtremaScanner()
    assert scanner.pending() is None
    assert scanner.step("a", 1) is None
    assert scanner.step("b", 3) is None
    assert scanner.pending() == dict(value="3", first_at="b", last_at="b",
                                     first_index=1, last_index=1,
                                     possible_kind="MAX", confirmed=False)
    point = scanner.step("c", 2)
    assert point.first_at == point.last_at == "b" and point.confirmed_at == "c"
    with pytest.raises(FrozenInstanceError):
        point.value = Decimal(5)


def test_incomplete_future_bar_does_not_advance_or_confirm():
    scanner = LocalExtremaScanner()
    scanner.step("a", 1)
    scanner.step("b", 3)
    saved = vars(scanner).copy()
    assert scanner.step("z", -999, completed=False) is None
    assert vars(scanner) == saved
    point = scanner.step("c", 2)
    assert point.confirmed_at == "c" and point.confirmed_index == 2


@pytest.mark.parametrize("key,value,completed", [
    ("b", 1, True), ("a", 1, True), ("", 1, True), (None, 1, True),
    ("c", "NaN", True), ("c", "Infinity", True), ("c", "-Infinity", True),
    ("c", "bad", True), ("c", True, True), ("c", 1.5, True),
    ("c", "1", "true"), ("c", "NaN", False),
])
def test_invalid_input_is_rejected_atomically_and_normal_next_bar_still_works(key, value, completed):
    scanner = LocalExtremaScanner()
    scanner.step("a", 1)
    scanner.step("b", 3)
    saved = vars(scanner).copy()
    with pytest.raises(ValueError):
        scanner.step(key, value, completed=completed)
    assert vars(scanner) == saved
    assert scanner.step("c", 2).value == 3


def batch_definition(values):
    """Independent batch definition: compare complete runs with both neighbours."""
    runs = []
    for index, value in enumerate(values):
        if runs and runs[-1][0] == value:
            runs[-1][2] = index
        else:
            runs.append([value, index, index])
    expected = []
    for left, middle, right in zip(runs, runs[1:], runs[2:]):
        if middle[0] > left[0] and middle[0] > right[0]:
            expected.append(("MAX", middle[0], middle[1], middle[2], right[1]))
        elif middle[0] < left[0] and middle[0] < right[0]:
            expected.append(("MIN", middle[0], middle[1], middle[2], right[1]))
    return expected


def test_exhaustive_3280_short_integer_sequences_against_batch_definition():
    count = 0
    for length in range(8):
        for values in product((-1, 0, 1), repeat=length):
            assert view(scan_values(list(values))) == batch_definition(values)
            count += 1
    assert count == 3280


def test_every_prefix_and_different_future_preserve_confirmed_events():
    prefix = [2, 5, 8, 6, 3, 4, 6, 4]
    known = view(scan_values(prefix))
    for tail in ([100, -100, 200], [-100, -101, 0], [4, 4, 4], []):
        full = scan_values(prefix + tail)
        assert view([p for p in full if p.confirmed_index < len(prefix)]) == known
        for length in range(len(prefix) + len(tail) + 1):
            assert view(scan_values((prefix + tail)[:length])) == view(
                [p for p in full if p.confirmed_index < length])


def test_real_saved_producer_contract_and_independent_literal_anchors():
    results = []
    for case in CASES:
        rows, quality = read_case(case)
        assert quality["timestampsUniqueAndOrdered"] and quality["withinDaySlotsComplete"]
        assert Decimal(quality["maxMacdEquationError"]) < Decimal("0.0000000001")
        results.append(summarize_case(rows, case, quality))
    assert sum(r["quality"]["rows"] for r in results) == 198
    assert len(literal_anchor_checks(results)) == 4
    # Real output lacks these columns. Never add mock columns to fake a contract.
    rows, _ = read_case(CASES[1])
    assert "ts_code" not in rows[0] and "freq" not in rows[0]


@pytest.mark.parametrize("change", ["missing", "duplicate", "date", "slot", "type", "null", "equation", "identity", "nonfinite"])
def test_bad_real_contract_is_rejected(change):
    rows, _ = read_case(CASES[0])
    rows = deepcopy(rows)
    if change == "missing": del rows[2]["macd_dif"]
    elif change == "duplicate": rows[2] = deepcopy(rows[1])
    elif change == "date": rows[2]["trade_date"] = "1999-01-01"
    elif change == "slot": rows[2]["trade_time"] = rows[2]["trade_time"][:11] + "12:00:00"
    elif change == "type": rows[2]["close"] = 123.0
    elif change == "null": rows[2]["macd_dif"] = None
    elif change == "equation": rows[2]["macd"] = "999"
    elif change == "identity": rows[2]["freq"] = "90"
    elif change == "nonfinite": rows[2]["close"] = "NaN"
    with pytest.raises(ValueError):
        validate_rows(rows, CASES[0])


def test_missing_period_is_caught_even_when_declared_total_is_adjusted():
    rows, _ = read_case(CASES[0])
    del rows[2]
    with pytest.raises(ValueError, match="within-day"):
        validate_rows(rows, replace(CASES[0], rows=71))


def test_normal_price_change_does_not_trigger_source_contract_false_rejection():
    rows, _ = read_case(CASES[0])
    rows[2]["close"] = "3100.1234"
    assert validate_rows(rows, CASES[0])["rows"] == 72


class LiteralImage:
    """Known RGB producer for the pixel contract, not a real-image substitute."""
    size = (24, 40)

    def __init__(self):
        self.pixels = {}
        for x, length in zip((2, 6, 10, 14, 18), (3, 8, 3, 6, 2)):
            for y in range(6, 6 + length):
                self.pixels[x, y] = (120, 180, 110)

    def getpixel(self, xy):
        return self.pixels.get(xy, (255, 255, 255))


PIXEL_SPEC = MeasurementSpec(zero_y=5, x_start=0, x_end=24,
                             y_end=35, seed_depth=4, max_gap=0)


def test_pixel_colours_are_distinct_from_hand_drawn_ink_and_background():
    assert is_green((120, 180, 110), 15)
    assert not is_green((0, 220, 0), 15) and is_ink((0, 220, 0))
    assert not is_green((250, 250, 250), 15)


def test_literal_unoccluded_columns_measure_as_expected_without_invented_bars():
    result = measure_columns(LiteralImage(), PIXEL_SPEC)
    assert [b["length_px"] for b in result["bars"]] == [3, 8, 3, 6, 2]
    assert result["censored_bars"] == 0 and result["gaps"] == []
    assert [Decimal(t["value"]) for t in result["turns"] if t["kind"] == "MAX"] == [8, 6]


def test_obscured_column_is_unknown_and_never_interpolated_or_used_as_a_peak():
    image = LiteralImage()
    image.pixels[6, 10] = (0, 220, 0)
    result = measure_columns(image, PIXEL_SPEC)
    assert result["bars"][1]["censored"] and result["bars"][1]["length_px"] is None
    assert not result["fullSequenceVerified"]
    assert not any(Decimal(t["value"]) == 8 for t in result["turns"])


def test_disconnected_pixel_groups_are_not_silently_stitched():
    image = LiteralImage()
    image.pixels = {xy: rgb for xy, rgb in image.pixels.items() if xy[0] != 10}
    result = measure_columns(image, PIXEL_SPEC)
    assert result["gaps"] and not result["fullSequenceVerified"]


def test_image_roi_outside_real_dimensions_is_rejected():
    with pytest.raises(ValueError, match="ROI"):
        measure_columns(LiteralImage(), MeasurementSpec())
