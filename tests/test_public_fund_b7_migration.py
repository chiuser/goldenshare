from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260810_000131_add_public_fund_b7_fund_portfolio_tables.py"
)


def test_b7_migration_is_linear_hdd_only_partitioned_unlogged_and_non_destructive() -> None:
    source = MIGRATION.read_text()
    assert 'revision = "20260810_000131"' in source
    assert 'down_revision = "20260807_000130"' in source
    assert "_PARTITION_COUNT = 32" in source
    assert "PARTITION BY HASH (end_date)" in source
    assert "CREATE UNLOGGED TABLE foundation.fund_portfolio_stage" in source
    assert "TABLESPACE gs_raw_cold_hdd" in source
    assert "_assert_hdd_tablespace()" in source
    assert "_move_partition_indexes_to_hdd(partition_name)" in source
    assert "ALTER INDEX" in source and "SET TABLESPACE" in source
    assert "NUMERIC NULL" in source
    assert "op.drop_table" not in source
    assert "不支持自动 downgrade 删除数据" in source
