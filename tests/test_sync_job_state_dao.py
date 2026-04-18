from __future__ import annotations

from datetime import date

from src.foundation.dao.sync_job_state_dao import SyncJobStateDAO


def test_mark_success_uses_upsert_that_preserves_existing_full_sync_done(mocker) -> None:
    session = mocker.Mock()
    dao = SyncJobStateDAO(session)

    dao.mark_success("job_a", "core.table_a", last_success_date=date(2026, 3, 24))

    statement = str(session.execute.call_args.args[0])
    params = session.execute.call_args.args[1]
    assert "ON CONFLICT (job_name) DO UPDATE" in statement
    assert "full_sync_done = ops.sync_job_state.full_sync_done" in statement
    assert params["job_name"] == "job_a"
    assert params["target_table"] == "core.table_a"
    assert params["last_success_date"] == date(2026, 3, 24)


def test_mark_success_initializes_new_row_full_sync_done_false(mocker) -> None:
    session = mocker.Mock()
    dao = SyncJobStateDAO(session)

    dao.mark_success("job_b", "core.table_b")

    statement = str(session.execute.call_args.args[0])
    assert "full_sync_done" in statement
    assert "false" in statement.lower()
