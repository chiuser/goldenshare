"""Audit supplied Nov13 speech against unchanged, previously saved predictions.

Author assertions, future conditional forecasts, and software observations are
distinct. No disappearance formula or correction membership is fitted here.
"""
import csv
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SOURCE = ROOT / 'sources/20251113_user_transcript.txt'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    text = SOURCE.read_text()
    lines = text.splitlines()
    specs = [
        ('daily_structure_disappeared_today', 1, 4, '今天的消失是结构消失',
         'Actual day-level daily assertion; not an explicit90-minute disappearance or timestamp'),
        ('near_trend_applicability', 5, 7, '60分钟及以上级别形成结构',
         'Contextual applicability near trend; no universal exclusion of60-minute signals'),
        ('coordination_axes', 8, 10, '指数呢就是不同指数',
         'Separate periods from indices despite speech slips; no quantitative score'),
        ('120_one_red_bar', 12, 16, '下面只有一根红脚线',
         'Actual current120-positive-histogram count; new-close high alone not enough'),
        ('120_future_eligibility', 14, 17, '需要两根红角线 需要收盘价格创新高',
         'Two red bars and new close high for this new-top-dulling context, not sufficient for every dulling event'),
        ('90_future_second', 17, 18, '二次也是 明天上午',
         'Future second90-minute event wording; does not identify preciseNov13 disappearance bar'),
        ('60_current_dulling', 18, 20, '60分钟就出钝化了',
         '60-minute dulling exists by this lecture; actual time not specified'),
        ('other_index_scope', 23, 32, '上证五菱日线也是得下周一',
         'Transcribed index identity uncertain; following120-today-dulling phrase not attributed to SSE without image/audio'),
        ('first_structure_action', 29, 31, '非得等第二次或第三次再操作',
         'Do not defer a qualifying first structure solely expecting another; no exact reduction amount here'),
        ('large_down_day_confirmation', 34, 38, '你再反应 实际上就有点有点晚了',
         'Large down day described as adjustment confirmation, not a universal prerequisite to structure defense'),
        ('additional_reduction_conditional', 40, 42, '单纯从周期之间的协调性的角度来讲 不需要再减',
         'Only improved period coordination does not warrant more reduction here; index coordination may change judgment'),
        ('correction_standard', 49, 50, '买回来的标准是什么 分钟线钝化消失',
         'Correction-standard speech; does not specify exact participating periods,AND/OR or actual fills'),
        ('disappearance_label_identity', 52, 53, '消失两个字前面是结构',
         'Read structure-vs-dulling wording in full context; not an always-nearest-historical-label matching algorithm'),
        ('future_coordination_observation', 93, 96, '不排除再继续减仓的可能性',
         'Conditional future observation, not proof an additional two-tenths trade occurred today'),
    ]
    claims = []
    for key, start, end, marker, interpretation in specs:
        assert marker in '\n'.join(lines[start-1:end]), (key, start, end)
        claims.append(dict(key=key, line_start=start, line_end_inclusive=end,
                           marker=marker, interpretation=interpretation,
                           literal_prefix_not_verified_video_time=True))

    old_screen_path = ROOT / 'november_followup_20261012.json'
    screen = json.loads(old_screen_path.read_text())
    request_path = ROOT / 'structure_withdrawal_next_source_20261012.json'
    request = json.loads(request_path.read_text())
    price_screen_path = ROOT / 'structure_withdrawal_price_context_20261012.json'
    assert request['screen_sha256'] == sha(price_screen_path)
    assert screen['candidate_sha256'] == sha(ROOT / 'active_reference_candidate.py')
    defs = json.loads((ROOT / 'structure_withdrawal_definitions_20261012.json').read_text())
    for spec in defs['inputs'].values():
        assert sha(REPO / spec['path']) == spec['sha256']
    series = {'60': read_rows('60_20250603_20261009.csv'),
              '90': read_rows('90_20250603_20260113.csv')}
    with (ROOT / 'discrimination_screen_20261012/derived_120.csv').open() as handle:
        series['120'] = [dict(time=r['time'], **{k: float(r[k]) for k in ('close', 'dif', 'hist')})
                         for r in csv.DictReader(handle)]
    variants = []
    prefix_checks = 0
    for policy in ('nearest_qualifying', 'strongest_eligible'):
        for gate in (.75, 1., 1.2):
            windows = {}
            for period, rows in series.items():
                # Never consume any input afterNov14, including diagnostics.
                rows = [r for r in rows if r['time'][:10] <= '2025-11-14']
                output = replay(rows, gate, reference_policy=policy, diagnostics=True)
                window = [r for r in output if '2025-11-13' <= r['time'][:10] <= '2025-11-14']
                for row in window:
                    prefix = [r for r in rows if r['time'] <= row['time']]
                    assert replay(prefix, gate, reference_policy=policy, diagnostics=True)[-1] == row
                    prefix_checks += 1
                windows[period] = window
                wanted = [r for r in window if r['event'] != 'NONE']
                for old_variant in screen['variants']:
                    if old_variant['gate_pct'] != gate or old_variant['reference_policy'] != policy:
                        continue
                    frozen = [r for r in old_variant['events'][period]
                              if '2025-11-13' <= r['time'][:10] <= '2025-11-14']
                    assert [{k: r[k] for k in frozen[0]} for r in wanted] == frozen
            end120 = next(r for r in windows['120'] if r['time'] == '2025-11-13 15:00:00')
            next120 = next(r for r in windows['120'] if r['time'] == '2025-11-14 11:30:00')
            assert end120['wave_count'] == 1 and end120['hist'] > 0 and end120['event'] == 'NONE'
            prior120 = end120['reference_refresh']['same_sign_last_two'][-1]
            assert end120['close'] > prior120['price'] and end120['dif'] < prior120['dif']
            assert next120['wave_count'] == 2 and next120['event'] == 'DULL'
            assert next120['close'] > prior120['price'] and next120['dif'] < prior120['dif']
            end60 = next(r for r in windows['60'] if r['time'] == '2025-11-13 15:00:00')
            assert end60['event'] == 'DULL' and end60['wave_count'] == 2
            assert all(r['event'] == 'NONE' for r in windows['90'] if r['time'][:10] == '2025-11-13')
            variants.append(dict(reference_policy=policy, gate_pct=gate, windows=windows,
                text_compatibility=dict(current60_dulling=True, current120_only_one_red_bar=True,
                    future120_conditional_prediction_compatible=True,
                    exact_minute_software_times_observed=False),
                prior120_history_count=prior120['count'],
                history_count_not_equated_with_current_two_bar_gate=True))

    sources = ROOT / 'sources'
    mcp = sorted(sources.glob('*vidiq_transcript.json'))
    user = sorted(sources.glob('*user_transcript.txt')) + [sources / '20251016_transcript.txt']
    manifest = dict(received_on='2026-10-12', date='2025-11-13',
        provider='user async-question reply', original_path=None, saved_path=str(SOURCE),
        sha256=sha(SOURCE), characters=len(text), lines=len(lines),
        capture_method='Manually save supplied full text including malformed prefixes and unrelated discussion; no original-file byte comparator',
        limitations=['No audio/video verification', 'Literal prefixes are not verified video times',
                    'No precise90-minute disappearance date/bar identified',
                    'Index identity in transcribed phrase上证五菱 is uncertain'])
    save(sources / '20251113_user_transcript_manifest.json', manifest)
    result = dict(research_date='2026-10-12', status='NEW_SOURCE_AGAINST_UNCHANGED_PREEXISTING_PREDICTIONS',
        source_sha256=sha(SOURCE), claims=claims, candidate_sha256=sha(ROOT / 'active_reference_candidate.py'),
        prior_screen_sha256=sha(old_screen_path), frozen_request_sha256=sha(request_path),
        frozen_price_screen_sha256=sha(price_screen_path), variants=variants, prefix_checks=prefix_checks,
        frozen_variant_matches=len(screen['variants']),
        frozen_withdrawal_predictions=request['primary'],
        withdrawal_scoring=dict(status='NOT_SCORABLE_FROM_SUPPLIED_TEXT',
            period='90', software_event_identity=None, software_event_time=None,
            reason='Opening disappearance is daily; later90-minute second-event forecast supplies noNov13 withdrawal bar'),
        distinctions=dict(daily_structure_disappearance='ACTUAL_AUTHOR_DAY_ASSERTION_NOT_CORRECTION',
            minute_dulling_disappearance='STATED_CORRECTION_STANDARD_NOT_ACTUAL_CORRECTION',
            correction_period_membership='UNRESOLVED', correction_join='UNRESOLVED',
            second_structure_additional_two_tenths='NOT_AUTOMATIC_ADDITION_PERIOD_COORDINATION_ALONE_INSUFFICIENT',
            final_holdings='NOT_ASSERTED', structure_withdrawal_formula='UNIDENTIFIED'),
        source_inventory=dict(mcp_files=len(mcp), user_files=len(user), total_files=len(mcp)+len(user),
            distinct_dates=len({p.name[:8] for p in mcp+user}),
            previous_user_file_count=9, previous_total=22,
            previous_doc_10_user_files_was_counting_error=True),
        next_material=dict(date='2025-11-13', period='90', type='indicator screenshot',
            purpose='Identify full disappearance wording and bar position before judging11/14/15 predictions',
            limits='A closing screenshot may locate a bar but does not itself prove intrabar first occurrence; near-zero14 histogram needs same-period software numbers'),
        software_labels_added=0,
        limitations=['Temporal forecasts are not independent observations ofNov14 software labels',
            'Two red bars plus new close high do not uniquely identify references,thresholds or software formula',
            'Prior single-positive-bar history is distinct from current-wave activation eligibility',
            'Statement about disappearance-prefix identity does not prove a nearest-label matching implementation',
            'No source-fitting,formal indicator changes,network fetches or trades'])
    save(ROOT / 'nov13_lecture_comparison_20261012.json', result)
    print(json.dumps(dict(source_lines=len(lines), source_characters=len(text), claims=len(claims),
        variant_cases=len(variants), frozen_variant_matches=len(screen['variants']), prefix_checks=prefix_checks,
        withdrawal_scoring=result['withdrawal_scoring']['status'], source_inventory=result['source_inventory']),
        ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
