"""An independent, loopback-only archive pool. Creating it never creates tables."""
from contextlib import contextmanager
import ipaddress

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from src.foundation.clients.announcement_archive.core import Blocked
from src.foundation.config.announcement_archive import ArchiveDatabasePolicy, announcements_enabled


def guarded_url(value, policy=ArchiveDatabasePolicy()):
    if not value:
        raise Blocked('archive_database_config_missing')
    try:
        url = make_url(value)
        host = url.host
        if host == 'localhost':
            host = '127.0.0.1'
        if (url.drivername != 'postgresql+psycopg' or url.query
                or not ipaddress.ip_address(host).is_loopback
                or url.port != policy.port or url.database != policy.database):
            raise ValueError
        return url.set(host=host)
    except (ValueError, TypeError, SQLAlchemyError):
        raise Blocked('archive_database_config_invalid') from None


class ArchiveDatabase:
    def __init__(self, value, policy=ArchiveDatabasePolicy()):
        if policy.schema != 'announcement_archive':
            raise ValueError('archive_schema_fixed')
        self.policy = policy
        url = guarded_url(value, policy)
        self.engine = create_engine(url, pool_size=policy.pool_size, max_overflow=0,
            pool_timeout=policy.pool_seconds, pool_pre_ping=True,
            connect_args={'connect_timeout': policy.connect_seconds})

        @event.listens_for(self.engine, 'connect')
        def guard_peer(connection, _record):
            # Autocommit prevents SET/peer inspection from leaving a hidden transaction.
            connection.autocommit = True
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT host(inet_server_addr()),current_database()')
                    peer, database = cursor.fetchone()
                    if not peer or not ipaddress.ip_address(peer).is_loopback or database != policy.database:
                        raise Blocked('archive_database_peer_invalid')
                    cursor.execute("SELECT set_config('lock_timeout',%s,false),"
                                   "set_config('statement_timeout',%s,false)",
                                   (str(policy.lock_milliseconds), str(policy.statement_milliseconds)))
            finally:
                connection.autocommit = False

    @contextmanager
    def transaction(self, *, read_only=False):
        try:
            with self.engine.begin() as connection:
                if read_only:
                    connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                yield connection
        except SQLAlchemyError:
            raise Blocked('archive_database_unavailable') from None

    def close(self):
        self.engine.dispose()


def configured_archive_database(settings, policy=ArchiveDatabasePolicy()):
    """Composition helper; disabled/Prod deployments allocate no archive pool."""
    if not announcements_enabled(settings):
        return None
    return ArchiveDatabase(settings.announcement_archive_database_url, policy)
