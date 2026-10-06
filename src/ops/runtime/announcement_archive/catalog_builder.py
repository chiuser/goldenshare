"""Serial, per-day local projection preparation. Never downloads or alters Raw."""
import os
import json
import time
import uuid
from contextlib import contextmanager
from datetime import date
from dataclasses import replace

from src.foundation.clients.announcement_archive.core import Blocked, source_projection, identity
from src.foundation.clients.announcement_archive.locking import ExecutionLock
from src.foundation.clients.announcement_archive.names import NameSnapshot, normalized_name
from src.foundation.config.announcement_archive import DataCenterPolicy
from src.foundation.clients.announcement_archive.budget import remaining


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


class CatalogBuilder:
    def __init__(self, catalog, source, names_source, initials, policy=DataCenterPolicy()):
        self.catalog, self.source, self.names_source, self.initials = catalog, source, names_source, initials
        self.policy = policy

    def check(self):
        self.source.control.check()

    def assert_source(self,full=False):
        self.source.assert_valid(full=full)
        self.names_source.assert_valid(full=full)

    def file_stat(self, volume, directory):
        volume.assert_valid()
        try:
            with volume.directory(directory) as fd:
                return os.stat('part-000.parquet', dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            raise Blocked('source_day_missing') from None
        except OSError:
            raise Blocked('source_read_failed') from None

    def names_signature(self):
        return identity([str(signature(self.file_stat(self.names_source.volume, f'{kind}/full')))
                         for kind in ('stock_basic', 'namechange')])

    def current(self, start, end):
        """Cheap request-side checks; full disk identity is validated by the worker."""
        from datetime import timedelta
        deadline = time.monotonic() + remaining(self.policy.sql_seconds)
        self.source.assert_valid()
        meta = self.catalog.meta()
        if self.initials.version != type(self.initials)(self.initials.path).version:
            return False
        if (meta['dictionary_version'] != self.initials.version or meta['name_version'] != self.names_signature()):
            return False
        day = date.fromisoformat(start)
        last = date.fromisoformat(end)
        while day <= last:
            if time.monotonic() >= deadline:
                raise Blocked('catalog_sql_timeout')
            value = self.catalog.day(day.isoformat())
            current = signature(self.file_stat(self.source.volume, f'ann_date={day.isoformat()}'))
            if value is None or value['dictionary_version'] != self.initials.version or current != tuple(value[k] for k in ('opened_dev','opened_ino','size','mtime_ns')):
                return False
            day += timedelta(days=1)
        return True

    def _check_budget(self, started):
        self.source.control.check()
        if time.monotonic() - started > self.policy.catalog_unit_seconds:
            raise Blocked('catalog_unit_timeout')

    def prepare_names(self):
        version = self.names_signature()
        meta = self.catalog.meta()
        if version == meta['name_version'] and self.initials.version == meta['dictionary_version']:
            return
        previous=json.loads(meta['name_facts'] or '{}')
        facts={}
        generation = uuid.uuid4().hex
        for kind, source_kind in [('stock_basic', 'raw_master'), ('namechange', 'history')]:
            current=signature(self.file_stat(self.names_source.volume,f'{kind}/full'))
            old=previous.get(kind)
            if old and current[:2]==(old['opened_dev'],old['opened_ino']) and current[2:]!=(old['size'],old['mtime_ns']):
                raise Blocked('source_file_changed')
            started = time.monotonic()
            with NameSnapshot(self.names_source, kind) as reader:
                for batch in reader:
                    self._check_budget(started)
                    rows = []
                    for value in batch:
                        code = value['ts_code']
                        if code is None or not code.strip():
                            continue
                        name = value['name'] or ''
                        cnspell = value.get('cnspell')
                        rows.append((source_kind,code,name,cnspell,self.initials(name,code,cnspell),
                                     normalized_name(name),'',generation,''))
                    self.catalog.add_names(rows)
                facts[kind]=dict(reader.verify(),mtime_ns=reader.open_stat.st_mtime_ns)
                self._check_budget(started)
        if version != self.names_signature():
            raise Blocked('source_file_changed')
        self.catalog.publish_names(generation, version, self.initials.version,facts)

    @contextmanager
    def preparation(self,query_id,conditions):
        lock=ExecutionLock(self.catalog.path.parent/'catalog-writer.lock').open()
        try:
            self._prepare(query_id,conditions)
            yield
        finally:
            lock.close()

    def prepare(self,query_id,conditions):
        with self.preparation(query_id,conditions):
            pass

    def _prepare(self, query_id, conditions):
        start, end = conditions['startDate'], conditions['endDate']
        days, records = 0, 0
        try:
            self.assert_source(full=True)
            self.initials=type(self.initials)(self.initials.path)
            self.prepare_names()
            self.source.options = replace(self.source.options, start_date=date.fromisoformat(start), end_date=date.fromisoformat(end))
            for reader in self.source.iter_days():
                self.catalog.build_progress(query_id,start,end,'preparing',reader.day,days,records)
                cached = self.catalog.day(reader.day)
                stat_before = self.file_stat(self.source.volume, f'ann_date={reader.day}')
                if cached and cached['dictionary_version'] == self.initials.version and signature(stat_before) == tuple(cached[k] for k in ('opened_dev','opened_ino','size','mtime_ns')):
                    days += 1
                    records += cached['footer_count']
                    self.catalog.update_query(query_id, dates_scanned=days, records_scanned=records)
                    continue
                if cached and signature(stat_before)[:2] == (cached['opened_dev'],cached['opened_ino']) and signature(stat_before)[2:] != (cached['size'],cached['mtime_ns']):
                    raise Blocked('source_file_changed')
                generation = uuid.uuid4().hex
                started = time.monotonic()
                day_count = 0
                with reader:
                    for batch in reader:
                        self._check_budget(started)
                        rows, aliases = [], {}
                        for value in batch:
                            key, day, artifact = source_projection(value, reader.day)
                            rows.append((day,generation,key,value['ann_date'],value['ts_code'],value['name'],
                                         value['title'],value['url'],value['rec_time'],artifact,(value['url'] or '').strip() or None))
                            if value['ts_code'] and value['ts_code'].strip():
                                name = value['name'] or ''
                                alias_key=(value['ts_code'],name)
                                aliases[alias_key]=min(key,aliases.get(alias_key,key))
                        names=[('announcement',code,name,None,self.initials(name,code),normalized_name(name),
                                reader.day,generation,key) for (code,name),key in aliases.items()]
                        self.catalog.add_records(reader.day,generation,rows,names)
                        day_count += len(batch)
                        self.catalog.update_query(query_id, dates_scanned=days, records_scanned=records+day_count)
                    facts = reader.verify()
                    self._check_budget(started)
                    # Replacement remains safe for the pinned reader, but cannot publish a stale live projection.
                    if signature(reader.open_stat) != signature(self.file_stat(self.source.volume, f'ann_date={reader.day}')):
                        raise Blocked('source_file_changed')
                    self.catalog.publish_day(reader.day,generation,facts,reader.open_stat.st_mtime_ns,self.initials.version)
                records += day_count
                days += 1
                self.catalog.update_query(query_id, dates_scanned=days, records_scanned=records)
            if not self.current(start,end):
                raise Blocked('source_file_changed')
            self.catalog.build_progress(query_id,start,end,'completed',None,days,records)
        except BaseException as error:
            self.catalog.build_progress(query_id,start,end,'error',None,days,records,str(error) if isinstance(error,Blocked) else 'catalog_build_failed')
            raise

    def close(self):
        self.source.close()
        self.names_source.close()
