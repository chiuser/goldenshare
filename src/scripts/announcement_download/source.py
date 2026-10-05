from __future__ import annotations

import hashlib
import math
import os
import stat
import threading
import time
from datetime import timedelta
from pathlib import Path

from .core import (
    ANNOUNCEMENT_FIELDS, SOURCE_CONTRACT_VERSION, Blocked, Cancelled, Control,
    DownloadOptions, DownloadPolicy, identity, source_projection,
)
from .volume import SourceVolume


RAW_ROOT = Path('/Volumes/datasource/data_lake/raw/tushare/anns_d')
COLUMNS_SQL = ', '.join(ANNOUNCEMENT_FIELDS)


class Source:
    """One pinned day at a time. No database, Dagster or Tushare connection."""

    def __init__(self, options: DownloadOptions, policy: DownloadPolicy, control: Control,
                 volume: SourceVolume | None = None):
        self.options, self.policy, self.control = options, policy, control
        if (not 0 < policy.batch_size <= 500 or policy.source_threads != 1
                or not math.isfinite(policy.source_query_timeout_seconds)
                or policy.source_query_timeout_seconds <= 0):
            raise Blocked('source_policy_invalid')
        self.volume = volume or SourceVolume(RAW_ROOT, policy)
        self.active_day = None
        try:
            import duckdb
        except ImportError:
            raise Blocked('source_duckdb_required') from None
        self.duckdb = duckdb
        self.config = dict(memory_limit=policy.source_memory_limit, threads=policy.source_threads,
                           max_temp_directory_size='0B', autoinstall_known_extensions=False,
                           autoload_known_extensions=False)

    def open(self):
        try:
            self.volume.open()
            connection = self.connect()
            connection.close()
            self.scope = 'dg-anns-d:' + identity([
                self.volume.volume_uuid, self.volume.relative_root, str(SOURCE_CONTRACT_VERSION)])
            return self
        except BaseException:
            self.close()
            raise

    def connect(self):
        try:
            return self.duckdb.connect(database=':memory:', config=self.config)
        except self.duckdb.Error:
            raise Blocked('source_duckdb_configuration') from None

    def iter_days(self):
        day = self.options.start_date
        while day <= self.options.end_date:
            self.control.check()
            reader = DayReader(self, day.isoformat())
            self.active_day = reader
            try:
                yield reader
            finally:
                reader.close()
                self.active_day = None
            if day == self.options.end_date:
                break
            day += timedelta(days=1)

    def assert_valid(self, full=False):
        self.volume.assert_valid(full=full)

    def close(self):
        if self.active_day:
            self.active_day.close()
        self.volume.close()


class DayReader:
    def __init__(self, source: Source, day: str):
        self.source, self.day = source, day
        self.fd = -1
        self.connection = None
        self.rows_read = 0

    def _call(self, operation):
        """Interrupt while the main thread is blocked inside DuckDB, then join before close."""
        self.source.control.check()
        finished = threading.Event()
        timed_out = threading.Event()
        deadline = time.monotonic() + self.source.policy.source_query_timeout_seconds

        def watch():
            while not finished.wait(min(self.source.policy.wait_slice, .05)):
                if self.source.control.stop.is_set() or time.monotonic() >= deadline:
                    if not self.source.control.stop.is_set():
                        timed_out.set()
                    self.connection.interrupt()
                    return

        watcher = threading.Thread(target=watch, name='announcement-source-watchdog')
        watcher.start()
        try:
            try:
                result = operation()
            except self.source.duckdb.Error:
                if self.source.control.stop.is_set():
                    raise Cancelled('user_cancelled') from None
                if timed_out.is_set():
                    raise Blocked('source_query_timeout') from None
                raise Blocked('source_read_failed') from None
            self.source.control.check()
            if timed_out.is_set() or time.monotonic() >= deadline:
                raise Blocked('source_query_timeout')
            return result
        finally:
            finished.set()
            watcher.join()

    def _metadata(self, query, limit):
        def read():
            return self.connection.execute(query, [self.fd_path]).fetchmany(limit)
        return self._call(read)

    def _fingerprint(self):
        digest, offset = hashlib.sha256(), 0
        while True:
            self.source.control.check()
            self.source.assert_valid()
            chunk = os.pread(self.fd, self.source.policy.chunk_size, offset)
            if not chunk:
                break
            digest.update(chunk)
            offset += len(chunk)
        return digest.hexdigest(), offset

    @staticmethod
    def _content_stat(value):
        # Atomic replace unlinks the old inode: nlink/ctime are allowed to change.
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    def __enter__(self):
        try:
            self.source.assert_valid(full=True)
            self.source.control.update(source_stage='opening', current_day=self.day)
            try:
                with self.source.volume.directory(f'ann_date={self.day}') as directory:
                    self.fd = os.open('part-000.parquet', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                      dir_fd=directory)
            except FileNotFoundError:
                raise Blocked('source_day_missing') from None
            self.open_stat = os.fstat(self.fd)
            if not stat.S_ISREG(self.open_stat.st_mode):
                raise Blocked('source_file_not_regular')
            if self.open_stat.st_dev != self.source.volume.device:
                raise Blocked('source_file_device_changed')
            self.fd_path = f'/dev/fd/{self.fd}'
            self.connection = self.source.connect()
            schema = self._metadata('SELECT name,duckdb_type,num_children FROM parquet_schema(?)', 8)
            expected = [('duckdb_schema', None, 6), *((name, 'VARCHAR', None) for name in ANNOUNCEMENT_FIELDS)]
            # Root node names differ by writer; leaf names/order/types must match exactly.
            if (len(schema) != 7 or schema[0][2] != 6 or schema[1:] != expected[1:]):
                raise Blocked('source_file_schema')
            count = self._metadata('SELECT num_rows FROM parquet_file_metadata(?)', 2)
            if len(count) != 1 or not isinstance(count[0][0], int) or count[0][0] < 0:
                raise Blocked('source_footer_invalid')
            self.source.control.update(source_stage='fingerprinting', current_day=self.day)
            digest, size = self._fingerprint()
            if size != self.open_stat.st_size:
                raise Blocked('source_file_changed')
            self.facts = dict(opened_dev=self.open_stat.st_dev, opened_ino=self.open_stat.st_ino,
                              size=size, sha256=digest, footer_count=count[0][0])
            return self
        except BaseException:
            self.close()
            raise

    def __iter__(self):
        self.source.control.update(source_stage='reading', current_day=self.day)
        self._call(lambda: self.connection.execute(
            f'SELECT {COLUMNS_SQL} FROM read_parquet(?,hive_partitioning=false)', [self.fd_path]))
        while True:
            self.source.control.check()
            self.source.assert_valid(full=True)
            values = self._call(lambda: self.connection.fetchmany(self.source.policy.batch_size))
            if not values:
                break
            rows = [dict(zip(ANNOUNCEMENT_FIELDS, row)) for row in values]
            for row in rows:
                source_projection(row, self.day)
            del values
            self.rows_read += len(rows)
            yield rows
            del rows
            self.source.control.check()
            self.source.assert_valid(full=True)

    def verify(self):
        self.source.control.update(source_stage='verifying', current_day=self.day)
        digest, size = self._fingerprint()
        if (digest != self.facts['sha256'] or size != self.facts['size']
                or self._content_stat(self.open_stat) != self._content_stat(os.fstat(self.fd))):
            raise Blocked('source_file_changed')
        if self.rows_read != self.facts['footer_count']:
            raise Blocked('source_row_count_mismatch')
        self.source.assert_valid(full=True)
        return self.facts

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __exit__(self, *_):
        self.close()
