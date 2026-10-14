"""Isolated turn-filter comparison against the saved stage-2 candidate.

Only same-color DIF filtering is varied. Integer modes use single-bar direction;
integer_round uses ties away from zero, not Python bankers rounding. display_3dp
uses the same explicit rounding and percentages of the quantized basis.
state_extreme anchors at state entry, then tracks its favorable raw DIF extreme;
resets the anchor on a state transition. Color-flip and cancellation remain raw.
Diagnostics describe eligibility under this replay, not known software state.
No production, DB/Lake, network, installation, or trading side effects.
"""
from replay import read_rows
from math import floor, ceil

def quantize(value, mode):
    if mode == "integer_trunc":
        return int(value)
    if mode == "integer_round":
        return floor(value + .5) if value >= 0 else ceil(value - .5)
    if mode == "display_3dp":
        value *= 1000
        return (floor(value + .5) if value >= 0 else ceil(value - .5)) / 1000
    return value


def replay(rows, threshold_pct, *, color_flip=True, flip_requires_turn=False,
           reference_policy="nearest_qualifying", max_refs=2, min_bars=2,
           turn_measure="single_bar", diagnostics=False):
    assert turn_measure in {"single_bar", "state_extreme", "integer_trunc",
                            "integer_round", "display_3dp"}
    assert reference_policy in {
        "nearest_qualifying", "strongest_eligible", "strongest_separate"
    }
    history = {1: [], -1: []}
    wave = None
    state, ref, previous, anchor = "NONE", None, None, None
    result = []
    for row in rows:
        sign = (row["hist"] > 0) - (row["hist"] < 0)
        event, route, direction = "NONE", "", 0
        event_ref = None
        diag = {}
        if wave is None or sign != wave["sign"]:
            if wave and wave["sign"]:
                old_sign = wave["sign"]
                # Evaluate the previous direction before destroying its state.
                if color_flip and sign == -old_sign and ref is not None:
                    if old_sign * (row["dif"] - ref["dif"]) > 0:
                        event, route = "CANCEL", "dif_break_on_flip"
                    elif state == "DULL":
                        basis = previous["dif"]
                        turn = old_sign * (row["dif"] - basis)
                        turn_ok = basis != 0 and turn < 0 and -turn >= abs(basis) * threshold_pct / 100
                        if not flip_requires_turn or turn_ok:
                            event, route = "STRUCTURE", "color_flip"
                    if event != "NONE":
                        direction, event_ref = old_sign, ref
                history[old_sign].append(wave)
            wave = dict(sign=sign, count=0, price=row["close"],
                        dif=row["dif"], start=row["time"])
            state, ref, anchor = "NONE", None, None
        wave["count"] += 1
        extreme = max if sign > 0 else min
        wave["price"] = extreme(wave["price"], row["close"])
        wave["dif"] = extreme(wave["dif"], row["dif"])
        chosen_start = ref["start"] if ref else ""
        if event == "NONE":
            if sign and ref and sign * (wave["dif"] - ref["dif"]) > 0:
                event, route, direction, event_ref = "CANCEL", "dif_break", sign, ref
                state, ref, anchor = "NONE", None, None
            elif sign and ref and previous is not None:
                basis = previous["dif"]
                if turn_measure == "state_extreme":
                    assert anchor is not None
                    if ((state == "DULL" and sign * (row["dif"] - anchor) > 0)
                            or (state == "STRUCTURE" and sign * (row["dif"] - anchor) < 0)):
                        anchor = row["dif"]
                    basis = anchor
                current_value = quantize(row["dif"], turn_measure)
                basis_value = quantize(basis, turn_measure)
                delta = sign * (current_value - basis_value)
                gate = abs(basis_value) * threshold_pct / 100
                diag = dict(state_before=state, basis=basis, evaluated_basis=basis_value,
                            previous_dif=previous["dif"], delta=delta,
                            magnitude_pct=100 * abs(delta) / abs(basis_value) if basis_value else None)
                basis = basis_value
                if basis != 0 and state == "DULL" and delta < 0 and -delta >= gate:
                    event, state, route = "STRUCTURE", "STRUCTURE", "dif_turn"
                elif basis != 0 and state == "STRUCTURE" and delta > 0 and delta >= gate:
                    event, state, route = "DULL", "DULL", "dif_return"
                if event != "NONE":
                    direction, event_ref = sign, ref
                    anchor = row["dif"]
            elif sign and wave["count"] >= min_bars and history[sign]:
                nearest = history[sign][-1]
                # Same price prerequisite supported by the Oct 16 holdout.
                if sign * (wave["price"] - nearest["price"]) > 0:
                    pool = list(reversed(history[sign][-max_refs:]))
                    if reference_policy != "nearest_qualifying":
                        pool.sort(key=lambda r: sign * r["dif"], reverse=True)
                    if reference_policy == "strongest_separate":
                        # Independent nearest-price gate; only strongest DIF is
                        # considered, regardless of that wave's price extreme.
                        pool = pool[:1]
                    for candidate in pool:
                        price_ok = (reference_policy == "strongest_separate"
                                    or sign * (wave["price"] - candidate["price"]) > 0)
                        if price_ok and sign * (wave["dif"] - candidate["dif"]) < 0:
                            ref, chosen_start = candidate, candidate["start"]
                            event, state, route = "DULL", "DULL", "activation"
                            anchor = row["dif"]
                            direction, event_ref = sign, ref
                            break
        result.append(dict(time=row["time"], event=event, state=state,
                           wave_count=wave["count"], ref_start=chosen_start,
                           close=row["close"], dif=row["dif"], hist=row["hist"],
                           wave_sign=sign, event_direction=direction, event_route=route,
                           event_ref_start=event_ref["start"] if event_ref else "",
                           event_ref_dif=event_ref["dif"] if event_ref else None,
                           event_ref_price=event_ref["price"] if event_ref else None))
        if diagnostics:
            result[-1]["filter_diagnostics"] = diag
        previous = row
    return result
