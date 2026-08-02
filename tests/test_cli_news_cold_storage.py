from __future__ import annotations

from datetime import datetime

from typer.testing import CliRunner

from src.cli import app
from src.foundation.services.migration.news_cold_storage.models import (
    NewsColdStorageCopyResult,
    NewsColdStoragePreparation,
    NewsColdStorageSummary,
    NewsColdStorageVerification,
)


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def _summary() -> NewsColdStorageSummary:
    return NewsColdStorageSummary(
        row_count=2,
        earliest_news_time=datetime.fromisoformat("2022-01-01T00:00:00+00:00"),
        latest_news_time=datetime.fromisoformat("2026-08-02T00:00:00+00:00"),
        rows_by_year=((2022, 1), (2026, 1)),
    )


def test_cli_news_cold_storage_copy_defaults_to_preview(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.copy.return_value = NewsColdStorageCopyResult(
        applied=False,
        copy_started_at=None,
        rows_affected=None,
        source=_summary(),
        stage_before_copy=_summary(),
    )
    mocker.patch("src.cli.NewsColdStorageMigrationService", return_value=service)

    result = CliRunner().invoke(app, ["migrate-news-cold-storage", "copy"])

    assert result.exit_code == 0
    assert "applied=False" in result.stdout
    service.copy.assert_called_once_with(session, apply=False)


def test_cli_news_cold_storage_cutover_preview_does_not_require_destructive_flags(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    summary = _summary()
    service.cutover.return_value = NewsColdStorageVerification(
        source=summary,
        stage=summary,
        source_missing_from_stage=0,
        stage_missing_from_source=0,
    )
    mocker.patch("src.cli.NewsColdStorageMigrationService", return_value=service)

    result = CliRunner().invoke(app, ["migrate-news-cold-storage", "cutover"])

    assert result.exit_code == 0
    assert "no lock, rename, view switch, or drop was executed" in result.stdout
    service.cutover.assert_called_once_with(
        session,
        apply=False,
        copy_started_at=None,
        drop_retired_table=False,
    )


def test_cli_news_cold_storage_cutover_apply_requires_all_explicit_flags(mocker) -> None:
    service_constructor = mocker.patch("src.cli.NewsColdStorageMigrationService")

    result = CliRunner().invoke(
        app,
        [
            "migrate-news-cold-storage",
            "cutover",
            "--apply",
            "--copy-started-at",
            "2026-08-02T19:00:00+08:00",
        ],
    )

    assert result.exit_code != 0
    assert "--drop-retired-table" in result.output
    service_constructor.assert_not_called()


def test_cli_news_cold_storage_prepare_prints_partition_layout(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.prepare.return_value = NewsColdStoragePreparation(
        partition_tablespaces=(("news_p2022", "gs_raw_cold_hdd"), ("news_p2026", "pg_default")),
        partition_indexes=(),
    )
    mocker.patch("src.cli.NewsColdStorageMigrationService", return_value=service)

    result = CliRunner().invoke(app, ["migrate-news-cold-storage", "prepare"])

    assert result.exit_code == 0
    assert "news_p2022: gs_raw_cold_hdd" in result.stdout
    service.prepare.assert_called_once_with(session)
