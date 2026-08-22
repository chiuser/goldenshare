from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.cli import app


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def test_cli_ops_seed_etf_series_active_dry_run(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        resource="fund_daily",
        seed_csv_path="reports/etf_series_active_seed_1395_20260617.csv",
        candidate_count=1395,
        created_count=1395,
        skipped_count=0,
        invalid_count=0,
    )
    mocker.patch("src.cli.EtfSeriesActiveSeedService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-seed-etf-series-active",
            "--resource",
            "fund_daily",
            "--from-seed-csv",
            "reports/etf_series_active_seed_1395_20260617.csv",
        ],
    )

    assert result.exit_code == 0
    assert "ops-seed-etf-series-active [dry-run] resource=fund_daily" in result.stdout
    assert "candidate=1395" in result.stdout
    assert "created=1395" in result.stdout
    service.run.assert_called_once_with(
        session,
        resource="fund_daily",
        seed_csv_path=Path("reports/etf_series_active_seed_1395_20260617.csv"),
        dry_run=True,
    )


def test_cli_ops_seed_etf_series_active_apply(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        resource="etf_rt_daily",
        seed_csv_path="reports/etf_series_active_seed_1395_20260617.csv",
        candidate_count=1395,
        created_count=0,
        skipped_count=1395,
        invalid_count=0,
    )
    mocker.patch("src.cli.EtfSeriesActiveSeedService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-seed-etf-series-active",
            "--resource",
            "etf_rt_daily",
            "--from-seed-csv",
            "reports/etf_series_active_seed_1395_20260617.csv",
            "--apply",
        ],
    )

    assert result.exit_code == 0
    assert "ops-seed-etf-series-active [apply] resource=etf_rt_daily" in result.stdout
    assert "skipped=1395" in result.stdout
    service.run.assert_called_once_with(
        session,
        resource="etf_rt_daily",
        seed_csv_path=Path("reports/etf_series_active_seed_1395_20260617.csv"),
        dry_run=False,
    )


def test_cli_ops_seed_etf_series_active_accepts_etf_sh_cons_resource(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        resource="etf_sh_cons",
        seed_csv_path="reports/etf_sh_cons_available_codes_20260618.csv",
        candidate_count=803,
        created_count=803,
        skipped_count=0,
        invalid_count=0,
    )
    mocker.patch("src.cli.EtfSeriesActiveSeedService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-seed-etf-series-active",
            "--resource",
            "etf_sh_cons",
            "--from-seed-csv",
            "reports/etf_sh_cons_available_codes_20260618.csv",
        ],
    )

    assert result.exit_code == 0
    assert "ops-seed-etf-series-active [dry-run] resource=etf_sh_cons" in result.stdout
    assert "candidate=803" in result.stdout
    service.run.assert_called_once_with(
        session,
        resource="etf_sh_cons",
        seed_csv_path=Path("reports/etf_sh_cons_available_codes_20260618.csv"),
        dry_run=True,
    )


def test_cli_ops_seed_etf_series_active_accepts_etf_sz_cons_resource(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        resource="etf_sz_cons",
        seed_csv_path="reports/etf_sz_cons_active_codes.csv",
        candidate_count=726,
        created_count=726,
        skipped_count=0,
        invalid_count=0,
    )
    mocker.patch("src.cli.EtfSeriesActiveSeedService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-seed-etf-series-active",
            "--resource",
            "etf_sz_cons",
            "--from-seed-csv",
            "reports/etf_sz_cons_active_codes.csv",
        ],
    )

    assert result.exit_code == 0
    assert "ops-seed-etf-series-active [dry-run] resource=etf_sz_cons" in result.stdout
    assert "candidate=726" in result.stdout
    service.run.assert_called_once_with(
        session,
        resource="etf_sz_cons",
        seed_csv_path=Path("reports/etf_sz_cons_active_codes.csv"),
        dry_run=True,
    )
