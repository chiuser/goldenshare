from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.errors import ExecutionCanceledError


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
    mocker.patch("src.foundation.services.sync.base_sync_service.DAOFactory", return_value=_build_fake_dao())

    service = _DummySyncService(session)
    result = service.run_incremental(trade_date=date(2026, 2, 25))

    assert result.trade_date == date(2026, 2, 25)
    session.commit.assert_called_once()


def test_sync_service_refreshes_snapshot_on_failure(mocker) -> None:
    session = mocker.Mock()
    mocker.patch("src.foundation.services.sync.base_sync_service.DAOFactory", return_value=_build_fake_dao())

    service = _DummySyncService(session, should_fail=True)

    try:
        service.run_incremental(trade_date=date(2026, 2, 25))
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")

    session.rollback.assert_called_once()
    session.commit.assert_called_once()


def test_sync_service_stops_immediately_when_execution_already_canceled(mocker) -> None:
    session = mocker.Mock()
    fake_dao = _build_fake_dao()
    finish_log = mocker.Mock()
    fake_dao.sync_run_log.finish_log = finish_log
    mocker.patch("src.foundation.services.sync.base_sync_service.DAOFactory", return_value=fake_dao)

    service = _DummySyncService(session)
    mocker.patch.object(service, "ensure_not_canceled", side_effect=ExecutionCanceledError("任务已收到停止请求，正在结束处理。"))

    try:
        service.run_incremental(trade_date=date(2026, 2, 25), execution_id=123)
    except ExecutionCanceledError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Expected ExecutionCanceledError")

    finish_log.assert_called_once()
    assert finish_log.call_args.args[1] == "CANCELED"
    session.rollback.assert_called_once()
    session.commit.assert_called_once()


def test_sync_service_blocks_legacy_raw_schema_routes(mocker) -> None:
    session = mocker.Mock()
    fake_dao = _build_fake_dao()
    fake_dao.raw_daily = SimpleNamespace(
        model=SimpleNamespace(
            __table__=SimpleNamespace(schema="raw"),
        )
    )
    mocker.patch("src.foundation.services.sync.base_sync_service.DAOFactory", return_value=fake_dao)

    try:
        _DummySyncService(session)
    except RuntimeError as exc:
        assert "legacy raw schema route" in str(exc)
        assert "raw_daily" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")
