from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "alembic/versions/20260813_000134_add_wealth_sector_overview_serving.py"


def _load_migration() -> Any:
    spec = spec_from_file_location("wealth_sector_overview_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    def __init__(self) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.created_tables: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.created_indexes: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.executed_sql: list[str] = []
        self.dropped_tables: list[tuple[str, str | None]] = []

    def get_bind(self) -> Any:
        return self.bind

    @staticmethod
    def f(name: str) -> str:
        return name

    def create_table(self, name: str, *items: Any, **kwargs: Any) -> None:
        self.created_tables.append((name, items, kwargs))

    def create_index(self, *args: Any, **kwargs: Any) -> None:
        self.created_indexes.append((args, kwargs))

    def execute(self, sql: str) -> None:
        self.executed_sql.append(sql)

    def drop_table(self, name: str, *, schema: str | None = None) -> None:
        self.dropped_tables.append((name, schema))


def test_migration_extends_the_reverified_single_head() -> None:
    migration = _load_migration()

    assert migration.revision == "20260813_000134"
    assert migration.down_revision == "20260812_000133"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_upgrade_creates_only_two_serving_tables_and_the_existing_role_grant(monkeypatch: Any) -> None:
    migration = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    assert [name for name, _, _ in recorder.created_tables] == [
        "wealth_sector_hierarchy",
        "wealth_sector_heat_daily",
    ]
    assert all(kwargs["schema"] == "core_serving" for _, _, kwargs in recorder.created_tables)
    assert len(recorder.created_indexes) == 3
    assert recorder.executed_sql[-1] == (
        "GRANT SELECT, INSERT, DELETE ON TABLE "
        "core_serving.wealth_sector_hierarchy TO lake_raw_writer"
    )
    assert recorder.executed_sql[:-1] == [
        "CREATE INDEX idx_wealth_sector_heat_daily_trade_score_code "
        "ON core_serving.wealth_sector_heat_daily (trade_date, heat_score DESC, sector_code)",
        "CREATE INDEX idx_wealth_sector_heat_daily_trade_delta_code "
        "ON core_serving.wealth_sector_heat_daily (trade_date, heat_delta_1d DESC, sector_code)",
        "CREATE INDEX idx_wealth_sector_heat_daily_sector_trade "
        "ON core_serving.wealth_sector_heat_daily (sector_code, trade_date DESC)",
    ]


def test_migration_contains_no_role_creation_source_dml_or_runtime_config() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    uppercase = source.upper()

    assert uppercase.count("GRANT SELECT, INSERT, DELETE ON TABLE") == 1
    for forbidden in (
        "CREATE ROLE",
        "CREATE USER",
        "ALTER ROLE",
        "INSERT INTO",
        "DELETE FROM",
        "TRUNCATE",
        "WEALTH_SECTOR_HEAT_DATABASE_URL",
        "WEALTH_SECTOR_READ_DATABASE_URL",
        "WEALTH_SECTOR_HIERARCHY_POSTGRES_",
    ):
        assert forbidden not in uppercase


def test_downgrade_drops_only_new_tables_in_dependency_order(monkeypatch: Any) -> None:
    migration = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(migration, "op", recorder)

    migration.downgrade()

    assert recorder.dropped_tables == [
        ("wealth_sector_heat_daily", "core_serving"),
        ("wealth_sector_hierarchy", "core_serving"),
    ]
