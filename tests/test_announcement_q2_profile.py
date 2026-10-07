"""Explicit opt-in real read-only profile. All PG control writes are disposable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_announcement_pg_migration import pg,pg_cluster
from src.foundation.dao.announcement_archive.pg_schema import install_schema

@pytest.mark.skipif(os.environ.get('ANNOUNCEMENT_Q2_READONLY_PROFILE')!='1',reason='explicit real-source readonly profile only')
def test_real_api_cold_and_warm(pg,tmp_path):
    with pg.transaction() as conn:install_schema(conn)
    evidence=[]
    for scenario in ('default30','stock155','all155','downloaded','undownloaded','historyManifest'):
        config=tmp_path/(scenario+'.json');config.write_text(json.dumps(dict(url=pg.engine.url.render_as_string(hide_password=False),database=pg.policy.database,port=pg.policy.port,scenario=scenario)))
        result=subprocess.run([sys.executable,'-B','tests/fixtures/announcement_q2_profile_runner.py',str(config)],
            env=dict(os.environ,PYTHONPATH=str(Path.cwd())),capture_output=True,text=True,timeout=180)
        assert result.returncode==0,(scenario,result.stdout,result.stderr)
        record=json.loads(result.stdout);evidence.append(record)
        Path('reports/wealth_data_center_q2_profile_20261007.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        assert record['announcementFdPeak']<=32 and record['rssMiB']<=512 and record['sqlMaxSeconds']<=4
        if scenario!='historyManifest':assert record['getP95Seconds']<=5 and record['unitMaxSeconds']<=5
