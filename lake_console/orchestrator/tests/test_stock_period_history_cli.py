import json

import pytest

from orchestrator.defs.bootstrap.stock_period_history_cli import main


def test_prepare_is_readonly_and_apply_requires_explicit_delete(tmp_path, capsys):
    argv = [
        "--lake-root",
        str(tmp_path / "lake"),
        "--staging-root",
        str(tmp_path / "staging"),
        "--request-id",
        "sample",
    ]
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert not (tmp_path / "lake").exists() and not (tmp_path / "staging").exists()
    with pytest.raises(SystemExit):
        main(["apply", *argv])
    assert not (tmp_path / "lake").exists()


def test_old_plans_and_old_prod_config_rejected():
    from orchestrator.defs.bootstrap.stock_monthly_history_cli import main as oldmonth
    from orchestrator.defs.bootstrap.stock_weekly_history_cli import main as oldweek
    from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig

    for entry in [oldmonth, oldweek]:
        with pytest.raises(ValueError, match="retired"):
            entry(["apply", "--plan", "old.json"])
    for config in [
        {"delivery_batch_id": "old", "closure_revision": 1},
        {"write_mode": "create_or_identical"},
        {"source": "weekly"},
    ]:
        with pytest.raises(ValueError):
            StockPeriodRawConfig(**config)
