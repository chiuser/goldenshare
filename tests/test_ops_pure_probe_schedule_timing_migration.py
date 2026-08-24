from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260824_000150_normalize_pure_probe_schedule_timing.py"
)


def test_pure_probe_timing_migration_follows_real_head_and_only_normalizes_schedule() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision = "20260824_000149"' in source
    assert "UPDATE ops.schedule" in source
    assert "WHERE trigger_mode = 'probe'" in source
    assert "schedule_type = 'cron'" in source
    assert "cron_expr = NULL" in source
    assert "next_run_at = NULL" in source
    assert "op.create_check_constraint" in source
    assert "DELETE FROM" not in source
    assert "ops.probe_rule" not in source
    assert "ops.task_run" not in source
