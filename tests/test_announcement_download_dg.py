"""DG consumer integration tests: temporary Parquet/ledgers, no formal Lake or PDF site."""
from __future__ import annotations
from fixtures.announcement_pg_runtime import pg_execute, pg_many
from test_announcement_pg_migration import pg, pg_cluster

import ast
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import duckdb
import httpx
import pytest

from src.scripts import download_announcements as cli
from src.ops.runtime.announcement_archive import executor
from src.foundation.clients.announcement_archive import source as source_module
from src.foundation.clients.announcement_archive.core import (
    ANNOUNCEMENT_FIELDS, SOURCE_CONTRACT_VERSION, Blocked, Cancelled, Control,
    DownloadOptions, DownloadPolicy, identity, source_projection,
)
from src.foundation.dao.announcement_archive.ledger import Ledger
from src.foundation.clients.announcement_archive.source import DayReader, Source
from src.foundation.clients.announcement_archive.volume import SourceVolume
from test_announcement_download_cli import archive, row, run, stage_rows, latest_run, PDF


OLD_KEYS = ('15f6d1f04d9e2e65c2055e8707c8f80e3d82a2ba9a30fbb303e99c3122f3e4f6', '8d20a061867aac9a5ef8812e4b4dca32e22945c7ec4aada974c8a77d1842c306', '69cda75a7e8fe7abcbe77630018bad661198c1459150c8b5eba03399993aaef3', 'b91f18b915ad4fff44c493960c785696d0165b74920db4ace61834e2e5fc0391', '81fb76db5cfab766e414c2eed07416148ad0e318e289e36f7a622391540e2946')
OLD_KEY = OLD_KEYS[0]


def write_day(root, day, rows, columns=ANNOUNCEMENT_FIELDS, types=None):
    path=root/f'ann_date={day}'/'part-000.parquet'
    path.parent.mkdir(parents=True,exist_ok=True)
    connection=duckdb.connect(':memory:')
    try:
        connection.execute('CREATE TABLE input_rows ('+', '.join(
            f'{name} {(types or {}).get(name,"VARCHAR")}' for name in columns)+')')
        if rows:
            connection.executemany('INSERT INTO input_rows VALUES ('+','.join('?' for _ in columns)+')',
                                   [tuple(r.get(name) for name in columns) for r in rows])
        connection.execute('COPY input_rows TO ? (FORMAT PARQUET)',[str(path)])
    finally:
        connection.close()
    return path


def raw_root(archive):
    return archive[0].mount/'data_lake/raw/tushare/anns_d'


def make_source(archive, options=None, policy=None):
    options=options or archive[2];policy=policy or archive[3]
    volume=SourceVolume(raw_root(archive),policy,archive[0].inspector)
    return Source(options,policy,archive[5],volume).open()


def source_run(archive, source, handler=None):
    client=httpx.Client(transport=httpx.MockTransport(handler or (lambda _: httpx.Response(200,content=PDF))))
    try:
        return executor.execute(source.options,source.policy,archive[5],archive[0],archive[1],source,source.scope,
                           client,archive[4])
    finally:
        client.close()


def test_contract_matches_published_dg_without_runtime_import():
    path=Path(__file__).parents[1]/'lake_console/orchestrator/src/orchestrator/defs/anns_d_contract.py'
    values={}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            name=node.targets[0].id
            if name in ('ANNOUNCEMENT_FIELDS','ANNOUNCEMENT_VERSION'):
                values[name]=ast.literal_eval(node.value)
    assert ANNOUNCEMENT_FIELDS==values['ANNOUNCEMENT_FIELDS']
    assert SOURCE_CONTRACT_VERSION==values['ANNOUNCEMENT_VERSION']==1


def test_dg_date_projection_keeps_old_pdf_key_and_raw_values():
    item=row();item['url']='  https://ann.example/1.pdf  '
    key,day,artifact=source_projection(item,'2026-09-30')
    assert day=='2026-09-30' and artifact==OLD_KEY
    assert identity(['20260930','600000.SH','https://ann.example/1.pdf'])!=OLD_KEY
    assert item['ann_date']=='20260930' and item['url'].startswith('  ')
    assert key!=artifact


def test_source_preserves_null_empty_and_whitespace_records(archive):
    rows=[]
    for field in ('name','url','rec_time'):
        for value in (None,'',' '):
            item=row(title=f'{field}:{value!r}');item[field]=value;rows.append(item)
    write_day(raw_root(archive),'2026-09-30',rows)
    calls=[]
    assert source_run(archive,make_source(archive),lambda req: calls.append(req) or httpx.Response(200,content=PDF))==0
    saved=[json.loads(r[0]) for r in pg_execute(archive[1],'SELECT metadata FROM announcement_archive.source_records WHERE source_records.archive_id=:a ')]
    assert {json.dumps(r,sort_keys=True) for r in saved}=={json.dumps(r,sort_keys=True) for r in rows}
    assert len(saved)==9 and len(calls)==1
    assert latest_run(archive[1])['missing_url_count']==3


def test_day_fd_survives_atomic_replace_and_next_run_reads_new(archive,tmp_path):
    root=raw_root(archive)
    old=[row(1),row(2),row(3)]
    path=write_day(root,'2026-09-30',old)
    replacement=write_day(tmp_path/'replacement','2026-09-30',[row(4)])
    source=make_source(archive)
    read=[]
    try:
        for day in source.iter_days():
            with day:
                for batch in day:
                    read+=batch
                    if len(read)==2:
                        os.replace(replacement,path)
                        assert os.fstat(day.fd).st_nlink==0
                day.verify()
        assert read==old
    finally:
        source.close()
    next_source=make_source(archive)
    try:
        for day in next_source.iter_days():
            with day:
                assert [r for b in day for r in b]==[row(4)]
                day.verify()
    finally:
        next_source.close()


def test_two_days_reused_fd_number_never_reuses_cached_file(archive):
    root=raw_root(archive)
    write_day(root,'2026-09-29',[row(1,day=date(2026,9,29))])
    write_day(root,'2026-09-30',[row(2)])
    source=make_source(archive,replace(archive[2],start_date=date(2026,9,29)))
    rows=[];connections=[]
    try:
        for day in source.iter_days():
            with day:
                connections.append(day.connection)
                rows.extend(r for b in day for r in b)
                day.verify()
        assert [r['ann_date'] for r in rows]==['20260929','20260930']
        assert connections[0] is not connections[1]
    finally:
        source.close()


def test_empty_day_valid_but_missing_next_day_blocks_all_http(archive):
    root=raw_root(archive)
    write_day(root,'2026-09-30',[])
    assert source_run(archive,make_source(archive),lambda _: pytest.fail('empty day'))==0
    assert latest_run(archive[1])['days_completed']==1
    write_day(root,'2026-09-30',[row()])
    source=make_source(archive,replace(archive[2],end_date=date(2026,10,1)))
    assert source_run(archive,source,lambda _: pytest.fail('missing day must block entire range'))==3
    latest=latest_run(archive[1])
    assert latest['reason']=='source_day_missing' and latest['days_completed']==1 and latest['enumeration_sealed']==0
    failed=pg_execute(archive[1],'SELECT * FROM announcement_archive.run_source_days WHERE run_source_days.archive_id=:a AND run_id=:p0 AND ann_date=:p1',(latest['run_id'],'2026-10-01')).fetchone()
    assert failed['state']=='blocked'


@pytest.mark.parametrize('change', ['extra','missing','reordered','numeric','invalid_date','null_date','iso_date','partition'])
def test_bad_physical_contract_blocks_before_http(archive,change):
    item=row();columns=ANNOUNCEMENT_FIELDS;types={}
    if change=='extra':columns=(*columns,'id');item['id']='1'
    if change=='missing':columns=columns[:-1]
    if change=='reordered':columns=tuple(reversed(columns))
    if change=='numeric':types={'name':'INTEGER'};item['name']=1
    if change=='invalid_date':item['ann_date']='20260931'
    if change=='null_date':item['ann_date']=None
    if change=='iso_date':item['ann_date']='2026-09-30'
    if change=='partition':item['ann_date']='20260929'
    write_day(raw_root(archive),'2026-09-30',[item],columns,types)
    assert source_run(archive,make_source(archive),lambda _: pytest.fail('bad contract'))==3
    assert not latest_run(archive[1])['enumeration_sealed']


def test_duplicate_six_field_record_is_rejected_not_silently_deduplicated(archive):
    write_day(raw_root(archive),'2026-09-30',[row(),row(),row(2)])
    assert source_run(archive,make_source(archive),lambda _: pytest.fail('duplicate Raw'))==3
    assert latest_run(archive[1])['reason']=='source_duplicate_record'
    assert latest_run(archive[1])['records_read']==0


def test_in_place_change_blocks_before_download(archive):
    path=write_day(raw_root(archive),'2026-09-30',[row()])
    source=make_source(archive)
    try:
        for day in source.iter_days():
            with day:
                assert [r for b in day for r in b]==[row()]
                with path.open('ab') as out: out.write(b'changed-inode')
                with pytest.raises(Blocked,match='source_file_changed'):day.verify()
    finally:
        source.close()


def test_symlink_and_fifo_source_never_followed(archive,tmp_path):
    path=write_day(tmp_path/'outside','2026-09-30',[row()])
    root=raw_root(archive)/'ann_date=2026-09-30';root.mkdir(parents=True)
    target=root/'part-000.parquet';target.symlink_to(path)
    assert source_run(archive,make_source(archive),lambda _: pytest.fail('symlink'))==3
    target.unlink();os.mkfifo(target)
    assert source_run(archive,make_source(archive),lambda _: pytest.fail('fifo'))==3
    assert latest_run(archive[1])['reason']=='source_file_not_regular'


def test_no_spill_source_and_batch_boundaries(archive):
    write_day(raw_root(archive),'2026-09-30',[row(i) for i in range(501)])
    policy=replace(archive[3],batch_size=500)
    source=make_source(archive,policy=policy)
    try:
        for day in source.iter_days():
            with day:
                assert day.connection.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0]=='0 bytes'
                assert day.connection.execute("SELECT current_setting('autoinstall_known_extensions')").fetchone()[0] is False
                assert [len(b) for b in day]==[500,1]
                day.verify()
    finally:
        source.close()
    assert not list(raw_root(archive).rglob('*.tmp'))


def test_source_read_only_volume_does_not_create_anything(archive,monkeypatch):
    root=raw_root(archive);write_day(root,'2026-09-30',[])
    before=set(root.rglob('*'))
    archive[6]['WritableVolume']=False
    with monkeypatch.context() as patch:
        patch.setattr('src.foundation.clients.announcement_archive.volume.os.mkdir',lambda *a,**kw: pytest.fail('source mkdir'))
        patch.setattr('src.foundation.clients.announcement_archive.volume.os.fsync',lambda *a: pytest.fail('source write probe'))
        source=make_source(archive)
        source.close()
    assert set(root.rglob('*'))==before


def test_unsealed_and_oversized_batch_cannot_be_consumed(archive):
    ledger=archive[1];rid=ledger.begin_run(archive[2],'dg')
    with pytest.raises(Blocked,match='not_sealed'):ledger.next_task(rid)
    with pytest.raises(Blocked,match='batch_limit'):ledger.ingest(rid,'dg','2026-09-30',[row()]*501)
    with pytest.raises(Blocked,match='incomplete'):ledger.seal(rid)


@pytest.mark.parametrize('cancel',[False,True])
def test_real_query_watchdog_interrupts_and_joins_in_subprocess(cancel):
    script='''
import threading,time,duckdb
from datetime import date
from src.foundation.clients.announcement_archive.core import *
from src.foundation.clients.announcement_archive.source import Source,DayReader
p=DownloadPolicy(source_query_timeout_seconds=.1 if not CANCEL else 15)
c=Control(p,lambda _:None)
s=Source(DownloadOptions(date(2026,9,30),date(2026,9,30)),p,c)
d=DayReader(s,'2026-09-30');d.connection=s.connect()
timer=threading.Timer(.1,c.stop.set) if CANCEL else None
if timer:timer.start()
started=time.monotonic()
try:
    d._call(lambda:d.connection.execute('SELECT sum(sqrt(i)) FROM range(10000000000) t(i)'))
    raise AssertionError('query did not stop')
except (Cancelled if CANCEL else Blocked) as exc:
    assert str(exc)==('user_cancelled' if CANCEL else 'source_query_timeout')
finally:
    if timer:timer.join()
    d.close();s.close()
assert time.monotonic()-started<2
assert not any(t.name=='announcement-source-watchdog' for t in threading.enumerate())
print('joined')
'''.replace('CANCEL',repr(cancel))
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=Path(__file__).parents[1],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='joined'


def test_duplicate_across_batches_keeps_only_previous_committed_evidence(archive):
    write_day(raw_root(archive),'2026-09-30',[row(1),row(2),row(1)])
    assert source_run(archive,make_source(archive),lambda _: pytest.fail('duplicate must never download'))==3
    assert latest_run(archive[1])['records_read']==2
    assert latest_run(archive[1])['reason']=='source_duplicate_record'
    assert tuple(pg_execute(archive[1],'SELECT records_committed,state FROM announcement_archive.run_source_days WHERE run_source_days.archive_id=:a ').fetchone().values())==(2,'blocked')


def test_footer_count_mismatch_blocks_before_sealing(archive,monkeypatch):
    write_day(raw_root(archive),'2026-09-30',[row()])
    original=DayReader._metadata
    def wrong_footer(self,query,limit):
        if 'parquet_file_metadata' in query:return [(2,)]
        return original(self,query,limit)
    monkeypatch.setattr(DayReader,'_metadata',wrong_footer)
    assert source_run(archive,make_source(archive),lambda _: pytest.fail('mismatched footer'))==3
    assert latest_run(archive[1])['reason']=='source_row_count_mismatch'
    assert latest_run(archive[1])['enumeration_sealed']==0




def test_missing_duckdb_is_explicit_and_has_no_fallback(archive,tmp_path,monkeypatch):
    import builtins
    original=builtins.__import__
    def unavailable(name,*a,**kw):
        if name=='duckdb':raise ImportError('fixture missing dependency')
        if name.startswith(('sqlalchemy','tushare','dagster')):pytest.fail('fallback dependency')
        return original(name,*a,**kw)
    monkeypatch.setattr(builtins,'__import__',unavailable)
    with pytest.raises(Blocked,match='source_duckdb_required'):
        Source(archive[2],archive[3],archive[5])


def test_source_record_key_uses_every_raw_field_and_null_is_not_empty():
    base=row()
    original=source_projection(base,'2026-09-30')[0]
    keys=[]
    for name in ('ts_code','name','title','url','rec_time'):
        for value in (None,'',' '):
            key=source_projection(dict(base,**{name:value}),'2026-09-30')[0]
            assert key!=original
            keys.append(key)
    assert len(set(keys))==15
    assert source_projection(dict(base,ann_date='20260929'),'2026-09-29')[0]!=original


def test_closed_range_does_not_read_neighbor_files_and_no_stock_pool(archive):
    root=raw_root(archive)
    for day in (date(2026,9,29),date(2026,9,30),date(2026,10,1)):
        write_day(root,day.isoformat(),[row(day=day,code='155162.SH')])
    assert source_run(archive,make_source(archive))==0
    assert latest_run(archive[1])['records_read']==1
    saved=json.loads(pg_execute(archive[1],'SELECT metadata FROM announcement_archive.source_records WHERE source_records.archive_id=:a ').fetchone()[0])
    assert saved['ts_code']=='155162.SH' and saved['ann_date']=='20260930'


def test_source_can_be_another_verified_external_volume(archive,tmp_path,monkeypatch):
    other=tmp_path/'other-disk';other.mkdir()
    root=other/'data_lake/raw/tushare/anns_d';write_day(root,'2026-09-30',[])
    monkeypatch.setattr('src.foundation.clients.announcement_archive.volume.os.path.ismount',
                        lambda path:Path(path) in (other,archive[0].mount))
    info=dict(MountPoint=str(other),VolumeUUID='other-source-volume',DeviceIdentifier='disk-other',
              WritableVolume=False,Internal=False,VirtualOrPhysical='Physical')
    volume=SourceVolume(root,archive[3],lambda _:info)
    source=Source(archive[2],archive[3],archive[5],volume).open()
    assert source.volume.volume_uuid!=archive[0].volume_uuid
    assert source_run(archive,source,lambda _:pytest.fail('empty'))==0


@pytest.mark.parametrize('policy',[
    replace(DownloadPolicy(),batch_size=0),replace(DownloadPolicy(),batch_size=501),
    replace(DownloadPolicy(),source_threads=2),replace(DownloadPolicy(),source_query_timeout_seconds=float('nan')),
])
def test_invalid_source_policy_is_rejected_before_any_read(policy):
    with pytest.raises(Blocked,match='source_policy_invalid'):
        Source(DownloadOptions(date(2026,9,30),date(2026,9,30)),policy,Control(policy,lambda _:None))


def test_low_source_memory_fails_without_spill(archive):
    write_day(raw_root(archive),'2026-09-30',[row()])
    source=make_source(archive,policy=replace(archive[3],source_memory_limit='64KiB'))
    assert source_run(archive,source,lambda _:pytest.fail('out-of-memory'))==3
    assert latest_run(archive[1])['reason']=='source_read_failed'
    assert not list(raw_root(archive).rglob('*.tmp'))
