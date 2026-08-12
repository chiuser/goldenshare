from __future__ import annotations

from pathlib import Path


def test_st_source_field_contract_migration_is_one_way_and_preserves_data() -> None:
    migration_text = Path("alembic/versions/20260812_000133_rename_st_type_field.py").read_text(encoding="utf-8")

    assert 'revision = "20260812_000133"' in migration_text
    assert 'down_revision = "20260811_000132"' in migration_text
    assert 'op.alter_column("st", "st_tpye", new_column_name="st_type", schema="raw_tushare")' in migration_text
    assert "ALTER VIEW core_serving_light.st RENAME COLUMN st_tpye TO st_type" in migration_text
    assert "raw_tushare.st 字段不符合迁移前契约" in migration_text
    assert "core_serving_light.st 字段不符合迁移前契约" in migration_text
    assert "DROP TABLE" not in migration_text
    assert "DELETE FROM" not in migration_text
    assert "TRUNCATE" not in migration_text
    assert "禁止 downgrade" in migration_text
