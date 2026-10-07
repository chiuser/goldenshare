"""Subprocess-only Q1 fixture; explicit temporary inventory and PG policy injection."""
import json
import os
from pathlib import Path
import signal
import sys
from dataclasses import replace
from contextlib import contextmanager, ExitStack

from src.foundation.clients.announcement_archive.core import Cancelled, Control, DownloadPolicy
from src.foundation.clients.announcement_archive.locking import ExecutionLock
from src.foundation.config.announcement_archive import ArchiveDatabasePolicy
from src.foundation.dao.announcement_archive.pg_database import ArchiveDatabase
from src.ops.runtime.announcement_archive.migration import ArchiveMigration, MigrationInventory


@contextmanager
def guard(source, mount, **_):
    from types import SimpleNamespace
    with ExitStack() as stack:
        for path in (source.path.parent/'execution.lock', mount/source.archive['root_relative_path']/'.state/archive.lock'):
            lock=ExecutionLock(path).open();stack.callback(lock.close)
        yield SimpleNamespace(assert_valid=lambda **_:None)


def main():
    spec=json.loads(Path(sys.argv[1]).read_text());mode=sys.argv[2]
    policy=replace(ArchiveDatabasePolicy(),database=spec['database'],port=spec['port'])
    db=ArchiveDatabase(f"postgresql+psycopg://q1_fixture@localhost:{spec['port']}/{spec['database']}",policy)
    control=Control(DownloadPolicy())
    signal.signal(signal.SIGINT,lambda *_:control.stop.set())
    stopped=False
    def emit(value):
        nonlocal stopped
        print(value,flush=True)
        event=json.loads(value)
        if not stopped and event.get('table')=='source_records' and event.get('rowsCommitted')==500:
            stopped=True
            if mode=='exit':os._exit(77)
            if mode=='signal':control.stop.wait(10)
    control.emit=emit
    inventory=MigrationInventory(tuple(Path(p) for p in spec['ledgers']),Path(spec['catalog']),Path(spec['mount']))
    try:
        result=ArchiveMigration(db,control,inventory,guard=guard).run(apply=True)
        print(json.dumps(result),flush=True)
        return 0
    except Cancelled:return 130
    finally:db.close()


if __name__=='__main__':raise SystemExit(main())
