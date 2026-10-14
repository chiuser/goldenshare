"""Audit one supplied daily chart against frozen numerical diagnostics.

Coordinates and software readouts are manual observations of the original PNG,
not OCR, inferred labels, or fitted software history. No candidate is modified.
"""
import hashlib
import json
import struct
from pathlib import Path

from active_reference_candidate import replay
from audit_november_followup import extend_daily
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
IMAGE = ROOT / 'sources/20251114_daily.png'
PRIOR = ROOT / 'nov14_lecture_comparison_20261012.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    prior = json.loads(PRIOR.read_text())
    assert sha(ROOT / 'active_reference_candidate.py') == prior['candidate_sha256']
    assert sha(ROOT / 'november_followup_20261012.json') == prior['prior_screen_sha256']
    png = IMAGE.read_bytes()
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    width, height = struct.unpack('>II', png[16:24])
    assert (width, height) == (2818, 1088)
    manifest = json.loads((ROOT / 'screenshot_manifest.json').read_text())
    assert len([m for m in manifest if m['sha256'] == sha(IMAGE)]) == 1

    # Approximate original-image coordinates, read visually. Dates are mapped
    # backwards from the displayed Nov14 last bar using saved trading dates;
    # daily OHLC shapes provide independent corroboration of the last bars.
    centers = [
        ('2025-11-06', 1252), ('2025-11-07', 1348),
        ('2025-11-10', 1444), ('2025-11-11', 1540),
        ('2025-11-12', 1636), ('2025-11-13', 1732),
        ('2025-11-14', 1828),
    ]
    observations = [
        dict(text='钝化', color='yellow', text_left_x=1443,
             mapped_date='2025-11-10', role='existing_context_anchor_only'),
        dict(text='结构形成', color='magenta', text_left_x=1540,
             mapped_date='2025-11-11', role='existing_context_anchor_only'),
        dict(text='消失', color='green', text_left_x=1729,
             mapped_date='2025-11-13', role='new_structure_disappearance_category'),
    ]
    for o in observations:
        nearest = min(centers, key=lambda t: abs(t[1] - o['text_left_x']))
        assert nearest[0] == o['mapped_date']
        o['anchor_distance_px'] = abs(nearest[1] - o['text_left_x'])
        o['date_evidence'] = 'mapped_not_cursor_readout'
        o['semantic_evidence'] = 'Nov14 lecture explicitly distinguishes structure disappearance'
    fixture_path = REPO / 'tests/fixtures/quote_trend_channel/000001_sh_daily_input.json'
    fixture = json.loads(fixture_path.read_text())['rows']
    trend_screen = json.loads((ROOT / 'november_followup_20261012.json').read_text())
    assert sha(fixture_path) == trend_screen['fixture_sha256']
    recent_fixture = [r for r in fixture if centers[0][0] <= r['trade_date'] <= centers[-1][0]]
    assert [r['trade_date'] for r in recent_fixture] == [d for d, _ in centers]

    software = dict(open=4007.13, high=4034.08, low=3990.31, close=3990.49,
                    dif=34.363, dea=36.454, hist=-4.181)
    price = recent_fixture[-1]
    price_checks = {k: round(float(price[k]), 2) == software[k]
                    for k in ('open', 'high', 'low', 'close')}
    assert all(price_checks.values())
    seed = read_rows('daily_2025.csv')
    variants = []
    prefix_checks = 0
    for mode in ('recovered_rounded_seed', 'fixture_first_close'):
        rows, derivation = extend_daily(seed, fixture, '2025-11-14', mode)
        for policy in ('nearest_qualifying', 'strongest_eligible'):
            for gate in (.75, 1., 1.2):
                output = replay(rows, gate, reference_policy=policy)
                window = [r for r in output if '2025-11-11' <= r['time'] <= '2025-11-14']
                first = window[0]
                assert first['event'] == 'STRUCTURE' and first['event_direction'] == 1
                assert all(r['event'] == 'NONE' and r['state'] == 'NONE' for r in window[1:])
                for r in window:
                    last = replay([x for x in rows if x['time'] <= r['time']], gate,
                                  reference_policy=policy)[-1]
                    assert last == r
                    prefix_checks += 1
                by_date = {r['time']: r for r in window}
                before, target = by_date['2025-11-12'], by_date['2025-11-13']
                rise_pct = 100 * (target['dif'] - before['dif']) / abs(before['dif'])
                assert rise_pct >= gate
                assert before['hist'] < 0 < target['hist']
                assert target['dif'] < first['dif'] < first['event_ref_dif']
                terminal = window[-1]
                derived = dict(dif=terminal['dif'], hist=terminal['hist'],
                               dea=terminal['dif']-terminal['hist']/2)
                numeric = {k: dict(software=software[k], derived=derived[k],
                                  software_minus_derived=software[k]-derived[k],
                                  nearest_three_decimal_match=round(derived[k], 3) == software[k],
                                  within_conservative_one_display_unit=abs(software[k]-derived[k]) <= .001)
                           for k in ('dif', 'dea', 'hist')}
                assert numeric['dif']['nearest_three_decimal_match']
                assert numeric['hist']['nearest_three_decimal_match']
                assert not numeric['dea']['nearest_three_decimal_match']
                variants.append(dict(initialization=mode, reference_policy=policy,
                                     gate_pct=gate, window=window, derivation=derivation,
                                     nov13_dif_rise_pct=rise_pct, terminal_numeric=numeric,
                                     old_candidate_matches_new_disappearance_event=False))

    result = dict(
        research_date='2026-10-12', image_date='2025-11-14', period='daily',
        status='MAPPED_NEW_EVENT_CATEGORY_NOT_PARAMETER_FITTING',
        image_sha256=sha(IMAGE), dimensions=[width, height],
        prior_lecture_audit_sha256=sha(PRIOR), candidate_sha256=prior['candidate_sha256'],
        source_sha256=prior['source_sha256'], fixture_sha256=sha(fixture_path),
        observations=observations, original_pixel_bar_centers=centers,
        source_line_range=[32, 37], software_terminal_readout=software,
        terminal_ohlc_checks=price_checks,
        displayed_hist_identity_residual=software['hist']-2*(software['dif']-software['dea']),
        saved_daily_fixture_recent_rows=recent_fixture,
        variants=variants, prefix_checks=prefix_checks,
        comparisons={
            'candidate_state_clear_on_nov12_equals_marker': 'NOT_MATCHED_UNDER_MAPPED_ANCHOR',
            'DIF_rise_vs_histogram_return': 'NOT_DISTINGUISHED_BOTH_ON_NOV13',
            'DIF_above_structure_bar_or_original_reference': 'NOT_MATCHED_ON_SAVED_NUMERICAL_PATH',
            'historical_structure_disappearance_requires_separate_tracking': 'SUPPORTED_THIS_CASE_OLD_STATE_ALREADY_NONE',
            'daily_disappearance_closes_defensive_episode': 'NOT_SUPPORTED_AUTHOR_CORRECTION_STILL_FAR',
            'daily_disappears_again_on_nov14': 'NO_NEW_VISIBLE_MARKER_NOT_PROOF_OF_FULL_STATE',
        },
        tally=dict(screenshots=len(manifest), legacy_software_labels_unchanged=52,
                   new_mapped_structure_disappearance_observations=1,
                   context_anchors_not_counted_again=2, new_daily_terminal_readouts=1,
                   legacy_minute_terminal_readouts_unchanged=21),
        next_step='Freeze contrasting dates where upward DIF turn and histogram return occur on different bars before requesting one more source',
        limitations=[
            'Text anchors are manually mapped; no cursor date or original software export',
            'Red annotations overlap the green text; software marker identity uses the matching lecture',
            'Nov12/13 historical software indicator values remain unobserved',
            'DIF and histogram round to terminal display, DEA differs by less than one display unit but does not round identically',
            'One terminal readout does not certify the entire numerical history',
            'No formula, gate, correction-period join, final holdings or trade performance identified',
        ],
    )
    (ROOT / 'nov14_daily_disappearance_20261012.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(mapped_marker_date='2025-11-13', variants=len(variants),
                         prefix_checks=prefix_checks, screenshots=len(manifest),
                         numeric=variants[0]['terminal_numeric']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
