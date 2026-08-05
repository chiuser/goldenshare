from __future__ import annotations

from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/20260805_000125_add_public_fund_b1_snapshot_tables.py"


def test_public_fund_b1_migration_is_hdd_only_and_non_destructive() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision = "20260803_000124"' in source
    assert "_assert_hdd_tablespace()" in source
    assert "postgresql_tablespace=_TABLESPACE" in source
    assert "SET TABLESPACE {_TABLESPACE}" in source
    assert "CREATE INDEX idx_fund_company_current_source_entity_key" in source
    assert "CREATE INDEX idx_fund_company_observation_entity_last_observed" in source
    assert "CREATE INDEX idx_mkt_idx_bmk_current_source_entity_key" in source
    assert "CREATE INDEX idx_mkt_idx_bmk_observation_entity_last_observed" in source
    assert "不支持自动 downgrade" in source
    assert "DROP TABLE" not in source
