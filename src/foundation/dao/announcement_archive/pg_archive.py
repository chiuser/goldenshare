"""Archive-scoped SQL primitives. Callers own transactions and migration policy."""
from sqlalchemy import text

from src.foundation.clients.announcement_archive.core import Blocked, identity, timestamp
from .pg_schema import TABLES, qualified, validate_schema


def placeholders(rows, columns, prefix='v'):
    params = {}
    groups = []
    for i, row in enumerate(rows):
        names = [f'{prefix}{i}_{j}' for j in range(len(columns))]
        params.update(zip(names, (row[c] for c in columns)))
        groups.append('(' + ','.join(':' + n for n in names) + ')')
    return ','.join(groups), params


class ArchiveDAO:
    def __init__(self, connection, archive_id, *, require_ready=True):
        self.connection, self.archive_id = connection, archive_id
        if require_ready:
            validate_schema(connection)
            archive = self.get('archives', {})
            if archive is None:
                raise Blocked('archive_not_found')
            if archive['import_state'] != 'ready':
                raise Blocked('archive_import_incomplete')

    def _conditions(self, table, values):
        if not set(values) <= set(TABLES[table]['columns']) - {'archive_id'}:
            raise ValueError('archive_columns_invalid')
        params = dict(values, archive_id=self.archive_id)
        sql = ' AND '.join(f'{c} IS NOT DISTINCT FROM :{c}' for c in params)
        return sql, params

    def get(self, table, key, *, lock=False):
        where, params = self._conditions(table, key)
        result = self.connection.execute(text(f'SELECT * FROM {qualified(table)} WHERE {where}'
            + (' FOR UPDATE' if lock else '')), params).mappings().all()
        if len(result) > 1:
            raise ValueError('archive_key_incomplete')
        return dict(result[0]) if result else None

    def count(self, table):
        return self.connection.scalar(text(f'SELECT count(*) FROM {qualified(table)} WHERE archive_id=:a'),
                                      {'a': self.archive_id})

    def matching(self, table, rows):
        if not rows:
            return []
        keys = [c for c in TABLES[table]['primary_key'] if c != 'archive_id']
        if not keys:
            return [self.get(table, {})] if self.get(table, {}) else []
        values, params = placeholders(rows, keys)
        params['archive'] = self.archive_id
        return [dict(r) for r in self.connection.execute(text(f'SELECT * FROM {qualified(table)} '
            f'WHERE archive_id=:archive AND ({",".join(keys)}) IN ({values})'), params).mappings()]

    def insert_identical(self, table, rows):
        """At most 500 complete rows; ignore only conflicts whose full values match."""
        if not rows:
            return
        columns = list(TABLES[table]['columns'])
        if len(rows) > 500 or any(set(r) != set(columns) or r['archive_id'] != self.archive_id for r in rows):
            raise ValueError('archive_batch_invalid')
        values, params = placeholders(rows, columns)
        self.connection.execute(text(f'INSERT INTO {qualified(table)} ({",".join(columns)}) VALUES {values} '
                                     'ON CONFLICT DO NOTHING'), params)
        self.verify_identical(table, rows)

    def verify_identical(self, table, rows):
        keys = TABLES[table]['primary_key']
        found = {tuple(r[c] for c in keys): r for r in self.matching(table, rows)}
        if len(found) != len(rows) or any(found.get(tuple(r[c] for c in keys)) != r for r in rows):
            raise Blocked('archive_migration_conflict')

    def update(self, table, key, values, *, expected=None):
        columns = set(TABLES[table]['columns']) - set(TABLES[table]['primary_key'])
        if not values or not set(values) <= columns:
            raise ValueError('archive_columns_invalid')
        where, params = self._conditions(table, dict(key, **(expected or {})))
        params.update({'set_' + c: value for c, value in values.items()})
        return self.connection.execute(text(f'UPDATE {qualified(table)} SET '
            + ','.join(f'{c}=:set_{c}' for c in values) + ' WHERE ' + where), params).rowcount

    def row_page(self, table, *, cursor=None, limit=100, descending=False):
        if table not in ('runs', 'source_records') or not 1 <= limit <= 100:
            raise ValueError('archive_cursor_invalid')
        if cursor is not None and (type(cursor) is not int or cursor <= 0):
            raise ValueError('archive_cursor_invalid')
        sql = f'SELECT * FROM {qualified(table)} WHERE archive_id=:a'
        if cursor is not None:
            sql += ' AND row_seq ' + ('<' if descending else '>') + ' :cursor'
        sql += ' ORDER BY row_seq ' + ('DESC' if descending else 'ASC') + ' LIMIT :limit'
        return [dict(r) for r in self.connection.execute(text(sql),
            {'a': self.archive_id, 'cursor': cursor, 'limit': limit}).mappings()]

    def claim_run(self, run_id, owner_token):
        slot = self.get('archive_execution', {}, lock=True)
        if slot is None or slot['active_run_id'] is not None:
            raise Blocked('archive_already_running')
        if self.get('runs', {'run_id': run_id}) is None:
            raise Blocked('run_not_found')
        self.update('archive_execution', {}, dict(active_run_id=run_id, owner_token=owner_token,
            heartbeat=timestamp(), revision=slot['revision'] + 1))


def register_archive(connection, volume_uuid, relative_root, *, source_version=0, created_at=None):
    archive_id = identity([volume_uuid, relative_root])
    dao = ArchiveDAO(connection, archive_id, require_ready=False)
    row = dict(archive_id=archive_id, volume_uuid=volume_uuid, root_relative_path=relative_root,
        created_at=created_at or timestamp(), source_schema_version=source_version,
        import_state='importing' if source_version else 'ready', import_completed_at=None)
    existing = dao.get('archives', {})
    if existing is None:
        dao.insert_identical('archives', [row])
        if not source_version:
            for table, values in [('cooldown', dict(last_request_finished_at=0., next_request_not_before=0.,
                    request_in_flight=0, reason=None)), ('archive_execution', dict(active_run_id=None,
                    owner_token=None, heartbeat=None, revision=0))]:
                dao.insert_identical(table, [dict(archive_id=archive_id, **values)])
    elif any(existing[c] != row[c] for c in ('volume_uuid', 'root_relative_path', 'source_schema_version')) or (
            source_version and existing['created_at'] != row['created_at']):
        raise Blocked('archive_migration_conflict')
    return dao
