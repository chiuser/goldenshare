from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.services.sync.base_sync_service import BaseSyncService


class _DummySyncService(BaseSyncService):
    job_name = "sync_dc_index"
    target_table = "core.dc_index"

    def __init__(self, session, should_fail: bool = False) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.should_fail = should_fail

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        if self.should_fail:
            raise RuntimeError("boom")
        return 1, 1, date(2026, 2, 25), "ok"


def _build_fake_dao() -> SimpleNamespace:
    return SimpleNamespace(
        sync_run_log=SimpleNamespace(
            start_log=lambda *args, **kwargs: object(),
            finish_log=lambda *args, **kwargs: None,
        ),
        sync_job_state=SimpleNamespace(
            mark_success=lambda *args, **kwargs: None,
            mark_full_sync_done=lambda *args, **kwargs: None,
        ),
    )


def test_sync_service_refreshes_snapshot_on_success(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.services.sync.base_sync_service.DAOFactory", return_value=_build_fake_dao())
    snapshot_service_cls = mocker.patch("src.operations.services.dataset_status_snapshot_service.DatasetStatusSnapshotService")
    snapshot_service = snapshot_service_cls.return_value

    service = _DummySyncService(session)
    result = service.run_incremental(trade_date=date(2026, 2, 25))

    assert result.trade_date == date(2026, 2, 25)
    snapshot_service.refresh_resources.assert_called_once_with(session, ["dc_index"])


def test_sync_service_refreshes_snapshot_on_failure(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.services.sync.base_sync_service.DAOFactory", return_value=_build_fake_dao())
    snapshot_service_cls = mocker.patch("src.operations.services.dataset_status_snapshot_service.DatasetStatusSnapshotService")
    snapshot_service = snapshot_service_cls.return_value

    service = _DummySyncService(session, should_fail=True)

    try:
        service.run_incremental(trade_date=date(2026, 2, 25))
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")

    snapshot_service.refresh_resources.assert_called_once_with(session, ["dc_index"])
