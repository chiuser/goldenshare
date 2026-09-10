"""Read saved minute evidence; independently reconstruct first triggers and hashes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.research.index_market.chan.m0_data import REPO, digest


def audit(report):
    report = report.resolve(strict=True)
    if not report.is_relative_to(REPO/'reports'):
        raise ValueError('report outside research results')
    manifest = json.loads((report/'manifest.json').read_text())
    for name,sha in manifest['artifacts_sha256'].items():
        path = (report/name).resolve(strict=True)
        if not path.is_relative_to(report) or digest(path.read_bytes())!=sha:
            raise ValueError(f'artifact changed: {name}')
    results = []
    for code in manifest['spec']['codes']:
        for freq in manifest['spec']['frequencies']:
            folder = report/f'{code}_{freq}'
            states,seen,rebuilt = {},set(),[]
            with (folder/'changes.jsonl').open() as handle:
                last_time = ''
                for line in handle:
                    item = json.loads(line)
                    key,ts,p = item['candidate_id'],item['time'],item['after']
                    if ts<last_time or states.get(key)!=item['before']:
                        raise ValueError('change order or before-state mismatch')
                    last_time = ts
                    if p is None:
                        del states[key]
                        continue
                    states[key] = p
                    if not p['sure']:
                        continue
                    prefix = 'B' if p['buy'] else 'S'
                    labels = p['types']
                    for suffix in ('1','2','3'):
                        match = (suffix in labels if suffix!='3' else '3a' in labels or '3b' in labels)
                        event_id = key+'|'+prefix+suffix
                        if not match or event_id in seen:
                            continue
                        seen.add(event_id)
                        rebuilt.append((event_id,ts,item['index'],p['anchor_index'],p['anchor_time']))
            events = json.loads((folder/'events.json').read_text())
            saved = [(e['event_id'],e['signal_time'],e['signal_index'],e['anchor_index'],e['anchor_time']) for e in events]
            if saved!=rebuilt:
                raise ValueError(f'first event reconstruction mismatch {code}/{freq}')
            results.append(dict(code=code,frequency=freq,events=len(events),reconstructed=True))
    return dict(artifact_hashes=len(manifest['artifacts_sha256']),cells=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.report),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
