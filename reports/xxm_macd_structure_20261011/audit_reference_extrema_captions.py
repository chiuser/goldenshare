"""Compare frozen extrema predictions with newly saved July 22 captions.

Uses saved data only; simulated candles are not new observed market labels.
Run after the extrema audit has been frozen, without regenerating that audit.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from audit_narrated_thresholds import next_dif_line
from reference_extrema_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audit_path = ROOT/'reference_extrema_audit.json'
    audit = json.loads(audit_path.read_text())
    frozen = audit['frozen_range_probe']
    assert sha(ROOT/'reference_extrema_candidate.py') == audit['candidate_sha256']
    rows = read_rows('120_20250401_20251111.csv')
    i = next(i for i, row in enumerate(rows) if row['time']=='2025-07-22 15:00:00')
    slope, intercept = next_dif_line(rows[i-1], rows[i])
    assert frozen['previous_dif'] == rows[i]['dif']
    source_path = ROOT/'sources/20250722_vidiq_transcript.json'
    caption = json.loads(source_path.read_text())
    text = caption['response']['transcription']
    start, end = text.index('开120分钟'), text.index('所以只要明天11点')
    comparisons = []
    for mode in ('whole', 'last_interior', 'last_boundary'):
        for price in (3578, rows[i]['close']):
            dif = slope*price + intercept
            current_dea = rows[i]['dif']-rows[i]['hist']/2
            next_dea = .2*dif + .8*current_dea
            simulated = dict(time=rows[i+1]['time'], close=price, dif=dif,
                             hist=2*(dif-next_dea))
            output = replay(rows[:i+1]+[simulated], 1, reference_policy='strongest_eligible',
                            historical_extrema=mode, reference_fields=('dif',), diagnostics=True)
            origin = output[-2]['historical_extrema']['active_reference']
            assert origin
            threshold = (origin['dif']-intercept)/slope
            boundary_key = ('whole' if mode=='whole' else 'local')+'_next_close_equality_boundary'
            assert abs(threshold-frozen[boundary_key]) < 1e-8
            expected = 'DULL' if price==3578 else 'NONE'
            comparisons.append(dict(mode=mode, simulated_close=price, simulated_dif=dif,
                simulated_hist=simulated['hist'], reference_dif=origin['dif'],
                next_close_equality_boundary=threshold, event=output[-1]['event'],
                state=output[-1]['state'], narrated_expected_state=expected,
                matches_caption=output[-1]['state']==expected))
    assert all(sha(ROOT/name)==digest for name, digest in audit['protected_files'].items())
    result = dict(as_of=datetime.now(timezone.utc).isoformat(),
        scope='New numerical caption evidence, not a new screenshot label',
        frozen_audit_sha256=sha(audit_path), candidate_sha256=sha(ROOT/'reference_extrema_candidate.py'),
        input_sha256=sha(ROOT/'inputs/120_20250401_20251111.csv'),
        source_file=str(source_path.relative_to(ROOT)), source_sha256=sha(source_path),
        source_url=caption['source_url'], caption_context=text[start:end],
        caption_claim=dict(frequency='120', simulated_3578='still DULL',
                           approximate_cancellation_boundary='3578 to 3579',
                           opening_flat='CANCEL anticipated'),
        frozen_probe=frozen, comparisons=comparisons, labels_added=0,
        protected_files_unchanged=True,
        limitations=['Reupload and ASR captions; not direct audio verification',
            'Narrated simulated intrabar condition, not a completed new actual bar',
            'DG and software numeric/initialization semantics not fully reconciled',
            'Only these explicit local-pivot variants are contradicted, not all pivot methods',
            'Do not promote the 90-minute observation to an exact aligned event label'],
        audit_script_sha256=sha(Path(__file__)))
    (ROOT/'reference_extrema_caption_review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(source_length=len(text), comparisons=comparisons,
                         protected_files_unchanged=True), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
