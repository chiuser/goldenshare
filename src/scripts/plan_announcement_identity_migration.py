"""Offline, bounded PLAN only. Input is a reviewed read-only JSONL export.

No database connection, production APPLY, or destructive data operation is provided.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from src.foundation.datasets.anns_d_contracts import covers, digest, maximal
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.row_transforms import _anns_d_row_transform


def plan(input_path: Path, output_path: Path) -> dict:
    definition = get_dataset_definition('anns_d')
    limit = definition.storage.reconciliation_max_group_versions
    if not limit:
        raise ValueError('Definition group budget is required')
    # Never overwrite an existing review artifact.
    with output_path.open('x'):
        pass
    conn = sqlite3.connect(output_path)
    try:
        conn.executescript('''CREATE TABLE input_rows(id INTEGER PRIMARY KEY,old_hash TEXT NOT NULL,
            group_key TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX input_group ON input_rows(group_key,id);
            CREATE TABLE candidates(raw_id INTEGER PRIMARY KEY,old_hash TEXT,new_hash TEXT,group_key TEXT,
              action TEXT,survivor_raw_id INTEGER,applied_at TEXT);
            CREATE UNIQUE INDEX unique_keep_hash ON candidates(new_hash) WHERE action='keep';
            CREATE TABLE header(singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload TEXT NOT NULL);''')
        count = 0
        source_digest = hashlib.sha256()
        with input_path.open() as stream:
            for line in stream:
                source_digest.update(line.encode())
                original = json.loads(line)
                if not isinstance(original['id'], int) or original['id'] < 1:
                    raise ValueError('raw id must be a positive integer')
                row = dict(original)
                row['ann_date'] = date.fromisoformat(str(original['ann_date']))
                normalized = _anns_d_row_transform(row)
                # This spool is solely a temporary PLAN input, not a source history store.
                conn.execute('INSERT INTO input_rows VALUES(?,?,?,?)', (original['id'], original['row_key_hash'],
                    normalized['group_key'], json.dumps(original, ensure_ascii=False)))
                count += 1
                if count % definition.storage.reconciliation_batch_rows == 0:
                    conn.commit()
        conn.commit()
        manifest = hashlib.sha256()
        after = ''
        keep_count = 0
        pending_rows = 0
        while True:
            next_group = conn.execute('SELECT group_key FROM input_rows WHERE group_key>? ORDER BY group_key LIMIT 1', (after,)).fetchone()
            if not next_group:
                break
            group = next_group[0]
            candidates = conn.execute('SELECT id,old_hash,payload FROM input_rows WHERE group_key=? ORDER BY id LIMIT ?', (group, limit + 1)).fetchall()
            if len(candidates) > limit:
                raise ValueError('anns_d.group_version_limit_exceeded')
            if pending_rows + len(candidates) > definition.storage.reconciliation_batch_rows:
                conn.commit()
                pending_rows = 0
            rows = []
            for raw_id, old_hash, payload in candidates:
                original = json.loads(payload)
                original['ann_date'] = date.fromisoformat(original['ann_date'])
                row = _anns_d_row_transform(original)
                row['id'], row['old_hash'] = raw_id, old_hash
                rows.append(row)
            survivors = maximal(rows)
            survivor_keys = {row['row_key_hash']: row for row in survivors}
            for row in rows:
                key = row['row_key_hash']
                if key in survivor_keys:
                    survivor = survivor_keys[key]
                    action = 'keep' if row['id'] == survivor['id'] else 'delete_identical'
                else:
                    survivor = min((other for other in survivors if covers(other, row)), key=lambda x: x['row_key_hash'])
                    action = 'delete_covered'
                entry = (row['id'], row['old_hash'], key, group, action, survivor['id'] if action != 'keep' else None)
                manifest.update(json.dumps(entry, ensure_ascii=False, separators=(',', ':')).encode() + b'\n')
                conn.execute('INSERT INTO candidates VALUES(?,?,?,?,?,?,NULL)', entry)
                keep_count += int(action == 'keep')
            pending_rows += len(candidates)
            if pending_rows >= definition.storage.reconciliation_batch_rows:
                conn.commit()
                pending_rows = 0
            after = group
        conn.commit()
        header = dict(migration_token=str(uuid.uuid4()), contract_digest=digest(('anns_d','information_dominance_v1',definition.source.source_fields)),
                      high_water_id=conn.execute('SELECT coalesce(max(id),0) FROM input_rows').fetchone()[0],
                      candidate_count=count, keep_count=keep_count, delete_count=count-keep_count,
                      manifest_digest=manifest.hexdigest(), source_digest=source_digest.hexdigest(), frozen=True)
        # Do not leave redundant source payloads in the final frozen review artifact.
        conn.execute('DROP TABLE input_rows')
        conn.execute('INSERT INTO header VALUES(1,?)', (json.dumps(header),))
        conn.commit()
        return header
    finally:
        conn.close()


def verify_plan(path: Path, *, expected_manifest_digest: str) -> dict:
    """Review a frozen artifact in read-only mode against an independently kept digest."""
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        header = json.loads(conn.execute('SELECT payload FROM header WHERE singleton=1').fetchone()[0])
        if header.get('frozen') is not True:
            raise ValueError('plan is not frozen')
        manifest = hashlib.sha256()
        count = keep = 0
        for entry in conn.execute('SELECT raw_id,old_hash,new_hash,group_key,action,survivor_raw_id FROM candidates ORDER BY group_key,raw_id'):
            manifest.update(json.dumps(entry, ensure_ascii=False, separators=(',', ':')).encode() + b'\n')
            count += 1
            keep += int(entry[4] == 'keep')
            if entry[4] not in {'keep','delete_identical','delete_covered'}:
                raise ValueError('unknown action')
        if manifest.hexdigest() != header['manifest_digest'] or manifest.hexdigest() != expected_manifest_digest:
            raise ValueError('manifest digest mismatch')
        if (count,keep,count-keep) != (header['candidate_count'],header['keep_count'],header['delete_count']):
            raise ValueError('plan counts mismatch')
        if conn.execute("""SELECT 1 FROM candidates c LEFT JOIN candidates k ON c.survivor_raw_id=k.raw_id
                WHERE c.action<>'keep' AND (k.raw_id IS NULL OR k.action<>'keep' OR k.group_key<>c.group_key) LIMIT 1""").fetchone():
            raise ValueError('invalid survivor')
        return header
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='公告身份迁移只生成离线候选，不连接或修改数据库')
    parser.add_argument('--input-jsonl', type=Path, required=True)
    parser.add_argument('--output-plan', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(plan(args.input_jsonl, args.output_plan), ensure_ascii=False))


if __name__ == '__main__':
    main()
