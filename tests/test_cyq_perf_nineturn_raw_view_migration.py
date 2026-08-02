from pathlib import Path


_MIGRATION_PATH = Path("alembic/versions/20260803_000124_make_cyq_perf_nineturn_raw_views.py")


def test_cyq_perf_nineturn_raw_view_migration_is_fail_closed_and_preserves_contracts() -> None:
    content = _MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision = "20260803_000124"' in content
    assert 'down_revision = "20260802_000123"' in content
    assert "Expected raw_tushare.% to be a physical table" in content
    assert "Expected core_serving.% to be a physical table" in content
    assert content.count("IS DISTINCT FROM 'r'") == 2
    assert "DROP TABLE core_serving.equity_cyq_perf" in content
    assert "DROP TABLE core_serving.equity_nineturn" in content
    assert "DROP TABLE core_serving.equity_cyq_perf CASCADE" not in content
    assert "DROP TABLE core_serving.equity_nineturn CASCADE" not in content
    assert "CREATE VIEW core_serving.equity_cyq_perf" in content
    assert "CREATE VIEW core_serving.equity_nineturn" in content
    assert "fetched_at AS created_at" in content
    assert "fetched_at AS updated_at" in content
    assert "api_name" not in content
    assert "raw_payload" not in content
    assert "automatic downgrade is forbidden" in content
