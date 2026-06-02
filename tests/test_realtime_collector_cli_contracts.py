from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.cli_parts.realtime_handlers import run_realtime_collector_serve
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from tests.realtime_runtime_config_helpers import seed_realtime_runtime_config


def test_realtime_collector_cli_uses_generic_command_only() -> None:
    cli_text = Path("src/cli.py").read_text(encoding="utf-8")
    handler_text = Path("src/cli_parts/realtime_handlers.py").read_text(encoding="utf-8")

    assert '@app.command("realtime-collector-serve")' in cli_text
    assert "run_realtime_collector_serve" in handler_text
    assert "realtime-stock-rt-daily-serve" not in cli_text
    assert "realtime-stock-rt-daily-serve" not in handler_text


def test_realtime_collector_systemd_unit_uses_generic_command() -> None:
    unit_text = Path("scripts/goldenshare-realtime-collector.service").read_text(encoding="utf-8")

    assert "goldenshare realtime-collector-serve" in unit_text
    assert "realtime-stock-rt-daily-serve" not in unit_text


def test_realtime_collector_cli_loads_runtime_config_from_database(mocker) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS foundation")
        RealtimeRuntimeConfigRecord.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with testing_session_local() as session:
        seed_realtime_runtime_config(session, daily={"lease_ttl_seconds": 55})

    collector = mocker.Mock()
    collector.run_due_cycle.return_value = SimpleNamespace(feed_runs=(), next_sleep_seconds=0.1)
    collector_cls = mocker.patch("src.cli_parts.realtime_handlers.RealtimeCollectorService", return_value=collector)
    mocker.patch("src.cli_parts.realtime_handlers.build_realtime_state_store", return_value=mocker.Mock())

    run_realtime_collector_serve(
        session_local=testing_session_local,
        max_cycles=1,
        echo_fn=lambda _message: None,
    )

    passed_config = collector_cls.call_args.kwargs["config"]
    assert passed_config.stock_rt_daily.lease_ttl_seconds == 55
    collector.run_due_cycle.assert_called_once()
