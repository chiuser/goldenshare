from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from typer.testing import CliRunner

from src.app.model_registry import MODEL_MODULES
from src.cli import app
from src.foundation.dao.factory import DAOFactory


MIGRATION_PATH = Path("alembic/versions/20260829_000157_drop_etf_series_active.py")


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MIGRATION_PATH.stem, MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_etf_series_active_is_removed_without_affecting_index_pool(mocker) -> None:
    assert "src.ops.models.ops.etf_series_active" not in MODEL_MODULES
    assert "src.ops.models.ops.index_series_active" in MODEL_MODULES

    factory = DAOFactory(mocker.Mock())

    assert not hasattr(factory, "etf_series_active")
    assert hasattr(factory, "index_series_active")


def test_etf_series_active_seed_command_is_retired() -> None:
    runner = CliRunner()

    retired = runner.invoke(app, ["ops-seed-etf-series-active"])
    help_result = runner.invoke(app, ["--help"])

    assert retired.exit_code == 2
    assert "No such command" in retired.output
    assert help_result.exit_code == 0
    assert "ops-seed-etf-series-active" not in help_result.output


def test_etf_series_active_drop_migration_targets_only_retired_table(mocker) -> None:
    migration = _load_migration()
    drop_table = mocker.Mock()
    migration.op = SimpleNamespace(drop_table=drop_table)

    migration.upgrade()

    assert migration.revision == "20260829_000157"
    assert migration.down_revision == "20260828_000156"
    drop_table.assert_called_once_with("etf_series_active", schema="ops")

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "CASCADE" not in source
    assert "IF EXISTS" not in source
    assert "index_series_active" not in source


def test_etf_series_active_drop_migration_is_irreversible() -> None:
    migration = _load_migration()

    with pytest.raises(
        RuntimeError,
        match="ops.etf_series_active retirement is irreversible",
    ):
        migration.downgrade()


def test_etf_series_active_historical_create_migration_is_preserved() -> None:
    assert Path("alembic/versions/20260618_000117_add_etf_series_active.py").is_file()
