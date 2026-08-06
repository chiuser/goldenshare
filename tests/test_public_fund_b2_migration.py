from __future__ import annotations

from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/20260806_000126_add_public_fund_b2_fund_basic_tables.py"


def test_public_fund_b2_migration_is_hdd_only_non_destructive_and_unseeded() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision = "20260805_000125"' in source
    assert source.index("_assert_hdd_tablespace()") < source.index('_create_fund_basic_table(name="fund_basic_current"')
    assert 'postgresql_tablespace=_TABLESPACE' in source
    assert "ALTER INDEX {_SCHEMA}.pk_core_serving_{table_name} SET TABLESPACE {_TABLESPACE}" in source
    assert "CREATE INDEX idx_fund_basic_current_source_entity_key" in source
    assert "CREATE INDEX idx_fund_basic_observation_entity_last_observed" in source
    assert source.count("TABLESPACE gs_raw_cold_hdd") == 2
    assert "DROP TABLE" not in source.upper()
    assert "INSERT INTO OPS" not in source.upper()
    assert "不支持自动 downgrade 删除数据" in source
