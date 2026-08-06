from __future__ import annotations

from pathlib import Path

from src.foundation.datasets.public_fund_contracts import FUND_MANAGER_SOURCE_FIELDS


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260806_000127_add_public_fund_b3_fund_manager_tables.py"
)


def test_public_fund_b3_migration_is_hdd_only_non_destructive_and_unseeded() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision = "20260806_000126"' in source
    assert source.index("_assert_hdd_tablespace()") < source.index(
        '_create_fund_manager_table(name="fund_manager_current"'
    )
    assert "postgresql_tablespace=_TABLESPACE" in source
    assert (
        "ALTER INDEX {_SCHEMA}.pk_core_serving_{table_name} SET TABLESPACE {_TABLESPACE}"
        in source
    )
    assert "CREATE UNIQUE INDEX uq_fund_manager_current_source_entity_key" in source
    assert "CREATE INDEX idx_fund_manager_current_ts_code" in source
    assert "CREATE INDEX idx_fund_manager_current_manager_identity_key" in source
    assert "CREATE INDEX idx_fund_manager_observation_entity_last_observed" in source
    assert "CREATE INDEX idx_fund_manager_observation_ts_code_last_observed" in source
    assert "CREATE INDEX idx_fund_manager_observation_manager_last_observed" in source
    assert source.count("TABLESPACE gs_raw_cold_hdd") == 6
    for field in FUND_MANAGER_SOURCE_FIELDS:
        assert f'sa.Column("{field}", sa.Text()' in source
    assert "DROP TABLE" not in source.upper()
    assert "INSERT INTO OPS" not in source.upper()
    assert "不支持自动 downgrade 删除数据" in source
