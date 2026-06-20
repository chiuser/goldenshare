from __future__ import annotations

from pathlib import Path


def test_etf_sh_cons_migration_uses_current_head_and_raw_view_only() -> None:
    migration_text = Path("alembic/versions/20260620_000118_add_etf_sh_cons_dataset.py").read_text(encoding="utf-8")

    assert 'revision = "20260620_000118"' in migration_text
    assert 'down_revision = "20260618_000117"' in migration_text
    assert 'op.create_table(\n        "etf_sh_cons"' in migration_text
    assert "CREATE OR REPLACE VIEW core_serving.etf_sh_cons" in migration_text
    assert "raw_tushare.fund_daily" not in migration_text
    assert "core_serving.fund_daily_bar" not in migration_text
    assert "ops.etf_series_active" not in migration_text
