"""One authorized read-only node; never reconnect the saved database source."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from time import monotonic

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


REPORT = Path(__file__).resolve().parent
FIELDS = ('open', 'high', 'low', 'close')
CODE_SQL = ', '.join('?' for _ in range(2))
TABLE_DDL = {
    'db_rows': 'ts_code VARCHAR, trade_date DATE, ' + ', '.join(
        f'"{field}{suffix}" DOUBLE' for suffix in ('', '_qfq') for field in FIELDS
    ) + ', adj_factor DOUBLE',
    'lake_prices': 'ts_code VARCHAR, trade_date DATE, ' + ', '.join(f'"{field}" DOUBLE' for field in FIELDS),
    'lake_factors': 'ts_code VARCHAR, trade_date DATE, adj_factor DOUBLE',
    'lake_basis': 'ts_code VARCHAR, trade_date DATE, adj_factor DOUBLE',
}
PRICE_COMPARISON_SQL = '''CREATE TEMP TABLE price_comparison AS
SELECT d.ts_code, d.trade_date, d.adj_factor AS database_factor,
       f.adj_factor AS lake_factor, b.trade_date AS basis_date,
       b.adj_factor AS basis_value,
       ''' + ',\n       '.join(
    f'd."{field}" AS database_{field}, p."{field}" AS lake_{field}, '
    f'd."{field}_qfq" AS database_{field}_qfq, '
    f'CAST(p."{field}" * f.adj_factor / b.adj_factor AS DOUBLE) AS calculated_{field}_qfq'
    for field in FIELDS
) + '''
FROM db_rows d
JOIN lake_prices p USING (ts_code, trade_date)
JOIN lake_factors f USING (ts_code, trade_date)
JOIN lake_basis b USING (ts_code)
ORDER BY d.ts_code, d.trade_date'''
FIELD_COMPARISON_SQL = '''CREATE TEMP TABLE field_comparison AS
SELECT c.ts_code, c.trade_date, v.price_field, v.database_raw, v.lake_raw,
       v.database_qfq, v.calculated_qfq,
       v.calculated_qfq - v.database_qfq AS signed_difference,
       abs(v.calculated_qfq - v.database_qfq) AS absolute_difference,
       round(v.calculated_qfq, 5) AS rounded_5,
       v.database_raw IS NOT DISTINCT FROM v.lake_raw AS raw_equal,
       v.database_qfq IS NOT DISTINCT FROM v.calculated_qfq AS native_equal,
       v.database_qfq IS NOT DISTINCT FROM round(v.calculated_qfq, 5) AS rounded_5_equal
FROM price_comparison c
CROSS JOIN LATERAL (VALUES ''' + ',\n'.join(
    f"('{field}', c.database_{field}, c.lake_{field}, c.database_{field}_qfq, c.calculated_{field}_qfq)"
    for field in FIELDS
) + ''') v(price_field, database_raw, lake_raw, database_qfq, calculated_qfq)
ORDER BY c.ts_code, c.trade_date, v.price_field'''
SUMMARY_SQL = '''SELECT ts_code, count(*) AS row_count,
       count(*) FILTER (WHERE raw_equal) AS raw_exact_count,
       count(*) FILTER (WHERE native_equal) AS qfq_native_exact_count,
       count(*) FILTER (WHERE rounded_5_equal) AS qfq_rounded_5_exact_count,
       max(absolute_difference) AS max_absolute_difference,
       max(absolute_difference / abs(database_qfq))
         FILTER (WHERE database_qfq <> 0) AS max_relative_difference
FROM field_comparison GROUP BY ts_code ORDER BY ts_code'''


def save(name, value):
    target = REPORT / name
    pending = target.with_suffix(target.suffix + '.tmp')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                  default=str, allow_nan=False) + '\n')
    os.replace(pending, target)


def rows(connection, sql, parameters=()):
    cursor = connection.execute(sql, parameters)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, values)) for values in cursor.fetchall()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connection():
    return duckdb.connect(':memory:', config={
        'threads': '1', 'memory_limit': '128MiB', 'max_temp_directory_size': '0B',
    })


def preflight():
    target = REPORT / 'sql_preflight_02.json'
    if target.exists():
        raise RuntimeError('Preflight evidence already exists; do not overwrite or automatically repeat')
    con = connection()
    try:
        negative_sql = 'SELECT count(*) rows FROM (VALUES (1)) AS sample(value)'
        try:
            con.execute(negative_sql)
        except duckdb.ParserException as error:
            old_failure = {'type': type(error).__name__, 'message': str(error)}
        else:
            raise AssertionError('The original alias defect was not reproduced')
        assert con.execute('SELECT count(*) AS row_count FROM (VALUES (1)) AS sample(value)').fetchone() == (1,)
        quoted = con.execute('SELECT count(*) AS "rows" FROM (VALUES (1)) AS sample(value)').fetchone()
        assert quoted == (1,)
        keyword = rows(con, "SELECT keyword_name, keyword_category FROM duckdb_keywords() WHERE keyword_name='rows'")
        for table, ddl in TABLE_DDL.items():
            con.execute(f'CREATE TEMP TABLE {table} ({ddl})')
        con.execute(PRICE_COMPARISON_SQL)
        con.execute(FIELD_COMPARISON_SQL)
        assert rows(con, SUMMARY_SQL) == []
        save('sql_preflight_02.json', {
            'status': 'passed', 'duckdb_version': duckdb.__version__,
            'script_sha256': sha(Path(__file__)),
            'old_sql': negative_sql, 'expected_old_failure': old_failure,
            'safe_alias_row_count': 1, 'quoted_alias_row_count': 1,
            'keyword_metadata': keyword,
            'comparison_and_summary_bound_on_empty_typed_tables': True,
            'lake_files_read': 0, 'database_connections': 0,
        })
        print('SQL preflight passed; original alias error reproduced; no source files read')
    finally:
        con.close()


def run():
    progress_path = REPORT / 'lake_probe_attempt_02.json'
    if progress_path.exists():
        raise RuntimeError('Attempt 02 already exists; no automatic repeat allowed')
    pre = json.loads((REPORT / 'sql_preflight_02.json').read_text())
    assert pre['status'] == 'passed' and pre['script_sha256'] == sha(Path(__file__))
    scope = json.loads((REPORT / 'resume_scope_02.json').read_text())
    cached = REPORT / scope['cached_database']
    cached_hash = sha(cached)
    db = json.loads(cached.read_text())
    codes = tuple(scope['codes'])
    assert db['status'] == 'read_success' and db['row_count'] == len(db['rows']) == 42
    db_dates = {code: {r['trade_date'] for r in db['rows'] if r['ts_code'] == code} for code in codes}
    dates = tuple(sorted(db_dates[codes[0]]))
    assert len(dates) == scope['expected_dates'] and db_dates[codes[0]] == db_dates[codes[1]]
    assert dates[0] == scope['first_date'] and dates[-1] == scope['last_date']
    assert len({(r['ts_code'], r['trade_date']) for r in db['rows']}) == 42
    root = Path(scope['lake_root'])
    groups = {
        'prices': [root / 'silver/quote/stock_daily' / f'trade_date={day}' / 'part-000.parquet' for day in dates],
        'factors': [root / 'silver/quote/adj_factor' / f'trade_date={day}' / 'part-000.parquet' for day in dates],
        'basis': [root / 'silver/quote/adj_factor' / f"trade_date={scope['latest_basis_date']}" / 'part-000.parquet'],
    }
    paths = [path for group in groups.values() for path in group]
    assert len(set(paths)) == len(paths) == scope['expected_files']['total']
    progress = {
        'status': 'running', 'stage': 'metadata_preflight', 'attempt': 2,
        'authorized': True, 'cached_database_sha256': cached_hash,
        'database_reconnected': False, 'formal_data_written': False,
        'source_files_expected': len(paths), 'source_files_metadata_inspected': 0,
        'source_files_data_read': 0, 'real_controls': 0, 'kernel_calls': 0,
        'previous_attempt_not_overwritten': True, 'stages': [],
    }
    save(progress_path.name, progress)
    start = monotonic()
    con = None
    manifest = []
    logical = 0

    def check_time():
        if monotonic() - start > scope['limits']['program_seconds']:
            raise TimeoutError('Authorized single-program duration exceeded')

    def execute(sql, parameters=()):
        check_time()
        return con.execute(sql, parameters)

    try:
        available = sorted(p.name.removeprefix('trade_date=')
                           for p in (root / 'silver/quote/adj_factor').iterdir()
                           if p.is_dir() and p.name.startswith('trade_date=')
                           and len(p.name) == len('trade_date=YYYY-MM-DD'))
        assert available and available[-1] == scope['latest_basis_date'], 'Declared latest basis has changed'
        for kind, group in groups.items():
            projected = ('ts_code', 'trade_date', *FIELDS) if kind == 'prices' else ('ts_code', 'trade_date', 'adj_factor')
            expected = {'ts_code': pa.string(), 'trade_date': pa.date32(),
                        **{field: pa.float64() for field in projected if field not in ('ts_code', 'trade_date')}}
            for path in group:
                check_time()
                assert path.is_file() and path.resolve() == path
                before = path.stat()
                handle = pq.ParquetFile(path)
                try:
                    schema = handle.schema_arrow
                    for name, data_type in expected.items():
                        assert name in schema.names and schema.field(name).type == data_type, (str(path), name, 'wrong schema')
                    metadata = handle.metadata
                    compressed = uncompressed = 0
                    for i in range(metadata.num_row_groups):
                        row_group = metadata.row_group(i)
                        for j in range(row_group.num_columns):
                            column = row_group.column(j)
                            if column.path_in_schema in projected:
                                compressed += column.total_compressed_size
                                uncompressed += column.total_uncompressed_size
                    manifest.append({
                        'kind': kind, 'path': str(path), 'size': before.st_size,
                        'mtime_ns': before.st_mtime_ns, 'inode': before.st_ino,
                        'file_rows': metadata.num_rows, 'row_groups': metadata.num_row_groups,
                        'projected_columns': projected, 'projected_compressed_bytes': compressed,
                        'projected_uncompressed_bytes': uncompressed,
                    })
                finally:
                    handle.close()
                progress['source_files_metadata_inspected'] += 1
        assert sum(m['projected_uncompressed_bytes'] for m in manifest) <= scope['limits']['projected_uncompressed_bytes']
        progress['source_manifest'] = manifest
        progress['candidate_physical_rows'] = sum(m['file_rows'] for m in manifest)
        progress['projected_compressed_bytes'] = sum(m['projected_compressed_bytes'] for m in manifest)
        progress['projected_uncompressed_bytes'] = sum(m['projected_uncompressed_bytes'] for m in manifest)
        progress['physical_disk_bytes_read'] = 'not_measured; footer sizes are candidate I/O cost only'
        progress['stage'] = 'bounded_data_read'
        save(progress_path.name, progress)
        con = connection()
        for table, ddl in TABLE_DDL.items():
            execute(f'CREATE TEMP TABLE {table} ({ddl})')
        fixed_db_columns = ('ts_code', 'trade_date', *FIELDS, *(f'{f}_qfq' for f in FIELDS), 'adj_factor')
        con.register('saved_database_input', pa.Table.from_pylist(
            [{key: row[key] for key in fixed_db_columns} for row in db['rows']]))
        execute('INSERT INTO db_rows SELECT ts_code, CAST(trade_date AS DATE), ' +
                ', '.join(f'CAST("{f}" AS DOUBLE)' for f in fixed_db_columns[2:]) + ' FROM saved_database_input')
        con.unregister('saved_database_input')
        logical += 42
        for kind, table in (('prices', 'lake_prices'), ('factors', 'lake_factors'), ('basis', 'lake_basis')):
            date_values = dates if kind != 'basis' else (scope['latest_basis_date'],)
            columns = ('ts_code', 'trade_date', *FIELDS) if kind == 'prices' else ('ts_code', 'trade_date', 'adj_factor')
            sql = (f'INSERT INTO {table} SELECT ' + ', '.join(f'"{name}"' for name in columns) +
                   f' FROM read_parquet(?, hive_partitioning=false) WHERE ts_code IN ({CODE_SQL}) '
                   'AND trade_date IN (' + ','.join('CAST(? AS DATE)' for _ in date_values) + ')')
            execute(sql, [[str(p) for p in groups[kind]], *codes, *date_values])
            progress['source_files_data_read'] += len(groups[kind])
            count = execute(f'SELECT count(*) AS row_count FROM {table}').fetchone()[0]
            expected_count = 2 if kind == 'basis' else 42
            assert count == expected_count, (kind, 'row_count', count, expected_count)
            unique = execute(f'SELECT count(*) FROM (SELECT ts_code,trade_date FROM {table} GROUP BY ts_code,trade_date)').fetchone()[0]
            assert unique == count, (kind, 'duplicate key')
            null_conditions = ' OR '.join(f'"{name}" IS NULL' for name in columns)
            assert execute(f'SELECT count(*) FROM {table} WHERE {null_conditions}').fetchone()[0] == 0
            if kind != 'prices':
                assert execute(f'SELECT count(*) FROM {table} WHERE NOT isfinite(adj_factor) OR adj_factor <= 0').fetchone()[0] == 0
            if kind != 'basis':
                assert execute(f'SELECT count(*) FROM ((SELECT ts_code,trade_date FROM db_rows EXCEPT SELECT ts_code,trade_date FROM {table}) UNION ALL (SELECT ts_code,trade_date FROM {table} EXCEPT SELECT ts_code,trade_date FROM db_rows))').fetchone()[0] == 0
            logical += count * 5
            progress['stages'].append({'stage': kind, 'selected_rows': count, 'source_files': len(groups[kind])})
            save(progress_path.name, progress)
        basis = rows(con, 'SELECT ts_code,trade_date AS basis_date,adj_factor AS basis_value FROM lake_basis ORDER BY ts_code')
        execute(PRICE_COMPARISON_SQL)
        wide = rows(con, 'SELECT * FROM price_comparison ORDER BY ts_code,trade_date')
        assert len(wide) == 42
        evidence = {'status': 'comparison_saved_before_summary', 'basis': basis, 'row_count': len(wide), 'rows': wide}
        save('price_comparison_02.json', evidence)
        logical += 42 * 4
        execute(FIELD_COMPARISON_SQL)
        field_rows = rows(con, 'SELECT * FROM field_comparison ORDER BY ts_code,trade_date,price_field')
        assert len(field_rows) == scope['qfq_comparisons']
        summaries = rows(con, SUMMARY_SQL)
        factor_summary = rows(con, '''SELECT ts_code, count(*) AS row_count,
            count(*) FILTER (WHERE database_factor IS NOT DISTINCT FROM lake_factor) AS factor_exact_count,
            count(DISTINCT lake_factor) AS factor_values,
            min(trade_date) AS first_date, max(trade_date) AS last_date
            FROM price_comparison GROUP BY ts_code ORDER BY ts_code''')
        logical += 42 + 168 * 3 + 42
        exact_inputs = all(s['raw_exact_count'] == s['row_count'] for s in summaries) and all(
            s['factor_exact_count'] == s['row_count'] for s in factor_summary)
        native_exact = all(s['qfq_native_exact_count'] == s['row_count'] for s in summaries)
        rounded_exact = all(s['qfq_rounded_5_exact_count'] == s['row_count'] for s in summaries)
        for item in manifest:
            now = Path(item['path']).stat()
            assert (now.st_size, now.st_mtime_ns, now.st_ino) == (item['size'], item['mtime_ns'], item['inode']), 'Source changed during read'
        assert sha(cached) == cached_hash, 'Saved database sample changed'
        check_time()
        assert logical <= scope['limits']['logical_rows']
        evidence.update({
            'status': 'completed', 'summary': summaries, 'factor_summary': factor_summary,
            'field_count': len(field_rows), 'fields': field_rows,
            'exact_raw_prices_and_factors': exact_inputs,
            'qfq_native_exact': native_exact,
            'qfq_rounded_5_exact': rounded_exact,
            'source_files_unchanged_during_read': True,
            'interpretation': 'Record native precision and 5-place comparisons separately. No baseline, price or tolerance changed.',
        })
        save('price_comparison_02.json', evidence)
        progress.update({
            'status': 'completed', 'stage': 'all_comparisons_saved',
            'summary': summaries, 'factor_summary': factor_summary,
            'basis': basis, 'exact_raw_prices_and_factors': exact_inputs,
            'qfq_native_exact': native_exact, 'qfq_rounded_5_exact': rounded_exact,
            'selected_rows_including_cached_database': 128,
            'price_field_comparisons': 168, 'sql_logical_rows_accounted': logical,
            'source_files_unchanged_during_read': True,
        })
    except BaseException as error:
        progress.update({'status': 'stopped', 'error_type': type(error).__name__,
                         'reason': str(error), 'no_automatic_retry': True})
        raise
    finally:
        if con is not None:
            con.close()
        progress['cleanup'] = {'duckdb_closed': True, 'parquet_metadata_handles_closed': True,
                               'formal_writes': 0, 'database_connections': 0}
        progress['elapsed_seconds'] = monotonic() - start
        save(progress_path.name, progress)
        print(json.dumps({k: v for k, v in progress.items() if k not in ('source_manifest',)},
                         ensure_ascii=False, default=str))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('preflight', 'run'))
    args = parser.parse_args()
    {'preflight': preflight, 'run': run}[args.stage]()
