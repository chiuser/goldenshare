"""Server-side, bounded identity-only migration. Never deletes announcement rows."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import inspect
import json
import logging
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update, bindparam
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.foundation.datasets import anns_d_contracts as contracts
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.announcement_stream import ANNOUNCEMENT_EXECUTION_LOCK, bounded_business_batch
from src.foundation.ingestion.row_transforms import _anns_d_row_transform
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.models.raw.raw_anns_d import RawAnnsD

LOG = logging.getLogger(__name__)
MAX_METADATA_BYTES = 16 * 1024
TABLE = RawAnnsD.__table__
BUSINESS_COLUMNS = tuple(c for c in TABLE.columns if c.name not in {'row_key_hash', 'group_key'})


def fail(message):
    raise contracts.AnnouncementPersistenceError('anns_d.identity_migration_invalid', message)


def old_identity(row):
    recorded = row.get('rec_time')
    if not row.get('url') or not recorded or recorded.tzinfo is None:
        fail(f"旧公告缺URL或有效时间，id={row['id']}")
    values = ('anns_d', row['ann_date'].isoformat(), row['ts_code'], row['title'], row['url'],
              recorded.astimezone(ZoneInfo('Asia/Shanghai')).isoformat())
    return hashlib.sha256('\x1f'.join(values).encode()).hexdigest()


def validate_row(row):
    normalized = _anns_d_row_transform(dict(row))
    if contracts.content(normalized) != contracts.content(row):
        fail(f"业务字段未按旧规则归一，id={row['id']}")
    group, key = contracts.identity(row)
    if row['group_key'] is None:
        if row['row_key_hash'] != old_identity(row):
            fail(f"旧身份不符（可能为显式时区或其他写入路径），id={row['id']}")
    elif (row['group_key'], row['row_key_hash']) != (group, key):
        fail(f"已迁移身份与业务字段不符，id={row['id']}")
    # Every stored row must retain the old completeness premises, including on resume.
    old_identity(row)
    return group, key


def _scalar(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value.isoformat() if hasattr(value, 'isoformat') else value


def business_bytes(row):
    return json.dumps([_scalar(row[c.name]) for c in BUSINESS_COLUMNS],
                      ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def state_digest(header):
    return hashlib.sha256(json.dumps({k:v for k,v in header.items() if k != 'state_digest'},
        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_metadata(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_METADATA_BYTES + 1)
    if len(raw) > MAX_METADATA_BYTES:
        fail('迁移摘要/恢复报告超过16KiB上限')
    value = json.loads(raw)
    if not isinstance(value, dict):
        fail('迁移摘要/恢复报告必须为JSON对象')
    return value


def atomic_json(path, payload):
    temporary = path.with_name(path.name + '.writing')
    owned = False
    try:
        with temporary.open('x') as stream:
            owned = True
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        # This tool owns only its temporary metadata file, never business or backup files.
        if owned:
            temporary.unlink(missing_ok=True)


class AnnouncementIdentityMigration:
    def __init__(self, engine):
        self.engine = engine
        self.storage = get_dataset_definition('anns_d').storage
        self.batch = self.storage.reconciliation_batch_rows
        self.seconds = self.storage.reconciliation_statement_timeout_seconds
        self.lock_seconds = self.storage.reconciliation_lock_timeout_seconds

    @contextmanager
    def locked(self):
        if self.engine.dialect.name != 'postgresql':
            fail('仅支持服务器PostgreSQL迁移')
        if self.engine.url.host not in {None, 'localhost', '127.0.0.1', '::1'}:
            fail('必须在数据库服务器通过本机连接执行，不允许远程读取公告迁移内容')
        if (host := self.engine.url.query.get('host')) and not str(host).startswith('/'):
            fail('数据库socket须为本机绝对路径')
        with self.engine.connect() as connection:
            connection.execute(text(f"SET LOCAL statement_timeout = '{self.seconds}s'"))
            acquired = connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': ANNOUNCEMENT_EXECUTION_LOCK}).scalar()
            connection.commit()
            if not acquired:
                raise contracts.AnnouncementPersistenceError('anns_d.dataset_busy', '公告维护正在运行')
            try:
                yield
            finally:
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': ANNOUNCEMENT_EXECUTION_LOCK})
                connection.commit()

    def _require_index(self):
        with Session(self.engine) as session:
            session.execute(text('SET TRANSACTION READ ONLY'))
            session.execute(text("SELECT set_config('statement_timeout',:v,true)"), {'v': f'{self.seconds}s'})
            ready = session.scalar(text("""SELECT indisunique AND indisvalid AND indisready
                FROM pg_index WHERE indexrelid=to_regclass('raw_tushare.uq_raw_tushare_anns_d_row_key_hash')
                AND indrelid=to_regclass('raw_tushare.anns_d')"""))
            if ready is not True:
                fail('公告身份唯一索引不存在或无效')

    def _max_id(self):
        with Session(self.engine) as session:
            session.execute(text('SET TRANSACTION READ ONLY'))
            session.execute(text("SELECT set_config('statement_timeout',:v,true)"), {'v': f'{self.seconds}s'})
            return session.scalar(select(TABLE.c.id).order_by(TABLE.c.id.desc()).limit(1)) or 0

    def _scope(self, start, end):
        url = self.engine.url
        return dict(start_id=start, end_id=end, database=dict(host=url.host, port=url.port, database=url.database,
                     socket=url.query.get('host')),
                    contract_digest=contracts.digest((inspect.getsource(contracts), inspect.getsource(_anns_d_row_transform),
                        inspect.getsource(sys.modules[__name__]), self.batch, self.seconds, self.lock_seconds)))

    def _scan(self, scope, check, emit, *, phase, require_new=False, draft=None, committed=None):
        fingerprint = hashlib.sha256()
        count = migrated = 0
        after = scope['start_id'] - 1
        while True:
            check()
            with Session(self.engine) as session:
                session.execute(text('SET TRANSACTION READ ONLY'))
                with bounded_business_batch(session, self.seconds, check):
                    rows = list(session.execute(select(TABLE).where(TABLE.c.id > after,
                        TABLE.c.id <= scope['end_id']).order_by(TABLE.c.id).limit(self.batch)).mappings())
                    for row in rows:
                        check(False)
                        validate_row(row)
                        if require_new and row['group_key'] is None:
                            fail(f"尚未迁移，id={row['id']}")
                        fingerprint.update(business_bytes(row))
                        migrated += row['group_key'] is not None
                        count += 1
            if not rows:
                break
            after = rows[-1]['id']
            if draft:
                atomic_json(draft, dict(frozen=False, scope=scope, checked_rows=count, last_id=after))
            emit(dict(phase=phase, last_id=after, checked_rows=count, completed=migrated if committed is None else committed))
            check()
        return dict(count=count, migrated=migrated, business_digest=fingerprint.hexdigest())

    @staticmethod
    def _verify_baseline(header, result):
        if (header['count'], header['business_digest']) != (result['count'], result['business_digest']):
            fail('公告数量或业务字段与冻结校验不符')

    def _recovery(self, path, scope, check, emit):
        report = read_metadata(path)
        if report.get('database') != scope['database'] or report.get('table') != 'raw_tushare.anns_d' or report.get('start_id', 0) > scope['start_id'] or report.get('end_id', 0) < scope['end_id']:
            fail('恢复报告未覆盖本次表和范围')
        try:
            restored = datetime.fromisoformat(report['restore_verified_at'])
            if restored.tzinfo is None:
                fail('恢复演练时间须带时区')
            backup = Path(report['backup_path'])
            if not backup.is_absolute() or not backup.is_file():
                fail('恢复备份文件不存在')
            fingerprint = hashlib.sha256()
            size = 0
            last_emit = 0.0
            with backup.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    check(False)
                    fingerprint.update(chunk)
                    size += len(chunk)
                    if time.monotonic()-last_emit >= 5:
                        emit(dict(phase='checking_backup', verified_bytes=size, completed=0))
                        last_emit = time.monotonic()
            emit(dict(phase='checking_backup', verified_bytes=size, completed=0))
            check()
            if fingerprint.hexdigest() != report['backup_sha256']:
                fail('恢复备份摘要不符')
        except contracts.AnnouncementPersistenceError:
            raise
        except (KeyError, ValueError) as exc:
            fail(f'恢复报告无效：{type(exc).__name__}')
        return contracts.digest(report)

    def run(self, *, mode, start_id, end_id, state_path, recovery_report_path=None, finalize=False,
            expected_state_digest=None, cancel=lambda: False, progress=lambda _: None):
        if mode not in {'CHECK', 'APPLY'} or type(start_id) is not int or type(end_id) is not int or not 1 <= start_id <= end_id:
            fail('须指定CHECK/APPLY及有效主键范围')
        if type(finalize) is not bool or finalize and mode != 'APPLY':
            fail('最终切换仅适用于APPLY')
        path = Path(state_path)
        if not path.is_absolute() or not path.parent.is_dir():
            fail('校验文件须为服务器已有目录下的绝对路径')
        last_cancel_check = 0.0
        def check(force=True):
            nonlocal last_cancel_check
            now = time.monotonic()
            if not force and now-last_cancel_check < 0.2:
                return
            last_cancel_check = now
            if cancel():
                raise IngestionCanceledError('公告身份迁移已在批次边界停止')
        def emit(value):
            value = {**value, 'updated_at': datetime.now(timezone.utc).isoformat(), 'eta': None}
            try:
                progress(value)
            except Exception:
                LOG.warning('公告身份迁移观察更新失败', exc_info=True)
        with self.locked():
            check()
            self._require_index()
            scope = self._scope(start_id, end_id)
            high_water = self._max_id()
            if end_id > high_water:
                fail('范围超过当前公告高水位')
            if mode == 'CHECK':
                if path.exists():
                    fail('禁止覆盖已有冻结校验文件')
                draft = path.with_name(path.name + '.draft')
                result = self._scan(scope, check, emit, phase='checking', draft=draft)
                if self._max_id() != high_water:
                    fail('公告高水位变化')
                check()
                header = dict(frozen=True, scope=scope, high_water_id=high_water, **result)
                header['state_digest'] = state_digest(header)
                atomic_json(path, header)
                return header
            header = read_metadata(path)
            actual_digest = state_digest(header)
            if not expected_state_digest or actual_digest != expected_state_digest or header.get('state_digest') != actual_digest:
                fail('冻结文件摘要不符或未指定已审阅摘要')
            if header.get('frozen') is not True or header.get('scope') != scope or header.get('high_water_id') != high_water:
                fail('冻结校验合同、范围或高水位不符')
            if finalize and (start_id != 1 or end_id != high_water):
                fail('最终切换须覆盖全表')
            if not recovery_report_path:
                fail('APPLY必须提供运营核验的备份恢复报告')
            recovery = self._recovery(Path(recovery_report_path), scope, check, emit)
            before = self._scan(scope, check, emit, phase='rechecking')
            self._verify_baseline(header, before)
            completed = before['migrated']
            emit(dict(phase='applying', completed=completed, total=header['count'], last_id=start_id-1))
            after = start_id - 1
            while True:
                check()
                changed = 0
                with Session(self.engine) as session:
                    with bounded_business_batch(session, self.seconds, check):
                        session.execute(text("SELECT set_config('lock_timeout',:v,true)"), {'v': f'{self.lock_seconds}s'})
                        rows = list(session.execute(select(TABLE).where(TABLE.c.id > after, TABLE.c.id <= end_id)
                            .order_by(TABLE.c.id).limit(self.batch).with_for_update()).mappings())
                        updates = []
                        for row in rows:
                            check(False)
                            group, key = validate_row(row)
                            if row['group_key'] is not None:
                                continue
                            updates.append(dict(old_id=row['id'], old_hash=row['row_key_hash'], new_group=group,
                                new_hash=key, **{f'old_{c.name}': row[c.name] for c in BUSINESS_COLUMNS if c.name != 'id'}))
                        if updates:
                            conditions = [TABLE.c.id == bindparam('old_id'), TABLE.c.row_key_hash == bindparam('old_hash'), TABLE.c.group_key.is_(None)]
                            conditions += [column.is_not_distinct_from(bindparam(f'old_{column.name}', type_=column.type)) for column in BUSINESS_COLUMNS if column.name != 'id']
                            try:
                                result = session.execute(update(TABLE).where(*conditions).values(group_key=bindparam('new_group'), row_key_hash=bindparam('new_hash')), updates)
                            except SQLAlchemyError as exc:
                                state = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
                                code = 'anns_d.identity_collision' if isinstance(exc, IntegrityError) else 'anns_d.identity_migration_invalid'
                                raise contracts.AnnouncementPersistenceError(code,
                                    f'身份写批失败，当前批回滚；id范围{rows[0]["id"]}..{rows[-1]["id"]}；SQLSTATE={state}') from None
                            if result.rowcount != len(updates):
                                fail('读取后公告发生变化，当前批回滚')
                            changed = len(updates)
                        check()
                    session.commit()
                if not rows:
                    break
                completed += changed
                after = rows[-1]['id']
                emit(dict(phase='applying', completed=completed, total=header['count'], last_id=after))
                check()
            verified = self._scan(scope, check, lambda value: emit({**value, 'total':header['count']}),
                phase='verifying', require_new=True, committed=completed)
            self._verify_baseline(header, verified)
            if self._max_id() != high_water:
                fail('公告高水位变化')
            check()
            self._require_index()
            if finalize:
                with Session(self.engine) as session:
                    with bounded_business_batch(session, self.seconds, check):
                        session.execute(text("SELECT set_config('lock_timeout',:v,true)"), {'v': f'{self.lock_seconds}s'})
                        session.execute(text('ALTER TABLE raw_tushare.anns_d ALTER COLUMN group_key SET NOT NULL'))
                        check()
                    session.commit()
            emit(dict(phase='complete', completed=completed, total=header['count'], last_id=end_id))
            return dict(**header, finalized=finalize, recovery_report_digest=recovery)
