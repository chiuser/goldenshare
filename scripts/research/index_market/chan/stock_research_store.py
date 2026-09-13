"""Bounded, authenticated content-addressed store for the frozen ten-stock research."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


@dataclass(frozen=True)
class StoreSpec:
    root: Path = Path(__file__).resolve().parents[4] / 'reports/stock_chan_research_20260912'
    roles: tuple = ('initial', 'calendar', 'parameters', 'timing', 'exits', 'sell_usage')
    version: int = 1
    record_bytes: int = 20 * 1024**2
    archive_bytes: int = 128 * 1024**2
    catalog_bytes: int = 2 * 1024**2


SPEC = StoreSpec()


def digest(data):
    return hashlib.sha256(data).hexdigest()


class StockResearchStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else SPEC.root
        self._hashes = {}
        receipt = json.loads(self._local('storage_receipt.json', SPEC.catalog_bytes))
        catalog = self._local('catalog.json', SPEC.catalog_bytes)
        archive = self._local('evidence.zip', SPEC.archive_bytes)
        if digest(catalog) != receipt['catalog_sha256'] or digest(archive) != receipt['archive_sha256']:
            raise ValueError('store fingerprint mismatch')
        self.catalog = json.loads(catalog)
        if self.catalog['version'] != SPEC.version or set(self.catalog['sources']) != set(SPEC.roles):
            raise ValueError('store version or roles')
        self.receipt = receipt
        self.consumed = {}

    def _local(self, name, limit):
        path = self.root/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise ValueError('store file missing, redirected or oversized')
        data = path.read_bytes()
        if name in self._hashes and self._hashes[name] != digest(data):
            raise ValueError('store changed during read')
        self._hashes[name] = digest(data)
        return data

    def _entry(self, key):
        key = str(key)
        path = PurePosixPath(key)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in SPEC.roles:
            raise ValueError('invalid store key')
        if key not in self.catalog['records']:
            raise ValueError(f'unknown store record: {key}')
        item = self.catalog['records'][key]
        if not 0 <= item['bytes'] <= SPEC.record_bytes:
            raise ValueError('record budget')
        return item

    def size(self, key):
        return self._entry(key)['bytes']

    def blob(self, key, expected=None):
        item = self._entry(key)
        h = item['sha256']
        if len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise ValueError('invalid object id')
        with ZipFile(self.root/'evidence.zip') as archive:
            info = archive.getinfo(h)
            if info.file_size != item['bytes']:
                raise ValueError('record size mismatch')
            data = archive.read(info)
        if digest(data) != h or (expected is not None and h != expected):
            raise ValueError('record fingerprint mismatch')
        self.consumed[str(key)] = h
        return data

    def read(self, key, expected=None):
        return json.loads(self.blob(key, expected))

    def sha(self, key):
        return digest(self.blob(key))

    def original_path(self, role):
        return self.catalog['sources'][role]

    def verify_code(self, path, expected):
        path = Path(path)
        actual = digest(path.read_bytes())
        if actual == expected:
            return
        migrations = json.loads(self._local('code_migration.json', SPEC.catalog_bytes))
        item = migrations.get(str(path))
        if item is None or item['before'] != expected or item['after'] != actual:
            raise ValueError(f'unapproved producer code change: {path}')

    def verify_unchanged(self):
        for name, expected in self._hashes.items():
            if digest((self.root/name).read_bytes()) != expected:
                raise ValueError('store changed during read')

    def root_key(self, role):
        if role not in SPEC.roles:
            raise ValueError('unknown role')
        return PurePosixPath(role)
