from pathlib import Path


ALEMBIC_ENV = Path(__file__).resolve().parents[1] / "alembic/env.py"


def test_online_alembic_migrations_apply_bounded_postgresql_lock_wait() -> None:
    source = ALEMBIC_ENV.read_text(encoding="utf-8")
    online_source = source[source.index("def run_migrations_online") :]

    assert '_ALEMBIC_LOCK_TIMEOUT_SQL = "SET LOCAL lock_timeout = \'15s\'"' in source
    assert 'if connection.dialect.name == "postgresql":' in online_source
    assert "connection.exec_driver_sql(_ALEMBIC_LOCK_TIMEOUT_SQL)" in online_source
    assert "ALTER SYSTEM" not in source
    assert "idle_in_transaction_session_timeout" not in source

    transaction_at = online_source.index("with context.begin_transaction():")
    dialect_guard_at = online_source.index('if connection.dialect.name == "postgresql":')
    timeout_at = online_source.index(
        "connection.exec_driver_sql(_ALEMBIC_LOCK_TIMEOUT_SQL)"
    )
    migrations_at = online_source.index("context.run_migrations()")
    assert transaction_at < dialect_guard_at < timeout_at < migrations_at


def test_offline_alembic_render_does_not_emit_runtime_lock_setting() -> None:
    source = ALEMBIC_ENV.read_text(encoding="utf-8")
    offline_source = source[
        source.index("def run_migrations_offline") : source.index(
            "def run_migrations_online"
        )
    ]

    assert "_ALEMBIC_LOCK_TIMEOUT_SQL" not in offline_source
    assert "exec_driver_sql" not in offline_source
