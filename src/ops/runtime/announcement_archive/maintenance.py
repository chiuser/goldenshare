"""Read-only archive observations and explicit single-file maintenance execution."""
from __future__ import annotations
import json
import signal
import sqlite3
from dataclasses import asdict
from src.foundation.clients.announcement_archive.core import Blocked, Cancelled, Control, DownloadPolicy, FileFailed
from src.foundation.clients.announcement_archive.volume import SourceVolume, Volume, no_symlinks
from src.foundation.dao.announcement_archive.ledger import Ledger
from src.foundation.dao.announcement_archive.maintenance import LedgerQuery, LedgerQueryPolicy
from src.foundation.clients.announcement_archive.files import Files, verify_one


def run_cli(args):
    policy, query_policy = DownloadPolicy(), LedgerQueryPolicy()
    control = Control(policy)
    volume = SourceVolume(args.output_root, policy)
    ledger = None
    old_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda *_: control.stop.set())
    def emit(**result):
        print(json.dumps(result, ensure_ascii=False), flush=True)
    try:
        volume.open()
        volume.assert_archive_path()
        path = volume.ledger_path()
        no_symlinks(path)
        ledger = Ledger(path, volume.volume_uuid, volume.relative_root, read_only=True)
        query = LedgerQuery(ledger, control, query_policy)
        context = dict(command=args.command, output_root=str(volume.output), ledger_path=str(path),
                       schema_version=query.version, policy=asdict(query_policy))
        if args.command == 'summary':
            result = query.summary()
        elif args.command == 'runs':
            result = query.runs(args.limit, args.before_rowid, args.run_id)
        elif args.command == 'files':
            result = query.files(args.limit, **{key:getattr(args,key) for key in (
                'start_date','end_date','ts_code','title','state','run_id','after_key')})
        elif args.command == 'show':
            result = query.show(args.artifact_key, args.limit, args.after_rowid)
        else:
            task = query.artifact(args.artifact_key)
            # Hashing/promoting a PDF must not keep a SQLite read transaction open.
            ledger.close(); ledger = None
            if args.command == 'verify':
                result = verify_one(task, volume, policy, control)
            else:
                control.check()
                prior_identity = volume.volume_uuid, volume.relative_root
                volume.close()
                volume = Volume(args.output_root, policy)
                volume.open()
                if (volume.volume_uuid,volume.relative_root) != prior_identity:
                    raise Blocked('archive_identity_mismatch')
                path = volume.ledger_path()
                no_symlinks(path)
                if not path.is_file():
                    raise Blocked('archive_ledger_missing')
                control.check()
                ledger = Ledger(path, volume.volume_uuid, volume.relative_root)
                result = repair_one(args.artifact_key, volume, ledger, policy, control)
                context['schema_version'] = ledger.conn.execute('SELECT schema_version FROM archive').fetchone()[0]
        if ledger:
            ledger.close(); ledger = None
        control.check()
        volume.assert_valid(full=True)
        emit(**context, result=result)
        if args.command == 'verify':
            return 0 if result['final']['status'] == 'matched' else 1
        if args.command == 'repair' and result['outcome'] == 'failed':
            return 1
        return 0
    except Cancelled:
        emit(command=args.command, error='user_cancelled')
        return 130
    except (Blocked, OSError, sqlite3.Error, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        emit(command=args.command, error=reason)
        return 3
    finally:
        if ledger:
            ledger.close()
        volume.close()
        control.close()
        signal.signal(signal.SIGINT, old_handler)


def repair_one(key, volume, ledger, policy: DownloadPolicy, control: Control):
    """Caller holds the original archive lock. Preserve download history and cooldown."""
    control.check()
    before = ledger.conn.execute('SELECT * FROM artifacts WHERE artifact_key=?', (key,)).fetchone()
    if before is None:
        raise Blocked('artifact_not_found')
    before = dict(before)
    files = Files(volume, ledger, policy, control)
    volume.assert_valid(full=True)
    try:
        task = files.allocate(dict(before))
        outcome = files.recover(task)
        if outcome == 'skipped':
            outcome = 'already_valid'
        elif outcome == 'succeeded':
            outcome = 'recovered'
        else:
            outcome = 'ready_for_download'
    except FileFailed as exc:
        ledger.state(key, 'failed', str(exc))
        outcome = 'failed'
    after = ledger.artifact(key)
    return dict(artifact_key=key, outcome=outcome, before=before, after=after, http_requests=0,
                redownload=dict(start_date=after['ann_date'], end_date=after['ann_date'], output_root=str(volume.output))
                if outcome in ('ready_for_download', 'failed') else None)
