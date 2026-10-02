from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.foundation.config.settings import _load_env_file_values, get_settings
from src.foundation.datasets.registry import get_dataset_definition

from .core import Blocked, DownloadOptions, DownloadPolicy


BATCH_SQL = '''SELECT id,row_key_hash,ann_date,ts_code,title,url,rec_time
FROM raw_tushare.anns_d
WHERE ann_date >= :start_date AND ann_date <= :end_date
AND id > :after_id AND id <= :upper_id ORDER BY id LIMIT :batch_size'''


def configured_database() -> tuple[str, str]:
    path = os.environ.get('GOLDENSHARE_ENV_FILE', '.env').strip() or '.env'
    values = _load_env_file_values(path)
    explicit = values.get('DATABASE_URL', os.environ.get('DATABASE_URL', ''))
    if not explicit.strip():
        raise Blocked('explicit_DATABASE_URL_required')
    url = get_settings().database_url
    parsed = make_url(url)
    if parsed.get_backend_name() != 'postgresql':
        raise Blocked('postgresql_required')
    # No username/password/query in the persisted source identity.
    scope = f'{parsed.host}:{parsed.port or 5432}/{parsed.database}/raw_tushare.anns_d'
    return url, scope


class Source:
    def __init__(self, url: str, options: DownloadOptions, policy: DownloadPolicy):
        definition = get_dataset_definition('anns_d')
        if (definition.storage.raw_table != 'raw_tushare.anns_d'
                or definition.date_model.observed_field != 'ann_date'):
            raise Blocked('dataset_contract_changed')
        self.options, self.policy = options, policy
        self.engine = create_engine(url, connect_args={'connect_timeout': int(policy.connect_timeout)}, pool_pre_ping=False)

    @contextmanager
    def transaction(self):
        with self.engine.connect() as connection:
            with connection.begin():
                connection.execute(text('SET TRANSACTION READ ONLY'))
                connection.execute(text("SELECT set_config('statement_timeout', :value, true)"),
                                   {'value': str(self.policy.db_timeout_ms)})
                yield connection

    def upper_id(self):
        with self.transaction() as conn:
            return conn.execute(text('SELECT id FROM raw_tushare.anns_d ORDER BY id DESC LIMIT 1')).scalar() or 0

    def batch(self, after_id: int, upper_id: int) -> list[dict]:
        with self.transaction() as conn:
            result = conn.execute(text(BATCH_SQL), dict(start_date=self.options.start_date,
                end_date=self.options.end_date, after_id=after_id, upper_id=upper_id,
                batch_size=self.policy.batch_size))
            return [dict(row) for row in result.mappings()]

    def has_artifact(self, task: dict) -> bool:
        # IDs can disappear after physical reconciliation; file identity stays stable.
        with self.transaction() as conn:
            return conn.execute(text("""SELECT 1 FROM raw_tushare.anns_d
                WHERE ann_date=:day AND ts_code=:code AND url=:url LIMIT 1"""),
                dict(day=task['ann_date'], code=task['ts_code'], url=task['url'])).first() is not None

    def close(self):
        self.engine.dispose()
