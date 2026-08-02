from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


MIGRATIONS_DIR = Path(__file__).parents[1] / "alembic" / "versions"


def _load_migration(filename: str) -> ModuleType:
    path = MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@pytest.mark.parametrize(
    ("filename", "target_count"),
    [
        ("20260421_000068_change_raw_moneyflow_vol_to_bigint.py", 1),
        ("20260421_000069_change_moneyflow_std_serving_vol_to_bigint.py", 2),
    ],
)
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_historical_moneyflow_volume_migrations_skip_absent_legacy_tables(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    target_count: int,
    direction: str,
) -> None:
    migration = _load_migration(filename)
    operations = Mock()
    operations.get_bind.return_value = object()
    inspector = Mock()
    inspector.has_table.return_value = False

    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    getattr(migration, direction)()

    assert inspector.has_table.call_count == target_count
    operations.alter_column.assert_not_called()


@pytest.mark.parametrize(
    ("filename", "target_count"),
    [
        ("20260421_000068_change_raw_moneyflow_vol_to_bigint.py", 1),
        ("20260421_000069_change_moneyflow_std_serving_vol_to_bigint.py", 2),
    ],
)
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_historical_moneyflow_volume_migrations_preserve_existing_targets(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    target_count: int,
    direction: str,
) -> None:
    migration = _load_migration(filename)
    operations = Mock()
    operations.get_bind.return_value = object()
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [
        {"name": column} for column in migration.VOLUME_COLUMNS
    ]

    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    getattr(migration, direction)()

    assert inspector.has_table.call_count == target_count
    assert inspector.get_columns.call_count == target_count
    assert operations.alter_column.call_count == target_count * len(migration.VOLUME_COLUMNS)


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_index_basic_width_migration_skips_absent_legacy_targets(
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    migration = _load_migration("20260423_000071_widen_index_basic_ts_code_length.py")
    operations = Mock()
    operations.get_bind.return_value = object()
    inspector = Mock()
    inspector.has_table.return_value = False

    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    getattr(migration, direction)()

    assert inspector.has_table.call_count == len(migration.TARGETS)
    operations.alter_column.assert_not_called()


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_index_basic_width_migration_preserves_existing_targets(
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    migration = _load_migration("20260423_000071_widen_index_basic_ts_code_length.py")
    operations = Mock()
    operations.get_bind.return_value = object()
    inspector = Mock()
    inspector.has_table.return_value = True

    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    getattr(migration, direction)()

    assert inspector.has_table.call_count == len(migration.TARGETS)
    assert operations.alter_column.call_count == len(migration.TARGETS)
