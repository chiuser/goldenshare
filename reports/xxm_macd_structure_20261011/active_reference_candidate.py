"""Research-only isolation of active-reference locking versus reselection.

History, whole-wave extrema, eligibility, state thresholds and flip handling
remain unchanged. Refresh never silently clears a reference when no candidate
qualifies, and never carries an active reference across a sign-wave reset.
Switching an active reference is silent: no extra DULL/STRUCTURE event is added.
"""
from replay import read_rows


def select_reference(wave, history, sign, policy, max_refs, min_bars):
    if not sign or wave['count'] < min_bars or not history[sign]:
        return None
    nearest = history[sign][-1]
    if sign * (wave['price']-nearest['price']) <= 0:
        return None
    pool = list(reversed(history[sign][-max_refs:]))
    if policy != 'nearest_qualifying':
        pool.sort(key=lambda r: sign*r['dif'], reverse=True)
    if policy == 'strongest_separate':
        pool = pool[:1]
    for candidate in pool:
        price_ok = policy == 'strongest_separate' or sign*(wave['price']-candidate['price']) > 0
        if price_ok and sign*(wave['dif']-candidate['dif']) < 0:
            return candidate
    return None


def replay(rows, threshold_pct, *, active_policy='locked', diagnostics=False,
           color_flip=True, flip_requires_turn=False,
           reference_policy="nearest_qualifying", max_refs=2, min_bars=2):
    assert reference_policy in {
        "nearest_qualifying", "strongest_eligible", "strongest_separate"
    }
    assert active_policy in {'locked', 'both_before', 'dull_before', 'both_after'}
    history = {1: [], -1: []}
    wave = None
    state, ref, previous = "NONE", None, None
    result = []
    for row in rows:
        sign = (row["hist"] > 0) - (row["hist"] < 0)
        event, route, direction = "NONE", "", 0
        event_ref = None
        reference_before = dict(ref) if ref else None
        refreshed = False
        refresh_attempted = False
        canceled_old_first = False
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
        wave["count"] += 1
        extreme = max if sign > 0 else min
        wave["price"] = extreme(wave["price"], row["close"])
        wave["dif"] = extreme(wave["dif"], row["dif"])
        if ref and sign and event == 'NONE' and active_policy != 'locked':
            old_break = sign*(wave['dif']-ref['dif']) > 0
            permitted = active_policy != 'dull_before' or state == 'DULL'
            canceled_old_first = active_policy == 'both_after' and old_break
            if permitted and not canceled_old_first:
                refresh_attempted = True
                candidate = select_reference(wave, history, sign, reference_policy, max_refs, min_bars)
                if candidate is not None and candidate['start'] != ref['start']:
                    ref, refreshed = candidate, True
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
                candidate = select_reference(wave, history, sign, reference_policy, max_refs, min_bars)
                if candidate is not None:
                    ref, chosen_start = candidate, candidate['start']
                    event, state, route = 'DULL', 'DULL', 'activation'
                    direction, event_ref = sign, ref
        result.append(dict(time=row["time"], event=event, state=state,
                           wave_count=wave["count"], ref_start=chosen_start,
                           close=row["close"], dif=row["dif"], hist=row["hist"],
                           wave_sign=sign, event_direction=direction, event_route=route,
                           event_ref_start=event_ref["start"] if event_ref else "",
                           event_ref_dif=event_ref["dif"] if event_ref else None,
                           event_ref_price=event_ref["price"] if event_ref else None))
        if diagnostics:
            result[-1]['reference_refresh'] = dict(
                state_reference_before=reference_before,
                active_reference=dict(ref) if ref else None,
                event_reference=dict(event_ref) if event_ref else None,
                same_sign_last_two=[dict(r) for r in history.get(sign, [])[-max_refs:]],
                attempted=refresh_attempted, changed=refreshed,
                old_cancel_priority=canceled_old_first,
                current_wave_price=wave['price'], current_wave_dif=wave['dif'])
        previous = row
    return result
