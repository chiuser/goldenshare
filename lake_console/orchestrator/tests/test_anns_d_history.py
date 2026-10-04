from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from unittest.mock import MagicMock

import pytest

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementControl,
)
from orchestrator.defs.anns_d_contract import AnnouncementCancelled, AnnouncementError
from orchestrator.defs.bootstrap.anns_d_history import (
    build_announcement_month,
    capture_announcement_month,
    promote_announcement_month,
)
from orchestrator.defs.prod_db.anns_d import (
    AnnouncementHistorySource,
    announcement_history_query,
)
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import checkpoint, source_row


class FakeResource:
    def __init__(self, records, expected=None):
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.named = MagicMock()
        self.connection.cursor.side_effect = lambda name=None: (
            self.named if name else self.cursor
        )
        self.cursor.__enter__.return_value = self.cursor
        self.named.__enter__.return_value = self.named
        self.cursor.fetchone.return_value = (
            len(records) if expected is None else expected,
        )
        self.named.fetchmany.side_effect = [records, []]
        self.closed = False

    @contextmanager
    def connect_readonly_transaction(self):
        try:
            yield self.connection
        finally:
            self.closed = True


def prod_record(raw_id=1, **values):
    row = source_row(**values)
    return (raw_id, date.fromisoformat(row["ann_date"]), *row.values(), True)


def test_sql_fixed_whitelist_and_date_first_order():
    sql, params = announcement_history_query("2023-06-09", 20)
    assert (
        "ORDER BY ann_date, id" in sql and "SELECT *" not in sql and "ops." not in sql
    )
    assert params == {
        "month_start": date(2023, 6, 1),
        "month_end": date(2023, 7, 1),
        "upper_id": 20,
    }
    assert "raw_payload::jsonb ?&" in sql and "AS keys_present" in sql
    for month, upper in [("2026-10-01", 20), ("2023-06-09", -1), ("bad", 20)]:
        with pytest.raises(AnnouncementError):
            announcement_history_query(month, upper)


def test_server_cursor_readonly_setup_fetch_bounds(archive):
    resource = FakeResource([prod_record()])
    source = AnnouncementHistorySource(resource, archive.policy)
    plan = []
    assert list(
        source.batches("2023-06-01", 20, archive.control, on_plan=plan.append)
    ) == [[source_row()]]
    statements = [call.args[0] for call in resource.cursor.execute.call_args_list]
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert "cursor_tuple_fraction" in statements[2]
    assert resource.named.fetchmany.call_args.args == (10000,) and resource.closed
    assert plan[0]["expected_rows"] == 1


@pytest.mark.parametrize(
    "records,expected",
    [
        ([prod_record(), prod_record()], 2),
        ([prod_record()], 2),
        ([(*prod_record()[:-1], False)], 1),
    ],
)
def test_invalid_key_order_and_count_block(archive, records, expected):
    with pytest.raises(AnnouncementError):
        list(
            AnnouncementHistorySource(
                FakeResource(records, expected), archive.policy
            ).batches("2023-06-01", 20, archive.control)
        )


def test_history_budget_cancel_and_generator_close(archive):
    resource = FakeResource([prod_record()], expected=2)
    with pytest.raises(AnnouncementError, match="month_budget"):
        list(
            AnnouncementHistorySource(
                resource, replace(archive.policy, max_month_rows=1)
            ).batches("2023-06-01", 20, archive.control)
        )
    resource = FakeResource([prod_record()])
    iterator = AnnouncementHistorySource(resource, archive.policy).batches(
        "2023-06-01", 20, archive.control
    )
    assert next(iterator) == [source_row()]
    iterator.close()
    assert resource.closed
    with pytest.raises(AnnouncementCancelled):
        list(
            AnnouncementHistorySource(FakeResource([]), archive.policy).batches(
                "2023-06-01", 20, AnnouncementControl(cancelled=lambda: True)
            )
        )


def test_month_zero_days_capture_build_and_partial_promote_resume(archive):
    class Source:
        calls = 0

        def batches(self, month, upper, control, on_plan):
            self.calls += 1
            on_plan({"expected_rows": 2})
            yield [source_row(), source_row()]

    source = Source()
    cp = AnnouncementCheckpoint(archive.directory / "month.json", {"month": "2023-06"})
    pages = capture_announcement_month(
        "2023-06-01", source, 20, archive, cp, archive.control
    )
    assert (
        capture_announcement_month(
            "2023-06-01", source, 20, archive, cp, archive.control
        )
        == pages
        and source.calls == 1
    )
    deliveries = build_announcement_month(
        "2023-06-01", pages, archive, cp, archive.control
    )
    assert (
        len(deliveries) == 30
        and sum(x["written_rows"] for x in deliveries.values()) == 1
    )

    def emit(event):
        if event.get("phase") == "promoted":
            archive.control.cancelled = lambda: True

    archive.control.emit = emit
    with pytest.raises(AnnouncementCancelled):
        promote_announcement_month(
            deliveries, archive, lambda day: checkpoint(archive, day), archive.control
        )
    assert len(list(archive.root.glob("raw/tushare/anns_d/*/*.parquet"))) == 1
    archive.control.cancelled = lambda: False
    archive.control.emit = lambda *_: None
    promote_announcement_month(
        deliveries, archive, lambda day: checkpoint(archive, day), archive.control
    )
    assert len(list(archive.root.glob("raw/tushare/anns_d/*/*.parquet"))) == 30


def test_bootstrap_target_conflict_never_merges(archive):
    page = archive.write_page(
        [source_row()], archive.directory / "old.parquet", archive.control
    )
    archive.promote_day(
        "2023-06-09", archive.build_day("2023-06-09", [page]), checkpoint(archive)
    )
    changed = archive.write_page(
        [source_row(url="changed")],
        archive.directory / "different.parquet",
        archive.control,
    )
    with pytest.raises(AnnouncementError, match="bootstrap_target_conflict"):
        archive.build_day("2023-06-09", [changed], bootstrap=True)


archive = _archive_fixture


def test_cancel_during_blocked_query_calls_libpq_cancel(archive):
    import threading
    import time

    resource = FakeResource([])
    cancelled = threading.Event()
    started = time.monotonic()
    control = AnnouncementControl(cancelled=lambda: time.monotonic() - started > 0.15)
    resource.connection.cancel.side_effect = cancelled.set

    def execute(sql, params=None):
        if sql.startswith("SELECT count"):
            assert cancelled.wait(2)
            raise RuntimeError("fake postgres query cancelled")

    resource.cursor.execute.side_effect = execute
    with pytest.raises(AnnouncementCancelled):
        list(
            AnnouncementHistorySource(resource, archive.policy).batches(
                "2023-06-01", 20, control
            )
        )
    assert resource.connection.cancel.called and resource.closed


def test_bad_prod_row_retains_business_sample_without_raw_payload(archive):
    import json

    resource = FakeResource([prod_record(url=123)])
    source = AnnouncementHistorySource(resource, archive.policy)
    cp = AnnouncementCheckpoint(
        archive.directory / "rejected-month.json", {"month": "2023-06"}
    )
    with pytest.raises(AnnouncementError, match="source_type"):
        capture_announcement_month(
            "2023-06-01", source, 20, archive, cp, archive.control
        )
    files = list(archive.directory.glob("month-*/rejected-row.json"))
    assert len(files) == 1
    evidence = json.loads(files[0].read_text())
    assert evidence["fields"]["url"] == 123 and "raw_payload" not in evidence
    assert cp.document["phase"] == "failed" and not cp.document["capture_complete"]
