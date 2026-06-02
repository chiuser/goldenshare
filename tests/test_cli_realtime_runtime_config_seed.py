from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def test_cli_ops_seed_realtime_runtime_config_dry_run(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        created_count=2,
        skipped_count=0,
        items=[
            mocker.Mock(object_key="stock_rt_daily", status="create", object_kind="collector_feed"),
            mocker.Mock(object_key="stock_rt_min", status="create", object_kind="feed_group"),
        ],
    )
    mocker.patch("src.cli.RealtimeRuntimeConfigSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-realtime-runtime-config"])

    assert result.exit_code == 0
    assert "ops-seed-realtime-runtime-config [dry-run]" in result.stdout
    assert "created=2" in result.stdout
    assert "skipped=0" in result.stdout
    service.run.assert_called_once_with(session, dry_run=True)


def test_cli_ops_seed_realtime_runtime_config_apply(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        created_count=0,
        skipped_count=2,
        items=[
            mocker.Mock(object_key="stock_rt_daily", status="existing", object_kind="collector_feed"),
            mocker.Mock(object_key="stock_rt_min", status="existing", object_kind="feed_group"),
        ],
    )
    mocker.patch("src.cli.RealtimeRuntimeConfigSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-realtime-runtime-config", "--apply"])

    assert result.exit_code == 0
    assert "ops-seed-realtime-runtime-config [apply]" in result.stdout
    assert "created=0" in result.stdout
    assert "skipped=2" in result.stdout
    assert "stock_rt_min: status=existing object_kind=feed_group" in result.stdout
    service.run.assert_called_once_with(session, dry_run=False)
