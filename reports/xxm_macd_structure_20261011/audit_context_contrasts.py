"""Bounded retrospective source contrasts, not an execution/decision engine.

Manual interpretations stay in definitions. Checks validate locators, immutable
inputs and causal replay; they do not validate the author's empirical forecasts.
"""
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
DEFS = ROOT / 'context_contrast_definitions_20261012.json'
KEYS = ('event', 'state', 'event_direction', 'event_route', 'event_ref_start')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_of(path):
    if path.suffix == '.json':
        return json.loads(path.read_text())['response']['transcription']
    return path.read_text()


def main():
    definitions = json.loads(DEFS.read_text())
    inventory = []
    files = sorted((ROOT / 'sources').glob('*_vidiq_transcript.json'))
    files += sorted((ROOT / 'sources').glob('*_user_transcript.txt'))
    files += [ROOT / 'sources/20251016_transcript.txt']
    for path in files:
        inventory.append(dict(file=path.name, date=path.name[:8], sha256=sha(path),
                              characters=len(text_of(path))))
    assert len(inventory) == 21
    assert len({r['date'] for r in inventory}) == 20
    cases, anchor_count = [], 0
    for case in definitions['cases']:
        path = ROOT / 'sources' / case['file']
        text = text_of(path)
        evidence = []
        for spec in case['anchors']:
            key, marker, offset, length = spec[:4]
            if offset is not None:
                assert text[offset:offset+len(marker)] == marker, (case['id'], key)
                start, end = max(0, offset-100), min(len(text), offset+length)
                locator = dict(char_start=start, char_end_exclusive=end,
                               marker_char_offset=offset, zero_based=True,
                               not_video_timestamp=True)
                excerpt = text[start:end]
            else:
                start, end = spec[4:]
                excerpt = '\n'.join(text.splitlines()[start-1:end])
                assert marker in excerpt, (case['id'], key)
                locator = dict(line_start=start, line_end_inclusive=end,
                               malformed_prefixes_preserved=True,
                               not_verified_video_timestamp=True)
            evidence.append(dict(key=key, marker=marker, locator=locator,
                                 excerpt=excerpt))
            anchor_count += 1
        cases.append({**{k:v for k,v in case.items() if k != 'anchors'},
                      'sha256':sha(path), 'evidence':evidence})
    variants, checks = [], 0
    numeric = definitions['numeric_scope']
    for gate in numeric['gates_pct']:
        for policy in numeric['policies']:
            results = {}
            for period, name in numeric['period_inputs'].items():
                rows = [r for r in read_rows(name) if r['time'][:10] <= numeric['dates'][-1]]
                output = replay(rows, gate, reference_policy=policy)
                selected = [i for i,r in enumerate(rows) if r['time'][:10] in numeric['dates']]
                for i in selected:
                    partial = replay(rows[:i+1], gate, reference_policy=policy)[-1]
                    assert all(partial[k] == output[i][k] for k in KEYS)
                    checks += 1
                results[period] = [output[i] for i in selected]
                assert not any(r['event'] == 'STRUCTURE' for r in results[period])
            variants.append(dict(gate_pct=gate, policy=policy, results=results))
    # Compare event/state paths, not possibly different selected references.
    paths = [{p:[{k:r[k] for k in ('time', *KEYS[:4])} for r in rows]
              for p,rows in v['results'].items()} for v in variants]
    assert all(p == paths[0] for p in paths)
    output = dict(research_date=definitions['research_date'],
        status='RETROSPECTIVE_CONTEXT_ANNOTATION_NOT_SOFTWARE_VALIDATION_OR_BLIND_TEST',
        definitions_sha256=sha(DEFS), candidate_sha256=sha(ROOT/'active_reference_candidate.py'),
        input_sha256={p:sha(ROOT/'inputs'/n) for p,n in numeric['period_inputs'].items()},
        source_inventory=inventory, inventory_files=len(inventory), distinct_dates=20,
        close_read_case_dates=len({c['date'] for c in cases}), located_anchors=anchor_count,
        cases=cases, hypotheses=definitions['hypotheses'], numeric_scope=numeric,
        variants=variants, prefix_checks=checks, all_event_state_paths_equal=True,
        january_formed_structure_not_observed=True, software_labels_added=0,
        candidate_events_not_author_software_truth=True,
        verification_limits=['Locator checks validate source presence, not semantic interpretation',
                             'No measured distance/size/coordination cutoff or trade-performance test',
                             'No full same-instrument observed conflict pair or expiry pair',
                             'No source fetching, new parameter/config or decision implementation'])
    (ROOT/'context_contrasts_20261012.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:output[k] for k in ('inventory_files','distinct_dates','close_read_case_dates','located_anchors','prefix_checks','all_event_state_paths_equal','software_labels_added')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
