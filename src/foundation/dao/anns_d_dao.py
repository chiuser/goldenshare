"""Bounded announcement reconciliation. Transaction ownership stays with caller."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, insert, select, text

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.datasets.anns_d_contracts import AnnouncementContractError, AnnouncementPersistenceError, content, identity, maximal
from src.foundation.models.raw.raw_anns_d import RawAnnsD
from src.utils import chunked


@dataclass
class ReconciliationResult:
    processed: int = 0
    inserted: int = 0
    identical: int = 0
    covered: int = 0
    deleted: int = 0
    conflicting_group_visits: int = 0


class AnnsDDAO(BaseDAO[RawAnnsD]):
    def __init__(self, session):
        super().__init__(session, RawAnnsD)

    @staticmethod
    def error(code, message):
        return AnnouncementPersistenceError(code, message)

    def require_identity_ready(self):
        ready = self.session.execute(text("""SELECT attnotnull FROM pg_attribute
            WHERE attrelid=to_regclass('raw_tushare.anns_d') AND attname='group_key' AND NOT attisdropped""")).scalar()
        if ready is not True:
            raise self.error('anns_d.identity_migration_required', '公告身份迁移未完成，禁止旧新口径同时写入')

    def reconcile(self, rows: list[dict], *, batch_rows: int, max_group_versions: int, statement_timeout_seconds: int, lock_timeout_seconds: int) -> ReconciliationResult:
        if any(type(value) is not int or value < 1 for value in
               (batch_rows,max_group_versions,statement_timeout_seconds,lock_timeout_seconds)):
            raise ValueError('reconciliation budgets must be positive')
        self.require_identity_ready()
        result = ReconciliationResult()
        # Savepoint makes every call atomic even if a caller catches a failure.
        with self.session.begin_nested():
            self.session.execute(text("SELECT set_config('lock_timeout',:value,true)"), {"value": f"{lock_timeout_seconds}s"})
            self.session.execute(text("SELECT set_config('statement_timeout',:value,true)"), {"value": f"{statement_timeout_seconds}s"})
            for batch in chunked(rows, batch_rows):
                grouped = defaultdict(list)
                for row in batch:
                    group, key = identity(row)
                    if row.get('group_key') != group or row.get('row_key_hash') != key:
                        raise self.error('anns_d.identity_collision', '公告身份与实际字段不一致')
                    grouped[group].append(row)
                for group, incoming in sorted(grouped.items()):
                    # A transaction advisory lock also protects a group not yet in the table.
                    lock = int.from_bytes(bytes.fromhex(group)[:8], 'big', signed=True)
                    self.session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock})
                    stored = list(self.session.execute(select(RawAnnsD.__table__).where(
                        RawAnnsD.group_key == group).order_by(RawAnnsD.id).limit(max_group_versions + 1).with_for_update()).mappings())
                    candidates = [dict(row) for row in stored] + incoming
                    expected_group = content(incoming[0])
                    for row in candidates:
                        actual = content(row)
                        if (actual[0], actual[1], actual[3]) != (expected_group[0], expected_group[1], expected_group[3]):
                            raise self.error('anns_d.identity_collision', '公告分组哈希碰撞')
                    if len(stored) > max_group_versions or len({content(row) for row in candidates}) > max_group_versions:
                        raise self.error('anns_d.group_version_limit_exceeded', '公告候选组超过声明版本上限')
                    try:
                        keep = maximal(candidates)
                    except AnnouncementContractError as exc:
                        raise self.error('anns_d.identity_collision', str(exc)) from exc
                    keys = {row['row_key_hash'] for row in keep}
                    existing = {row['row_key_hash'] for row in stored}
                    # Classify the input separately from deletes of previously persisted rows.
                    seen = set(existing)
                    for row in incoming:
                        key = row['row_key_hash']
                        result.processed += 1
                        if key in seen:
                            result.identical += 1
                        elif key not in keys:
                            result.covered += 1
                        else:
                            result.inserted += 1
                        seen.add(key)
                    obsolete = [row['id'] for row in stored if row['row_key_hash'] not in keys]
                    if obsolete:
                        self.session.execute(delete(RawAnnsD).where(RawAnnsD.group_key == group, RawAnnsD.id.in_(obsolete)))
                        result.deleted += len(obsolete)
                    columns = {c.name for c in RawAnnsD.__table__.columns} - {'id'}
                    additions = [{k: v for k, v in row.items() if k in columns} for row in keep if row['row_key_hash'] not in existing]
                    if additions:
                        self.session.execute(insert(RawAnnsD), additions)
                    result.conflicting_group_visits += int(len(keep) > 1)
        return result
