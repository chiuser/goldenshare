"""M2 subprocess fixture: temporary simulated volume, no DB or network access."""
from __future__ import annotations

import json
import os
import signal
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx

from src.scripts.download_announcements import execute
from src.scripts.announcement_download.core import Control, DownloadOptions, DownloadPolicy
from src.scripts.announcement_download.files import Files
from src.scripts.announcement_download.ledger import Ledger
from src.scripts.announcement_download.volume import Volume
from src.scripts.announcement_download import volume as volume_module


PDF = b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n'


def main():
    root, mode = Path(sys.argv[1]), sys.argv[2]
    mount = root / 'disk'
    mount.mkdir(exist_ok=True)
    volume_module.sys.platform = 'darwin'
    volume_module.os.path.ismount = lambda p: Path(p) == mount
    info = dict(MountPoint=str(mount), VolumeUUID='process-fixture', DeviceIdentifier='disk-fixture',
                WritableVolume=True, Internal=False, VirtualOrPhysical='Physical')
    policy = replace(DownloadPolicy(), reserve_bytes=0, max_file_size=1024)
    options = DownloadOptions(date(2026, 9, 30), date(2026, 9, 30), 0, mount / 'announcements')
    requests = []
    control = Control(policy, lambda _: None)
    signal.signal(signal.SIGINT, lambda *_: control.stop.set())
    rows = [dict(ann_date='20260930',name='样本公司',ts_code='600000.SH',
                 title=f'公告{n}', url=f'https://fixture.example/{n}.pdf', rec_time=None)
            for n in (1, 2)]
    if mode in ('prepared', 'renamed', 'resume_one'):
        rows = rows[:1]

    class Day:
        day='2026-09-30'
        facts=dict(opened_dev=1,opened_ino=1,size=0,sha256='0'*64,footer_count=len(rows))
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def __iter__(self):
            if mode == 'query_cancel':
                from src.scripts.announcement_download.source import Source as RawSource, DayReader
                source = RawSource(options, policy, control)
                reader = DayReader(source, self.day)
                reader.connection = source.connect()
                print('query_ready', flush=True)
                try:
                    reader._call(lambda: reader.connection.execute(
                        'SELECT sum(sqrt(i)) FROM range(10000000000) t(i)'))
                finally:
                    reader.close()
                    source.close()
            if mode == 'enumerating':
                yield rows[:1]
                os._exit(73)
            yield rows
        def verify(self): return self.facts

    class Source:
        def iter_days(self): yield Day()
        def assert_valid(self,full=False): pass
        def close(self): pass

    class ExitStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'%PDF-1.7\n'
            os._exit(73)

    def handler(request):
        requests.append(str(request.url))
        if mode == 'downloading' and len(requests) == 2:
            return httpx.Response(200, stream=ExitStream())
        return httpx.Response(200, content=PDF)

    if mode == 'prepared':
        Files.promote = lambda *args: os._exit(73)
    original_state = Ledger.state
    if mode == 'renamed':
        def state(self, key, value, error=None):
            if value == 'succeeded':
                os._exit(73)
            return original_state(self, key, value, error)
        Ledger.state = state

    volume = Volume(options.output_root, policy, lambda _: info)
    ledger = None
    try:
        volume.open()
        ledger = Ledger(root / 'local-state/downloads.sqlite', volume.volume_uuid, volume.relative_root)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = execute(options, policy, control, volume, ledger, Source(), 'process-fixture', client)
        print(json.dumps({'exit_code': result, 'requests': len(requests)}))
        return result
    finally:
        if ledger:
            ledger.close()
        volume.close()


if __name__ == '__main__':
    raise SystemExit(main())
