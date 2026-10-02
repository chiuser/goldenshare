"""Insert original announcements; ignore only identical complete source records."""
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.datasets.anns_d_contracts import AnnouncementPersistenceError, canonical_payload, identity
from src.foundation.models.raw.raw_anns_d import RawAnnsD
from src.utils import chunked


@dataclass
class AnnouncementInsertResult:
    processed: int = 0
    inserted: int = 0
    identical: int = 0


class AnnsDDAO(BaseDAO[RawAnnsD]):
    def __init__(self, session):
        super().__init__(session, RawAnnsD)

    def require_storage_ready(self):
        ready = self.session.execute(text("""SELECT
            NOT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=to_regclass('raw_tushare.anns_d')
                       AND attname='group_key' AND NOT attisdropped)
            AND EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=to_regclass('raw_tushare.anns_d')
                       AND attname='raw_payload' AND attnotnull AND NOT attisdropped)""")).scalar()
        if ready is not True:
            raise AnnouncementPersistenceError('anns_d.storage_upgrade_required', '公告原始存储结构尚未切换，禁止混用旧哈希口径')

    def insert_ignore(self, rows: list[dict], *, batch_rows: int, statement_timeout_seconds: int,
                      lock_timeout_seconds: int) -> AnnouncementInsertResult:
        if any(type(value) is not int or value < 1 for value in
               (batch_rows, statement_timeout_seconds, lock_timeout_seconds)):
            raise ValueError('insert budgets must be positive integers')
        self.require_storage_ready()
        result = AnnouncementInsertResult()
        columns = {c.name for c in RawAnnsD.__table__.columns} - {'id'}
        # A collision or SQL failure rolls back the entire call; caller owns commit.
        with self.session.begin_nested():
            self.session.execute(text("SELECT set_config('lock_timeout',:value,true)"), {'value': f'{lock_timeout_seconds}s'})
            self.session.execute(text("SELECT set_config('statement_timeout',:value,true)"), {'value': f'{statement_timeout_seconds}s'})
            for batch in chunked(rows, batch_rows):
                unique = {}
                payloads = {}
                for row in batch:
                    payload = canonical_payload(row['raw_payload'])
                    key = identity(payload)
                    if row.get('row_key_hash') != key or (key in payloads and payloads[key] != payload):
                        raise AnnouncementPersistenceError('anns_d.identity_collision', '公告源载荷与哈希不一致或发生碰撞')
                    payloads[key] = payload
                    unique.setdefault(key, {k: v for k, v in row.items() if k in columns})
                if not unique:
                    continue
                # Sorted keys avoid opposite-order unique-index waits between callers.
                statement = insert(RawAnnsD).values([unique[key] for key in sorted(unique)])
                inserted = list(self.session.execute(statement.on_conflict_do_nothing(
                    index_elements=['row_key_hash']).returning(RawAnnsD.row_key_hash)).scalars())
                # A fresh READ COMMITTED statement sees a concurrent inserter after conflict wait.
                stored = self.session.execute(select(RawAnnsD.row_key_hash, RawAnnsD.raw_payload).where(
                    RawAnnsD.row_key_hash.in_(list(unique))))
                verified = set()
                for key, payload in stored:
                    if canonical_payload(payload) != payloads[key]:
                        raise AnnouncementPersistenceError('anns_d.identity_collision', '同一哈希对应不同公告源载荷，当前批回滚')
                    verified.add(key)
                if verified != set(unique):
                    raise AnnouncementPersistenceError('anns_d.identity_collision', '公告插入后载荷读回不完整')
                result.processed += len(batch)
                result.inserted += len(inserted)
                result.identical += len(batch) - len(inserted)
        return result
