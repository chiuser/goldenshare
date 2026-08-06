from __future__ import annotations

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260807_000128_add_public_fund_b4_fund_share_tables.py"
)


def test_public_fund_b4_migration_is_hdd_only_non_destructive_and_unseeded() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision = "20260806_000127"' in source
    assert source.index("_assert_hdd_tablespace()") < source.index(
        '_create_fund_share_table(name="fund_share_current"'
    )
    assert "postgresql_tablespace=_TABLESPACE" in source
    assert "CREATE UNIQUE INDEX uq_fund_share_current_source_entity_key" in source
    assert "CREATE INDEX idx_fund_share_current_date_market_code" in source
    assert "CREATE INDEX idx_fund_share_current_code_date" in source
    assert "CREATE INDEX idx_fund_share_observation_entity_last_observed" in source
    assert "CREATE INDEX idx_fund_share_observation_date_market_code" in source
    assert "CREATE INDEX idx_fund_share_observation_code_date_last_observed" in source
    assert source.count("TABLESPACE gs_raw_cold_hdd") == 6
    assert "DROP TABLE" not in source.upper()
    assert "INSERT INTO OPS" not in source.upper()
    assert "不支持自动 downgrade 删除数据" in source
