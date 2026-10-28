"""P1 hand-written r4 inputs and expected facts; no detector/solver imports.

Authority: product LLD v1 sections 2, 3, 6, 11.2.1 and 16.  Values below
are artificial completed inputs, not a sampled market series.  DEA and hist
are both explicit input values.  P1 checks the material and independent
arithmetic only; P2/P3 must separately assert these facts against production.

Bar/check/reference indices are one-based positions in each case.  Event
links such as ``event@6`` describe which actual event must supply the ID;
they do not pretend to know the hash before P2 fixes the formal Spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


# All are genuine calendar dates, but these artificial cases do not claim to
# validate exchange-day completeness.  Minute inputs use that day's 15:00
# endpoint, valid in all three supported minute periods; missing intraday
# endpoints are intentionally outside a calculator-only unit case.
DATES = (
    "2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06",
    "2023-01-09", "2023-01-10", "2023-01-11", "2023-01-12",
    "2023-01-13", "2023-01-16", "2023-01-17", "2023-01-18",
)
PERIODS = ("day", "m60", "m90", "m120")


@dataclass(frozen=True)
class Reference:
    name: str
    start: int
    end: int
    price: float
    dif: float


@dataclass(frozen=True)
class Check:
    at: int
    state: str
    direction: str | None
    reference: str | None
    # (type, route, direction, event reference name); empty means NO event.
    events: tuple[tuple[str, str, str, str | None], ...] = ()
    # Explicit state/history/waiting facts for subsequent production tests.
    facts: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class Case:
    name: str
    rules: tuple[str, ...]
    why: str
    # Explicit source values: close, DIF, DEA, MACD histogram.
    values: tuple[tuple[float, float, float, float], ...]
    references: tuple[Reference, ...]
    checks: tuple[Check, ...]

    def inputs(self, period: str) -> tuple[dict, ...]:
        """Only attach fixed dates/period formatting; never calculate a signal."""
        if period not in PERIODS:
            raise ValueError("Unsupported artificial-input period")
        return tuple({
            "time": DATES[i] if period == "day" else DATES[i] + "T15:00:00+08:00",
            "close": c, "dif": d, "dea": a, "hist": h, "completed": True,
        } for i, (c, d, a, h) in enumerate(self.values))


TOP = ((100, 50, 49, 2), (90, 0, 1, -2),
       (101, 40, 39, 2), (102, 41, 40, 2))
TWO_TOPS = ((130, 30, 29, 2), (90, 0, 1, -2),
            (120, 20, 19, 2), (90, 0, 1, -2))
SWITCH_TOP = ((100, 41.186, 40.186, 2), (90, 0, 1, -2),
              (120, 24.935, 23.935, 2), (90, 0, 1, -2),
              (130, 17.649, 16.649, 2), (131, 17.649, 16.649, 2))
BOTTOM = ((100, -10, -9, -2), (99, -11, -10, -2),
          (105, -5, -6, 2), (98, -9, -8, -2),
          (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2))
WAITING = BOTTOM + ((100, -9, -9, 0),)
B_TOP = (Reference("B", 1, 1, 100, 50),)
AB_TOP = (Reference("A", 1, 1, 130, 30), Reference("B", 3, 3, 120, 20))
SWITCH_REFS = (Reference("A", 1, 1, 100, 41.186), Reference("B", 3, 3, 120, 24.935))
B_BOTTOM = (Reference("B", 1, 2, 99, -11),)


CASES = (
    Case("no_completed_same_color_reference", ("R05", "R07"),
         "The first continuous red wave has two bars but no historical red B.",
         ((100, 10, 9, 2), (101, 11, 10, 2)), (),
         (Check(2, "NONE", None, None, facts=(("count", 2),
                    ("completed_same_color_count", 0))),)),
    Case("one_nonzero_colored_bar_is_insufficient", ("R07",),
         "Price and DIF qualify against B, but the new red wave has only one true bar.",
         ((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2)), B_TOP,
         (Check(3, "NONE", None, None, facts=(("count", 1),)),)),
    Case("nearest_before_stronger_far", ("R07",),
         "B is eligible; stronger A must not replace it.",
         TWO_TOPS + ((131, 15, 14, 2), (132, 16, 15, 2)), AB_TOP,
         (Check(5, "NONE", None, None),
          Check(6, "DULL", "TOP", "B", (("DULL", "activation", "TOP", "B"),)))),
    Case("far_only_after_near_fails", ("R07",),
         "Price passes B, DIF exceeds B but is below A; choose A.",
         TWO_TOPS + ((131, 25, 24, 2), (132, 26, 25, 2)), AB_TOP,
         (Check(6, "DULL", "TOP", "A", (("DULL", "activation", "TOP", "A"),)),)),
    Case("near_price_gate_blocks_far", ("R07",),
         "A would qualify alone, but 119 has not exceeded nearest B's 120.",
         ((100, 30, 29, 2),) + TWO_TOPS[1:] + ((119, 10, 9, 2), (119, 10, 9, 2)),
         (Reference("A", 1, 1, 100, 30), Reference("B", 3, 3, 120, 20)),
         (Check(6, "NONE", None, None),)),
    Case("first_price_equality_rejected", ("R07",),
         "120 equals B price; first entry requires a strict break.",
         TWO_TOPS + ((120, 10, 9, 2), (120, 10, 9, 2)), AB_TOP,
         (Check(6, "NONE", None, None),)),
    Case("first_dif_equality_rejected", ("R07",),
         "B DIF fails and A DIF equals 30; neither is first divergence.",
         TWO_TOPS + ((131, 30, 29, 2), (132, 30, 29, 2)), AB_TOP,
         (Check(6, "NONE", None, None),)),
    Case("third_candidate_not_searched", ("R07",),
         "The oldest 60 peak would qualify, but only latest B/A remain.",
         ((150, 60, 59, 2), (90, 0, 1, -2)) + TWO_TOPS
         + ((160, 40, 39, 2), (161, 40, 39, 2)),
         (Reference("old", 1, 1, 150, 60), Reference("A", 3, 3, 130, 30),
          Reference("B", 5, 5, 120, 20)),
         (Check(8, "NONE", None, None, facts=(("pool_starts", (3, 5)),)),)),
    Case("same_color_zero_is_not_opposite", ("R05", "R07"),
         "Red-zero-red is one wave; no completed red reference exists.",
         ((100, 50, 49, 2), (101, 30, 30, 0), (102, 31, 30, 2)), (),
         (Check(3, "NONE", None, None, facts=(("wave_start", 1), ("count", 2),
                                             ("completed_same_color_count", 0))),)),
    Case("zero_does_not_supply_second_colored_bar", ("R05", "R07"),
         "Zero raises price but count remains one; next true red supplies two.",
         ((100, 50, 49, 2), (90, 0, 1, -2), (98, 5, 4, 2),
          (101, 5, 5, 0), (102, 5, 4, 2)), B_TOP,
         (Check(4, "NONE", None, None, facts=(("count", 1),)),
          Check(5, "DULL", "TOP", "B", (("DULL", "activation", "TOP", "B"),),
                (("count", 2),)))),
    Case("zero_day_first_activation", ("R05", "R07"),
         "Two true red bars already exist; zero day first passes price gate.",
         ((100, 50, 49, 2), (90, 0, 1, -2), (98, 5, 4, 2),
          (99, 6, 5, 2), (101, 6, 6, 0)), B_TOP,
         (Check(4, "NONE", None, None),
          Check(5, "DULL", "TOP", "B", (("DULL", "activation", "TOP", "B"),),
                (("count", 2),)))),
    Case("opening_zero_not_backfilled", ("R05",),
         "Leading zeros cannot acquire the following red color or a history.",
         ((100, 1, 1, 0), (99, -1, -1, 0), (100, 2, 1, 2)), (),
         (Check(2, "NONE", None, None, facts=(("wave_start", None),)),
          Check(3, "NONE", None, None, facts=(("wave_start", 3), ("count", 1))))),
    Case("first_entry_is_not_same_bar_structure", ("R09",),
         "41 to 40 turns by more than 1%, but first eligible root only activates.",
         ((100, 50, 49, 2), (90, 0, 1, -2), (102, 41, 40, 2),
          (103, 40, 39, 2)), B_TOP,
         (Check(4, "DULL", "TOP", "B", (("DULL", "activation", "TOP", "B"),)),)),
    Case("exact_one_percent_zero_target", ("R05", "R09"),
         "100 to 99 is exactly 1%; zero histogram still confirms TOP structure.",
         ((100, 200, 199, 2), (90, 0, 1, -2), (101, 90, 89, 2),
          (102, 100, 99, 2), (102, 99, 99, 0)),
         (Reference("B", 1, 1, 100, 200),),
         (Check(4, "DULL", "TOP", "B", (("DULL", "activation", "TOP", "B"),)),
          Check(5, "STRUCTURE", "TOP", "B", (("STRUCTURE", "dif_turn", "TOP", "B"),),
                (("top_history.confirmed_event", "event@5"),
                 ("top_history.original_reference", "B"), ("top_history.price", 102),
                 ("top_history.price_at", 4))))),
    Case("less_than_one_percent_remains_dull", ("R09",),
         "100 to 99.1 drops only 0.9%; no turn event.",
         ((100, 200, 199, 2), (90, 0, 1, -2), (101, 90, 89, 2),
          (102, 100, 99, 2), (102, 99.1, 99.1, 0)),
         (Reference("B", 1, 1, 100, 200),), (Check(5, "DULL", "TOP", "B"),)),
    Case("previous_zero_dif_is_not_skipped", ("R09",),
         "Previous completed DIF=0 blocks the next ordinary 1% return.",
         ((100, 10, 9, 2), (90, 0, 1, -2), (101, 1, 0, 2),
          (102, .5, -.5, 2), (102, 0, 0, 0), (102, -1, -2, 2)),
         (Reference("B", 1, 1, 100, 10),),
         (Check(5, "STRUCTURE", "TOP", "B", (("STRUCTURE", "dif_turn", "TOP", "B"),)),
          Check(6, "STRUCTURE", "TOP", "B"))),
    Case("previous_zero_bar_dif_is_adjacent_basis", ("R09", "R10"),
         "Return compares 40.35 with immediately prior zero day's 39.9, not 40.",
         TOP + ((102, 40, 39, 2), (102, 39.9, 39.9, 0), (102, 40.35, 39.35, 2)), B_TOP,
         (Check(7, "DULL", "TOP", "B", (("DULL", "dif_return", "TOP", "B"),),
                (("top_history.status", "ENDED"), ("top_history.end_reason", "new_top_DULL"))),)),
    Case("true_flip_confirms_without_one_percent", ("R05", "R09", "R10"),
         "True green confirms old TOP; 40.9 versus 41 is below 1%; 999 is not old peak.",
         TOP + ((102, 41, 41, 0), (999, 40.9, 41.9, -2)), B_TOP,
         (Check(6, "NONE", None, None, (("STRUCTURE", "color_flip", "TOP", "B"),),
                (("top_history.price", 102), ("top_history.price_at", 4),
                 ("old_wave_end", 5), ("wave_start", 6))),)),
    Case("true_flip_break_precedes_confirmation", ("R09",),
         "51 strictly breaks old 50 on true flip; CANCEL wins over color confirmation.",
         TOP + ((999, 51, 52, -2),), B_TOP,
         (Check(5, "NONE", None, None, (("CANCEL", "dif_break_on_flip", "TOP", "B"),),
                (("top_history_exists", False),)),)),
    Case("same_bar_near_to_far_switch", ("R08", "R10"),
         "B is broken on zero day, A qualifies on that SAME root; no cancel/new DULL.",
         SWITCH_TOP + ((132, 26.754, 26.754, 0), (131, 27.890, 26.890, 2),
                       (131, 27.4, 26.4, 2)), SWITCH_REFS,
         (Check(6, "DULL", "TOP", "B", (("DULL", "activation", "TOP", "B"),)),
          Check(7, "DULL", "TOP", "A", facts=(("original_event@6.reference", "B"),
                                                ("count", 2))),
          Check(9, "STRUCTURE", "TOP", "A", (("STRUCTURE", "dif_turn", "TOP", "A"),),
                (("top_history.original_reference", "A"),)))),
    Case("true_flip_never_rescues_with_eligible_a", ("R08", "R09"),
         "A is eligible, but the same bar is a true green flip; cancel old B before any rescue.",
         SWITCH_TOP + ((132, 26.754, 27.754, -2),), SWITCH_REFS,
         (Check(7, "NONE", None, None, (("CANCEL", "dif_break_on_flip", "TOP", "B"),),
                (("top_history_exists", False), ("wave_start", 7))),)),
    Case("far_qualifies_only_next_bar", ("R08",),
         "A price140 fails at132, so cancel today; 141 qualifies tomorrow and cannot erase it.",
         ((140, 41.186, 40.186, 2),) + SWITCH_TOP[1:]
         + ((132, 26.754, 25.754, 2), (141, 27.890, 26.890, 2)),
         (Reference("A", 1, 1, 140, 41.186), Reference("B", 3, 3, 120, 24.935)),
         (Check(7, "NONE", None, None, (("CANCEL", "dif_break", "TOP", "B"),)),
          Check(8, "DULL", "TOP", "A", (("DULL", "activation", "TOP", "A"),),
                (("preserve_event@7", True),)))),
    Case("structure_does_not_use_dull_switch", ("R08",),
         "Already STRUCTURE, so B break cancels even though A would qualify.",
         SWITCH_TOP + ((131, 17, 16, 2), (132, 26.754, 26.754, 0)), SWITCH_REFS,
         (Check(7, "STRUCTURE", "TOP", "B", (("STRUCTURE", "dif_turn", "TOP", "B"),)),
          Check(8, "NONE", None, None, (("CANCEL", "dif_break", "TOP", "B"),),
                (("top_history.end_reason", "original_reference_break"),)))),
    Case("equal_active_reference_does_not_switch", ("R08",),
         "DIF exactly equals B; no cancellation or A search.",
         SWITCH_TOP + ((132, 24.935, 23.935, 2),), SWITCH_REFS,
         (Check(7, "DULL", "TOP", "B"),)),
    Case("bottom_same_bar_switch", ("R08", "R10"),
         "Bottom symmetric values are explicit; -26.754 breaks B but not A.",
         ((100, -41.186, -40.186, -2), (110, 0, -1, 2),
          (80, -24.935, -23.935, -2), (110, 0, -1, 2),
          (70, -17.649, -16.649, -2), (69, -17.649, -16.649, -2),
          (68, -26.754, -26.754, 0), (69, -27.890, -26.890, -2),
          (69, -27.4, -26.4, -2)),
         (Reference("A", 1, 1, 100, -41.186), Reference("B", 3, 3, 80, -24.935)),
         (Check(6, "DULL", "BOTTOM", "B", (("DULL", "activation", "BOTTOM", "B"),)),
          Check(7, "DULL", "BOTTOM", "A", facts=(("original_event@6.reference", "B"),)),
          Check(9, "STRUCTURE", "BOTTOM", "A", (("STRUCTURE", "dif_turn", "BOTTOM", "A"),),
                (("bottom_history.structure_event", "event@9"),
                 ("bottom_history.original_reference", "A"))))),
    Case("bottom_has_no_negative_current_dif_gate", ("R07",),
         "Current DIF=1 is positive, but current valley0 remains above old -1.",
         ((100, -1, 0, -2), (110, 1, 0, 2), (99, 0, 1, -2), (98, 1, 2, -2)),
         (Reference("B", 1, 1, 100, -1),),
         (Check(4, "DULL", "BOTTOM", "B", (("DULL", "activation", "BOTTOM", "B"),)),)),
    Case("bottom_current_close_starts_waiting", ("R10",),
         "Old cumulative low97 cannot replace today's100; threshold is strictly below99.",
         WAITING, B_BOTTOM,
         (Check(5, "DULL", "BOTTOM", "B", (("DULL", "activation", "BOTTOM", "B"),)),
          Check(6, "STRUCTURE", "BOTTOM", "B", (("STRUCTURE", "dif_turn", "BOTTOM", "B"),),
                (("bottom_history.price", 97), ("bottom_history.price_at", 5))),
          Check(7, "NONE", None, None, (("STRUCTURE_DISAPPEARED", "dif_return", "BOTTOM", "B"),),
                (("wait.status", "WAITING"), ("wait.reference", "B"),
                 ("wait.nearest_price", 99), ("wait.structure_event", "event@6"),
                 ("wait.disappeared_event", "event@7"),
                 ("bottom_history.end_reason", "structure_disappeared"))))),
    Case("zero_day_bottom_reactivation", ("R05", "R10"),
         "98.5 is strictly below99 on later zero day; use saved B and original structure link.",
         WAITING + ((98.5, -9.2, -9.2, 0),), B_BOTTOM,
         (Check(8, "DULL", "BOTTOM", "B", (("DULL", "reactivation", "BOTTOM", "B"),),
                (("wait.status", "REACTIVATED"), ("wait.end_reason", "price_requalified"),
                 ("wait.structure_event", "event@6"), ("wait.disappeared_event", "event@7"),
                 ("event@8.related_wait", "wait@7"), ("event@8.related_bottom_history", None),
                 ("count", 3))),)),
    Case("waiting_price_equality_not_reactivated", ("R10",),
         "Current99 equals gate; earlier97 cannot reactivate this zero day.",
         WAITING + ((99, -9.2, -9.2, 0),), B_BOTTOM,
         (Check(8, "NONE", None, None, facts=(("wait.status", "WAITING"),
                                             ("wave_price", 97))),)),
    Case("waiting_reference_break_invalidates", ("R10",),
         "Saved B=-11 is strictly broken; no A search or price reactivation.",
         WAITING + ((98.5, -11.1, -11.1, 0),), B_BOTTOM,
         (Check(8, "NONE", None, None, facts=(("wait.status", "INVALIDATED"),
                    ("wait.end_reason", "reference_dif_break"))),)),
    Case("waiting_true_red_ends_segment", ("R05", "R10"),
         "Actual red ends old waiting; zero never supplies this reason.",
         WAITING + ((100, -9, -10, 2),), B_BOTTOM,
         (Check(8, "NONE", None, None, facts=(("wait.status", "SEGMENT_ENDED"),
                    ("wait.end_reason", "color_flip"))),)),
    Case("historical_top_price_withdrawal", ("R10",),
         "After top structure, close103 strictly exceeds saved102; active state is separate.",
         TOP + ((102, 40, 39, 2), (103, 39.9, 38.9, 2), (104, 39.8, 38.8, 2)), B_TOP,
         (Check(6, "STRUCTURE", "TOP", "B",
                (("RESEARCH_HISTORICAL_WITHDRAWAL", "historical_price_break", "TOP", "B"),),
                (("top_history.status", "ENDED"), ("top_history.end_reason", "historical_price_break"),
                 ("top_history.price", 102))), Check(7, "STRUCTURE", "TOP", "B"))),
    Case("bottom_history_withdraws_only_after_real_red", ("R05", "R10"),
         "Red at7 leaves original green; close96 at8 breaks frozen low97.",
         BOTTOM + ((105, -8.8, -9.8, 2), (96, -8, -7, -2)), B_BOTTOM,
         (Check(7, "NONE", None, None, facts=(("bottom_history.left_origin_at", 7),)),
          Check(8, "NONE", None, None,
                (("RESEARCH_HISTORICAL_WITHDRAWAL", "historical_price_break", "BOTTOM", "B"),),
                (("bottom_history.end_reason", "historical_price_break"),
                 ("bottom_history.structure_event", "event@6"))))),
    Case("cumulative_close_and_separate_dif_dates", ("R06", "R07"),
         "First entry uses earlier125, not current119; peak DIF25 is from a different root.",
         ((120, 50, 49, 2), (110, 0, 1, -2), (125, 20, 19, 2), (119, 25, 24, 2)),
         (Reference("B", 1, 1, 120, 50),),
         (Check(4, "DULL", "TOP", "B", (("DULL", "activation", "TOP", "B"),),
                (("wave_price", 125), ("wave_price_at", 3), ("wave_dif", 25),
                 ("wave_dif_at", 4))),)),
    Case("first_top_requires_positive_current_dif", ("R07",),
         "Cumulative peak1 is positive but current DIF0 cannot first activate TOP.",
         ((120, 20, 19, 2), (110, 0, 1, -2), (131, 1, 0, 2), (132, 0, -1, 2)),
         (Reference("B", 1, 1, 120, 20),), (Check(4, "NONE", None, None),)),
    Case("active_reference_equality_then_strict_break", ("R07", "R09"),
         "Existing DULL survives equality50; 50.01 cancels on that exact next root.",
         TOP + ((102, 50, 49, 2), (102, 50.01, 49.01, 2)), B_TOP,
         (Check(5, "DULL", "TOP", "B"),
          Check(6, "NONE", None, None, (("CANCEL", "dif_break", "TOP", "B"),)))),
    Case("price_fall_alone_does_not_cancel_existing_dull", ("R07", "R09"),
         "Latest close99 falls below B100, but established DULL keeps B and DIF41 has not broken50.",
         TOP + ((99, 41, 40, 2),), B_TOP,
         (Check(5, "DULL", "TOP", "B", facts=(("wave_price", 102),)),)),
)


# Independent rational projection for FUTURE hypothetical closes only.
# Authority: LLD 11.2.1, EMA12/26/9 recurrence on paper.  Actual inputs above
# are never recalculated using this model; it does not import old proof code.
FORECAST_MATH = {
    "basis": "LLD 6.1/6.4/11.2.1; literal e12=102,e26=100,DEA=-2",
    # This is an entire first-entry example under explicit artificial state,
    # not a universal range inferred from the DIF inequality alone.  It is
    # exact full_float/rational minute math; daily .001 ties remain guarded.
    "entry_context": {
        "direction": "TOP", "state": "NONE", "colored_count": 1,
        "current_close": 100, "wave_price": 100, "wave_dif": 2,
        "current_dea": -2, "current_hist": 8,
        "nearest_reference": {"price": 70, "dif": 10}, "far_reference": None,
        "next_colored_count": 2, "precision": "full_float",
    },
    "e12": Fraction(102), "e26": Fraction(100), "dea": Fraction(-2),
    "first_dif_p": Fraction(28, 351), "first_dif_b": Fraction(-2206, 351),
    "entry_lower": Fraction(1103, 14), "entry_upper": Fraction(1429, 7),
    "entry_lower_inclusive": False, "entry_upper_inclusive": False,
    "P": Fraction(100), "D1": Fraction(22, 13), "DEA1": Fraction(-82, 65),
    "D1_minus_D2_at_zero": Fraction(192, 65), "one_percent": Fraction(22, 1300),
    # Hand-expanded D2 = AP*P + K*C + B2.
    "second_dif_p": Fraction(22, 169) - Fraction(50, 729),
    "second_dif_c": Fraction(28, 351),
    "second_dif_b": Fraction(12342, 169) - Fraction(62500, 729),
    "zero_target_C_at_P100": Fraction(30137, 455),
    "turn_target_C_at_P100": Fraction(1875539, 18200),
    "zero_target_lower_inclusive": True,
    "color_flip_upper_inclusive": False,
    "positive_close_lower": Fraction(0), "positive_close_lower_inclusive": False,
    "literal_outcomes": (
        (Fraction(40), "STRUCTURE", "color_flip"),
        (Fraction(100), "STRUCTURE", "dif_turn"),
        (Fraction(110), "DULL", None),
    ),
    # Source .001 tie at +.0005 has two legal source representations; it is
    # NOT a deterministic positive-DIF first entry on the daily source.
    "daily_tie_raw_dif": Fraction(1, 2000),
    "daily_tie_options": (Fraction(0), Fraction(1, 1000)),
    "daily_tie_result": "PRECISION_UNRESOLVED",
}
