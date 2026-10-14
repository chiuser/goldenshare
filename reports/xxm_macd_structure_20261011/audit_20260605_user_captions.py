"""Compare user captions and received images with frozen research candidates.

This is retrospective source review, not a blind test or software formula.
No supplied caption is promoted to an intraday screenshot event label.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
MODES = ('locked', 'both_before', 'dull_before', 'both_after')
GATES = (0.75, 1, 1.2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def excerpt(lines, start, end):
    first = lines.index(start)
    last = lines.index(end, first)
    return dict(start_line=first + 1, end_line=last + 1,
                text='\n'.join(lines[first:last + 1]))


def main():
    before = json.loads(Path('/private/tmp/xxm_20261011_jun5_receipt_before.json').read_text())
    protected = {name: digest for name, digest in before['files'].items()
                 if name != 'screenshot_manifest.json'}
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    manifest = json.loads((ROOT / 'screenshot_manifest.json').read_text())
    assert manifest[:32] == before['manifest'] and len(manifest) == 35
    for item in manifest[-3:]:
        assert sha(Path(item['saved_path'])) == item['sha256']
    frozen = json.loads((ROOT / 'active_reference_audit.json').read_text())
    assert sha(ROOT / 'active_reference_candidate.py') == frozen['candidate_sha256']

    source = ROOT / 'sources/20260605_user_transcript.txt'
    lines = source.read_text().splitlines()
    assert lines[1] == '今天是2026年的6月5号星期五'
    contexts = {
        '120': excerpt(lines, '好我们再看120分钟', '不看不用看 90分钟'),
        '90': excerpt(lines, '序列第六', '所以要观察'),
        '60': excerpt(lines, '60分钟逻辑一样', '为准'),
        'acceleration': excerpt(lines, '假如说', '筑底呀对吧'),
        'period_selection': excerpt(lines, '我们不看周线啊', '其实我们就在做一件事情嘛'),
    }
    # The first "假如说" belongs to the large-down-candle scenario in this text.
    assert '60分钟90分钟动画可能大概率都消失了' in contexts['acceleration']['text']
    assert '30分钟' not in source.read_text()

    selected_times = {
        '60_20250603_20261009.csv': [
            '2025-12-16 10:30:00', '2025-12-16 11:30:00',
            '2025-12-16 14:00:00', '2025-12-16 15:00:00',
            '2026-06-05 10:30:00', '2026-06-05 11:30:00',
            '2026-06-05 14:00:00', '2026-06-05 15:00:00',
            '2026-06-08 10:30:00', '2026-06-08 11:30:00'],
        '30_20250603_20261009.csv': [
            '2026-06-05 14:30:00', '2026-06-05 15:00:00'],
    }
    comparisons, prefix_checks = [], 0
    for name, times in selected_times.items():
        rows = read_rows(name)
        for gate in GATES:
            for mode in MODES:
                kwargs = dict(reference_policy='strongest_eligible',
                              active_policy=mode, diagnostics=True)
                output = replay(rows, gate, **kwargs)
                by_time = {row['time']: row for row in output}
                for time in times:
                    i = next(i for i, row in enumerate(rows) if row['time'] == time)
                    assert replay(rows[:i + 1], gate, **kwargs)[-1] == by_time[time]
                    prefix_checks += 1
                if name.startswith('60_'):
                    assert by_time['2026-06-05 15:00:00']['wave_count'] == 1
                    assert by_time['2026-06-05 15:00:00']['state'] == 'NONE'
                    assert by_time['2026-06-08 10:30:00']['event'] == 'DULL'
                    assert by_time['2026-06-08 11:30:00']['event'] == 'CANCEL'
                    assert by_time['2025-12-16 15:00:00']['state'] == 'DULL'
                else:
                    event = 'CANCEL' if mode in ('locked', 'both_after') else 'NONE'
                    assert by_time['2026-06-05 14:30:00']['event'] == event
                    event = 'DULL' if mode in ('locked', 'both_after') else 'NONE'
                    assert by_time['2026-06-05 15:00:00']['event'] == event
                comparisons.append(dict(input=name, gate=gate, mode=mode,
                                        rows=[by_time[time] for time in times]))

    software = {
        '120': dict(close=3824.81, dif=-15.359, dea=-9.039, hist=-12.639,
                    visible='Recent yellow bottom dulling; exact triggering bar unscored'),
        'daily': dict(close=3824.81, dif=-16.631, dea=-11.916, hist=-9.430,
                      visible='No new dulling/structure text seen at the right edge'),
        '60': dict(close=3824.81, dif=-16.223, dea=-9.596, hist=-13.253,
                   visible='Recent yellow bottom dulling; exact triggering bar unscored'),
    }
    dg = next(x for x in comparisons if x['input'].startswith('60_')
              and x['gate'] == 1 and x['mode'] == 'locked')['rows'][3]
    values = {key: dg[key] for key in ('close', 'dif', 'hist')}
    values['dea'] = dg['dif'] - dg['hist'] / 2
    differences = {key: software['60'][key] - values[key] for key in values}
    assert any(abs(differences[key]) > 0.001 for key in ('dif', 'dea', 'hist'))
    all_csvs = []
    for path in sorted((ROOT / 'inputs').glob('*.csv')):
        rows = read_rows(path.name)
        all_csvs.append(dict(file=path.name, first=rows[0]['time'], last=rows[-1]['time']))
    result = dict(
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        basis='User transcript and screenshots; frozen candidate parameters unchanged',
        candidate_sha256=sha(ROOT / 'active_reference_candidate.py'),
        frozen_audit_sha256=sha(ROOT / 'active_reference_audit.json'),
        source_file=str(source.relative_to(ROOT)), source_sha256=sha(source),
        source_chars=len(source.read_text()), source_contexts=contexts,
        transcript_findings={
            '30': 'Not discussed; frozen 30-minute switching target remains unobserved; stop requesting this date/period',
            '120': 'Speaker says continuous negative histogram bars and no current or short-term structure; no June 5 replay input',
            '90': 'Speaker explicitly says no dulling and one green bar; possible next-Monday activation, not a confirmed June 5 event; no June 5 replay input',
            '60': 'Mixed present/future ASR wording; Monday prospective dulling and earlier disappearances are discussed. Do not locate the two past disappearances or assert a June 5 event',
            'risk': 'Large future falls may cancel dulling; not every dulling forms a structure',
            'selection': 'Period attention reflects this lesson and trading method, not universal invalidity of small-period indicators',
        },
        screenshots=dict(date='2025-12-16', software=software, count=35,
                         old_entries_preserved=32, archived=manifest[-3:]),
        numeric_check_60=dict(dg=values, software_minus_dg=differences,
                             identical_at_3_decimals=False,
                             limitation='Closes agree at 2 decimals; indicators need calculation/initialization reconciliation. Not proof of software bar alignment'),
        dec16_missing_inputs=['daily', '120'], input_coverage=all_csvs,
        comparisons=comparisons, causal_prefix_checks=prefix_checks,
        june8='Retrospective check only; actual next Monday is not a blind outcome or software label',
        locking_conclusion='Unresolved: no 30-minute observation; December 16 60/daily/120 images cannot replace the 90-minute target',
        added_screenshot_event_labels=0, conditional_event_labels=50,
        subtitle_counts=dict(mcp=13, user_only=2, user_only_dates=['2025-10-16', '2026-06-05'],
                             unique_dates=14, note='October 16 exists in both user and MCP sources'),
        protected_files=protected, protected_files_unchanged=True,
        manifest_before_sha256=before['files']['screenshot_manifest.json'],
        manifest_after_sha256=sha(ROOT / 'screenshot_manifest.json'),
        script_sha256=sha(Path(__file__)),
        next_step='Reconcile December 16 90-minute bins/indicator values before scoring its cancellation history; no more captions requested now',
    )
    (ROOT / 'caption_20260605_user_review.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(source_chars=result['source_chars'], screenshots=35,
                          prefix_checks=prefix_checks, old_files_unchanged=len(protected),
                          labels_added=0, locking='unresolved'), ensure_ascii=False))


if __name__ == '__main__':
    main()
