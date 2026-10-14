"""Bounded next-bar threshold audit from saved inputs and fetched captions.

No DB/Lake access, installations, product signals, or frozen-label changes.
Narrated prices are approximate evidence, not chart-marker observations.
"""
import hashlib
import json
from pathlib import Path

from replay import read_rows
from replay_color_flip import replay

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def next_dif_line(previous, current):
    # Recover the current slow EMA from two consecutive DIF values and C.
    # D_t = (a-b)C_t + (b-a)S_(t-1) + (1-a)D_(t-1).
    a, b = 2 / 13, 2 / 27
    slope = a - b
    slow_previous = (current['dif'] - slope * current['close']
                     - (1 - a) * previous['dif']) / (b - a)
    slow = b * current['close'] + (1 - b) * slow_previous
    fast = slow + current['dif']
    intercept = (1 - a) * fast - (1 - b) * slow
    return slope, intercept


def inspect(filename, current_time, quoted_price):
    rows = read_rows(filename)
    i = next(i for i, row in enumerate(rows) if row['time'] == current_time)
    slope, intercept = next_dif_line(rows[i - 1], rows[i])
    policies = {}
    for policy in ('nearest_qualifying', 'strongest_eligible'):
        # This state extraction stops at the narrated calculation origin.
        outputs = replay(rows[:i + 1], 1, reference_policy=policy)
        origin = outputs[-1]
        reference = next(x for x in reversed(outputs)
                         if x['event_ref_start'] == origin['ref_start']
                         and x['event_ref_dif'] is not None)
        target = reference['event_ref_dif']
        critical = (target - intercept) / slope
        policies[policy] = {
            'origin_state': origin['state'],
            'reference_start': origin['ref_start'],
            'reference_dif': target,
            'next_close_equality_boundary': critical,
            'distance_from_approximate_quote': critical - quoted_price,
        }
    next_actual = rows[i + 1]
    turns = {
        str(pct): (rows[i]['dif'] * (1 - pct / 100) - intercept) / slope
        for pct in (0.75, 1, 1.2)
    }
    return {
        'input': filename, 'input_sha256': digest(ROOT / 'inputs' / filename),
        'origin_time': current_time, 'origin_close': rows[i]['close'],
        'origin_dif': rows[i]['dif'], 'quoted_next_close_approximate': quoted_price,
        'next_dif_slope': slope, 'next_dif_intercept': intercept,
        'policies': policies, 'top_structure_relative_turn_boundaries': turns,
        'next_actual_time': next_actual['time'],
        'next_actual_dif': next_actual['dif'],
        'next_actual_dif_residual': next_actual['dif']
        - (slope * next_actual['close'] + intercept),
        'software_label': 'NARRATED_THRESHOLD_ONLY_NO_NEW_SCREENSHOT',
    }


def main():
    frozen_path = ROOT / 'stage2_next_screenshot.json'
    frozen_before = digest(frozen_path)
    result = {
        'scope': 'New narrated thresholds checked against unchanged stage-2 hypotheses',
        'script_sha256': digest(Path(__file__)),
        'frozen_predictions_sha256': frozen_before,
        'sources': {
            date: {
                'file': f'sources/{date}_vidiq_transcript.json',
                'sha256': digest(ROOT / 'sources' / f'{date}_vidiq_transcript.json'),
            }
            for date in ('20250815', '20250818')
        },
        'audits': [
            inspect('120_20250401_20251111.csv', '2025-08-15 15:00:00', 3750),
            inspect('daily_2025.csv', '2025-08-15', 3699),
        ],
        'limitations': [
            'Reuploaded speaker captions may misrecognize numbers; no new chart supplied.',
            'Prices are approximate, and equality versus strict crossing is unresolved.',
            'This distinguishes the two candidate references locally, not every reference rule.',
            'Aug18 captions do not uniquely locate the final marker in AM versus PM.',
            'Intrabar cancellation may reverse; only completed bars are replayed.',
        ],
    }
    minute_rows = read_rows('120_20250401_20251111.csv')
    j = next(j for j, row in enumerate(minute_rows)
             if row['time'] == '2025-08-18 11:30:00')
    slope, intercept = next_dif_line(minute_rows[j - 1], minute_rows[j])
    retained_peak = result['audits'][0]['policies']['strongest_eligible']['reference_dif']
    result['afternoon_recalculation'] = {
        'origin_time': minute_rows[j]['time'], 'reference_dif': retained_peak,
        'next_close_equality_boundary': (retained_peak - intercept) / slope,
        'next_actual_close': minute_rows[j + 1]['close'],
        'next_actual_dif': minute_rows[j + 1]['dif'],
        'software_label': 'PREDICTION_NO_NEW_SCREENSHOT',
    }
    assert abs(result['audits'][0]['next_actual_dif_residual']) < 1e-8
    # Daily DIF is exported with only three decimals.
    assert abs(result['audits'][1]['next_actual_dif_residual']) < 0.003
    assert frozen_before == digest(frozen_path)
    out = ROOT / 'audit_narrated_thresholds.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(out), 'audits': result['audits']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
