"""M2 subprocess fixture: temporary simulated volume, no DB or network access."""
from __future__ import annotations

import json
import os
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
    rows = [dict(id=n, row_key_hash=f'row-{n}', ann_date=options.start_date, ts_code='600000.SH',
                 title=f'公告{n}', url=f'https://fixture.example/{n}.pdf', rec_time=None)
            for n in (1, 2)]
    if mode in ('prepared', 'renamed', 'resume_one'):
        rows = rows[:1]

    class Source:
        def upper_id(self):
            return rows[-1]['id']

        def batch(self, after, upper):
            return [r for r in rows if after < r['id'] <= upper]

        def has_artifact(self, task):
            return True

        def close(self):
            pass

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
