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


def test_cli_ops_seed_moneyflow_multi_source_dry_run(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        dataset_key="moneyflow",
        created_mapping_rules=2,
        created_cleansing_rules=2,
        created_source_statuses=2,
        created_resolution_policy=1,
        updated_resolution_policy=0,
    )
    mocker.patch("src.cli.MoneyflowMultiSourceSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-moneyflow-multi-source"])
    assert result.exit_code == 0
    assert "ops-seed-moneyflow-multi-source [dry-run] dataset=moneyflow" in result.stdout
    service.run.assert_called_once_with(session, dry_run=True)


def test_cli_ops_seed_moneyflow_multi_source_apply(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        dataset_key="moneyflow",
        created_mapping_rules=0,
        created_cleansing_rules=0,
        created_source_statuses=0,
        created_resolution_policy=0,
        updated_resolution_policy=1,
    )
    mocker.patch("src.cli.MoneyflowMultiSourceSeedService", return_value=service)

    result = CliRunner().invoke(app, ["ops-seed-moneyflow-multi-source", "--apply"])
    assert result.exit_code == 0
    assert "ops-seed-moneyflow-multi-source [apply] dataset=moneyflow" in result.stdout
    service.run.assert_called_once_with(session, dry_run=False)
