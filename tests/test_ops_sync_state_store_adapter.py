from __future__ import annotations

from datetime import date

from src.ops.models.ops.sync_job_state import SyncJobState
from src.ops.sync_state_store_adapter import OpsSyncJobStateStore


class _FakeSession:
    def __init__(self) -> None:
        self.new: list[object] = []
        self.add_calls = 0

    def get(self, model, key):  # type: ignore[no-untyped-def]
        _ = (model, key)
        return None

    def add(self, item: object) -> None:
        self.add_calls += 1
        self.new.append(item)


def test_ops_job_state_store_reuses_pending_state_between_success_and_full_done() -> None:
    session = _FakeSession()
    store = OpsSyncJobStateStore(session)  # type: ignore[arg-type]

    store.mark_success(
        job_name="sync_stk_mins",
        target_table="raw_tushare.stk_mins",
        last_success_date=date(2026, 4, 24),
    )
    store.mark_full_sync_done(job_name="sync_stk_mins", target_table="raw_tushare.stk_mins")

    assert session.add_calls == 1
    assert len(session.new) == 1
    state = session.new[0]
    assert isinstance(state, SyncJobState)
    assert state.job_name == "sync_stk_mins"
    assert state.target_table == "raw_tushare.stk_mins"
    assert state.full_sync_done is True
