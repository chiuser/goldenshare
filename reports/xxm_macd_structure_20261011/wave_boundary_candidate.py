"""Causal wave-boundary hypotheses; local saved-data research only.

cut_bars=1 reproduces the frozen stage-2 rules. cut_bars=2 holds a first
opposite bar pending, discards it if the old sign returns, and commits the new
wave on the second consecutive opposite bar. At commit both observed pending
bars define the new wave, but earlier outputs are never revised. Pending bars
are excluded from the old wave's extrema and count. Zero histogram ends a wave.
flip_timing separates raw first-bar structure confirmation from delayed wave
confirmation. Independent DIF turns remain eligible during pending bars, but
new dull activation does not use an opposite pending bar's price/count.
The alternative is an explicit hypothesis, not a unique meaning of smoothing.
"""


def replay(rows, threshold_pct, *, cut_bars=1, flip_timing='raw',
           reference_policy='strongest_eligible', max_refs=2, min_bars=2,
           defer_at=None, diagnostics=False):
    assert cut_bars in (1, 2)
    assert flip_timing in ('raw', 'confirmed')
    assert reference_policy == 'strongest_eligible'
    history = {1: [], -1: []}
    wave, previous = None, None
    state, ref = 'NONE', None
    pending, result = [], []
    for row in rows:
        raw_sign = (row['hist'] > 0) - (row['hist'] < 0)
        event, route, direction, event_ref = 'NONE', '', 0, None
        opposite = bool(wave and wave['sign'] and raw_sign == -wave['sign'])
        if opposite:
            pending.append(row)
        else:
            pending = []
        # A dated exception is a local causal diagnostic, never a proposed rule.
        effective_cut = cut_bars if (defer_at is None or
                         (pending and pending[0]['time'] in defer_at)) else 1
        switch = (wave is None or (raw_sign != wave['sign'] and
                  (raw_sign == 0 or wave['sign'] == 0 or len(pending) >= effective_cut)))
        chosen_start = ref['start'] if ref else ''
        # Raw DIF reference cancellation does not depend on boundary smoothing.
        if opposite and ref is not None:
            old_sign = wave['sign']
            if old_sign * (row['dif'] - ref['dif']) > 0:
                event, route, direction, event_ref = 'CANCEL', 'dif_break_on_flip', old_sign, ref
                state, ref = 'NONE', None
            elif state == 'DULL' and ((flip_timing == 'raw' and len(pending) == 1)
                                      or (flip_timing == 'confirmed' and switch)):
                event, route, direction, event_ref = 'STRUCTURE', 'color_flip', old_sign, ref
                state = 'STRUCTURE'
        additions = []
        if switch:
            if wave and wave['sign']:
                history[wave['sign']].append(wave)
            additions = pending[:] if opposite else [row]
            wave = dict(sign=raw_sign, count=0, price=additions[0]['close'],
                        dif=additions[0]['dif'], start=additions[0]['time'])
            pending = []
            state, ref, chosen_start = 'NONE', None, ''
        elif not opposite:
            additions = [row]
        for observed in additions:
            extreme = max if wave['sign'] > 0 else min
            wave['count'] += 1
            wave['price'] = extreme(wave['price'], observed['close'])
            wave['dif'] = extreme(wave['dif'], observed['dif'])
        sign = wave['sign']
        # Keep DIF confirmation independent of the color confirmation path.
        if event == 'NONE' and (raw_sign == sign or (opposite and not switch)):
            if sign and ref and sign * (wave['dif'] - ref['dif']) > 0:
                event, route, direction, event_ref = 'CANCEL', 'dif_break', sign, ref
                state, ref = 'NONE', None
            elif sign and ref and previous is not None:
                basis = previous['dif']
                delta = sign * (row['dif'] - basis)
                gate = abs(basis) * threshold_pct / 100
                if basis != 0 and state == 'DULL' and delta < 0 and -delta >= gate:
                    event, state, route = 'STRUCTURE', 'STRUCTURE', 'dif_turn'
                elif basis != 0 and state == 'STRUCTURE' and delta > 0 and delta >= gate:
                    event, state, route = 'DULL', 'DULL', 'dif_return'
                if event != 'NONE':
                    direction, event_ref = sign, ref
            elif sign and raw_sign == sign and wave['count'] >= min_bars and history[sign]:
                nearest = history[sign][-1]
                if sign * (wave['price'] - nearest['price']) > 0:
                    pool = list(reversed(history[sign][-max_refs:]))
                    pool.sort(key=lambda r: sign * r['dif'], reverse=True)
                    for candidate in pool:
                        if (sign * (wave['price'] - candidate['price']) > 0
                                and sign * (wave['dif'] - candidate['dif']) < 0):
                            ref, chosen_start = candidate, candidate['start']
                            event, state, route = 'DULL', 'DULL', 'activation'
                            direction, event_ref = sign, ref
                            break
        result.append(dict(time=row['time'], event=event, state=state,
                           wave_count=wave['count'], ref_start=chosen_start,
                           close=row['close'], dif=row['dif'], hist=row['hist'],
                           wave_sign=sign, event_direction=direction, event_route=route,
                           event_ref_start=event_ref['start'] if event_ref else '',
                           event_ref_dif=event_ref['dif'] if event_ref else None,
                           event_ref_price=event_ref['price'] if event_ref else None))
        if diagnostics:
            result[-1]['boundary_diagnostics'] = dict(raw_sign=raw_sign, wave_start=wave['start'],
                pending_count=len(pending), switch=switch,
                history_top=[dict(r) for r in history[1][-max_refs:]],
                history_bottom=[dict(r) for r in history[-1][-max_refs:]])
        previous = row
    return result
