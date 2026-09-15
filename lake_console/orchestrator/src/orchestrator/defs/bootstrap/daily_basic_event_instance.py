"""Existing formal storage only; read-only by default, no automatic DDL."""

from contextlib import ExitStack, contextmanager
from pathlib import Path

import dagster as dg
import yaml
from dagster._config import process_config
from dagster._core.instance.ref import InstanceRef
from dagster._core.instance.types import InstanceType
from dagster._core.storage.config import pg_config
from dagster._core.storage.root import LocalArtifactStorage
from dagster._serdes import ConfigurableClassData
from dagster_postgres import PostgresEventLogStorage, PostgresRunStorage
from dagster_postgres.utils import pg_url_from_config
from sqlalchemy.engine import make_url

from orchestrator.defs.daily_basic_contract import DailyBasicValidationError

INSTANCE_HOME = Path("/Users/congming/.goldenshare/dagster_home")


@contextmanager
def daily_basic_event_instance(*, writable=False):
    config = yaml.safe_load((INSTANCE_HOME / "dagster.yaml").read_text())
    if any(
        k in config
        for k in (
            "instance_class",
            "run_storage",
            "event_log_storage",
            "schedule_storage",
        )
    ):
        raise DailyBasicValidationError("history_instance_config")
    storage = config.get("storage", {})
    if set(storage) != {"postgres"}:
        raise DailyBasicValidationError("history_instance_storage")
    artifact = config.get("local_artifact_storage", {})
    if artifact.get("class") != "LocalArtifactStorage" or artifact.get(
        "module"
    ) not in ("dagster._core.storage.root", "dagster.core.storage.root"):
        raise DailyBasicValidationError("history_instance_artifact_config")
    artifact_root = Path(artifact.get("config", {}).get("base_dir", ""))
    if not artifact_root.is_absolute() or not artifact_root.is_dir():
        raise DailyBasicValidationError("history_instance_artifact_root")
    resolved = process_config(pg_config(), storage["postgres"])
    if not resolved.success:
        raise DailyBasicValidationError("history_instance_postgres_config")
    url = make_url(pg_url_from_config(resolved.value))
    if (
        url.host not in ("localhost", "127.0.0.1", "::1")
        or url.database != "goldenshare_dagster"
        or url.query
    ):
        raise DailyBasicValidationError("history_instance_identity")
    url = url.update_query_dict(
        {
            "options": "-c statement_timeout=10000"
            + ("" if writable else " -c default_transaction_read_only=on")
        }
    ).render_as_string(hide_password=False)
    ref = InstanceRef(
        local_artifact_storage_data=ConfigurableClassData(
            "dagster._core.storage.root",
            "LocalArtifactStorage",
            yaml.safe_dump({"base_dir": str(artifact_root)}),
        ),
        compute_logs_data=ConfigurableClassData(
            "dagster._core.storage.noop_compute_log_manager",
            "NoOpComputeLogManager",
            "{}",
        ),
        scheduler_data=None,
        run_coordinator_data=None,
        run_launcher_data=None,
        settings={"telemetry": {"enabled": False}},
        run_storage_data=None,
        event_storage_data=None,
        schedule_storage_data=None,
    )
    with ExitStack() as stack:
        event = PostgresEventLogStorage(url, should_autocreate_tables=False)
        stack.callback(event.dispose)
        run = PostgresRunStorage(url, should_autocreate_tables=False)
        stack.callback(run.dispose)
        yield dg.DagsterInstance(
            instance_type=InstanceType.PERSISTENT,
            local_artifact_storage=LocalArtifactStorage(str(artifact_root)),
            run_storage=run,
            event_storage=event,
            schedule_storage=None,
            compute_log_manager=None,
            run_coordinator=None,
            run_launcher=None,
            settings={"telemetry": {"enabled": False}},
            ref=ref,
        )
