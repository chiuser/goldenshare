"""Frozen schema-1 startup from 777d6901; only tests old-program refusal after upgrade."""
from pathlib import Path
import sqlite3
from src.foundation.clients.announcement_archive.core import Blocked, timestamp
SCHEMA = (Path(__file__).with_name('announcement_download_schema_v1.sql')).read_text()


class Ledger:
    def __init__(self, path: Path, volume_uuid: str, relative_root: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute('PRAGMA journal_mode=DELETE')
            self.conn.execute('PRAGMA synchronous=FULL')
            self.conn.executescript(SCHEMA)
            if "missing_url_count" not in {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}:
                self.conn.execute("ALTER TABLE runs ADD COLUMN missing_url_count INTEGER NOT NULL DEFAULT 0")
            with self.conn:
                self.conn.execute('INSERT OR IGNORE INTO archive VALUES(1,1,?,?,?)',
                                  (volume_uuid, relative_root, timestamp()))
                existing = self.conn.execute('SELECT * FROM archive').fetchone()
                if (existing['schema_version'] != 1 or existing['volume_uuid'] != volume_uuid
                        or existing['root_relative_path'] != relative_root):
                    raise Blocked('archive_identity_mismatch')
                self.conn.execute('INSERT OR IGNORE INTO cooldown(singleton) VALUES(1)')
        except BaseException:
            self.conn.close()
            raise
