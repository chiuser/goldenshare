"""Stage-2 research hypotheses; no production signals or DB/Lake access.

Copied from frozen replay_color_flip.py; only historical-reference eligibility is extended.
Retirement policies are unproved research hypotheses, not software facts.
Frozen v1 stays untouched. This version tests confirmation before sign-wave
reset and explicit DIF-reference alternatives. A color-flip event belongs to
the ended wave; `state` always describes the newly current wave. Historical
reference validity after a flip is not modeled by this event replay.
"""
from replay import read_rows


def replay(rows, threshold_pct, *, color_flip=True, flip_requires_turn=False,
           reference_policy="nearest_qualifying", max_refs=2, min_bars=2, retirement_policy="none", history_min_bars=1):
    assert reference_policy in {
        "nearest_qualifying", "strongest_eligible", "strongest_separate"
    }
    assert retirement_policy in {"none", "raw_dif_cross", "dominated"}
    retired = set()
    history = {1: [], -1: []}
    wave = None
    state, ref, previous = "NONE", None, None
    result = []
    for row in rows:
        sign = (row["hist"] > 0) - (row["hist"] < 0)
        event, route, direction = "NONE", "", 0
        event_ref = None
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
            state, ref = "NONE", None
        # Permanent retirement affects new selections only. Historical waves still
        # count toward the fixed window; locked references use the original rules.
        if retirement_policy == "raw_dif_cross":
            for old_sign, old_waves in history.items():
                for old in old_waves:
                    if old_sign * (row["dif"] - old["dif"]) > 0:
                        retired.add(old["start"])
        wave["count"] += 1
        extreme = max if sign > 0 else min
        wave["price"] = extreme(wave["price"], row["close"])
        wave["dif"] = extreme(wave["dif"], row["dif"])
        chosen_start = ref["start"] if ref else ""
        if event == "NONE":
            if sign and ref and sign * (wave["dif"] - ref["dif"]) > 0:
                event, route, direction, event_ref = "CANCEL", "dif_break", sign, ref
                state, ref = "NONE", None
            elif sign and ref and previous is not None:
                basis = previous["dif"]
                delta = sign * (row["dif"] - basis)
                gate = abs(basis) * threshold_pct / 100
                if basis != 0 and state == "DULL" and delta < 0 and -delta >= gate:
                    event, state, route = "STRUCTURE", "STRUCTURE", "dif_turn"
                elif basis != 0 and state == "STRUCTURE" and delta > 0 and delta >= gate:
                    event, state, route = "DULL", "DULL", "dif_return"
                if event != "NONE":
                    direction, event_ref = sign, ref
            elif sign and wave["count"] >= min_bars and history[sign]:
                nearest = history[sign][-1]
                # Same price prerequisite supported by the Oct 16 holdout.
                if sign * (wave["price"] - nearest["price"]) > 0:
                    pool = list(reversed(history[sign][-max_refs:]))
                    if history_min_bars > 1:
                        # Alternative: count only longer completed segments when
                        # choosing the reference window; nearest-price gate stays.
                        pool = list(reversed([c for c in history[sign]
                                              if c["count"] >= history_min_bars][-max_refs:]))
                    if retirement_policy == "raw_dif_cross":
                        pool = [c for c in pool if c["start"] not in retired]
                    elif retirement_policy == "dominated":
                        pool = [c for c in pool if not any(
                            later["start"] > c["start"]
                            and sign * (later["price"] - c["price"]) >= 0
                            and sign * (later["dif"] - c["dif"]) >= 0
                            for later in history[sign])]
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
                            direction, event_ref = sign, ref
                            break
        result.append(dict(time=row["time"], event=event, state=state,
                           wave_count=wave["count"], ref_start=chosen_start,
                           close=row["close"], dif=row["dif"], hist=row["hist"],
                           wave_sign=sign, event_direction=direction, event_route=route,
                           event_ref_start=event_ref["start"] if event_ref else "",
                           event_ref_dif=event_ref["dif"] if event_ref else None,
                           event_ref_price=event_ref["price"] if event_ref else None))
        previous = row
    return result
