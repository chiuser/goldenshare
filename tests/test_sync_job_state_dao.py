from __future__ import annotations

from datetime import date

from src.dao.sync_job_state_dao import SyncJobStateDAO


def test_mark_success_preserves_full_sync_done_for_existing_record(mocker) -> None:
    session = mocker.Mock()
    dao = SyncJobStateDAO(session)
    existing = mocker.Mock()
    existing.full_sync_done = True
    mocker.patch.object(dao, "fetch_by_pk", return_value=existing)
    bulk_upsert = mocker.patch.object(dao, "bulk_upsert")

    dao.mark_success("job_a", "core.table_a", last_success_date=date(2026, 3, 24))

    row = bulk_upsert.call_args.args[0][0]
    assert row["job_name"] == "job_a"
    assert row["target_table"] == "core.table_a"
    assert row["last_success_date"] == date(2026, 3, 24)
    assert "full_sync_done" not in row


def test_mark_success_initializes_full_sync_done_for_new_record(mocker) -> None:
    session = mocker.Mock()
    dao = SyncJobStateDAO(session)
    mocker.patch.object(dao, "fetch_by_pk", return_value=None)
    bulk_upsert = mocker.patch.object(dao, "bulk_upsert")

    dao.mark_success("job_b", "core.table_b")

    row = bulk_upsert.call_args.args[0][0]
    assert row["full_sync_done"] is False
