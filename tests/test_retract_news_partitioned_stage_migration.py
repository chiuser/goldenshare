from pathlib import Path


_MIGRATION_PATH = Path("alembic/versions/20260802_000122_retract_news_partitioned_stage.py")


def test_retract_news_partitioned_stage_only_drops_an_empty_stage() -> None:
    content = _MIGRATION_PATH.read_text(encoding="utf-8")
    normalized = content.lower()

    assert 'revision = "20260802_000122"' in content
    assert 'down_revision = "20260802_000121"' in content
    assert "select count(*) from raw_tushare.news_partitioned_stage" in normalized
    assert "stage 非空" in content
    drop_statements = [line.strip() for line in content.splitlines() if "DROP TABLE" in line]
    assert drop_statements == ['op.execute("DROP TABLE raw_tushare.news_partitioned_stage")']
