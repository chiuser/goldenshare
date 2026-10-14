"""Compare a new chart with frozen predictions; never refit the candidate.

Uses the existing bundled Pillow runtime only to read original PNG pixels.
Historical label timestamps remain conditional geometric mappings.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = json.loads(Path('/private/tmp/xxm_july3_chart_before_20261012.json').read_text())
    manifest_path = ROOT / 'screenshot_manifest.json'
    manifest_name = str(manifest_path.relative_to(REPO))
    for name, digest in before.items():
        if name != manifest_name:
            assert sha(REPO / name) == digest, name
    manifest = json.loads(manifest_path.read_text())
    assert len(manifest) == 42
    assert hashlib.sha256((json.dumps(manifest[:41], ensure_ascii=False, indent=2) + '\n').encode()).hexdigest() == before[manifest_name]
    request_path = ROOT / 'july3_next_chart_request_20261012.json'
    request = json.loads(request_path.read_text())
    frozen_path = ROOT / 'withdrawal_next_source_july3_20261012.json'
    frozen = json.loads(frozen_path.read_text())
    assert request['frozen_predictions'] == frozen['predictions']
    assert sha(ROOT / 'active_reference_candidate.py') == frozen['candidate_sha256']
    assert sha(ROOT / 'structure_withdrawal_price_context_20261012.json') == frozen['old_screen_sha256']
    assert sha(ROOT / 'withdrawal_recensor_screen_20261012.json') == frozen['recensor_screen_sha256']
    assert sha(ROOT / 'sources/20250703_user_transcript.txt') == request['source_text_sha256']
    assert sha(ROOT / 'july3_lecture_comparison_20261012.json') == request['lecture_audit_sha256']
    image_path = ROOT / 'sources/20250703_90.png'
    source = manifest[-1]
    assert source['saved_path'] == str(image_path)
    assert sha(image_path) == source['sha256']
    assert Path(source['original_path']).read_bytes() == image_path.read_bytes()
    with Image.open(image_path) as original:
        assert original.size == (2824, 1140)
        pixels = original.convert('RGB')
    rows = read_rows('90_20250603_20260113.csv')
    visible = [r for r in rows if '2025-06-27' <= r['time'][:10] <= '2025-07-03']
    observations = [
        dict(text='结构形成', color='magenta', left_x=899, time='2025-06-27 14:00:00', kind='STRUCTURE', role='older_unexplained_marker'),
        dict(text='钝化', color='yellow', left_x=1348, time='2025-07-01 14:00:00', kind='DULL', role='recent_ordinary'),
        dict(text='结构形成', color='magenta', left_x=1576, time='2025-07-02 14:00:00', kind='STRUCTURE', role='recent_ordinary'),
        dict(text='消失', color='green', left_x=1802, time='2025-07-03 14:00:00', kind='historical_disappearance', role='frozen_discriminator'),
    ]
    centers = [(r['time'], 1882 - (len(visible) - 1 - i) * 75.2) for i, r in enumerate(visible)]
    for obs in observations:
        time, x = min(centers, key=lambda pair: abs(pair[1] - obs['left_x']))
        assert time == obs['time'], (obs, time)
        obs.update(anchor_distance_px=abs(x - obs['left_x']), confidence='mapped_not_cursor')
        for last in (1876, 1888):
            for step in (74.8, 75.6):
                for left in (obs['left_x'] - 6, obs['left_x'] + 6):
                    altered = [(r['time'], last - (len(visible) - 1 - i) * step) for i, r in enumerate(visible)]
                    assert min(altered, key=lambda pair: abs(pair[1] - left))[0] == obs['time']
    # Read line order around the mapped event centre; do not infer exact DIF
    # values or histogram bar colour from the dark/blurred histogram pixels.
    line_order = []
    for x in (1798, 1803, 1808):
        yellow = []
        white = []
        for y in range(935, 976):
            r, g, b = pixels.getpixel((x, y))
            if min(r, g) > 70 and min(r, g) - b > 15:
                yellow.append((min(r, g), y, (r, g, b)))
            if min(r, g, b) > 80 and max(r, g, b) - min(r, g, b) < 15:
                white.append((min(r, g, b), y, (r, g, b)))
        _, yellow_y, yellow_rgb = max(yellow)
        _, white_y, white_rgb = max(white)
        assert white_y > yellow_y
        line_order.append(dict(x=x, dea_yellow_y=yellow_y, dea_rgb=yellow_rgb,
                               dif_white_y=white_y, dif_rgb=white_rgb, white_below_yellow=True))
    software = dict(close=3461.15, dif=14.157, dea=14.744, hist=-1.173)
    endpoint = next(r for r in rows if r['time'] == '2025-07-03 15:00:00')
    dg = dict(close=endpoint['close'], dif=endpoint['dif'], hist=endpoint['hist'],
              dea=endpoint['dif'] - endpoint['hist'] / 2)
    delta = {k: software[k] - dg[k] for k in software}
    assert abs(delta['close']) < .005 and software['hist'] < 0 and dg['hist'] < 0
    assert all(abs(delta[k]) > .001 for k in ('dif', 'dea', 'hist'))
    variants = []
    prefix_checks = 0
    cutoff_rows = [r for r in rows if r['time'] <= endpoint['time']]
    by_input = {r['time']: r for r in rows}
    for policy in ('nearest_qualifying', 'strongest_eligible'):
        for gate in (.75, 1., 1.2):
            output = replay(cutoff_rows, gate, reference_policy=policy)
            window = [r for r in output if '2025-06-27' <= r['time'][:10] <= '2025-07-03']
            by_time = {r['time']: r for r in window}
            for row in window:
                assert replay([r for r in cutoff_rows if r['time'] <= row['time']], gate, reference_policy=policy)[-1] == row
                prefix_checks += 1
            for obs in observations:
                if obs['role'] == 'recent_ordinary':
                    assert by_time[obs['time']]['event'] == obs['kind']
            assert by_time['2025-07-02 14:00:00']['event_ref_dif'] == 19.28212366483376
            assert by_time['2025-07-02 14:00:00']['event_ref_start'] == '2025-06-24 11:00:00'
            assert by_time['2025-06-27 14:00:00']['event'] == 'NONE'
            assert by_time['2025-07-03 14:00:00']['event'] == 'NONE'
            variants.append(dict(policy=policy, gate_pct=gate, window=window,
                recent_ordinary_matches=2, older_structure_marker_unexplained=True,
                historical_withdrawal_event_missing=True))
    at14 = by_input['2025-07-03 14:00:00']
    assert at14['dif'] == frozen['numeric_at_price_first']['dif']
    assert at14['hist'] == frozen['numeric_at_price_first']['hist']
    previous = by_input['2025-07-03 11:00:00']
    formation = by_input['2025-07-02 14:00:00']
    reference_dif = 19.28212366483376
    price_peak = max(r['close'] for r in rows if '2025-06-30 15:00:00' <= r['time'] <= formation['time'])
    assert price_peak == 3458.5686 and at14['close'] > price_peak
    assert at14['dif'] < formation['dif'] < reference_dif
    result = dict(research_date='2026-10-12', source=source, dimensions=[2824, 1140],
        original_copy_byte_equal=True, candidate_sha256=frozen['candidate_sha256'],
        input_sha256=sha(ROOT / 'inputs/90_20250603_20260113.csv'),
        frozen_request_sha256=sha(request_path), frozen_prelecture_request_sha256=sha(frozen_path),
        frozen_predictions=request['frozen_predictions'], observations=observations,
        approximate_bar_centers=centers,
        mapping_conditions=['Three successive endpoint bars per trading day; terminal July3 15:00',
            'Manual text-left-edge and regular spacing convention',
            'Not a cursor timestamp, intrabar first-display observation or proof of no retrospective relocation'],
        green_identity=dict(raw_text='消失', interpretation='conditional_structure_withdrawal',
            author_explicit_marker_identity=False, reason='Recent preceding magenta structure, continued whiteDIF below yellowDEA and no oldDIF-reference break on saved inputs'),
        line_order_pixels=line_order,
        negative_histogram_evidence=dict(mapped14='DIF white visibly below DEA yellow; negative under displayed MACD relation',
            terminal15='Direct negative numeric display', exact14_software_values_known=False,
            histogram_bar_pixel_colour_claimed=False, saved_numeric_bias_used_as_bound=False),
        conditional_prediction_assessment=dict(price_only='compatible', price_and_dif='compatible_not_identifiable',
            price_and_positive_hist='contradicted_if_mapping_and_structure_identity_hold',
            price_dif_and_positive_hist='contradicted_if_mapping_and_structure_identity_hold',
            scope='Positive histogram is not necessary for this mapped withdrawal; no universal withdrawal formula or sufficient-condition proof'),
        numerical_endpoint=dict(time=endpoint['time'], software=software, dg=dg,
            software_minus_dg=delta, display_identity_residual=software['hist'] - 2 * (software['dif'] - software['dea'])),
        saved14_context=dict(row=at14, previous_dif=previous['dif'], price_peak=price_peak,
            price_margin=at14['close'] - price_peak,
            dif_rise_pct=(at14['dif'] - previous['dif']) / abs(previous['dif']) * 100,
            prior_structure_dif=formation['dif'], old_reference_dif=reference_dif),
        variants=variants, prefix_checks=prefix_checks,
        preserved_prior_files=len(before) - 1, prior_manifest_entries_preserved=41,
        tally=dict(screenshots=42, original_labels_unchanged=52, new_ordinary_mapped_anchors_separate=2,
            cumulative_conditional_historical_disappearance_observations=3,
            cumulative_minute_numeric_endpoints=25, daily_numeric_endpoints=1,
            subtitle_files=25, distinct_subtitle_dates=24),
        next_step='Request fulfilled. Separate historical structure lifecycle from active dulling and whole-defense correction in research design; retain price-only vs price+DIF until an independent differing prediction or software formula is available. No additional July3 source request.',
        limitations=['Older June27 historical structure also remains unexplained; do not claim full-chart match',
            'Six frozen candidates reproduce recent ordinary anchors but no historical withdrawal event',
            'No unique DIF gate, reference policy, withdrawal formula or correction AND/OR set identified',
            'No production code, parameter, DB/Lake, dependency, branch, commit or trade change'])
    target = ROOT / 'july3_chart_comparison_20261012.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(result=str(target), prefix_checks=prefix_checks, line_order=line_order,
        old_files_preserved=len(before) - 1, numeric_delta=delta), ensure_ascii=False))


if __name__ == '__main__':
    main()
