"""Review saved captions against frozen active-reference targets.

Captions confirm period availability and the closing state, not marker anchors.
No caption-only observations are appended to the screenshot label ledger.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audit_path=ROOT/'active_reference_audit.json'
    audit=json.loads(audit_path.read_text())
    assert sha(ROOT/'active_reference_candidate.py')==audit['candidate_sha256']
    source_path=ROOT/'sources/20251216_vidiq_transcript.json'
    source=json.loads(source_path.read_text())
    text=source['response']['transcription']
    start=text.index('比方大家再看这个90分钟')
    end=text.index('但是你不要觉得',start)
    assert '现在新的钝化' in text[start:end]
    rows=read_rows('90_20250603_20260113.csv')
    times=('2025-12-15 15:00:00','2025-12-16 11:00:00',
           '2025-12-16 14:00:00','2025-12-16 15:00:00')
    focal=[]
    for mode in ('locked','both_before','dull_before','both_after'):
        output={r['time']:r for r in replay(rows,1,reference_policy='strongest_eligible',
                                          active_policy=mode,diagnostics=True)}
        assert output[times[-1]]['state']=='DULL'
        focal.append(dict(mode=mode,rows=[output[t] for t in times]))
    assert all(sha(ROOT/name)==digest for name,digest in audit['protected_files'].items())
    result=dict(as_of=datetime.now(timezone.utc).isoformat(),
        frozen_audit_sha256=sha(audit_path),candidate_sha256=sha(ROOT/'active_reference_candidate.py'),
        source_file=str(source_path.relative_to(ROOT)),source_sha256=sha(source_path),
        source_url=source['source_url'],source_length=len(text),caption_context=text[start:end],
        availability=dict(date='2025-12-16',period='90 minutes',
                          basis='Speaker explicitly directs viewers to the 90-minute chart'),
        narrated_close='Bottom dulling present; a possible future structure is discussed',
        cannot_distinguish='All four candidates have DULL at close; the phrase new dulling does not uniquely locate cancellation and reactivation.',
        added_screenshot_labels=0,focal=focal,
        proposed_screenshot=dict(date='2025-12-16',period='90 minutes',
            need='MACD labels and final DIF/DEA/hist; preferably history since December 5',
            reason='Check whether green disappearance then new yellow dulling occur during December 16',
            prerequisite='First reconcile software OHLC/indicator values and bar timestamps with DG 90-minute bins',
            fallback='Leave locking unresolved if alignment or marker positions are unclear'),
        deferred_30_minute_target=dict(date='2026-06-05',
            video='https://www.youtube.com/watch?v=cFhQ9WaI9tE',
            availability='Unconfirmed: transcript not obtained due to vidIQ credits; no retry'),
        limitations=['Reuploaded video and ASR transcript, not directly verified audio',
                     'No new screenshot; no exact marker anchor inferred from captions',
                     'DG 90-minute timestamps are hypotheses for comparison, not verified software bar times'],
        protected_files_unchanged=True,audit_script_sha256=sha(Path(__file__)))
    (ROOT/'active_reference_caption_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(source_length=len(text),period_available=True,
                         closing_state_distinguishes=False,labels_added=0,
                         protected_files_unchanged=True),ensure_ascii=False))


if __name__=='__main__':main()
