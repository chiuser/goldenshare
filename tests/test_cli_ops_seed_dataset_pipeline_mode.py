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


def test_cli_ops_seed_dataset_pipeline_mode_dry_run(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(dataset_total=44, created=12, updated=0)
    mocker.patch("src.cli.DatasetPipelineModeSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-dataset-pipeline-mode"])
    assert result.exit_code == 0
    assert "ops-seed-dataset-pipeline-mode [dry-run]" in result.stdout
    assert "dataset_total=44" in result.stdout
    service.run.assert_called_once_with(session, dry_run=True)


def test_cli_ops_seed_dataset_pipeline_mode_apply(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(dataset_total=44, created=0, updated=3)
    mocker.patch("src.cli.DatasetPipelineModeSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-dataset-pipeline-mode", "--apply"])
    assert result.exit_code == 0
    assert "ops-seed-dataset-pipeline-mode [apply]" in result.stdout
    service.run.assert_called_once_with(session, dry_run=False)
