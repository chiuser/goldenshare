"""Isolated counter evidence for the old-data read before target ownership rejection."""
import json
import os
import tempfile
from pathlib import Path
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_combined import bootstrap, combined_intent, combined_source

with tempfile.TemporaryDirectory(prefix='guard-', dir='/private/tmp/dg-period-independent-audit-20261028') as directory:
    arguments = bootstrap(Path(directory))
    target = raw.target_path(arguments['root'], 'week', '2026-10-02')
    stamp = target.stat()
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
    stages = []
    original = raw.execute
    def tracked(*args, **kwargs):
        stages.append(kwargs.get('stage'))
        return original(*args, **kwargs)
    raw.execute = tracked
    output = {}
    try:
        history.run_period(**arguments, intent=combined_intent('audit-guard-after-old-read'), transport=combined_source)
    except Exception as error:
        output['error'] = f'{type(error).__name__}:{error}'
    finally:
        raw.execute = original
    output['completed_sql_stages_before_rejection'] = stages
    output['old_data_location_scan_happened'] = 'locate_old_keys' in stages
    output['old_data_copy_happened'] = 'read_affected_once' in stages
    output['partition_copy_happened'] = 'partition_copy' in stages
    print(json.dumps(output, ensure_ascii=False, indent=2))
