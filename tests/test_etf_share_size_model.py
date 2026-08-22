from __future__ import annotations

from pathlib import Path


def test_etf_share_size_migration_creates_raw_table_and_serving_view_only() -> None:
    migration_text = Path("alembic/versions/20260822_000140_add_etf_share_size_dataset.py").read_text(encoding="utf-8")

    assert 'revision = "20260822_000140"' in migration_text
    assert 'down_revision = "20260822_000139"' in migration_text
    assert 'op.create_table(\n        "etf_share_size"' in migration_text
    assert 'sa.PrimaryKeyConstraint("trade_date", "ts_code", name="pk_raw_tushare_etf_share_size")' in migration_text
    assert "idx_raw_tushare_etf_share_size_ts_code_trade_date" in migration_text
    assert '"idx_raw_tushare_etf_share_size_trade_date"' not in migration_text
    assert "CREATE OR REPLACE VIEW core_serving.etf_share_size" in migration_text
    assert "core_serving.etf_share_size" in migration_text
    assert migration_text.count("op.create_table(") == 1
