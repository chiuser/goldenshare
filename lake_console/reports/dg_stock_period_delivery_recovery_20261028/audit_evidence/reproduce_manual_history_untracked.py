"""Isolated manual history file/event gap is not registered in the shared queue."""
import json
import tempfile
from pathlib import Path
import dagster as dg
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs import stock_period_update as update
from orchestrator.defs.run_contracts.stock_period import VERSION
from tests.test_stock_period_combined import bootstrap, combined_source
from tests.test_stock_period_delivery_confirmation import _emit

with tempfile.TemporaryDirectory(prefix='history-', dir='/private/tmp/dg-period-independent-audit-20261028') as directory:
    base = Path(directory)
    arguments = bootstrap(base)
    state_path = arguments['staging'] / 'stock_period/daily.json'
    raw.atomic_json(state_path, {'pending_work': {}})
    instance_path = base / 'instance'
    instance_path.mkdir()
    (instance_path / 'dagster.yaml').write_text('telemetry:\n  enabled: false\n')
    with dg.DagsterInstance.local_temp(str(instance_path)) as instance:
        intent = {'version': VERSION, 'mode': 'history', 'frequencies': ['week'], 'codes': ['000001.SZ'], 'request_id': 'audit-history-one'}
        old = history.run_period(**arguments, intent=intent, transport=combined_source)
        # Actual SDK event records: original Mat present, native checks have not completed.
        _emit(instance, old, checks='none')
        def confirmation(run):
            return update.confirm_period_delivery(instance, run, root=arguments['root'], staging=arguments['staging'])
        proof = confirmation(Path(old['path']))
        target = old['files'][-1]['target']
        before = raw.file_version(target)
        requests = []
        def next_source(params):
            requests.append(params)
            payload = json.loads(combined_source(params))
            for row in payload['data']['items']:
                row[4:] = ['4.0000'] * 17
            return json.dumps(payload).encode()
        output = {'first_delivery_complete': proof['events_complete'], 'first_delivery_missing': proof['reason'], 'queued_manual_history_count': len(raw.read_json(state_path)['pending_work'])}
        second = history.run_period(**arguments, intent={**intent, 'request_id': 'audit-history-two'}, transport=next_source, confirm_delivery=confirmation)
        output['new_history_source_requests'] = len(requests)
        output['new_history_files_committed'] = len(second['files'])
        output['old_unconfirmed_target_replaced'] = raw.file_version(target) != before
        try:
            confirmation(Path(old['path']))
        except Exception as error:
            output['original_delivery_confirmation_after_new_write'] = f'{type(error).__name__}:{error}'
        print(json.dumps(output, ensure_ascii=False, indent=2))
