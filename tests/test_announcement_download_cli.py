from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.scripts import download_announcements as cli
from src.scripts.announcement_download.core import (
    Blocked, Cancelled, Control, DownloadOptions, DownloadPolicy, FileFailed,
)
from src.scripts.announcement_download.files import Files, title_name, valid_url
from src.scripts.announcement_download.http import Limiter, retry_seconds
from src.scripts.announcement_download.ledger import Ledger
from src.scripts.announcement_download.source import Source, configured_database
from src.scripts.announcement_download.volume import Volume, external_volume


PDF = b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


class Clock:
    def __init__(self):
        self.now = 1_700_000_000.0
        self.waits = []

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class FakeSource:
    def __init__(self, rows, options, size=500):
        self.rows, self.options, self.size = rows, options, size
        self.calls = []
        self.closed = False

    def upper_id(self):
        return max((r['id'] for r in self.rows), default=0)

    def batch(self, after, upper):
        self.calls.append(after)
        return [r for r in self.rows if after < r['id'] <= upper and
                self.options.start_date <= r['ann_date'] <= self.options.end_date][:self.size]

    def has_artifact(self, task):
        return any(str(r['ann_date']) == task['ann_date'] and r['ts_code'] == task['ts_code']
                   and r['url'] == task['url'] for r in self.rows)

    def close(self):
        self.closed = True


def row(n=1, title='董事会决议公告', url=None, day=date(2026, 9, 30), code='600000.SH'):
    return dict(id=n, row_key_hash=f'row-{n}', ann_date=day, ts_code=code, title=title,
                url=url or f'https://ann.example/{n}.pdf', rec_time='2026-09-30T08:00:00+08:00')


@pytest.fixture
def archive(tmp_path, monkeypatch):
    mount = tmp_path / 'disk'
    mount.mkdir()
    output = mount / 'announcements'
    info = dict(MountPoint=str(mount), VolumeUUID='test-external-volume', DeviceIdentifier='disk7s1',
                WritableVolume=True, Internal=False, FilesystemType='apfs',
                APFSPhysicalStores=[{'APFSPhysicalStore': 'disk6s2'}])
    physical = dict(Internal=False, VirtualOrPhysical='Physical')
    def inspect(target):
        return physical if target == 'disk6s2' else info
    monkeypatch.setattr('src.scripts.announcement_download.volume.sys.platform', 'darwin')
    monkeypatch.setattr('src.scripts.announcement_download.volume.os.path.ismount', lambda p: Path(p) == mount)
    policy = replace(DownloadPolicy(), max_file_size=1024, reserve_bytes=0, batch_size=2)
    volume = Volume(output, policy, inspect).open()
    ledger = Ledger(tmp_path / 'local-state/downloads.sqlite', volume.volume_uuid, volume.relative_root)
    options = DownloadOptions(date(2026, 9, 30), date(2026, 9, 30), 5, output)
    clock = Clock()
    output_log = []
    control = Control(policy, lambda s: output_log.append(json.loads(s)))
    control.wait = clock.wait
    yield volume, ledger, options, policy, clock, control, info, output_log
    ledger.close()
    volume.close()


def run(archive, rows, handler=None):
    volume, ledger, options, policy, clock, control, *_ = archive
    client = httpx.Client(transport=httpx.MockTransport(handler or (lambda _: httpx.Response(200, content=PDF))))
    source = FakeSource(rows, options, policy.batch_size)
    code = cli.execute(options, policy, control, volume, ledger, source, 'prod/test/anns_d',
                       client=client, clock=clock)
    return code, source


def latest_run(ledger):
    return ledger.conn.execute('SELECT * FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', '-inf'])
def test_invalid_interval_rejected_before_disk(value):
    with pytest.raises(SystemExit) as exc:
        cli.parse_options(['--start-date', '2026-09-30', '--end-date', '2026-09-30', '--interval-seconds', value])
    assert exc.value.code == 2


@pytest.mark.parametrize('start,end', [('20260930', '2026-09-30'), ('2026-02-30', '2026-09-30'),
                                     ('2026-10-01', '2026-09-30')])
def test_invalid_dates(start, end):
    with pytest.raises(SystemExit):
        cli.parse_options(['--start-date', start, '--end-date', end])


def test_default_path_and_debug_zero():
    options = cli.parse_options(['--start-date', '2026-09-30', '--end-date', '2026-09-30', '--interval-seconds', '0'])
    assert options.output_root == Path('/Volumes/datasource/announcements')
    assert options.interval_seconds == 0


def test_startup_gate_precedes_configuration_and_state(monkeypatch):
    touched = []
    def gate(self):
        touched.append('gate')
        raise Blocked('external_mount_required')
    monkeypatch.setattr(Volume, 'open', gate)
    monkeypatch.setattr(cli, 'configured_database', lambda: pytest.fail('DB configuration touched before gate'))
    monkeypatch.setattr(cli, 'Ledger', lambda *a: pytest.fail('ledger touched before gate'))
    assert cli.main(['--start-date', '2026-09-30', '--end-date', '2026-09-30']) == 2
    assert touched == ['gate']


def test_no_default_database_and_existing_settings_precedence(tmp_path, monkeypatch):
    from src.foundation.config.settings import get_settings
    env = tmp_path / '.env'
    monkeypatch.setenv('GOLDENSHARE_ENV_FILE', str(env))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(Blocked, match='explicit_DATABASE_URL'):
            configured_database()
        env.write_text('DATABASE_URL=postgresql+psycopg://file_user:file_secret@file-host/prod\n')
        monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://env_user:env_secret@env-host/dev')
        url, scope = configured_database()
        assert 'file-host' in url
        assert scope == 'file-host:5432/prod/raw_tushare.anns_d'
        assert 'secret' not in scope and 'user' not in scope
        assert 'env-host' in os.environ['DATABASE_URL']
    finally:
        get_settings.cache_clear()


def test_source_readonly_first_bound_range_and_batch(monkeypatch):
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value = [row()]
    monkeypatch.setattr('src.scripts.announcement_download.source.create_engine', lambda *a, **kw: engine)
    options = DownloadOptions(date(2026, 9, 1), date(2026, 9, 30))
    source = Source('not-connected', options, DownloadPolicy())
    assert source.batch(4, 20)[0]['id'] == 1
    calls = connection.execute.call_args_list
    assert str(calls[0].args[0]) == 'SET TRANSACTION READ ONLY'
    assert 'statement_timeout' in str(calls[1].args[0])
    sql, params = calls[2].args
    assert 'ann_date >= :start_date AND ann_date <= :end_date' in str(sql)
    assert 'raw_payload' not in str(sql) and 'SELECT *' not in str(sql)
    assert params == dict(start_date=options.start_date, end_date=options.end_date, after_id=4, upper_id=20, batch_size=500)
    assert connection.begin.return_value.__exit__.called
    source.close()
    engine.dispose.assert_called_once()


def test_closed_date_range_and_empty_range(archive):
    rows = [row(1, day=date(2026, 9, 29)), row(2), row(3, day=date(2026, 10, 1))]
    requests = []
    code, source = run(archive, rows, lambda req: requests.append(str(req.url)) or httpx.Response(200, content=PDF))
    assert code == 0 and source.closed and len(requests) == 1
    assert latest_run(archive[1])['records_read'] == 1
    assert run(archive, [rows[0], rows[2]])[0] == 0
    assert archive[1].stats(latest_run(archive[1])['run_id'])['total'] == 0


def test_resume_deduplicates_url_and_discovers_new_records(archive):
    requests = []
    handler = lambda req: requests.append(str(req.url)) or httpx.Response(200, content=PDF)
    rows = [row(1), row(2, url='https://ann.example/1.pdf', title='同文件的新标题')]
    assert run(archive, rows, handler)[0] == 0
    assert len(requests) == 1
    assert archive[1].conn.execute('SELECT count(*) FROM source_records').fetchone()[0] == 2
    assert run(archive, rows + [row(3)], handler)[0] == 0
    assert len(requests) == 2
    stats = archive[1].stats(latest_run(archive[1])['run_id'])
    assert stats['total'] == 2 and stats['skipped'] == 1 and stats['succeeded'] == 1
    assert run(archive, rows + [row(3)], handler)[0] == 0
    assert len(requests) == 2


def test_collision_and_unknown_existing_file_preserved(archive):
    output = archive[2].output_root / '2026-09-30/600000.SH'
    output.mkdir(parents=True)
    unknown = output / '董事会决议公告.pdf'
    unknown.write_bytes(b'keep me')
    assert run(archive, [row(1), row(2)])[0] == 0
    assert unknown.read_bytes() == b'keep me'
    files = list(output.glob('*.pdf'))
    assert len(files) == 3
    assert len({p.name.casefold() for p in files}) == 3
    assert sum(p.read_bytes() == PDF for p in files) == 2


def test_corrupt_success_is_preserved_and_redownloaded(archive):
    assert run(archive, [row()])[0] == 0
    ledger = archive[1]
    old = ledger.conn.execute('SELECT relative_path FROM artifacts').fetchone()[0]
    path = archive[2].output_root / old
    path.write_bytes(b'corrupt')
    requests = []
    assert run(archive, [row()], lambda req: requests.append(req) or httpx.Response(200, content=PDF))[0] == 0
    assert len(requests) == 1 and path.read_bytes() == b'corrupt'
    new = ledger.conn.execute('SELECT relative_path FROM artifacts').fetchone()[0]
    assert new != old and (archive[2].output_root / new).read_bytes() == PDF


def test_rename_before_success_ledger_failure_recovers_without_request(archive, monkeypatch):
    ledger = archive[1]
    original = ledger.state
    def fail(key, state, error=None):
        if state == 'succeeded':
            raise sqlite3.OperationalError('injected local disk failure')
        return original(key, state, error)
    with monkeypatch.context() as patch:
        patch.setattr(ledger, 'state', fail)
        assert run(archive, [row()])[0] == 3
    artifact = ledger.conn.execute('SELECT * FROM artifacts').fetchone()
    assert artifact['state'] == 'prepared'
    assert (archive[2].output_root / artifact['relative_path']).read_bytes() == PDF
    assert run(archive, [row()], lambda req: pytest.fail('recovered final should not request HTTP'))[0] == 0
    assert ledger.artifact(artifact['artifact_key'])['state'] == 'succeeded'


def test_prepared_part_promotes_without_request(archive):
    ledger, options = archive[1], archive[2]
    run_id = ledger.begin_run(options, 'prod/test/anns_d')
    ledger.ingest(run_id, 'prod/test/anns_d', [row()])
    files = Files(archive[0], ledger, archive[3], archive[5])
    task = files.allocate(ledger.next_task(run_id))
    import hashlib
    path = options.output_root / task['relative_path']
    path.parent.mkdir(parents=True)
    (path.parent / files.part_name(task)).write_bytes(PDF)
    ledger.prepared(task['artifact_key'], len(PDF), hashlib.sha256(PDF).hexdigest())
    assert run(archive, [row()], lambda req: pytest.fail('prepared part should not request HTTP'))[0] == 0
    assert path.read_bytes() == PDF
    assert ledger.conn.execute('SELECT phase,reason FROM runs WHERE run_id=?', (run_id,)).fetchone()['reason'] == 'process_exit_recovered'


def test_cancel_mid_second_file_then_resume_only_unfinished(archive):
    control = archive[5]
    requests = []
    class InterruptStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'%PDF-1.7\n'
            control.stop.set()
            yield b'partial\n'
    def handler(req):
        requests.append(str(req.url))
        return httpx.Response(200, content=PDF) if len(requests) == 1 else httpx.Response(200, stream=InterruptStream())
    assert run(archive, [row(1), row(2)], handler)[0] == 130
    assert latest_run(archive[1])['phase'] == 'cancelled'
    assert len(list(archive[2].output_root.rglob('*.pdf'))) == 1
    control.stop.clear()
    requests.clear()
    assert run(archive, [row(1), row(2)], lambda req: requests.append(req) or httpx.Response(200, content=PDF))[0] == 0
    assert len(requests) == 1
    assert len(list(archive[2].output_root.rglob('*.pdf'))) == 2


def test_batch_cursor_and_rows_rollback_together(archive):
    ledger = archive[1]
    run_id = ledger.begin_run(archive[2], 'prod')
    bad = row(2)
    bad.pop('row_key_hash')
    with pytest.raises(KeyError):
        ledger.ingest(run_id, 'prod', [row(), bad])
    assert ledger.conn.execute('SELECT after_id FROM runs WHERE run_id=?', (run_id,)).fetchone()[0] == 0
    assert ledger.conn.execute('SELECT count(*) FROM artifacts').fetchone()[0] == 0


def test_redirect_and_retry_all_obey_intervals(archive):
    clock, calls = archive[4], []
    def handler(req):
        calls.append((str(req.url), clock()))
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '90'})
        if req.url.path == '/1.pdf':
            return httpx.Response(302, headers={'Location': '/final.pdf'})
        return httpx.Response(200, content=PDF)
    assert run(archive, [row()], handler)[0] == 0
    assert len(calls) == 3
    assert calls[1][1] - calls[0][1] >= 90
    assert calls[2][1] - calls[1][1] >= 5
    saved = archive[1].cooldown()
    assert saved['next_request_not_before'] >= clock() + 5


def test_restart_cannot_shorten_cooldown(archive):
    volume, ledger, _, _, clock, control, *_ = archive
    ledger.request_finished(clock(), clock() + 90, 'http_429')
    limiter = Limiter(ledger, 0, control, volume, clock)
    limiter.before()
    assert clock.waits == [90]
    limiter.after()
    ledger.request_started()
    limiter = Limiter(ledger, 7, control, volume, clock)
    limiter.before()
    assert clock.waits[-1] == 7
    limiter.after()


@pytest.mark.parametrize('status', [403, 404, 410])
def test_http_failures_and_403_stops_remaining(archive, status):
    calls = []
    code, _ = run(archive, [row(1), row(2)], lambda req: calls.append(req) or httpx.Response(status))
    assert code == (3 if status == 403 else 1)
    assert len(calls) == (1 if status == 403 else 2)
    if status == 403:
        assert archive[1].conn.execute("SELECT count(*) FROM artifacts WHERE state='blocked'").fetchone()[0] == 1


@pytest.mark.parametrize('body,headers,error', [
    (b'<html>error</html>', {'Content-Type': 'text/html'}, 'html_instead_of_pdf'),
    (b'%PDF-1.7\ntruncated', {}, 'invalid_pdf_tail'),
    (PDF, {'Content-Length': '99999'}, 'file_too_large'),
    (PDF, {'Content-Encoding': 'deflate'}, 'unexpected_content_encoding'),
])
def test_invalid_pdf_never_committed(archive, body, headers, error):
    code, _ = run(archive, [row()], lambda _: httpx.Response(200, stream=httpx.ByteStream(body), headers=headers))
    assert code == 1
    assert archive[1].conn.execute('SELECT error FROM artifacts').fetchone()[0] == error
    assert not list(archive[2].output_root.rglob('*.pdf'))


def test_captcha_blocks_run(archive):
    code, _ = run(archive, [row(1), row(2)], lambda _: httpx.Response(200, content=b'<html>captcha</html>',
                                                               headers={'Content-Type': 'text/html'}))
    assert code == 3 and latest_run(archive[1])['reason'] == 'challenge_page'


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://user:password@example.com/a', 'https://', 'https://x/\x00'])
def test_unsafe_urls(url):
    with pytest.raises(FileFailed):
        valid_url(url)


def test_title_utf8_budget_and_canonical_unicode():
    name = title_name('公告' * 200, '__0123456789ab', 200)
    assert len(name.encode()) <= 200 and name.endswith('__0123456789ab.pdf')
    assert title_name('e\u0301/公告.pdf', '', 200) == 'é_公告.pdf'
    with pytest.raises(FileFailed):
        title_name('...', '', 200)


@pytest.mark.parametrize('changes,reason', [({'Internal': True}, 'external_physical'),
                                          ({'VirtualOrPhysical': 'Virtual'}, 'disk_image')])
def test_external_apfs_requires_physical_store(changes, reason):
    info = dict(MountPoint='/Volumes/test', VolumeUUID='uuid', WritableVolume=True,
                FilesystemType='apfs', APFSPhysicalStores=[{'APFSPhysicalStore': 'disk6s2'}])
    physical = dict(Internal=False, VirtualOrPhysical='Physical', **{})
    physical.update(changes)
    with pytest.raises(Blocked, match=reason):
        external_volume(info, lambda _: physical)


def test_no_mount_does_not_create_directory(tmp_path, monkeypatch):
    monkeypatch.setattr('src.scripts.announcement_download.volume.sys.platform', 'darwin')
    monkeypatch.setattr('src.scripts.announcement_download.volume.os.path.ismount', lambda p: Path(p) == Path('/'))
    output = tmp_path / 'not-mounted/announcements'
    volume = Volume(output, DownloadPolicy(), lambda _: pytest.fail('diskutil should not inspect root'))
    with pytest.raises(Blocked, match='external_mount'):
        volume.open()
    assert not output.exists()


def test_changed_uuid_blocks_all_requests(archive):
    archive[6]['VolumeUUID'] = 'different-disk'
    assert run(archive, [row()], lambda _: pytest.fail('disk mismatch should stop HTTP'))[0] == 3


def test_symlink_company_directory_never_written(archive, tmp_path):
    output = archive[2].output_root / '2026-09-30'
    output.mkdir()
    target = tmp_path / 'unrelated'
    target.mkdir()
    (output / '600000.SH').symlink_to(target, target_is_directory=True)
    assert run(archive, [row()])[0] == 3
    assert not list(target.iterdir())


def test_same_archive_lock_blocks_second_process(archive):
    second = Volume(archive[0].output, archive[3], archive[0].inspector)
    try:
        with pytest.raises(Blocked, match='archive_already_running'):
            second.open()
    finally:
        second.close()


def test_retry_after_date_and_invalid():
    assert retry_seconds('Tue, 14 Nov 2023 22:15:20 GMT', 1_700_000_000) == 120
    assert retry_seconds('invalid', 1_700_000_000) == 0


def test_retries_are_bounded_and_truncated_body_never_promoted(archive):
    requests = []
    code, _ = run(archive, [row()], lambda req: requests.append(archive[4]()) or
                  httpx.Response(200, content=PDF, headers={'Content-Length': str(len(PDF) + 1)}))
    assert code == 1 and len(requests) == 3
    assert requests[1] - requests[0] >= 30 and requests[2] - requests[1] >= 60
    assert not list(archive[2].output_root.rglob('*.pdf'))


@pytest.mark.parametrize('location,error', [('http://ann.example/a.pdf', 'https_downgrade_forbidden'),
                                           ('https://ann.example/1.pdf', 'redirect_loop'),
                                           ('file:///tmp/a.pdf', 'https_downgrade_forbidden')])
def test_bad_redirects_do_not_issue_second_request(archive, location, error):
    requests = []
    code, _ = run(archive, [row()], lambda req: requests.append(req) or
                  httpx.Response(302, headers={'Location': location}))
    assert code == 1 and len(requests) == 1
    assert archive[1].conn.execute('SELECT error FROM artifacts').fetchone()[0] == error


def test_enumeration_crash_keeps_batch_and_next_run_refreshes(archive):
    from sqlalchemy.exc import SQLAlchemyError
    volume, ledger, options, policy, clock, control, *_ = archive
    source = FakeSource([row(1), row(2), row(3)], options, policy.batch_size)
    batch = source.batch
    def fail(after, upper):
        if after:
            raise SQLAlchemyError('injected source outage')
        return batch(after, upper)
    source.batch = fail
    client = httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('no HTTP during enumeration')))
    assert cli.execute(options, policy, control, volume, ledger, source, 'prod/test/anns_d', client, clock) == 3
    client.close()
    assert latest_run(ledger)['after_id'] == 2
    assert ledger.conn.execute('SELECT count(*) FROM source_records').fetchone()[0] == 2
    requests = []
    assert run(archive, [row(1), row(2), row(3), row(4)], lambda req: requests.append(req) or httpx.Response(200, content=PDF))[0] == 0
    assert len(requests) == 4 and latest_run(ledger)['records_read'] == 4


def test_idempotent_results_and_progress_monotonic(archive):
    assert run(archive, [row(1), row(2)])[0] == 0
    volume, ledger, _, _, _, _, _, log = archive
    percentages = [v['percent'] for v in log if v['phase'] == 'downloading']
    assert percentages == sorted(percentages)
    run_id = latest_run(ledger)['run_id']
    key = ledger.conn.execute('SELECT artifact_key FROM run_artifacts WHERE run_id=? LIMIT 1', (run_id,)).fetchone()[0]
    before = ledger.stats(run_id)
    ledger.result(run_id, key, 'succeeded')
    assert ledger.stats(run_id) == before


def test_interval_zero_has_no_artificial_wait(archive):
    zero = (*archive[:2], replace(archive[2], interval_seconds=0), *archive[3:])
    assert run(zero, [row(1), row(2)])[0] == 0
    assert archive[4].waits == []


def test_readonly_and_unknown_physical_disks_rejected_before_writes(archive):
    info = dict(archive[6], WritableVolume=False)
    with pytest.raises(Blocked, match='read_only'):
        external_volume(info, lambda _: pytest.fail('must fail before physical lookup'))
    info['WritableVolume'] = True
    with pytest.raises(Blocked, match='physical_store_unknown'):
        external_volume(info, lambda _: {'Internal': False})


def test_space_and_fsync_failure_do_not_commit_pdf(archive, monkeypatch):
    def no_space(*a, **kw):
        raise Blocked('insufficient_disk_space')
    with monkeypatch.context() as patch:
        patch.setattr(archive[0], 'check_space', no_space)
        assert run(archive, [row()])[0] == 3
    assert not list(archive[2].output_root.rglob('*.pdf'))
    with monkeypatch.context() as patch:
        patch.setattr('src.scripts.announcement_download.files.os.fsync', lambda *a: (_ for _ in ()).throw(OSError('unsupported')))
        assert run(archive, [row()])[0] == 3
    assert not list(archive[2].output_root.rglob('*.pdf'))


def test_cancel_during_cooldown_no_new_http(archive):
    archive[1].defer(archive[4]() + 90, 'http_429')
    def cancel_wait(seconds):
        archive[5].stop.set()
    archive[5].wait = cancel_wait
    assert run(archive, [row()], lambda _: pytest.fail('cancelled wait must not issue HTTP'))[0] == 130


def test_volume_disappears_between_request_and_file_write(archive):
    def disconnected(req):
        archive[6]['WritableVolume'] = False
        return httpx.Response(200, content=PDF)
    # Slow metadata checking happens at request/commit boundaries, not once per 64KiB.
    assert run(archive, [row()], disconnected)[0] == 3
    assert not list(archive[2].output_root.rglob('*.pdf'))


def test_missing_url_preserves_mapping_and_cursor_without_http(archive):
    missing=row();missing['url']=None;missing['rec_time']=None
    calls=[]
    result, source = run(archive,[missing],lambda request: calls.append(request) or httpx.Response(200,content=PDF))
    assert result==0 and not calls
    ledger=archive[1]
    saved=ledger.conn.execute('SELECT * FROM source_records').fetchone()
    counters=ledger.conn.execute('SELECT * FROM runs ORDER BY updated_at DESC LIMIT 1').fetchone()
    assert saved['artifact_key'] is None and saved['raw_id']==1
    assert counters['after_id']==1 and counters['missing_url_count']==1 and counters['artifacts_total']==0


def test_replaced_source_is_not_downloaded(archive):
    volume,ledger,options,policy,clock,control,*_=archive
    source=FakeSource([row()],options,policy.batch_size)
    source.has_artifact=lambda task: False
    calls=[]
    client=httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200,content=PDF)))
    try:
        assert cli.execute(options,policy,control,volume,ledger,source,'test',client,clock)==0
        assert not calls
        assert ledger.conn.execute('SELECT skipped_count FROM runs').fetchone()[0]==1
        assert ledger.conn.execute('SELECT error FROM artifacts').fetchone()[0]=='source_record_replaced'
        assert source.closed
    finally:
        client.close()
