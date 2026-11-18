from contextlib import contextmanager
from time import monotonic, sleep

from sqlalchemy import event, text

from src.foundation.datasets.financial_statement_contracts import (
    FINANCIAL_STATEMENT_MAX_PAGE_BYTES,
    FINANCIAL_STATEMENT_OBSERVATION_TIMEOUT_SECONDS,
    FINANCIAL_STATEMENT_SOURCE_TIMEOUT_SECONDS,
    FINANCIAL_STATEMENT_TRANSACTION_TIMEOUT_SECONDS,
)
from src.foundation.ingestion.errors import IngestionWriteError, StructuredError


class FinancialStatementSourceControl:
    max_response_bytes = FINANCIAL_STATEMENT_MAX_PAGE_BYTES
    source_timeout = FINANCIAL_STATEMENT_SOURCE_TIMEOUT_SECONDS

    def __init__(self, check, publish):
        self._check = check
        self._publish = publish
        self._last_check = float("-inf")
        self._last_report = float("-inf")
        self.page = 0
        self.phase = "取数"

    def check(self, *, force=False):
        now = monotonic()
        if force or now - self._last_check >= FINANCIAL_STATEMENT_OBSERVATION_TIMEOUT_SECONDS:
            self._check()
            self._last_check = now

    def report(self, *, force=False):
        now = monotonic()
        if force or now - self._last_report >= FINANCIAL_STATEMENT_OBSERVATION_TIMEOUT_SECONDS:
            self._publish(self.phase, self.page)
            self._last_report = now

    def fetching(self, page_number, _offset):
        self.check(force=True)
        self.page = page_number
        self.report()

    def wait(self, seconds):
        self.phase = "等待重试"
        self.report(force=True)
        deadline = monotonic() + seconds
        while (remaining := deadline - monotonic()) > 0:
            self.check()
            self.report()
            sleep(min(remaining, FINANCIAL_STATEMENT_OBSERVATION_TIMEOUT_SECONDS))
        self.check(force=True)
        self.phase = "取数"


@contextmanager
def financial_statement_transaction(session, unit_id, check):
    check()
    connection = session.connection()
    postgres = connection.dialect.name == "postgresql"
    if postgres:
        session.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": f"{FINANCIAL_STATEMENT_OBSERVATION_TIMEOUT_SECONDS}s"},
        )
    deadline = monotonic() + FINANCIAL_STATEMENT_TRANSACTION_TIMEOUT_SECONDS

    def remaining_ms():
        check()
        remaining = int((deadline - monotonic()) * 1000)
        if remaining <= 0:
            raise IngestionWriteError(StructuredError(
                error_code="write_failed", error_type="write", phase="writer",
                message="财务报表执行单元超过事务期限，未提交当前单元",
                retryable=True, unit_id=unit_id,
            ))
        return remaining

    def before_sql(_conn, cursor, _statement, _parameters, _context, _executemany):
        remaining = remaining_ms()
        if postgres:
            cursor.execute(f"SET LOCAL statement_timeout = '{remaining}ms'")

    def before_commit(_session):
        remaining_ms()

    event.listen(connection, "before_cursor_execute", before_sql)
    event.listen(session, "before_commit", before_commit)
    try:
        yield
    finally:
        event.remove(session, "before_commit", before_commit)
        event.remove(connection, "before_cursor_execute", before_sql)
