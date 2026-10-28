"""Isolated current-coordinator audit: no formal resources and no code edits."""
import json
import tempfile
from pathlib import Path
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import execution_id
from tests.test_stock_period_combined import bootstrap, combined_intent, combined_source

with tempfile.TemporaryDirectory(prefix='fixture-', dir='/private/tmp/dg-period-independent-audit-20261028') as directory:
    arguments = bootstrap(Path(directory))
    intent = combined_intent('audit-after-replace-before-cp')
    run = arguments['staging'] / 'stock_period/runs' / execution_id(intent['request_id'])
    real_atomic = raw.atomic_json
    interrupted = []
    def fail_committed(path, value):
        if 'committed' in Path(path).parts:
            interrupted.append({'checkpoint': str(path), 'candidate': value['candidate'], 'target': value['target'], 'version': value['version']})
            raise OSError('audit_interrupt_after_replace_before_committed_checkpoint')
        return real_atomic(path, value)
    raw.atomic_json = fail_committed
    output = {}
    try:
        history.run_period(**arguments, intent=intent, transport=combined_source)
    except Exception as error:
        output['first_error'] = f'{type(error).__name__}:{error}'
    finally:
        raw.atomic_json = real_atomic
    first = interrupted[0]
    output['checkpoint_missing'] = not Path(first['checkpoint']).exists()
    output['candidate_missing_after_replace'] = not Path(first['candidate']).exists()
    before = raw.file_version(first['target'])
    output['target_matches_promoted_version'] = before == first['version']
    def no_source(_):
        raise AssertionError('resume must not download')
    try:
        history.run_period(**arguments, intent=intent, transport=no_source)
    except Exception as error:
        output['coordinator_resume_error'] = f'{type(error).__name__}:{error}'
    output['target_unchanged_after_failed_resume'] = raw.file_version(first['target']) == before
    candidates = raw.read_json(run / 'week.candidates.json')
    candidate = next(item for item in candidates if item['target'] == first['target'])
    recovered = raw.publish(candidate, checkpoint=Path(first['checkpoint']))
    output['original_publish_recovered_checkpoint_without_rewrite'] = Path(first['checkpoint']).exists() and recovered['version'] == before and raw.file_version(first['target']) == before
    output['manifest_phase'] = raw.read_json(run / 'manifest.json')['phase']
    print(json.dumps(output, ensure_ascii=False, indent=2))
