"""Pinned local Raw snapshot reader and deterministic initials projection."""
import json
import os
import re
import stat
import unicodedata
from pathlib import Path

from .core import Blocked, identity
from .source import DayReader

NAME_ROOT = Path('/Volumes/datasource/data_lake/raw/tushare')
INITIALS_FILE = Path(__file__).resolve().parents[4] / 'config/wealth/announcement-name-initials.json'


def normalized_name(value):
    return unicodedata.normalize('NFC', value or '').strip().casefold()


class NameInitials:
    def __init__(self, path=INITIALS_FILE):
        try:
            from pypinyin import lazy_pinyin, Style
        except ImportError:
            raise Blocked('source_pypinyin_required') from None
        self.convert, self.style = lazy_pinyin, Style.FIRST_LETTER
        self.path=Path(path)
        try:
            raw = json.loads(self.path.read_text())
        except (OSError,ValueError):
            raise Blocked('initials_dictionary_invalid') from None
        if set(raw) != {'version', 'overrides'} or not isinstance(raw['version'], int):
            raise Blocked('initials_dictionary_invalid')
        self.overrides = {}
        for item in raw['overrides']:
            if (not {'name', 'initials'} <= set(item) <= {'name', 'initials', 'tsCode'}
                    or not re.fullmatch('[A-Z0-9]+', item['initials'])):
                raise Blocked('initials_dictionary_invalid')
            key = (item.get('tsCode'), normalized_name(item['name']))
            if key in self.overrides:
                raise Blocked('initials_dictionary_invalid')
            self.overrides[key] = item['initials']
        self.version = identity([str(raw['version']), json.dumps(raw, sort_keys=True, ensure_ascii=False)])

    def __call__(self, name, ts_code=None, cnspell=None):
        if cnspell and cnspell.strip():
            return ''.join(c for c in unicodedata.normalize('NFC',cnspell).upper() if c.isascii() and c.isalnum()) or None
        normalized = normalized_name(name)
        override = self.overrides.get((ts_code, normalized), self.overrides.get((None, normalized)))
        if override:
            return override
        text = unicodedata.normalize('NFC', name or '')
        result = ''.join(self.convert(text, style=self.style, errors=lambda value: list(value))).upper()
        return ''.join(c for c in result if c.isascii() and c.isalnum()) or None


class NameSnapshot(DayReader):
    """Only requested columns; FD pinned, bounded reads and two content fingerprints."""
    def __init__(self, source, kind):
        super().__init__(source, '')
        self.kind = kind
        self.columns = ('ts_code', 'name', 'cnspell') if kind == 'stock_basic' else ('ts_code', 'name')

    def __enter__(self):
        try:
            self.source.assert_valid(full=True)
            try:
                with self.source.volume.directory(f'{self.kind}/full') as directory:
                    self.fd = os.open('part-000.parquet', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                raise Blocked('source_names_missing') from None
            self.open_stat = os.fstat(self.fd)
            if not stat.S_ISREG(self.open_stat.st_mode) or self.open_stat.st_dev != self.source.volume.device:
                raise Blocked('source_file_not_regular')
            self.fd_path = f'/dev/fd/{self.fd}'
            self.connection = self.source.connect()
            # Ignore unrelated Raw columns, never infer requested fields from hive paths.
            schema = self._metadata('SELECT name,duckdb_type FROM parquet_schema(?) WHERE num_children IS NULL', 128)
            mapping = dict(schema)
            if any(mapping.get(column) != 'VARCHAR' for column in self.columns):
                raise Blocked('source_file_schema')
            count = self._metadata('SELECT num_rows FROM parquet_file_metadata(?)', 2)
            if len(count) != 1 or count[0][0] < 0:
                raise Blocked('source_footer_invalid')
            digest, size = self._fingerprint()
            self.facts = dict(opened_dev=self.open_stat.st_dev, opened_ino=self.open_stat.st_ino,
                              size=size, sha256=digest, footer_count=count[0][0])
            return self
        except BaseException:
            self.close()
            raise

    def __iter__(self):
        self._call(lambda: self.connection.execute(
            'SELECT ' + ','.join(self.columns) + ' FROM read_parquet(?,hive_partitioning=false)', [self.fd_path]))
        while True:
            self.source.control.check()
            self.source.assert_valid()
            values = self._call(lambda: self.connection.fetchmany(self.source.policy.batch_size))
            if not values:
                break
            self.rows_read += len(values)
            yield [dict(zip(self.columns, value)) for value in values]
