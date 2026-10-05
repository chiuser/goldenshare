"""Announcement-only read contract, month snapshot and server-side batches."""

import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, timedelta

from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementError,
    announcement_date,
    normalize_announcement_rows,
)


def announcement_month_bounds(day):
    parsed = announcement_date(day).replace(day=1)
    end = (parsed.replace(day=28) + timedelta(days=4)).replace(day=1)
    if parsed < date(2020, 1, 1) or end > date(2026, 10, 1):
        raise AnnouncementError("announcement_bootstrap_range")
    return parsed, end


def announcement_history_query(day, upper_id):
    first, end = announcement_month_bounds(day)
    if isinstance(upper_id, bool) or not isinstance(upper_id, int) or upper_id < 0:
        raise AnnouncementError("announcement_invalid_upper_id")
    projections = ", ".join(
        f"raw_payload::jsonb -> '{field}' AS {field}" for field in ANNOUNCEMENT_FIELDS
    )
    key_list = ", ".join(f"'{field}'" for field in ANNOUNCEMENT_FIELDS)
    sql = (
        f"SELECT id, ann_date AS partition_date, {projections}, "
        f"(raw_payload::jsonb ?& ARRAY[{key_list}] AND (raw_payload::jsonb - ARRAY[{key_list}]) = '{{}}'::jsonb) AS keys_present "
        "FROM raw_tushare.anns_d "
        "WHERE ann_date >= %(month_start)s AND ann_date < %(month_end)s "
        "AND id <= %(upper_id)s ORDER BY ann_date, id"
    )
    return sql, {"month_start": first, "month_end": end, "upper_id": upper_id}


class AnnouncementHistorySource:
    def __init__(self, resource, policy):
        self.resource, self.policy = resource, policy

    def inventory(self, start, end, control):
        first, _ = announcement_month_bounds(start)
        _, last = announcement_month_bounds(end)
        if first.isoformat() != start or (last - timedelta(days=1)).isoformat() != end:
            raise AnnouncementError("announcement_bootstrap_full_months_required")
        started = time.monotonic()
        rows = []
        with (
            self.resource.connect_readonly_transaction() as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute(
                "SET LOCAL statement_timeout = %s", (self.policy.sql_timeout_ms,)
            )
            with self.observed_read(connection, control, started):
                cursor.execute(
                    "SELECT ann_date, count(*), max(id) FROM raw_tushare.anns_d "
                    "WHERE ann_date >= %(start)s AND ann_date < %(end)s "
                    "GROUP BY ann_date ORDER BY ann_date",
                    {"start": first, "end": last},
                )
            while True:
                control.check()
                with self.observed_read(connection, control, started):
                    batch = cursor.fetchmany(256)
                if not batch:
                    break
                rows.extend(
                    {"day": day.isoformat(), "rows": count, "upper_id": upper}
                    for day, count, upper in batch
                )
                if len(rows) > 2465:
                    raise AnnouncementError("announcement_inventory_budget")
        return rows

    def batches(self, month, upper_id, control, on_plan=lambda summary: None):
        sql, params = announcement_history_query(month, upper_id)
        started = time.monotonic()
        with self.resource.connect_readonly_transaction() as connection:
            # The resource has already established read-only before any business read.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                cursor.execute(
                    "SET LOCAL statement_timeout = %s", (self.policy.sql_timeout_ms,)
                )
                cursor.execute("SET LOCAL cursor_tuple_fraction = 1.0")
                control.check()
                with self.observed_read(connection, control, started):
                    cursor.execute(
                        "SELECT count(*) FROM raw_tushare.anns_d "
                        "WHERE ann_date >= %(month_start)s AND ann_date < %(month_end)s "
                        "AND id <= %(upper_id)s",
                        params,
                    )
                expected = cursor.fetchone()[0]
                if expected > self.policy.max_month_rows:
                    raise AnnouncementError("announcement_month_budget")
                on_plan(
                    {
                        "expected_rows": expected,
                        **{k: str(v) for k, v in params.items()},
                    }
                )
            with connection.cursor(name="anns_" + uuid.uuid4().hex) as cursor:
                cursor.itersize = self.policy.prod_fetch_rows
                with self.observed_read(connection, control, started):
                    cursor.execute(sql, params)
                count, previous = 0, None
                while True:
                    control.check()
                    if time.monotonic() - started >= self.policy.month_deadline:
                        raise AnnouncementError("announcement_month_timeout")
                    with self.observed_read(connection, control, started):
                        records = cursor.fetchmany(self.policy.prod_fetch_rows)
                    control.check()
                    if not records:
                        break
                    batch = []
                    for record in records:
                        raw_id, partition_date, *values, keys_present = record
                        row = dict(zip(ANNOUNCEMENT_FIELDS, values, strict=True))
                        sample = {
                            "raw_id": raw_id,
                            "partition_date": str(partition_date),
                            "fields": row,
                        }
                        key = (partition_date, raw_id)
                        if not keys_present or (
                            previous is not None and key <= previous
                        ):
                            raise AnnouncementError(
                                "announcement_history_identity", source_sample=sample
                            )
                        previous = key
                        try:
                            batch.extend(
                                normalize_announcement_rows(
                                    [row], day=partition_date.isoformat()
                                )
                            )
                        except AnnouncementError as error:
                            error.source_sample = sample
                            raise
                    count += len(batch)
                    if count > expected or count > self.policy.max_month_rows:
                        raise AnnouncementError("announcement_history_row_count")
                    control.progress(
                        phase="capturing",
                        month=month,
                        rows_captured=count,
                        source_rows=expected,
                    )
                    yield batch
                if count != expected:
                    raise AnnouncementError("announcement_history_row_count")

    def _observe_fetch(self, connection, control, stopped, started):
        while not stopped.wait(0.1):
            if (
                control.cancelled()
                or time.monotonic() - started >= self.policy.month_deadline
            ):
                connection.cancel()
                return
            if time.monotonic() - control.last_report >= 5:
                control.progress(phase="source_fetch")

    @contextmanager
    def observed_read(self, connection, control, started):
        control.check()
        stopped = threading.Event()
        monitor = threading.Thread(
            target=self._observe_fetch,
            args=(connection, control, stopped, started),
            daemon=True,
        )
        monitor.start()
        try:
            yield
        except Exception:  # noqa: BLE001 -- Translate database failures into safe source reason codes.
            control.check()
            if time.monotonic() - started >= self.policy.month_deadline:
                raise AnnouncementError("announcement_month_timeout") from None
            raise AnnouncementError("announcement_history_read_failed") from None
        finally:
            stopped.set()
            monitor.join(timeout=1)
        control.check()
        if time.monotonic() - started >= self.policy.month_deadline:
            raise AnnouncementError("announcement_month_timeout")
