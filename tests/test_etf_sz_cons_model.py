from __future__ import annotations

from pathlib import Path


def test_etf_sz_cons_migration_creates_raw_table_and_serving_view_only() -> None:
    migration_text = Path("alembic/versions/20260822_000141_add_etf_sz_cons_dataset.py").read_text(encoding="utf-8")

    assert 'revision = "20260822_000141"' in migration_text
    assert 'down_revision = "20260822_000140"' in migration_text
    assert 'op.create_table(\n        "etf_sz_cons"' in migration_text
    assert 'sa.PrimaryKeyConstraint("trade_date", "ts_code", "con_code", name="pk_raw_tushare_etf_sz_cons")' in migration_text
    assert "idx_raw_tushare_etf_sz_cons_ts_code_trade_date" in migration_text
    assert "idx_raw_tushare_etf_sz_cons_con_code" in migration_text
    assert '"idx_raw_tushare_etf_sz_cons_trade_date"' not in migration_text
    assert "CREATE OR REPLACE VIEW core_serving.etf_sz_cons" in migration_text
    assert migration_text.count("op.create_table(") == 1
