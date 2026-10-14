"""One-factor research candidate: historical whole-wave versus last local pivot.

Only ended-wave reference extrema change. Active/current extrema, state paths,
window and gates stay identical to replay_color_flip. No DB or formal signals.
A local pivot needs an observed favorable slope followed by an adverse slope;
flat values keep the preceding slope. No pivot means fallback to whole-wave
extreme. Boundary mode may use the first already-observed outside-wave row to
confirm a last-wave value; that outside value never becomes the reference.
"""
from replay import read_rows


def last_pivot(rows, field, sign, boundary=None):
    """Return last favorable-to-adverse turn, with causal confirmation metadata."""
    latest, slope = None, 0
    observations = rows + ([boundary] if boundary is not None else [])
    for i in range(1, len(observations)):
        previous, current = observations[i-1], observations[i]
        delta = sign * (current[field] - previous[field])
        direction = (delta > 0) - (delta < 0)
        if direction < 0 and slope > 0:
            latest = dict(value=previous[field], pivot_time=previous['time'],
                          confirmed_at=current['time'], boundary=current is boundary)
        if direction:
            slope = direction
    return latest


def freeze_reference(wave, boundary, mode, fields):
    frozen = {k: wave[k] for k in ('sign', 'count', 'price', 'dif', 'start')}
    details = {}
    for field in ('price', 'dif'):
        source_field = 'close' if field == 'price' else 'dif'
        pivot = (last_pivot(wave['rows'], source_field, wave['sign'],
                            boundary if mode == 'last_boundary' else None)
                 if mode != 'whole' and field in fields else None)
        if pivot:
            frozen[field] = pivot['value']
        details[field] = dict(whole=wave[field], selected=frozen[field], pivot=pivot,
                              fallback=mode != 'whole' and field in fields and pivot is None)
    frozen['extrema_details'] = details
    frozen['available_at'] = boundary['time']
    return frozen


def replay(rows, threshold_pct, *, historical_extrema='whole',
           reference_fields=('price', 'dif'), diagnostics=False,
           color_flip=True, flip_requires_turn=False,
           reference_policy="nearest_qualifying", max_refs=2, min_bars=2):
    assert reference_policy in {
        "nearest_qualifying", "strongest_eligible", "strongest_separate"
    }
    assert historical_extrema in {'whole', 'last_interior', 'last_boundary'}
    assert set(reference_fields) <= {'price', 'dif'}
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
                history[old_sign].append(freeze_reference(wave, row, historical_extrema, reference_fields))
            wave = dict(sign=sign, count=0, price=row["close"],
                        dif=row["dif"], start=row["time"], rows=[])
            state, ref = "NONE", None
        wave["rows"].append(row)
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
        if diagnostics:
            result[-1]['historical_extrema'] = {
                'same_sign_last_two': [dict(r) for r in history.get(sign, [])[-max_refs:]],
                'event_reference': dict(event_ref) if event_ref else None,
                'active_reference': dict(ref) if ref else None,
            }
        previous = row
    return result
