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


def test_cli_ops_seed_default_single_source_dry_run(mocker) -> None:
    session = _patch_session_local(mocker)

    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        source_key="tushare",
        dataset_total=10,
        created_mapping_rules=10,
        created_cleansing_rules=10,
        created_resolution_policies=10,
        created_source_statuses=10,
    )
    mocker.patch("src.cli.DefaultSingleSourceSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-default-single-source"])

    assert result.exit_code == 0
    assert "ops-seed-default-single-source [dry-run] source=tushare" in result.stdout
    assert "dataset_total=10" in result.stdout
    service.run.assert_called_once_with(session, source_key="tushare", dry_run=True)


def test_cli_ops_seed_default_single_source_apply(mocker) -> None:
    session = _patch_session_local(mocker)

    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        source_key="tushare",
        dataset_total=10,
        created_mapping_rules=0,
        created_cleansing_rules=0,
        created_resolution_policies=0,
        created_source_statuses=0,
    )
    mocker.patch("src.cli.DefaultSingleSourceSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-default-single-source", "--apply"])

    assert result.exit_code == 0
    assert "ops-seed-default-single-source [apply] source=tushare" in result.stdout
    service.run.assert_called_once_with(session, source_key="tushare", dry_run=False)
