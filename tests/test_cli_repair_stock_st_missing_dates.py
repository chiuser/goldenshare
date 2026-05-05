from __future__ import annotations

from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.foundation.services.migration.stock_st_missing_date_repair.models import (
    StockStMissingDateRepairResult,
    StockStMissingDatePreview,
    StockStPreviewArtifacts,
)


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def _build_result(tmp_path: Path) -> StockStMissingDateRepairResult:
    preview = StockStMissingDatePreview(
        trade_date=date(2020, 4, 23),
        prev_date=date(2020, 4, 22),
        next_date=date(2020, 4, 24),
        prev_count=1,
        next_count=1,
        st_same_day_count=0,
        candidate_count=1,
        selected_namechange_count=1,
        unresolved_candidate_count=0,
        selected_non_st_count=0,
        reconstructed_count=1,
        validation_ok_total=1,
        validation_not_ok_total=0,
        manual_review_count=0,
        candidates=(),
        review_items=(),
    )
    artifacts = StockStPreviewArtifacts(
        output_dir=tmp_path,
        summary_path=tmp_path / "summary.csv",
        preview_rows_path=tmp_path / "rows.csv",
        manual_review_path=tmp_path / "review.csv",
    )
    return StockStMissingDateRepairResult(
        artifacts=artifacts,
        date_previews=(preview,),
        applied=False,
        applied_date_count=0,
        applied_row_count=0,
        skipped_review_dates=(),
    )


def test_cli_repair_stock_st_missing_dates_preview(mocker, tmp_path) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = _build_result(tmp_path)
    mocker.patch("src.cli.StockStMissingDateRepairService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "repair-stock-st-missing-dates",
            "--date",
            "2020-04-23",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "repair-stock-st-missing-dates [preview]" in result.stdout
    assert "summary.csv" in result.stdout
    service.run.assert_called_once_with(
        session,
        trade_dates=[date(2020, 4, 23)],
        output_dir=tmp_path,
        apply=False,
        fail_on_review_items=False,
    )


def test_cli_repair_stock_st_missing_dates_supports_date_file(mocker, tmp_path) -> None:
    session = _patch_session_local(mocker)
    date_file = tmp_path / "missing_dates.txt"
    date_file.write_text("2020-04-23\n# comment\n2020-04-24\n", encoding="utf-8")
    service = mocker.Mock()
    service.run.return_value = _build_result(tmp_path)
    mocker.patch("src.cli.StockStMissingDateRepairService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "repair-stock-st-missing-dates",
            "--date-file",
            str(date_file),
        ],
    )

    assert result.exit_code == 0
    service.run.assert_called_once_with(
        session,
        trade_dates=[date(2020, 4, 23), date(2020, 4, 24)],
        output_dir=None,
        apply=False,
        fail_on_review_items=False,
    )

